from __future__ import annotations

from lxml import etree


def well_formed(xml_text: str) -> bool:
    if not isinstance(xml_text, str) or not xml_text.strip():
        return False
    try:
        etree.fromstring(xml_text.encode("utf-8"))
        return True
    except etree.XMLSyntaxError:
        return False
