"""Build an importable SAP CPI Integration Flow project ZIP around a generated .iflw.

The bundle is what SAP CPI Web IDE expects on `Actions → Import`:

  <name>.zip
  ├── META-INF/MANIFEST.MF                       # OSGi headers (SAP-BundleType, Bundle-SymbolicName, ...)
  └── src/main/resources/
      ├── scenarioflows/integrationflow/<name>.iflw
      ├── parameters.prop                        # externalized config (placeholder, empty)
      └── parameters.propdef                     # parameter definitions (placeholder)

This is the minimal layout CPI accepts. Real tenant exports also ship Camel
contexts, message-mapping XSDs, and Groovy scripts under
`src/main/resources/`; those are wired into the iflw by reference and can be
added later in Web IDE. The `Import-Package` list mirrors what CPI emits for
a generic Integration Flow bundle — enough to import; a real deploy may
re-resolve based on the adapters actually used.
"""
from __future__ import annotations

import io
import re
import zipfile

from ..schemas.flow import IFlow
from .iflw_xml import build_iflw_xml


def _safe_filename(name: str) -> str:
    """Make a name safe for a filesystem path inside the zip."""
    s = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_")
    return s or "Integration_Flow"


def _safe_bundle_id(flow_id: str) -> str:
    """OSGi Bundle-SymbolicName: ASCII alphanum, dot and hyphen only."""
    s = re.sub(r"[^A-Za-z0-9.-]+", "", flow_id.lower())
    return s or "intelliflow.iflow"


def _fold_manifest_line(line: str) -> str:
    """Fold a manifest line per JAR/OSGi spec: max 72 bytes per line incl. CRLF;
    continuation lines start with a single space."""
    MAX_FIRST = 70  # 72 bytes - 2 for CRLF
    MAX_CONT = 69   # 72 bytes - 1 for leading space - 2 for CRLF
    encoded = line.encode("utf-8")
    if len(encoded) <= MAX_FIRST:
        return line + "\r\n"
    chunks = [encoded[:MAX_FIRST].decode("utf-8")]
    rest = encoded[MAX_FIRST:]
    while rest:
        chunks.append(" " + rest[:MAX_CONT].decode("utf-8"))
        rest = rest[MAX_CONT:]
    return "\r\n".join(chunks) + "\r\n"


_IMPORT_PACKAGE = (
    'com.sap.esb.application.services.cxf.interceptor;version="1.0.0",'
    'com.sap.esb.security,'
    'com.sap.it.op.agent.api;version="1.1.0",'
    'com.sap.it.op.agent.collector.camel;version="1.1.0",'
    'com.sap.it.op.agent.collector.cxf;version="1.1.0",'
    'com.sap.it.op.agent.mpl;version="1.1.0",'
    'javax.jms,javax.jws,javax.wsdl,javax.xml.bind.annotation,'
    'javax.xml.namespace,javax.xml.ws,'
    'org.apache.camel,org.apache.camel.builder,'
    'org.apache.camel.component.cxf,org.apache.camel.model,'
    'org.apache.camel.processor,org.apache.camel.processor.aggregate,'
    'org.apache.camel.spi,org.apache.commons.logging,'
    'org.apache.cxf.binding,org.apache.cxf.binding.soap,'
    'org.apache.cxf.binding.soap.spring,org.apache.cxf.bus,'
    'org.apache.cxf.bus.resource,org.apache.cxf.bus.spring,'
    'org.apache.cxf.buslifecycle,org.apache.cxf.catalog,'
    'org.apache.cxf.configuration.jsse,org.apache.cxf.configuration.spring,'
    'org.apache.cxf.endpoint,org.apache.cxf.feature,org.apache.cxf.headers,'
    'org.apache.cxf.interceptor,org.apache.cxf.management.counters,'
    'org.apache.cxf.message,org.apache.cxf.phase,org.apache.cxf.resource,'
    'org.apache.cxf.service.factory,org.apache.cxf.service.model,'
    'org.apache.cxf.transport,org.apache.cxf.transport.common.gzip,'
    'org.apache.cxf.transport.http,org.apache.cxf.transport.http.policy,'
    'org.apache.cxf.workqueue,org.apache.cxf.ws.rm.persistence,'
    'org.apache.cxf.wsdl11,org.osgi.framework;version="1.7.0",'
    'org.slf4j;version="1.6.0",'
    'org.springframework.beans.factory.config;version="4.2.0.RELEASE",'
    'com.sap.esb.camel.security.cms,'
    'org.apache.camel.spring.spi;version="2.16.0"'
)


def _manifest_mf(*, bundle_id: str, name: str, version: str = "1.0.0") -> bytes:
    headers = [
        "Manifest-Version: 1.0",
        "Bundle-ManifestVersion: 2",
        f"Bundle-Name: {name}",
        f"Bundle-SymbolicName: {bundle_id}; singleton:=true",
        f"Bundle-Version: {version}",
        "SAP-BundleType: IntegrationFlow",
        "SAP-NodeType: IFLMAP",
        f"Origin-Bundle-Name: {name}",
        f"Origin-Bundle-SymbolicName: {bundle_id}",
        f"Origin-Bundle-Version: {version}",
        f"Import-Package: {_IMPORT_PACKAGE}",
        "Service-Component: ",
    ]
    folded = "".join(_fold_manifest_line(h) for h in headers)
    # MANIFEST.MF requires a blank line terminating the main section.
    return (folded + "\r\n").encode("utf-8")


def build_iflw_bundle(iflow: IFlow, *, flow_id: str) -> bytes:
    """Render an :class:`IFlow` as an importable SAP CPI .zip bundle."""
    name = iflow.flow_name or "Integration Flow"
    safe_name = _safe_filename(name)
    bundle_id = _safe_bundle_id(flow_id)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("META-INF/MANIFEST.MF", _manifest_mf(bundle_id=bundle_id, name=name))
        z.writestr(
            f"src/main/resources/scenarioflows/integrationflow/{safe_name}.iflw",
            build_iflw_xml(iflow),
        )
        z.writestr("src/main/resources/parameters.prop", b"")
        z.writestr(
            "src/main/resources/parameters.propdef",
            b'<?xml version="1.0" encoding="UTF-8"?>\n<parameters/>\n',
        )
    return buf.getvalue()
