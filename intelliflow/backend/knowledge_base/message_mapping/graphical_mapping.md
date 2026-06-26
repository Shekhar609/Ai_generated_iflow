---
topic: message_mapping_graphical
adapter_type: Message Mapping
protocol: any
pattern_family: transformation
cpi_version: "2024.05"
---

# Graphical Message Mapping

## Overview

Message Mapping converts one message structure into another using a graphical, drag-and-drop
mapper. It is the default transformation tool in CPI; use it for structured XML-to-XML and
JSON-to-XML conversions where source and target schemas are stable.

## Components of a Mapping

- **Source Type**: XSD, WSDL, or JSON Schema describing the input.
- **Target Type**: same.
- **Mapping**: per-target-field expression. The expression is a chain of standard functions
  (text, arithmetic, node, constants) and custom user-defined functions in Groovy.

## Standard Functions

- **Text**: `concat`, `substring`, `replaceString`, `trim`, `toUpperCase`, `toLowerCase`.
- **Arithmetic**: `add`, `subtract`, `multiply`, `divide`, `round`.
- **Boolean**: `equalS`, `lessThan`, `greaterThan`, `if`, `ifWithoutElse`.
- **Node**: `exists`, `createIf`, `removeContexts`, `mapWithDefault`.
- **Constants**: literal values pinned at design time.

## Context Handling

The single most-misunderstood concept in MM. Each source field carries a **context** — the
enclosing node at which sibling occurrences are grouped. By default, the context is the
immediate parent.

- Use `removeContexts` to flatten — for example, treating `Items/Item/Price` as a flat list of
  prices regardless of which `Item` they belong to.
- Use `splitByValue` to group repeating values into sub-lists by a key field.
- Use `useOneAsMany` to repeat a single-value source against a multi-value target.

## User-Defined Functions

When standard functions are not enough, write a Groovy UDF:

```groovy
String formatIBAN(String[] input, MappingContext ctx) {
  String iban = input[0]
  return iban.replaceAll("\\s", "").toUpperCase()
}
```

Register as `Cache: Single Value`, `Queue`, or `Context` depending on whether it consumes a
single value, a flat list, or a context-grouped list.

## When NOT to Use Message Mapping

- For one-line passthroughs — use a Content Modifier instead.
- For schemaless JSON shaping — use a Groovy Script with `JsonSlurper` / `JsonBuilder`.
- For payloads >20 MB — Message Mapping materializes the DOM; switch to XSLT Mapping.

## Pitfalls

1. Forgetting `createIf` on optional target elements — empty `<Foo/>` elements appear in the output.
2. Misusing `removeContexts` — silently merges parallel branches into one.
3. Hard-coding a value in a Constant function that should come from a Configure-time parameter.
4. Building a 200-target-field mapping by hand instead of generating from sample messages.
