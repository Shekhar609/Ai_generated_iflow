---
topic: exception_subprocess
adapter_type: Exception Subprocess
protocol: any
pattern_family: error_handling
cpi_version: "2024.05"
---

# Exception Subprocess

## Overview

The Exception Subprocess is CPI's structured `try/catch`. It's a separate process inside the
same integration flow that fires when the main process throws an unhandled exception.

## Configuration

- Place an **Exception Subprocess** on the canvas (right-click → Add Exception Subprocess).
- Add steps inside it just like a normal subprocess.
- Optionally set the **Catch Condition** by exception class
  (`org.apache.camel.MessagingException`, `org.xml.sax.SAXException`).

If no condition is set, the subprocess catches every uncaught exception.

## Typical Pattern: Log + Notify + Dead-Letter

```
Exception Subprocess (catches all)
  → Content Modifier
       Properties:
         errorMessage:   ${exception.message}
         errorClass:     ${exception.class.simpleName}
         originalBody:   ${property.originalPayload}
         mpl:            ${header.SAP_MessageProcessingLogID}

  → Groovy Script (write structured log line)

  → Router (recoverable vs. terminal)
       ├── recoverable (HTTP 502/503/504, SocketTimeout)
       │     → JMS Receiver (queue: <flow>.retry, delay: 60s)
       │
       └── terminal (4xx, schema validation, business logic)
             → Mail Receiver (To: integration-owners)
             → JMS Receiver (queue: <flow>.dlq)
```

## Save the Original Body Up Front

Inside the main process, before any transformation, save the inbound body:

```
Content Modifier (main process, step 1)
  Properties:
    originalPayload   Source: Body   Type: java.lang.String
```

The Exception Subprocess can then access `${property.originalPayload}` and write it to the
dead-letter queue. Without this, the transformed (and possibly destructive) body is what gets
DLQ'd.

## Behaviour

- The Exception Subprocess runs **once** per exception; it cannot itself throw to another
  subprocess.
- If the Exception Subprocess throws, the message goes to the CPI runtime default error handler
  (logged and discarded).
- The main process does **not** continue after the exception fires.

## Pitfalls

1. Doing recovery logic inline in the main flow with try/catch-style Routers — Exception
   Subprocess is the supported primitive, use it.
2. Not saving the original body — DLQ contains a partially-transformed message that nobody can
   reprocess.
3. Mail-flooding on a partner outage — group failures and notify periodically, not per message.
4. Letting the Exception Subprocess silently swallow exceptions without logging — operations
   has no signal.
