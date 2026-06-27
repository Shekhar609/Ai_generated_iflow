---
topic: https_receiver
adapter_type: HTTPS Receiver
protocol: HTTPS
pattern_family: synchronous
cpi_version: "2024.05"
---

# HTTPS Receiver Adapter

## Overview

The HTTPS Receiver adapter is the standard **outbound** channel in SAP Cloud Integration (CPI).
It sends an HTTP/HTTPS request from the iFlow to an external REST endpoint and returns the response
to the next step. Use it for any REST/JSON call out of CPI — partner APIs, S/4HANA Cloud REST
endpoints, regional micro-services, downstream SaaS providers (Salesforce REST, ServiceNow Table API,
custom webhooks), and any HTTP destination that is not SOAP.

The name follows SAP CPI's convention: the adapter is named after the **external system's role**.
Here the external system is the one **receiving** the request from the iFlow, so the adapter is a
"Receiver". Do not confuse this with the HTTPS Sender, which is the inbound adapter that exposes
the iFlow as an HTTP endpoint for external callers to push data INTO CPI.

## Key Configuration Properties

- **Address**: full URL of the target endpoint (`https://api.partner.com/v1/orders`).
- **Method**: `POST`, `GET`, `PUT`, `PATCH`, `DELETE`. Defaults to `POST`.
- **Proxy Type**: `Internet` for public endpoints, `On-Premise` when routing through Cloud Connector.
- **Authentication**: `None`, `Basic`, `Client Certificate`, `OAuth2 Client Credentials`, `OAuth2 SAML Bearer`, or `Principal Propagation`.
- **Credential Name**: name of the deployed Security Material (User Credentials, OAuth2 Credentials, etc.).
- **Request Headers**: typically include `Content-Type: application/json` and `Accept: application/json`.
  Use a Content Modifier upstream to set per-call headers (idempotency keys, correlation IDs).
- **Timeout**: connection timeout (default 30s) and request timeout (default 60s).
- **Allow Chunking**: enable for streaming uploads; disable for legacy targets that reject chunked transfer.

## When to Use

- Calling any external REST/JSON API from the iFlow (partner SaaS, internal micro-services, webhooks).
- Pushing data to a S/4HANA Cloud REST endpoint (when an OData service is not available).
- Fan-out to multiple destinations: route through a Router, then end each branch with its own
  HTTPS Receiver pointing at the per-destination URL.
- Country-based or tenant-based routing where each branch posts to a different regional endpoint
  (e.g. `US`, `IN`, `UK` micro-services) — each branch ends in its own HTTPS Receiver.

Use the **SOAP Receiver** instead when the partner exposes a WSDL and expects a SOAP envelope.
Use the **OData Receiver** instead when the target is an OData service (preferred for S/4HANA Cloud).
Use the **SFTP Receiver** for file uploads to a remote SFTP folder.

## Error Behaviour

A non-2xx response from the target is converted into a `HttpResponseException` carrying the
status code, response headers, and body. Wrap the call in an Exception Subprocess to:

- Classify retriable errors (`408`, `429`, `5xx`) and trigger a retry with exponential backoff.
- Classify non-retriable errors (`4xx` other than 408/429) and route the original payload to a
  dead-letter destination (JMS Receiver pointing at `cpi.dlq.<flow_name>` or an SFTP error folder).
- Log the `messageProcessingLogId`, target URL, request headers, and the truncated response body.

Honour the partner's `Retry-After` header on `429` and `503` responses.

## Pairing

Canonical outbound request/response shape:

```
Content Modifier (set headers, e.g. Content-Type, Authorization, Idempotency-Key)
  → Message Mapping (canonical → partner JSON schema)
  → HTTPS Receiver  (target URL, method=POST, OAuth2 Client Credentials)
  → Message Mapping (partner JSON → canonical response)
```

Multi-destination routing:

```
Router  ── //country='US' ──→ Content Modifier (US headers) → HTTPS Receiver (US endpoint URL)
        ── //country='IN' ──→ Content Modifier (IN headers) → HTTPS Receiver (IN endpoint URL)
        ── //country='UK' ──→ Content Modifier (UK headers) → HTTPS Receiver (UK endpoint URL)
```

XML-in → JSON-out chain (for an HTTPS Sender entry that needs to call JSON receivers):

```
HTTPS Sender (inbound XML)
  → XML Validator
  → Message Mapping (XML → JSON, output type = application/json)
  → Router (branch on payload field)
  → HTTPS Receiver (target accepts application/json)
```

## Performance

- Reuse connections by enabling HTTP keep-alive (default for HTTPS Receiver).
- For high-fan-out scenarios, prefer asynchronous patterns — push messages to a JMS Receiver and let
  a separate iFlow drain the queue with parallel workers calling HTTPS Receivers.
- Avoid blocking on long-running targets in a synchronous flow; switch to async + callback.

## Security

- Always pin the target's TLS certificate in the CPI keystore for sensitive endpoints.
- Prefer `OAuth2 Client Credentials` over `Basic` authentication.
- Rotate Basic credentials at least every 90 days.
- Never log the `Authorization` header value — use the Content Modifier's "Do not trace" option.

## Common Pitfalls

1. Confusing HTTPS Receiver with HTTPS Sender: the **Receiver** adapter is for OUTBOUND calls
   (the iFlow invokes an external URL); the **Sender** adapter is for INBOUND calls (external
   systems invoke the iFlow). Typing an outbound call as "HTTPS Sender" is a frequent mistake;
   the runtime will fail at deployment with an adapter-direction validation error.
2. Forgetting `Content-Type: application/json` when posting JSON — many partners default to
   `text/plain` and reject the body silently.
3. Using `Authentication: None` against a public endpoint that requires an API key in a header;
   results in `401` or `403`.
4. Not handling `429 Too Many Requests` — the iFlow will retry immediately and amplify the rate
   limit breach. Always honour `Retry-After`.

## Reference

- SAP Help Portal: Configure the HTTPS Receiver Adapter
- CPI runtime version 2024.05 and newer
