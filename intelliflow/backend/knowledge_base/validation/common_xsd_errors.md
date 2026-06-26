---
topic: common_xsd_errors
adapter_type: XML Validator
protocol: any
pattern_family: validation
cpi_version: "2024.05"
---

# Common XSD Validation Errors and Their Fixes

## cvc-complex-type.2.4.a: Invalid content was found starting with element 'X'

The element appears in the wrong order or the parent type does not allow it. XSD `xs:sequence`
is strict order; `xs:all` allows any order. Fix:

- Reorder the offending element to match the schema sequence.
- If order should be flexible, change the parent type to `xs:all` (max one of each child).

## cvc-complex-type.2.4.b: The content of element 'X' is not complete

A required child element is missing. Fix:

- Add the missing element to the payload, or
- If the field really is optional, change `minOccurs="1"` to `"0"` in the XSD.

## cvc-datatype-valid.1.2.1: 'abc' is not a valid value for 'integer'

The text content has the wrong type. Fix:

- Coerce the source: `<xsl:value-of select="xs:integer(.)"/>` in XSLT, or a Message Mapping
  `formatNum` function.
- If the source genuinely contains non-numeric strings, change the XSD type to `xs:string` or
  add validation upstream.

## cvc-elt.1: Cannot find the declaration of element 'X'

The root element isn't declared in the XSD, usually because of a namespace mismatch. Fix:

- Add `xmlns="<targetNamespace>"` to the payload root.
- If the source genuinely has no namespace, generate an XSD without `targetNamespace`.

## cvc-pattern-valid: Value 'X' is not facet-valid with respect to pattern 'Y'

The value violates an `xs:pattern` regex. Fix:

- Normalize upstream (e.g. strip dashes from a phone number).
- Loosen the regex if business rules have changed.

## cvc-enumeration-valid: Value 'X' is not facet-valid with respect to enumeration

Value not in the allowed list. Fix:

- Use a Value Mapping artifact to translate partner codes to your enumeration.
- Update the enumeration if the new value is legitimate.

## Recovery Pattern

Always run validation with `interrupt=No`, then branch on the error header:

```
XML Validator (interrupt=No)
  → Router
       ├── valid:   main flow
       └── invalid: structured error response with the specific cvc-* code mapped to a caller-friendly message
```

This lets you give the partner a precise, actionable message instead of "validation failed".
