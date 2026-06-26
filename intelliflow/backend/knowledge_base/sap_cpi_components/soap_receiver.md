---
topic: soap_receiver
adapter_type: SOAP Receiver
protocol: SOAP
pattern_family: synchronous
cpi_version: "2024.05"
---

# SOAP Receiver Adapter

## Overview

The SOAP Receiver adapter sends a SOAP 1.1 or 1.2 envelope to an external web service. It is the
canonical outbound adapter when calling SAP backends (ECC, S/4HANA on-premise via SOAP services,
SuccessFactors SFAPI, Concur, Fieldglass) or any partner exposing a WSDL contract.

## Key Configuration Properties

- **Address**: full URL of the SOAP endpoint (`https://...`).
- **Proxy Type**: `Internet` for public endpoints, `On-Premise` when routing through Cloud Connector.
- **Authentication**: `Basic`, `Client Certificate`, `OAuth2 Client Credentials`, or `Principal Propagation`.
- **WS-Addressing**: enable when the partner requires `wsa:Action` headers.
- **Allow Chunking**: disable for legacy SAP backends that reject chunked transfer encoding.

## When to Use

- Calling SAP ECC RFC-exposed-as-SOAP services.
- Pushing data into S/4HANA on-premise via the standard SOAP services published in Customizing.
- Integrating with partner systems that publish a WSDL.

Prefer the **OData Receiver** for any S/4HANA Cloud target — OData is the strategic API surface.
Use the **HTTPS Receiver** for REST/JSON; SOAP Receiver is strictly for SOAP envelopes.

## Error Behaviour

A SOAP fault is converted into a `MessagingException` with the fault string in the message body.
Wire the **Exception Subprocess** to log the fault to the monitoring tile and route the original
payload to a dead-letter queue (typically a JMS Receiver pointing at `cpi.dlq.<flow_name>`).

## Pairing

```
Content Modifier (set SOAPAction header)
  → Message Mapping (canonical → partner schema)
  → SOAP Receiver
```

Wrap the call in an Exception Subprocess to capture `SoapFaultException` and log structured details
(fault code, fault string, message processing log ID).

## Performance

- Set the connection timeout to **60s** and the request timeout to **300s** for batch endpoints.
- Avoid per-record SOAP calls — batch with a Splitter+Aggregator pair where the partner supports it.
- Enable response compression (`Accept-Encoding: gzip`) for endpoints returning large payloads.

## Security

- Always pin the partner certificate in the CPI keystore.
- Rotate Basic credentials at least every 90 days; switch to OAuth Client Credentials when possible.

## Common Pitfalls

1. Setting `Content-Type: text/xml` but the partner requires `application/soap+xml` for SOAP 1.2 →
   results in `415 Unsupported Media Type`.
2. Forgetting `<SOAP-ENV:Header/>` when the partner expects it as a hint for routing — symptom: silent
   `200 OK` with empty body.
3. Using the SOAP Receiver against an S/4HANA Cloud endpoint that only supports OData; results in a
   `404 Not Found` or `405 Method Not Allowed`.
