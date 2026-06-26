---
topic: mail_receiver
adapter_type: Mail Receiver
protocol: SMTP
pattern_family: notification
cpi_version: "2024.05"
---

# Mail Receiver Adapter

## Overview

The Mail Receiver sends an email via SMTP. It is the right choice for low-volume, human-readable
notifications: monitoring alerts, end-of-day summaries, escalations from an Exception Subprocess.

## Configuration

- **Address**: `smtp.outbound.example.com:587`.
- **Authentication**: `Plain`, `Login`, or `OAuth2`.
- **From / To / Subject**: support SimpleLanguage. Always parameterize From with a recognized
  domain — most receivers reject mail with a mismatched From.
- **Protection**: pick `STARTTLS Mandatory` for any production endpoint.
- **Mail Body**: text or HTML; for HTML, set the `Content-Type` header to `text/html`.
- **Attachments**: attach the original payload by mapping `${in.body}` to an attachment.

## When to Use

- Notifying an integration owner when an Exception Subprocess fires.
- Sending a daily reconciliation report to a distribution list.
- Forwarding an unparseable inbound payload to a human for triage.

Do **not** use the Mail Receiver as a critical integration channel — SMTP is best-effort, not
guaranteed delivery. Use a JMS queue + retry for guaranteed flows.

## Pairing

Inside an Exception Subprocess:

```
Exception Subprocess
  → Content Modifier (build HTML body with MPL link)
  → Mail Receiver (To: integration-owners@example.com, Subject: ${header.SAP_FlowName} failed)
```

## Anti-Patterns

- Sending mail per record from a Splitter — your inbox will hate you. Aggregate first, then send
  one summary message.
- Using a personal mailbox as From — many tenants flag it as phishing.
- Putting the entire payload in the subject line — most servers truncate at 998 characters.

## Throttling and Quotas

The Mail Receiver respects the upstream SMTP server's rate limits. CPI does not retry on `5xx`
SMTP errors by default — wrap in an Exception Subprocess if the receiving server bursts.
