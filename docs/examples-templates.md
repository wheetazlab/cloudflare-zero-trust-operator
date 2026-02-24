# Example: CloudflareZeroTrustTemplates

Templates define reusable origin, TLS, Access Application, and Service Token settings that are referenced by HTTPRoutes. They are installed automatically by the Helm chart and can be opted out via `exampleTemplates.install: false` in values.

## Merge order

```
base-<tenant-name>  →  per-route template  →  annotation overrides
```

The operator discovers the base template by naming convention — no field on the tenant CR.

---

## base-\<tenant-name\>

The base template establishes defaults for every route under a tenant. Name it `base-<tenant-name>` (e.g. `base-my-tenant`).

```yaml
apiVersion: cfzt.cloudflare.com/v1alpha1
kind: CloudflareZeroTrustTemplate
metadata:
  name: base-mytenant  # pattern: base-<tenant-name> — change to match your tenant CR name
  namespace: cloudflare-zero-trust-operator
spec:
  originService:
    url: "https://traefik.traefik.svc.cluster.local:443"
    httpRedirect: true
    originTLS:
      noTLSVerify: true
      tlsTimeout: 10
      http2Origin: false
      matchSNIToHost: false

  accessApplication:
    enabled: false

  serviceToken:
    enabled: false
```

---

## protected-adauth

Tunnel route protected by an existing Cloudflare Access policy using identity-based auth. Suitable for human/browser consumers that authenticate via an identity provider.

`originService` is intentionally absent — inherited from the base template.

```yaml
apiVersion: cfzt.cloudflare.com/v1alpha1
kind: CloudflareZeroTrustTemplate
metadata:
  name: protected-adauth
  namespace: cloudflare-zero-trust-operator
spec:
  accessApplication:
    enabled: true
    sessionDuration: "24h"
    existingPolicyNames:
      - "ADAUTH"   # Cloudflare Access policy name — operator resolves to UUID at reconcile time
    autoRedirectToIdentity: true
    appLauncherVisible: true
    skipInterstitial: false
    httpOnlyCookieAttribute: true
    sameSiteCookieAttribute: "lax"
```

---

## unprotected-public

Tunnel route with no Cloudflare Access gate. Suitable for intentionally public-facing services.

`originService` is intentionally absent — inherited from the base template.

```yaml
apiVersion: cfzt.cloudflare.com/v1alpha1
kind: CloudflareZeroTrustTemplate
metadata:
  name: unprotected-public
  namespace: cloudflare-zero-trust-operator
spec:
  accessApplication:
    enabled: false
```

---

## protected-service-cred

Tunnel route for machine-to-machine access using a non_identity Access policy. No browser/human auth — intended for API and CLI consumers. `serviceAuth401Redirect: true` returns HTTP 401 instead of a browser redirect.

Only the fields that differ from the base template are specified here.

```yaml
apiVersion: cfzt.cloudflare.com/v1alpha1
kind: CloudflareZeroTrustTemplate
metadata:
  name: protected-service-cred
  namespace: cloudflare-zero-trust-operator
spec:
  # base: httpRedirect=true, tlsTimeout=10 — overridden below for API consumers
  originService:
    httpRedirect: false   # base: true — API/CLI consumers must not be redirected at the edge
    originTLS:
      tlsTimeout: 15      # base: 10 — slightly longer timeout for service protocol handshakes

  accessApplication:
    enabled: true
    sessionDuration: "24h"
    existingPolicyNames:
      - "ServiceCred"   # Cloudflare Access policy name — operator resolves to UUID at reconcile time
    serviceAuth401Redirect: true
    appLauncherVisible: false
    skipInterstitial: true
    httpOnlyCookieAttribute: true
    sameSiteCookieAttribute: "none"
```

---

## internal-dnsonly

Creates a plain Cloudflare DNS A record pointing at a private cluster IP. No tunnel, no Access Application.

The target IP is supplied per-route via annotation — **not** in the template:

```
cfzt.cloudflare.com/dnsIp: "192.168.x.x"
```

The operator validates the IP is in an RFC 1918 private CIDR block (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`) and rejects public addresses at reconciliation time.

```yaml
apiVersion: cfzt.cloudflare.com/v1alpha1
kind: CloudflareZeroTrustTemplate
metadata:
  name: internal-dnsonly
  namespace: cloudflare-zero-trust-operator
spec:
  dnsOnly:
    enabled: true
    proxied: false
    ttl: 120
    # staticIp is intentionally absent — supply cfzt.cloudflare.com/dnsIp on each HTTPRoute.
    # Optionally set ingressServiceRef here to auto-discover from a LoadBalancer Service.
```
