---
topic: pattern_request_reply
adapter_type: HTTPS Sender
protocol: HTTPS
pattern_family: synchronous
cpi_version: "2024.05"
---

# Pattern: Synchronous Request–Reply

## Intent

Expose an HTTPS endpoint that maps an inbound request, calls a backend system, and returns the
backend's response (transformed) to the caller in the same HTTP transaction.

## When to Use

- A partner needs a real-time `GET` or `POST` against your data.
- You can reasonably bound the backend latency (< 30s).
- The caller can cope with synchronous failure.

If any of those is false, prefer the **Asynchronous Decoupled Queue** pattern instead.

## Reference Implementation

```
HTTPS Sender (Address: /api/customers, role: ESBMessaging.send)
  → Content Modifier (extract path/query params into properties)
  → XML Validator (XSD: customer_request_v1.xsd, interrupt=No)
  → Router (valid / invalid)
       │
       ├── valid
       │     → Message Mapping (canonical → backend schema)
       │     → OData Receiver (backend, OAuth2)
       │     → Message Mapping (backend → canonical response)
       │     → end
       │
       └── invalid
             → Content Modifier (build problem+json body, CamelHttpResponseCode=400)
             → end
```

## Required Components

- HTTPS Sender (inbound boundary)
- Content Modifier (one or more, for request/response shaping)
- XML Validator (schema check)
- Router (valid vs. invalid)
- Message Mapping (canonical ↔ backend)
- OData Receiver (or SOAP Receiver, depending on backend)

## Error Handling Variant

Wrap the OData Receiver in an Exception Subprocess. On `MessagingException`, build a structured
error response with the MPL ID so callers can quote it in support tickets.

```
Exception Subprocess
  → Content Modifier
       Body:    {"error":{"code":"BACKEND_FAILURE","mpl":"${header.SAP_MessageProcessingLogID}"}}
       Header:  CamelHttpResponseCode = 502
  → end
```

## Performance Targets

- p95 ≤ 2x backend latency.
- p99 ≤ 3x backend latency (network jitter).
- Idle CPU usage on the worker should remain < 10%.

## Pitfalls

1. Doing a Splitter inside a synchronous request — the caller waits for the slowest sub-call.
2. Forgetting to map the backend `4xx` to a meaningful `4xx` for the caller; raw passthrough
   leaks backend implementation details.
3. Returning XML when the caller `Accept: application/json` — set `Content-Type` explicitly in a
   Content Modifier and convert with a JSON-to-XML / XML-to-JSON converter.
