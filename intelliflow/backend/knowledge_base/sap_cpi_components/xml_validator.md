---
topic: xml_validator
adapter_type: XML Validator
protocol: any
pattern_family: validation
cpi_version: "2024.05"
---

# XML Validator

## Overview

The XML Validator step parses the current message body and validates it against an XSD schema
stored in the integration package. It produces a hard error if the message is not well-formed and
a soft error (controllable) if it does not conform to the XSD.

## Configuration

- **XSD Resource**: pick the XSD from the integration project. Use schema location
  `src/main/resources/schema/...`.
- **Interrupt Message Processing on Validation Errors**:
  - `Yes`: the flow throws `org.xml.sax.SAXException` and routes to Exception Subprocess (default).
  - `No`: validation errors are collected into the `SAP_XSD_Validation_Errors` header; the message
    proceeds. Use this when you want to branch on validation outcome.
- **Prevent Exception on Failure**: the same idea exposed in the v3 designer.

## When to Use

- Before invoking an SAP backend whose contract demands strict schema compliance.
- After an external partner pushes a payload into your tenant — fail fast at the boundary.
- After a Message Mapping when you want to verify the mapping output matches the target schema.

## Typical Pattern

```
HTTPS Sender
  → XML Validator (XSD: customer_request_v1.xsd, interrupt=No)
  → Router
     ├── valid:    XPath="not(boolean(${header.SAP_XSD_Validation_Errors}))"
     │             → Message Mapping → backend call
     └── invalid:  Default route
                   → Content Modifier (build SOAP fault / problem+json body)
                   → end with HTTP 400
```

## Error Reporting

When validation fails, `SAP_XSD_Validation_Errors` contains a newline-separated list of structured
error lines:

```
cvc-complex-type.2.4.a: Invalid content was found starting with element 'Foo'. One of '{Bar}' is expected.
cvc-datatype-valid.1.2.1: 'abc' is not a valid value for 'integer'.
```

Parse these in a Groovy Script if you need to map them to structured fields for the caller.

## Performance

- Validation is O(n) in payload size. For payloads >10 MB, prefer streaming validation by enabling
  the Streaming option.
- Cache the compiled schema — CPI does this automatically when the XSD resource is not changed.

## Pitfalls

1. Importing an XSD that imports another XSD without uploading the dependency — silent `unresolved
   schema location` warning, then `IllegalStateException` at runtime.
2. Validating after a JSON-to-XML conversion that produces namespace-less XML against an XSD that
   declares a target namespace — set the namespace in the conversion step.
3. Using `Interrupt Message Processing = Yes` and then trying to recover via Router — too late;
   you must use an Exception Subprocess.
