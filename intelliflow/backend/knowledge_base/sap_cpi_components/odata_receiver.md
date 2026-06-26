---
topic: odata_receiver
adapter_type: OData Receiver
protocol: OData
pattern_family: synchronous
cpi_version: "2024.05"
---

# OData Receiver Adapter

## Overview

The OData Receiver adapter is the strategic outbound channel for SAP cloud backends. Use it for
S/4HANA Cloud, SAP SuccessFactors, SAP Marketing Cloud, SAP Customer Experience, and any partner
exposing an OData v2 or v4 service.

## Key Configuration Properties

- **Address**: the service root (`https://my300000.s4hana.cloud.sap/sap/opu/odata/sap/API_BUSINESS_PARTNER`).
- **Resource Path**: the entity collection (`A_BusinessPartner`).
- **Operation**: `Query (GET)`, `Read (GET)`, `Create (POST)`, `Update (PUT)`, `Patch (MERGE)`, `Delete (DELETE)`.
- **Authentication**: `OAuth2 Client Credentials` (preferred), `Basic`, or `Principal Propagation`.
- **CSRF Fetch**: enable for modifying operations on services that require it (S/4HANA defaults to on).
- **Page Size**: default `1000`; lower for endpoints that return large records.

## When to Use

- Any modern SAP cloud backend.
- Querying or modifying business objects with `$filter`, `$expand`, `$orderby`, `$top`, `$skip`.
- Bulk reads via OData v4 `$batch` requests.

Do not use OData Receiver for fire-and-forget posting of large XML payloads — prefer an
**HTTPS Receiver** to a custom inbox; OData is structured around entity semantics.

## Query Modeling Tips

- Build the `$filter` clause in a Content Modifier before the OData Receiver so the URL is visible
  in the trace log.
- For server-side paging, set `Process in Pages of` to enable the streaming Splitter pattern.
- Always include `$select` for production flows — fetching every property is the #1 latency culprit.

## Error Behaviour

OData errors arrive as an `<error>` element with `<code>` and `<message>`. Use a Router to branch
on `${header.CamelHttpResponseCode}`:

- `200/201/204` → success path
- `400/409` → validation/concurrency error subprocess
- `401/403` → re-authenticate (CSRF token expired) and retry once
- `500/502/503` → exponential backoff via Exception Subprocess

## Pairing

```
HTTPS Sender → Content Modifier (build $filter)
            → OData Receiver (GET A_BusinessPartner)
            → Message Mapping (OData JSON/XML → canonical)
            → HTTPS Receiver (return to caller)
```

## Performance

- Cache CSRF tokens for the duration of a single message processing (CPI does this automatically).
- Use `$top=1000` with paging rather than unbounded queries.
- Push down filtering to the server — never read everything then `Filter` in CPI.

## Common Pitfalls

1. Forgetting `$select` and pulling 200 properties when you need 5.
2. Hard-coding the service host instead of using a Cloud Connector destination — breaks on tenant
   migration.
3. Treating OData like REST — `MERGE` (PATCH) is the partial-update verb, not `PUT`.
4. Not handling the `__next` link in v2 responses → silently dropping pages 2..N.
