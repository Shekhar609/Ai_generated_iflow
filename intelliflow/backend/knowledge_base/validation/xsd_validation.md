---
topic: xsd_validation
adapter_type: XML Validator
protocol: any
pattern_family: validation
cpi_version: "2024.05"
---

# XSD Validation in CPI

## Overview

XSD validation is the structural contract check. Use it at every system boundary: at the
inbound HTTPS Sender, before invoking a strict backend, and after a Message Mapping when you
want a hard guarantee on output shape.

## Levels of Validation

1. **Well-formedness**: the message parses as XML. Done implicitly by every XML-aware step in
   CPI; raises `SAXException` if it fails.
2. **Required-field check**: business-level — has the message included the fields a downstream
   step depends on. Implemented as XPath assertions in a Content Modifier + Router, or in a
   Groovy script.
3. **XSD compliance**: structural and type-level conformance to a schema document.

Always run all three at the inbound boundary. Skipping (1) lets garbage propagate. Skipping (2)
lets schema-valid but semantically broken messages reach the backend. Skipping (3) lets new
elements pass through silently.

## Producing Useful Error Messages

The XML Validator returns the raw SAX errors. These are accurate but ugly. To produce a
caller-friendly message:

```
XML Validator (interrupt=No)
  → Router (valid / invalid)
  invalid branch:
       → Groovy Script (parse SAP_XSD_Validation_Errors, produce structured JSON)
       → Content Modifier (CamelHttpResponseCode=400)
       → end
```

Structured error response:

```json
{
  "error": "ValidationFailed",
  "details": [
    {"level": "xsd", "message": "Invalid value 'abc' for xs:integer", "xpath": "/Order/Quantity", "line": 4},
    {"level": "required_field", "message": "Customer.Email missing", "xpath": "/Order/Customer/Email"}
  ]
}
```

## XSD Best Practices

- Pin a `targetNamespace`. Schema-less XML against a namespaced XSD will silently fail.
- Use `xs:enumeration` rather than free text for code values; validation catches typos.
- Avoid `xs:any` — it disables type checking on the wildcard region.
- Use `minOccurs` and `maxOccurs` precisely. `minOccurs="0"` on a required business field is
  the single most common cause of "validation passed but backend rejected".

## Pitfalls

1. Validating against an outdated XSD that the partner has revised — your flow rejects valid
   messages. Subscribe to the partner's schema change feed.
2. Using `interrupt=Yes` and discovering you cannot recover gracefully; pair with Exception
   Subprocess if you keep interrupt mode.
3. Forgetting to ship dependent XSDs (imports) — silent `unresolved schema location`.
