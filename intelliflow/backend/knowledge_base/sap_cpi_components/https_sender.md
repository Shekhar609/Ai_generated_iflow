---
topic: https_sender
adapter_type: HTTPS Sender
protocol: HTTPS
pattern_family: synchronous
cpi_version: "2024.05"
---

# HTTPS Sender Adapter

## Overview

The HTTPS Sender adapter is the most common inbound channel in SAP Cloud Integration (CPI). It exposes
an integration flow as an HTTPS endpoint and accepts synchronous or asynchronous requests over TLS.
Use it when a third-party system, SAP system, or partner needs to push data into CPI on demand.

## Key Configuration Properties

- **Address**: relative URL path that is appended to the runtime host
  (e.g. `/customer/sync` becomes `https://<tenant>/http/customer/sync`).
- **Authorization**: choose `User Role` for role-based access (recommended) or `Client Certificate`
  for mTLS scenarios. Never select `None` outside a private VPC.
- **CSRF Protected**: enable for browser-originated calls; disable for server-to-server.
- **User Role**: the role group that callers must hold (`ESBMessaging.send` by default).

## When to Use

- Real-time, request/response integrations (REST or SOAP-over-HTTP).
- Webhook receivers from external SaaS providers.
- Partner endpoints where the partner cannot poll SFTP or read OData.

Do **not** use HTTPS Sender for fire-and-forget event streams; prefer the AMQP Sender or the JMS
queue pattern. Do not use it when the caller cannot perform certificate rotation — pick OAuth
client credentials instead.

## Error Behaviour

The HTTPS Sender returns the HTTP status code emitted by the last step before the end event. If the
flow throws a `MessagingException`, CPI returns `500` with a JSON body containing `messageProcessingLogId`.
For request validation errors, return `400` with a structured payload — use a Content Modifier to set
the body and the `CamelHttpResponseCode` header.

## Pairing with Other Components

Typical synchronous request/response flow:

```
HTTPS Sender → Content Modifier (extract headers)
            → XML Validator (against XSD)
            → Message Mapping (request schema → target schema)
            → SOAP Receiver / OData Receiver
            → Message Mapping (response schema → caller schema)
            → end
```

For asynchronous push flows, follow the Sender with a JMS Receiver to decouple in-bound traffic from
back-end processing. The HTTPS Sender confirms receipt with `202 Accepted` once the message lands
in the JMS queue.

## Security Notes

- Always require `User Role` authorization and rotate the `ESBMessaging.send` role group quarterly.
- Enable Cloud Connector for back-end calls to on-premise systems.
- Validate request payloads with the **XML Validator** component before invoking downstream systems
  to prevent malformed data from polluting the integration.

## Common Pitfalls

1. Forgetting to URL-encode the Address — `/customer sync` (with a space) silently routes to a `404`.
2. Leaving CSRF protection on for server-to-server calls; partners will see `403`.
3. Using `Client Certificate` authorization but forgetting to whitelist the partner CN in the
   Keystore Monitor — symptoms: `SSL handshake failed` in the trace log.

## Reference

- SAP Help Portal: Configure the HTTPS Sender Adapter
- CPI runtime version 2024.05 and newer
