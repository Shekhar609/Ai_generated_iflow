---
topic: content_modifier
adapter_type: Content Modifier
protocol: any
pattern_family: stateless
cpi_version: "2024.05"
---

# Content Modifier

## Overview

The Content Modifier is the workhorse of SAP CPI. It manipulates message headers, exchange
properties, and the message body in one declarative step. Every non-trivial flow uses several.

## What It Can Do

- **Headers**: set, copy, or remove HTTP / JMS / custom headers visible to downstream adapters.
- **Properties**: set exchange-scoped variables that survive across steps but are not transmitted.
- **Message Body**: replace the body with a literal string, a Camel SimpleLanguage expression, or
  the value of a property/header.

## Expression Language

Content Modifier uses Apache Camel SimpleLanguage. Key tokens:

- `${header.<name>}` — read an HTTP/inbound header.
- `${property.<name>}` — read an exchange property.
- `${in.body}` — current message body (string).
- `${date:now:yyyy-MM-dd'T'HH:mm:ss'Z'}` — formatted UTC timestamp.

Concatenation: `Order-${property.orderId}-${date:now:yyyyMMdd}`.

## Common Patterns

### Build an OData $filter

```
Name:  $filter
Source Type:  Expression
Source Value: BusinessPartner eq '${property.bpId}' and CreationDate ge datetime'${property.fromDate}'
```

### Stash the original payload before mapping

```
Properties:
  Name:        originalPayload
  Source:      Body
  Type:        java.lang.String
```

You can later restore it inside an exception subprocess with another Content Modifier reading
`${property.originalPayload}`.

### Set HTTP response code

```
Headers:
  Name:  CamelHttpResponseCode
  Value: 202
```

This is how you return `202 Accepted` from an async flow without a Groovy script.

## When to Use vs. Alternatives

- Use **Content Modifier** for declarative header/property/body work.
- Use **Groovy Script** only when SimpleLanguage cannot express the logic (complex looping, hashing,
  encoding, signing).
- Use **Message Mapping** for schema-to-schema transformation; never use Content Modifier to build
  a 50-field XML body.

## Pitfalls

1. Setting `CamelHttpMethod` thinking it changes the receiver — it does not; the receiver adapter
   controls the verb. Use `CamelHttpMethod` only when the receiver is an HTTPS Receiver in dynamic mode.
2. Using `${in.body}` after a streaming splitter — the body may already have been consumed; copy
   it to a property first.
3. Putting secrets in Content Modifier values; use Secure Parameters or the Credential artifact.
