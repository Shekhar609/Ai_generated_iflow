---
topic: sftp_adapters
adapter_type: SFTP Sender
protocol: SFTP
pattern_family: batch_file
cpi_version: "2024.05"
---

# SFTP Sender and SFTP Receiver

## Overview

SFTP adapters move files between SAP CPI and partner SFTP servers. The **SFTP Sender** polls a
remote directory at a fixed interval and pulls each matching file as a CPI message. The **SFTP
Receiver** writes the current message body to a remote directory.

## SFTP Sender Configuration

- **Address**: `sftp.partner.example.com:22`.
- **Path**: `/in/orders/`.
- **File Name Pattern**: glob like `*.csv` or `ORDER_*.xml`.
- **Polling Interval**: minimum 1 minute; for higher cadence use a JMS bridge.
- **Post-Processing**: `Delete`, `Move to <archive_dir>`, or `Keep` (requires idempotent dedup).
- **Authentication**: `User/Password`, `Public Key`, or `Dual` (key + password).

## SFTP Receiver Configuration

- **Address / Path / File Name**: support SimpleLanguage so the file name can include date and
  message ID, e.g. `ORDER_${date:now:yyyyMMddHHmmss}_${header.SAP_MessageProcessingLogID}.xml`.
- **Append / Overwrite / Append Time Stamp**: pick `Append Time Stamp` for safe writes; never
  `Overwrite` to a shared directory.
- **Create Temporary File**: enable; the file is uploaded with a `.tmp` suffix and atomically
  renamed on success. Partners that watch the directory will not see partial files.

## When to Use

- Batch end-of-day file exchanges with partners that do not expose APIs.
- Bank statement (MT940 / CAMT.053) ingestion.
- Legacy mainframe interfaces using fixed-format files.

Prefer the **AS2** or **AS4** adapter for B2B EDI with non-repudiation requirements; SFTP alone
does not give you signed receipts.

## Idempotency

Always pair the SFTP Sender with the **Idempotent Process Call** option enabled. CPI keeps a
record of consumed file names per flow; without it, a partner that fails to delete and re-lists
the file will be re-processed.

## Performance

- The SFTP Sender is single-threaded per flow. For high file volumes, run multiple deployments
  with disjoint file-name patterns (`A-M_*.csv` and `N-Z_*.csv`).
- Reading 1000 small files is slower than one big file — encourage partners to batch.

## Pitfalls

1. Forgetting `Create Temporary File` on the Receiver — partners see partial files and process
   them with truncated rows.
2. Using `Delete` post-processing without confirming the partner has acknowledged — a CPI crash
   between read and delete causes message loss only if the dedup table also rolls back, which it
   does. Safer is `Move to archive`.
3. Polling every 30 seconds with a partner that lists 10k files; SFTP `LIST` becomes the
   bottleneck and the flow falls behind.
