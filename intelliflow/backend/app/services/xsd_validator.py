"""Three-level XML validation cascade (PRD §8.2)."""
from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Iterable

from lxml import etree


@dataclass
class XmlValidationError:
    level: str
    message: str
    xpath: str | None = None
    line: int | None = None


def _path_to(elem) -> str:
    parts = []
    while elem is not None and elem.tag is not None:
        if isinstance(elem.tag, str):
            parts.append(elem.tag)
        elem = elem.getparent()
    return "/" + "/".join(reversed(parts)) if parts else ""


def _wellformed(xml: str) -> tuple[etree._Element | None, list[XmlValidationError]]:
    try:
        root = etree.fromstring(xml.encode("utf-8"))
        return root, []
    except etree.XMLSyntaxError as exc:
        return None, [
            XmlValidationError(
                level="wellformedness",
                message=str(exc),
                line=exc.lineno,
            )
        ]


def _required_fields(root: etree._Element, required: Iterable[str]) -> list[XmlValidationError]:
    errors: list[XmlValidationError] = []
    for xp in required:
        try:
            hits = root.xpath(xp)
        except etree.XPathEvalError as exc:
            errors.append(
                XmlValidationError(
                    level="required_field",
                    message=f"Invalid XPath '{xp}': {exc}",
                    xpath=xp,
                )
            )
            continue
        is_present = False
        if isinstance(hits, list):
            for h in hits:
                if isinstance(h, str):
                    if h.strip():
                        is_present = True
                        break
                elif h is not None:
                    is_present = True
                    break
        elif hits:
            is_present = True
        if not is_present:
            errors.append(
                XmlValidationError(
                    level="required_field",
                    message=f"Required field not present: {xp}",
                    xpath=xp,
                )
            )
    return errors


def _xsd_compliance(root: etree._Element, xsd_text: str) -> list[XmlValidationError]:
    try:
        schema_doc = etree.fromstring(xsd_text.encode("utf-8"))
        schema = etree.XMLSchema(schema_doc)
    except (etree.XMLSyntaxError, etree.XMLSchemaParseError) as exc:
        return [XmlValidationError(level="xsd", message=f"Invalid XSD: {exc}")]
    if schema.validate(root):
        return []
    errors: list[XmlValidationError] = []
    for err in schema.error_log:
        errors.append(
            XmlValidationError(
                level="xsd",
                message=err.message,
                xpath=err.path,
                line=err.line,
            )
        )
    return errors


def validate_three_level(
    xml: str,
    *,
    xsd_base64: str | None = None,
    required_fields: Iterable[str] = (),
) -> list[XmlValidationError]:
    root, wf_errs = _wellformed(xml)
    if wf_errs:
        return wf_errs

    errors: list[XmlValidationError] = []
    errors.extend(_required_fields(root, required_fields))

    if xsd_base64:
        try:
            xsd_text = base64.b64decode(xsd_base64).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            errors.append(XmlValidationError(level="xsd", message=f"Could not decode XSD base64: {exc}"))
        else:
            errors.extend(_xsd_compliance(root, xsd_text))

    return errors
