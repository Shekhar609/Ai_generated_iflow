---
topic: message_mapping_xslt
adapter_type: Message Mapping
protocol: any
pattern_family: transformation
cpi_version: "2024.05"
---

# XSLT Mapping

## Overview

XSLT Mapping applies an XSLT 1.0 or 2.0 stylesheet to the current XML body. It is the right tool
when the graphical Message Mapping cannot express the transformation cleanly — typically because
the transformation depends on grouping, sorting, or recursive logic.

## When to Use vs. Graphical Mapping

| Concern                                  | XSLT      | Graphical |
|------------------------------------------|-----------|-----------|
| Grouping `<Item>` by `Category`          | natural   | painful   |
| Conditional sibling selection            | easy      | easy      |
| Sort by multiple keys                    | trivial   | UDF       |
| Maintain by non-developer                | hard      | easier    |
| Streaming large input                    | yes       | no        |
| 1:1 schema mapping                       | overkill  | natural   |

## Skeleton

```xml
<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet version="2.0"
                xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
                xmlns:xs="http://www.w3.org/2001/XMLSchema">

  <xsl:output method="xml" indent="yes"/>

  <xsl:template match="/Orders">
    <Batch>
      <xsl:for-each-group select="Order" group-by="Customer/Id">
        <CustomerBatch customerId="{current-grouping-key()}">
          <xsl:for-each select="current-group()">
            <Order id="{@id}">
              <Total>
                <xsl:value-of select="sum(LineItem/Amount)"/>
              </Total>
            </Order>
          </xsl:for-each>
        </CustomerBatch>
      </xsl:for-each-group>
    </Batch>
  </xsl:template>

</xsl:stylesheet>
```

## Streaming

CPI runs XSLT through Saxon. For payloads >50 MB enable Streaming on the XSLT Mapping step and
write streamable templates (`xsl:stream`, `xsl:iterate`). Standard `for-each` requires the whole
DOM and will OOM.

## Pitfalls

1. Targeting `XSLT 1.0` semantics on Saxon — Saxon defaults to 2.0; some 1.0 idioms produce
   different results (e.g. `string` casts).
2. Embedding business logic in XSLT that should live in a Value Mapping; XSLT changes require
   a redeploy.
3. Forgetting `<xsl:output encoding="UTF-8"/>` — downstream consumers see ISO-8859-1 garbage
   when source had multi-byte characters.
