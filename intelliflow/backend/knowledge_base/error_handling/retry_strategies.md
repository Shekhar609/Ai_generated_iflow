---
topic: retry_strategies
adapter_type: Exception Subprocess
protocol: any
pattern_family: error_handling
cpi_version: "2024.05"
---

# Retry Strategies in CPI

## Overview

Not every failure is terminal. Network blips, backend cold-starts, and rate-limit `429`s are
transient and worth a retry. Permanent failures (4xx validation, business-rule violations) are
not. The retry decision belongs in the Exception Subprocess.

## Classification

| HTTP Code         | Type        | Retry?       |
|-------------------|-------------|--------------|
| 408, 425, 429     | transient   | yes, backoff |
| 500, 502, 503, 504| transient   | yes, backoff |
| 400, 401, 403, 404, 409, 422 | permanent | no |
| TLS handshake     | transient   | yes, once    |
| DNS failure       | transient   | yes, once    |

The classifier lives in a Groovy step or as a Router on `${header.CamelHttpResponseCode}`.

## Exponential Backoff via JMS Delay

CPI does not ship a generic retry primitive. The idiomatic approach is a JMS-delayed redelivery:

```
Exception Subprocess (catches MessagingException)
  → Content Modifier
       Property attempt:  ${property.attempt + 1} (init to 1 in main flow)
  → Router
       ├── attempt <= 3
       │     → JMS Receiver (queue: <flow>.retry,
       │                     header JMSDeliveryDelay=expression(2^attempt*1000))
       │
       └── attempt > 3
             → JMS Receiver (queue: <flow>.dlq)
```

The consumer flow pulls from `<flow>.retry` and re-enters the main processing.

## Idempotency Is Mandatory

If the backend has already partially processed an aborted request, a retry can double-charge or
double-write. Either:

- Make the backend call idempotent with an `Idempotency-Key` header containing the MPL ID.
- Or check state with a `GET` before retrying the `POST`.

Most modern SAP cloud APIs accept an `If-Match: <etag>` header or an `Idempotency-Key`.

## Circuit Breaker

For repeated terminal failures from a backend, implement a manual circuit breaker:

- Maintain a counter in a Data Store entry per backend.
- Exception Subprocess increments on failure, resets on success.
- A simple Router at the top of the main process checks the counter; if >N within a window,
  short-circuit to the dead-letter queue with a `BackendDegraded` error.

CPI 2024.08+ ships a built-in Circuit Breaker step for HTTPS Receiver — prefer it when available.

## Pitfalls

1. Retrying a `400 Bad Request` — wastes capacity and never succeeds.
2. Linear backoff (1s, 1s, 1s) instead of exponential — synchronizes herd retries and DDoSes the
   recovering backend.
3. Forgetting to bound retries — a never-ending retry loop fills the queue.
