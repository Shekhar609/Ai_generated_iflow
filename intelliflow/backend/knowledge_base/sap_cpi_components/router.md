---
topic: router
adapter_type: Router
protocol: any
pattern_family: routing
cpi_version: "2024.05"
---

# Router

## Overview

The Router evaluates an XPath, header, or property condition and forwards the message to one of
multiple downstream branches. It is the standard branching primitive in SAP CPI, equivalent to a
content-based router in EIP terminology.

## Configuration

- **Routing Conditions**: ordered list of `(branch_label, condition)` tuples. The first matching
  condition wins; the rest are ignored.
- **Default Route**: required. Catches messages that match no condition.
- **Condition Type**: `XPath` (default), `Non-XML` (string/regex against headers).

## When to Use

- Branching by document type after an HTTPS Sender receives a polymorphic payload.
- Branching by validation result (`valid` vs. `invalid`) after an XML Validator.
- Splitting by environment header (`X-Env: prod` vs. `staging`).

If branches share most steps and differ only in a single property, prefer a Content Modifier
followed by a single linear path. A Router is justified when downstream branches diverge
substantially.

## Example Conditions

| Branch  | Condition                                                |
|---------|----------------------------------------------------------|
| valid   | `/Envelope/Validation/Status/text() = 'OK'`              |
| invalid | `/Envelope/Validation/Status/text() = 'FAIL'`            |
| retry   | `${property.attempt} <= 3`                               |

XPath expressions run against the **current** message body. Make sure the body is XML at the
point the Router fires — if a previous Message Mapping converted to JSON, use Non-XML conditions
on a property the mapping wrote.

## Pairing After an XML Validator

The most common pattern in CPI is XML Validator → Router(valid/invalid):

```
XML Validator (against XSD)
  → Router
     ├── label: valid    → continue main flow
     └── label: invalid  → Content Modifier (build error envelope)
                         → end with HTTP 400
```

The XML Validator writes the validation result into the `SAP_XSD_Validation_Errors` header on
failure. The Router can branch on `${header.CamelHttpResponseCode}` or on the presence of that
header.

## Pitfalls

1. Forgetting the **Default Route** — flow design becomes invalid and won't deploy.
2. Putting overlapping conditions in the wrong order — the first match wins; debug with the trace
   log and check which branch label appears in the MPL.
3. Branching on a header that was never set; the condition silently evaluates to false and the
   message falls through to default.
