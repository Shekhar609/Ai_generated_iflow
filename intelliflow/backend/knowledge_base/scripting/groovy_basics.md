---
topic: groovy_basics
adapter_type: Groovy Script
protocol: any
pattern_family: scripting
cpi_version: "2024.05"
---

# Groovy Script: Basics

## Overview

Groovy Script lets you embed custom code in a CPI flow when no declarative step suffices. The
canonical entry point is `processData(Message message)`.

## Standard Skeleton

```groovy
import com.sap.gateway.ip.core.customdev.util.Message
import groovy.json.JsonSlurper
import groovy.json.JsonBuilder

Message processData(Message message) {
    def body = message.getBody(String) ?: ""
    def headers = message.getHeaders()
    def properties = message.getProperties()

    // Parse, transform, write back.
    def parsed = new JsonSlurper().parseText(body)
    parsed.timestamp = new Date().format("yyyy-MM-dd'T'HH:mm:ss'Z'", TimeZone.getTimeZone("UTC"))

    message.setBody(new JsonBuilder(parsed).toString())
    message.setHeader("Content-Type", "application/json")
    return message
}
```

## Reading and Writing

- **Body**: `message.getBody(String)` returns the body as a string; `(byte[])` for binary;
  `(InputStream)` for streaming. Always pick the right type to avoid unnecessary materialization.
- **Headers**: visible to the next adapter (HTTP, JMS).
- **Properties**: exchange-scoped; not transmitted.

## When to Use

- Format conversions Camel SimpleLanguage cannot express (HMAC signing, JWT building, base64
  variants).
- Calling Java libraries (`java.security.MessageDigest`, `java.time`).
- Implementing a custom Aggregator strategy.

## When NOT to Use

- For 1-line operations a Content Modifier expression covers — Groovy adds a JVM hop.
- For schema-to-schema transformations — use Message Mapping; Groovy is unmaintainable for that.
- For HTTP calls — use a Receiver adapter, not `HttpURLConnection` from Groovy.

## Security

- Never log secrets. `message.getProperties()` may contain credential fragments — never `println`
  the whole map.
- Validate any input you parse from the body; assume hostile content if the upstream is a
  partner.
- Don't disable certificate verification (`TrustAllX509TrustManager`) — pin certificates in the
  keystore instead.

## Performance

- Avoid `parseText` on a 100 MB body; use `parse(InputStream)` for streaming.
- Cache reflection / compiled patterns at the script-level (Groovy scripts are reloaded only on
  deploy).

## Pitfalls

1. Returning `null` from `processData` — the message is dropped silently.
2. Mutating the body without setting `Content-Type` — downstream adapters guess wrong.
3. Using `eval()` or `Eval.me` on user input — same risk profile as `eval` in any language.
