---
topic: groovy_signing
adapter_type: Groovy Script
protocol: any
pattern_family: scripting
cpi_version: "2024.05"
---

# Groovy: HMAC Signing and Hashing

## Overview

Many partner APIs require an HMAC-SHA256 signature of the canonical request, base64-encoded and
sent in a header. CPI does not provide a declarative step for this; a Groovy script is the
standard solution.

## HMAC-SHA256 Signing

```groovy
import com.sap.gateway.ip.core.customdev.util.Message
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

Message processData(Message message) {
    def body = message.getBody(String) ?: ""
    def secret = message.getProperty("apiSecret") as String
    def timestamp = new Date().toInstant().toString()

    def canonical = "${timestamp}\n${body}"
    def mac = Mac.getInstance("HmacSHA256")
    mac.init(new SecretKeySpec(secret.bytes, "HmacSHA256"))
    def signature = mac.doFinal(canonical.bytes).encodeBase64().toString()

    message.setHeader("X-Timestamp", timestamp)
    message.setHeader("X-Signature", signature)
    return message
}
```

## Loading the Secret

Never hardcode. Read from a Secure Parameter:

```groovy
import com.sap.it.api.ITApiFactory
def credService = ITApiFactory.getApi(com.sap.it.api.securestore.SecureStoreService, null)
def cred = credService.getUserCredential("partner-api-secret")
def secret = new String(cred.getPassword())
```

## Hashing

```groovy
import java.security.MessageDigest

def md = MessageDigest.getInstance("SHA-256")
def hashHex = md.digest(payload.bytes).encodeHex().toString()
```

## JWT Construction

For OAuth client assertions, build the JWT manually (when no library is available):

```groovy
def header = '{"alg":"RS256","typ":"JWT"}'.bytes.encodeBase64Url()
def payload = body.bytes.encodeBase64Url()
def toSign = "${header}.${payload}"
def sig = sign(toSign.bytes, privateKey).encodeBase64Url()
def jwt = "${toSign}.${sig}"
```

Use a PrivateKey loaded from the keystore via `KeystoreService`, not pasted into the script.

## Pitfalls

1. Using `encodeBase64Url` (Groovy 3+) vs. `encodeBase64()` — JWT needs URL-safe; partner APIs
   vary. Read their docs.
2. Including a trailing newline in the canonical string — invalidates the signature against a
   strict server.
3. Logging the signature value to the trace log — defeats the integrity guarantee.
