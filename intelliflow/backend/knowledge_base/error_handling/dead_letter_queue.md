---
topic: dead_letter_queue
adapter_type: JMS Receiver
protocol: JMS
pattern_family: error_handling
cpi_version: "2024.05"
---

# Dead-Letter Queue (DLQ) Pattern

## Overview

A dead-letter queue holds messages that could not be processed even after retries. It is the
boundary between "the system will keep trying" and "a human must look at this".

## Design

- One DLQ per flow: `cpi.dlq.<flow_name>`.
- Each message carries the original body, the error class/message, and the MPL ID as headers.
- A separate monitoring flow consumes the DLQ and writes a daily / hourly summary email.

## Producing to the DLQ

Inside the Exception Subprocess, after retries are exhausted:

```
Content Modifier
  Body:   ${property.originalPayload}
  Headers:
    X-Error-Class:    ${property.errorClass}
    X-Error-Message:  ${property.errorMessage}
    X-MPL-Id:         ${header.SAP_MessageProcessingLogID}
    X-Failed-At:      ${date:now:yyyy-MM-dd'T'HH:mm:ss'Z'}
    X-Flow-Name:      ${header.SAP_FlowName}
JMS Receiver
  Queue:   cpi.dlq.${header.SAP_FlowName}
  Persistent: true
```

## Replay

To replay a DLQ message, deploy a one-shot flow that:

1. Consumes from the DLQ.
2. Restores the body and any required headers.
3. Sends back into the original flow's entry point (via an internal `direct:` endpoint or by
   POSTing to the HTTPS Sender path).
4. Logs the replay attempt.

Never auto-replay from the DLQ — a human should approve.

## Sizing and Monitoring

- Provision DLQs with `Max Queue Size` 10x expected daily failures. CPI rejects new messages
  when full.
- Monitor `JMS_Pending_Messages` per DLQ. Sustained growth means the underlying issue isn't
  being fixed; escalate.
- Auto-expire DLQ messages after 30 days (set `TimeToLive` on the JMS Receiver). After that,
  the source data is usually stale anyway.

## Pitfalls

1. One global DLQ for all flows — impossible to triage; each flow needs its own.
2. Sending only the error message to the DLQ, not the original body — operations cannot
   reprocess.
3. Auto-replaying on a fixed schedule — same failure repeats; instead, replay only after the
   root cause is fixed.
4. Storing PII in the DLQ longer than your retention policy allows — add a periodic purge job.
