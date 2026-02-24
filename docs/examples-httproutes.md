# Example: HTTPRoutes

HTTPRoutes are annotated to tell the operator which tenant, template, and hostname to use. They live with each application — not in the operator's namespace.

## Annotation reference

| Annotation | Description |
|---|---|
| `cfzt.cloudflare.com/enabled` | `"true"` to opt this route into operator management |
| `cfzt.cloudflare.com/hostname` | Public hostname to publish (required) |
| `cfzt.cloudflare.com/tenant` | Name of the `CloudflareZeroTrustTenant` CR |
| `cfzt.cloudflare.com/template` | Name of a `CloudflareZeroTrustTemplate` CR (optional) |
| `cfzt.cloudflare.com/dnsIp` | Private IP for `internal-dnsonly` routes |
| `cfzt.cloudflare.com/origin.url` | Override origin URL |
| `cfzt.cloudflare.com/origin.noTLSVerify` | Override TLS verification |
| `cfzt.cloudflare.com/access.enabled` | Override Access Application enabled flag |
| `cfzt.cloudflare.com/access.existingPolicyNames` | Comma-separated policy names |
| `cfzt.cloudflare.com/access.sessionDuration` | Override session duration |
| `cfzt.cloudflare.com/access.autoRedirectToIdentity` | Override auto-redirect |
| `cfzt.cloudflare.com/access.appLauncherVisible` | Override App Launcher visibility |
| `cfzt.cloudflare.com/access.serviceAuth401Redirect` | Override 401 redirect behaviour |
| `cfzt.cloudflare.com/access.skipInterstitial` | Override interstitial page |
| `cfzt.cloudflare.com/access.httpOnlyCookieAttribute` | Override HttpOnly cookie flag |
| `cfzt.cloudflare.com/access.sameSiteCookieAttribute` | Override SameSite cookie value |
| `cfzt.cloudflare.com/serviceToken.enabled` | Override Service Token enabled flag |
| `cfzt.cloudflare.com/serviceToken.duration` | Override Service Token duration |

---

## Example 1: Route using a template

The template holds all settings. The HTTPRoute only needs a template name and hostname.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: my-app
  namespace: my-app
  annotations:
    cfzt.cloudflare.com/enabled: "true"
    cfzt.cloudflare.com/hostname: "my-app.example.com"
    cfzt.cloudflare.com/tenant: "prod"
    cfzt.cloudflare.com/template: "protected-adauth"
spec:
  parentRefs:
    - name: default
      namespace: my-app
  hostnames:
    - "my-app.example.com"
  rules:
    - backendRefs:
        - name: my-app
          port: 8080
```

---

## Example 2: No template — all settings as annotations

Identical result to Example 1, but every setting is specified directly on the HTTPRoute. Useful when a route needs settings that don't fit any existing template.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: my-other-app
  namespace: my-other-app
  annotations:
    cfzt.cloudflare.com/enabled: "true"
    cfzt.cloudflare.com/hostname: "other-app.example.com"
    cfzt.cloudflare.com/tenant: "prod"
    # No template — all settings come from annotations below.
    cfzt.cloudflare.com/origin.url: "https://traefik.traefik.svc.cluster.local:443"
    cfzt.cloudflare.com/origin.noTLSVerify: "true"
    cfzt.cloudflare.com/access.enabled: "true"
    cfzt.cloudflare.com/access.existingPolicyNames: "My ADAUTH Policy"
    cfzt.cloudflare.com/access.sessionDuration: "24h"
    cfzt.cloudflare.com/access.autoRedirectToIdentity: "true"
    cfzt.cloudflare.com/access.appLauncherVisible: "true"
    cfzt.cloudflare.com/access.httpOnlyCookieAttribute: "true"
    cfzt.cloudflare.com/access.sameSiteCookieAttribute: "lax"
spec:
  parentRefs:
    - name: default
      namespace: my-other-app
  hostnames:
    - "other-app.example.com"
  rules:
    - backendRefs:
        - name: my-other-app
          port: 8080
```

---

## Example 3: Machine-to-machine route using a template

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: my-api
  namespace: my-api
  annotations:
    cfzt.cloudflare.com/enabled: "true"
    cfzt.cloudflare.com/hostname: "api.example.com"
    cfzt.cloudflare.com/tenant: "prod"
    cfzt.cloudflare.com/template: "protected-service-cred"
spec:
  parentRefs:
    - name: default
      namespace: my-api
  hostnames:
    - "api.example.com"
  rules:
    - backendRefs:
        - name: my-api
          port: 8080
```

---

## Example 4: Machine-to-machine route — all settings as annotations

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: my-other-api
  namespace: my-other-api
  annotations:
    cfzt.cloudflare.com/enabled: "true"
    cfzt.cloudflare.com/hostname: "other-api.example.com"
    cfzt.cloudflare.com/tenant: "prod"
    cfzt.cloudflare.com/origin.url: "https://traefik.traefik.svc.cluster.local:443"
    cfzt.cloudflare.com/origin.noTLSVerify: "true"
    cfzt.cloudflare.com/access.enabled: "true"
    cfzt.cloudflare.com/access.existingPolicyNames: "My Service Token Policy"
    cfzt.cloudflare.com/access.serviceAuth401Redirect: "true"
    cfzt.cloudflare.com/access.appLauncherVisible: "false"
    cfzt.cloudflare.com/access.skipInterstitial: "true"
    cfzt.cloudflare.com/access.sameSiteCookieAttribute: "none"
spec:
  parentRefs:
    - name: default
      namespace: my-other-api
  hostnames:
    - "other-api.example.com"
  rules:
    - backendRefs:
        - name: my-other-api
          port: 8080
```

---

## Example 5: DNS-only route (private A record)

Creates a plain Cloudflare DNS A record — no tunnel, no Access Application. The target IP must be a private RFC 1918 address supplied via annotation per-route.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: internal-service
  namespace: internal
  annotations:
    cfzt.cloudflare.com/enabled: "true"
    cfzt.cloudflare.com/hostname: "nas.example.com"
    cfzt.cloudflare.com/tenant: "prod"
    cfzt.cloudflare.com/template: "internal-dnsonly"
    cfzt.cloudflare.com/dnsIp: "192.168.1.50"   # RFC 1918 private address required
spec:
  parentRefs:
    - name: default
      namespace: internal
  hostnames:
    - "nas.example.com"
  rules:
    - backendRefs:
        - name: nas
          port: 443
```
