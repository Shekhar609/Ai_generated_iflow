---
topic: splitter_aggregator
adapter_type: Splitter
protocol: any
pattern_family: batch
cpi_version: "2024.05"
---

# Splitter and Aggregator

## Overview

The Splitter breaks a composite message into many sub-messages, processes each, and (optionally)
the Aggregator merges results back. This is the canonical batch pattern in CPI: it lets a single
inbound document drive many outbound calls in parallel or sequence.

## Splitter Variants

- **General Splitter**: split by XPath, JSON path, or line.
- **IDoc Splitter**: one IDoc per output message — preserves IDoc control record headers.
- **PKCS7/CMS Splitter**: split a signed bundle into individual signed parts.
- **Tar/Zip Splitter**: split an archive into per-file messages.

Choose **Iterating Splitter** when each sub-message is independent (parallel-safe). Choose
**General Splitter** when you need access to the parent context inside sub-processing.

## Aggregator

The Aggregator collects sub-messages keyed by a correlation ID (typically `${header.SAP_MplCorrelationId}`)
and emits one combined message when the completion condition is met. Configure:

- **Completion Condition**: `Last Message`, `Size` (e.g. 50), or `Timeout` (e.g. 60s).
- **Aggregation Strategy**: `Combine` (concatenate XML), `Custom Groovy`, or a Message Mapping.

## Typical Pattern: Parallel Backend Calls

```
HTTPS Sender (order batch of N items)
  → Splitter (XPath: /Orders/Order)
     → Message Mapping → OData Receiver (POST /Orders)
  → Aggregator (Size=N, strategy=Combine)
  → HTTPS Receiver (return summary)
```

For 200 items, this completes in ~1.5x the time of a single call (network-bound), versus 200x for
a sequential loop.

## Pitfalls

1. Forgetting the Aggregator on a synchronous flow — the caller sees only the **last** processed
   sub-message, not the combined result.
2. Using `Last Message` completion on an infinite stream — the flow never completes.
3. Splitting a 1-GB IDoc bundle without enabling streaming — out-of-memory in the worker.
4. Choosing parallel processing on an idempotent receiver — many backends throttle parallel writes;
   set the Splitter parallel processing to `1` or use sequential mode.

## Streaming

For payloads >50 MB, enable **Streaming** in the Splitter. The splitter then emits sub-messages
without materializing the full input. The Aggregator must also be configured for streaming or you
will OOM at the merge.
