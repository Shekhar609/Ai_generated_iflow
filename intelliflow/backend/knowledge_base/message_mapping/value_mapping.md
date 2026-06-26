---
topic: message_mapping_value_mapping
adapter_type: Message Mapping
protocol: any
pattern_family: transformation
cpi_version: "2024.05"
---

# Value Mapping

## Overview

Value Mapping translates code values between agency/schema systems — for example, ISO country
codes to SAP country codes, or partner-specific currency codes to ISO 4217. The mapping table is
maintained as a separate artifact and shared across flows.

## Configuration

- **Source Agency / Identifier**: e.g. `PartnerA / CountryCode`.
- **Target Agency / Identifier**: e.g. `SAP / Country`.
- **Mappings**: a table of `(source_value, target_value)` rows.
- **Default Value**: applied when no mapping matches; leave empty to throw an error.

## Usage Inside Message Mapping

In a graphical mapping, drag a **valueMapping** standard function into a field's expression. The
function takes the source agency/identifier, the target agency/identifier, and the source value
as inputs.

## When to Use

- Code conversions where the mapping table changes more often than the flow itself.
- Lookups shared across multiple flows (one table, many mappers).
- Audit-sensitive translations where business owners maintain the table directly via the Value
  Mapping editor — not via redeploy.

## Pairing

```
Message Mapping
  ├── source field "Country"
  └── target field "LandCode"
       └── valueMapping("PartnerA","Country","SAP","Land",${source.Country})
```

## Pitfalls

1. Hard-coding mappings in a Groovy UDF instead of using Value Mapping — business users now
   need a developer for every change.
2. Forgetting to deploy the Value Mapping artifact after editing — runtime sees the previous
   version until the next deploy.
3. Leaving the default value empty without an Exception Subprocess — unmapped values bring
   down the flow.
