---
topic: pattern_file_to_api
adapter_type: SFTP Sender
protocol: SFTP
pattern_family: batch_file
cpi_version: "2024.05"
---

# Pattern: File-to-API (SFTP → REST/OData)

## Intent

Poll an SFTP location, parse each file into N records, post each record to a backend API, and
write a summary report back to the partner.

## When to Use

- Partner produces nightly CSV / XML / EDI files.
- Backend has per-record API endpoints (no bulk import).
- You need a reconciliation report (counts, errors) sent back to the partner.

## Reference Implementation

```
SFTP Sender (poll /in/orders, *.csv, post-process: Move to /in/orders/archive)
  → Content Modifier (set property fileName = ${header.CamelFileName})
  → CSV to XML Converter
  → XML Validator (XSD: orders_batch.xsd, interrupt=No)
  → Router
       │
       ├── invalid
       │     → Content Modifier (build rejection report)
       │     → SFTP Receiver (/out/reports/${property.fileName}_REJECTED.txt)
       │
       └── valid
             → Splitter (XPath: /Orders/Order)
                  → Message Mapping (canonical → backend POST body)
                  → OData Receiver (POST /Orders)
                  → Filter (capture status, error reason)
             → Aggregator (Size=Last Message, strategy=Combine)
             → Message Mapping (combined → report XML)
             → SFTP Receiver (/out/reports/${property.fileName}_REPORT.xml)
```

## Required Components

- SFTP Sender (poll + post-process: Move)
- Content Modifier
- CSV-to-XML converter (or direct XML reader)
- XML Validator
- Router (valid / invalid)
- Splitter + Aggregator
- Message Mapping (two: per-record, then summary)
- OData Receiver
- Filter (drop per-record body, keep status header)
- SFTP Receiver (for the report)
- Exception Subprocess for terminal SFTP failure

## Volumes and Performance

For files up to 100k records, expect a single-thread pass in ~10 minutes against a backend with
50 ms p50 latency. Beyond that, run parallel Splitters or batch the backend calls with `$batch`.

## Reconciliation Discipline

Always write the report back, even on full success — partners expect the file as a heartbeat.
Include `total_records`, `succeeded`, `failed`, and per-failure `error_code` + `error_message`.

## Pitfalls

1. Skipping the XML Validator and discovering schema drift mid-batch — Splitter has already
   committed half the records to the backend.
2. Using a single `OData Receiver` per record without retry logic — one transient `502` rolls
   back nothing and the report quietly under-reports successes.
3. Not archiving processed files — repeated re-polling of the same file with `Delete` disabled.
