---
topic: pattern_async_queue
adapter_type: JMS Receiver
protocol: JMS
pattern_family: asynchronous
cpi_version: "2024.05"
---

# Pattern: Asynchronous Decoupled Queue

## Intent

Accept inbound traffic on a fast endpoint, immediately persist it to a JMS queue, and process
asynchronously. The caller receives `202 Accepted` once persistence succeeds.

## When to Use

- Inbound rate exceeds backend capacity (peak smoothing).
- Backend latency is high or variable.
- Loss-of-message is unacceptable (JMS gives durable, transactional delivery).

## Reference Implementation

**Inbound flow** (publisher):

```
HTTPS Sender (Address: /events/orders)
  → Content Modifier
       Header:  CamelHttpResponseCode = 202
  → JMS Receiver (queue: orders.in)
  → end
```

**Worker flow** (consumer):

```
JMS Sender (queue: orders.in, concurrency: 5)
  → Message Mapping (canonical → backend)
  → OData Receiver (backend)
  → end
```

## Required Components

- HTTPS Sender (inbound boundary, returns 202 quickly)
- JMS Receiver (durable persistence)
- JMS Sender (worker pull)
- Message Mapping
- OData Receiver (or other backend adapter)
- Exception Subprocess on the worker

## Why Two Flows?

A single flow with HTTPS Sender → JMS → backend would either block on the backend or lose the
return-value path. Splitting publisher from consumer lets each scale independently and isolates
failure: a backend outage queues messages instead of pushing back-pressure to the caller.

## Idempotency

The consumer **must** be idempotent because JMS delivers at-least-once. Use the `JMSMessageID`
plus an Idempotent Repository in CPI to dedupe replays.

## Dead-Letter Handling

Wrap the consumer's backend call in an Exception Subprocess that, on terminal failure, routes
the message to `orders.dlq`. A separate monitoring flow consumes `orders.dlq` and notifies
operators via the Mail Receiver.

## Pitfalls

1. Returning `200 OK` instead of `202 Accepted` from an async endpoint — callers assume the
   business work has been completed.
2. Configuring the worker with too high concurrency (`>10`) and overrunning the backend's
   rate limit.
3. Forgetting the dead-letter routing — failed messages silently rot in the retry queue.
