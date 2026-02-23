# cloudflare-zero-trust-operator Helm Chart

Installs the **Cloudflare Zero Trust Operator** — an Ansible-based Kubernetes operator that watches `HTTPRoute` resources and reconciles them with the Cloudflare API to manage tunnel routing, Access Applications, and service tokens.

## How it works

The operator container ships Ansible roles internally. The Helm chart's job is to:

1. Install the four CRDs (from `crds/` — Helm applies these before any templates)
2. Create the namespace, ServiceAccount, and ClusterRole/ClusterRoleBinding
3. Deploy the **manager** container (`ROLE=manager`) with runtime configuration via environment variables
4. Optionally create the `CloudflareZeroTrustTenant` CR (and its API token Secret) if `tenant.create=true`

### Three-tier deployment

After the manager pod starts, it creates two additional worker Deployments in the same namespace:

| Pod | `ROLE` env | Responsibility |
|-----|-----------|----------------|
| **manager** | `manager` | Watches `CloudflareZeroTrustOperatorConfig` CR; applies self-updates; keeps worker Deployments alive |
| **kube_worker** | `kube_worker` | Lists HTTPRoutes + Tenants; detects annotation changes; creates `CloudflareTask` CRs |
| **cloudflare_worker** | `cloudflare_worker` | Claims `CloudflareTask` CRs; executes all Cloudflare REST API calls; writes result IDs back |

`CloudflareTask` is an internal CRD that acts as a work queue between the two workers, decoupling Kubernetes API access from Cloudflare API calls.

---

## Requirements

The following must be in place **before** installing this chart:

| Requirement | Notes |
|---|---|
| Kubernetes **1.25+** | Earlier versions are untested |
| **Gateway API CRDs** installed | `httproutes.gateway.networking.k8s.io` must exist — see [Gateway API install guide](https://gateway-api.sigs.k8s.io/guides/#installing-gateway-api) |
| A **Cloudflare API token** | Must have _Account → Cloudflare Tunnel: Edit_ and _Account → Access: Edit_ permissions |
| An **existing Cloudflare Tunnel** | You need both the **Account ID** and **Tunnel ID** before deploying a tenant |
| The **operator container image** built and pushed | Image is built from this repo's `container/` directory; tag a `v*.*.*` release or run the workflow manually to publish it |

### Where to find your Cloudflare IDs

| Value | Where to find it |
|---|---|
| **Account ID** | Cloudflare dashboard → right sidebar → _Account ID_ (32-char hex) |
| **Tunnel ID** | Cloudflare dashboard → Zero Trust → Networks → Tunnels → click tunnel → UUID in URL |
| **Zone ID** | Cloudflare dashboard → select domain → right sidebar → _Zone ID_ (optional, 32-char hex) |

---

## Cloudflare API Token

### Required permissions

The operator makes calls to four Cloudflare API surface areas. When creating a token at
**My Profile → API Tokens → Create Token → Custom Token**, grant the following:

| Permission | Level | Access | Why |
|---|---|---|---|
| **Cloudflare Tunnel** | Account | Edit | Read and write tunnel ingress rules (publish/remove hostname routes) |
| **Access: Apps and Policies** | Account | Edit | Create and update Access Applications; attach existing policies and groups to them |
| **Access: Service Tokens** | Account | Edit | Create service tokens for machine-to-machine access |
| **Zone: DNS** | Zone | Edit | Create the CNAME record for each tunnel hostname route, and A records in dns-only mode. Required whenever `tenant.zoneId` is set. |

> **Note on existing policies:** The operator references policies and groups by their ID when attaching them to
> Access Applications. It does **not** create or modify Identity Provider policies or Access Groups —
> those must already exist in your Zero Trust dashboard before the operator references them.
> _Access: Apps and Policies: Edit_ is still required even when only referencing existing groups,
> because attaching a policy to an application is itself a write operation.

> **DNS is not managed by this operator** in tunnel mode. Tunnel hostname routes are written directly to the tunnel
> configuration (`cfd_tunnel` API). You are responsible for the CNAME DNS records that point your
> hostnames at the tunnel (e.g. `<tunnel-id>.cfargotunnel.com`). Those can be created manually or via
> the Cloudflare dashboard.
>
> **In tunnel mode**, when `tenant.zoneId` is set the operator automatically creates the CNAME record
> `<hostname> CNAME <tunnel-id>.cfargotunnel.com` (proxied, TTL auto) after writing the tunnel ingress
> rule. The record ID is stored in `cfzt.cloudflare.com/cnameRecordId` on the HTTPRoute for
> idempotent updates. If `zoneId` is **not** set, the operator logs a warning and you must create
> the CNAME manually.
>
> **In dns-only mode** the operator creates an A record pointing directly at your cluster IP.
> `Zone: DNS: Edit` and `zoneId` on the tenant are both required.

### How to create the token

1. Go to [dash.cloudflare.com](https://dash.cloudflare.com) → **My Profile** → **API Tokens**
2. Click **Create Token** → **Custom Token** → **Get started**
3. Under **Permissions**, add:
   - Account → **Cloudflare Tunnel** → **Edit**
   - Account → **Access: Apps and Policies** → **Edit**
   - Account → **Access: Service Tokens** → **Edit**
4. Under **Account Resources**, select the specific account (or _All accounts_)
5. Click **Continue to summary** → **Create Token**
6. Copy the token — **it is only shown once**

Store it in a Kubernetes Secret:

```bash
kubectl create secret generic prod-tenant-api-token \
  --from-literal=token=<YOUR_TOKEN> \
  --namespace cloudflare-zero-trust
```

Or pass it inline at install time (Helm will create the Secret for you):

```bash
helm install cloudflare-zero-trust-operator ./charts/cloudflare-zero-trust-operator \
  --namespace cloudflare-zero-trust \
  --create-namespace \
  --set tenant.create=true \
  --set tenant.name=prod-tenant \
  --set tenant.accountId=<ACCOUNT_ID> \
  --set tenant.tunnelId=<TUNNEL_ID> \
  --set tenant.apiToken=<YOUR_TOKEN>
```

---

## Install

### Operator only (no tenant created)

Install the operator and create tenant resources manually afterwards:

```bash
helm install cloudflare-zero-trust-operator ./charts/cloudflare-zero-trust-operator \
  --namespace cloudflare-zero-trust \
  --create-namespace
```

### Operator + tenant bootstrap via values file (recommended)

Create a `my-values.yaml` — **do not put secrets in version control**:

```yaml
# my-values.yaml

operator:
  logLevel: INFO
  pollIntervalSeconds: 60
  watchNamespaces: ""   # empty = watch all namespaces

tenant:
  create: true
  name: "prod-tenant"                              # required — choose a meaningful name
  accountId: "abcdef1234567890abcdef1234567890"    # required — 32-char hex
  tunnelId:  "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" # required — UUID
  zoneId:    "fedcba0987654321fedcba0987654321"    # optional

  # Option A — inline token (Helm creates the Secret for you):
  apiToken: "your-cloudflare-api-token"

  # Option B — use a Secret you've already created in the cluster
  #             (takes precedence over apiToken when both are set):
  # existingSecret:
  #   name: "my-cf-token-secret"
  #   key: "token"

  defaults:
    sessionDuration: "24h"
    originService: "http://traefik.traefik.svc.cluster.local:80"
    httpRedirect: true
    originTLS:
      noTLSVerify: true
      tlsTimeout: 10
      http2Origin: false
      matchSNIToHost: false
```

Install with the values file:

```bash
helm install cloudflare-zero-trust-operator ./charts/cloudflare-zero-trust-operator \
  --namespace cloudflare-zero-trust \
  --create-namespace \
  -f my-values.yaml
```

### What `tenant.create=true` produces

When all required tenant values are supplied, Helm renders:

1. A `Secret` named `<tenant.name>-api-token` (only when `apiToken` is set)
2. A `CloudflareZeroTrustTenant` CR pointing `credentialRef` at that Secret

**The chart will fail at render time if any of the following are missing:**

| Missing value | Error |
|---|---|
| `tenant.name` | `tenant.name is required when tenant.create=true` |
| `tenant.accountId` | `tenant.accountId is required when tenant.create=true` |
| `tenant.tunnelId` | `tenant.tunnelId is required when tenant.create=true` |
| both `apiToken` and `existingSecret.name` empty | `Either tenant.apiToken or tenant.existingSecret.name must be set when tenant.create=true` |

---

## DNS-only mode (internal / direct-to-cluster routing)

When you want a Cloudflare DNS entry that points directly at your cluster's VIP or
LoadBalancer IP — without routing traffic through a tunnel — use a dns-only template.

### When to use it

- Services only reachable on your internal network (LAN, VPN)
- Split-horizon DNS — Cloudflare holds the record but traffic never leaves your network
- You already have a LoadBalancer (MetalLB, etc.) assigning IPs to services

### What it does

- Creates (or updates) a Cloudflare DNS **A record** for the hostname
- Cloudflare proxy is **off** by default — traffic hits your cluster IP directly
- The `cfzt.cloudflare.com/dnsRecordId` and `cfzt.cloudflare.com/dnsRecordIp` annotations
  are written back to the HTTPRoute for idempotent reconciliation
- Access Application and Service Token features are **not available** in this mode

### Requirements

- `tenant.zoneId` **must** be set on the `CloudflareZeroTrustTenant`
- API token needs the additional **Zone: DNS: Edit** permission (see above)

### Template: static IP

```yaml
apiVersion: cfzt.cloudflare.com/v1alpha1
kind: CloudflareZeroTrustTemplate
metadata:
  name: internal-static
  namespace: cloudflare-zero-trust
spec:
  tenantRef: prod-tenant   # tenant must have zoneId set
  dnsOnly:
    enabled: true
    staticIp: "192.168.10.100"   # your MetalLB VIP or fixed cluster IP
    proxied: false
    ttl: 120
```

### Template: auto-discover IP from a LoadBalancer Service

```yaml
apiVersion: cfzt.cloudflare.com/v1alpha1
kind: CloudflareZeroTrustTemplate
metadata:
  name: internal-auto
  namespace: cloudflare-zero-trust
spec:
  tenantRef: prod-tenant
  dnsOnly:
    enabled: true
    ingressServiceRef:
      name: traefik         # Service to read .status.loadBalancer.ingress[0].ip from
      namespace: traefik    # omit to default to the HTTPRoute's namespace
    proxied: false
    ttl: 120
```

### Annotate an HTTPRoute to use it

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: homeassistant
  namespace: default
  annotations:
    cfzt.cloudflare.com/enabled: "true"
    cfzt.cloudflare.com/tenant: "prod-tenant"
    cfzt.cloudflare.com/template: "internal-static"   # or internal-auto
    cfzt.cloudflare.com/hostname: "ha.internal.example.com"
spec:
  parentRefs:
    - name: default
      namespace: default
  hostnames:
    - "ha.internal.example.com"
  rules:
    - backendRefs:
        - name: homeassistant
          port: 8123
```

After the first reconcile the operator writes back:

```
cfzt.cloudflare.com/dnsRecordId:  <cloudflare record UUID>
cfzt.cloudflare.com/dnsRecordIp:  192.168.10.100
cfzt.cloudflare.com/lastReconcile: 2026-02-23T05:00:00Z
```

---

If you prefer to manage tenant resources yourself after the operator is running:

### 1. Create the credential Secret

```bash
kubectl create secret generic prod-tenant-api-token \
  --from-literal=token=<YOUR_CLOUDFLARE_API_TOKEN> \
  --namespace cloudflare-zero-trust
```

### 2. Create the CloudflareZeroTrustTenant CR

```yaml
apiVersion: cfzt.cloudflare.com/v1alpha1
kind: CloudflareZeroTrustTenant
metadata:
  name: prod-tenant
  namespace: cloudflare-zero-trust
spec:
  accountId: "abcdef1234567890abcdef1234567890"
  tunnelId:  "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
  zoneId:    "fedcba0987654321fedcba0987654321"   # optional
  credentialRef:
    name: prod-tenant-api-token
    key: token
  logLevel: INFO
  defaults:
    sessionDuration: "24h"
    originService: "http://traefik.traefik.svc.cluster.local:80"
    httpRedirect: true
    originTLS:
      noTLSVerify: true
      tlsTimeout: 10
      http2Origin: false
      matchSNIToHost: false
```

### 3. Annotate HTTPRoutes

The operator watches `HTTPRoute` resources that carry the tenant annotation:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: my-app
  namespace: default
  annotations:
    cfzt.cloudflare.com/tenant: prod-tenant
spec:
  parentRefs:
    - name: my-gateway
  rules:
    - backendRefs:
        - name: my-app-svc
          port: 8080
```

---

## Upgrade

```bash
helm upgrade cloudflare-zero-trust-operator ./charts/cloudflare-zero-trust-operator \
  --namespace cloudflare-zero-trust \
  -f my-values.yaml
```

## Uninstall

```bash
helm uninstall cloudflare-zero-trust-operator --namespace cloudflare-zero-trust
```

> **Note:** Helm never auto-deletes CRDs on uninstall. Remove them manually if you want a full teardown:
> ```bash
> kubectl delete crd \
>   cloudflarezerotrusttenants.cfzt.cloudflare.com \
>   cloudflarezerotrusttemplates.cfzt.cloudflare.com \
>   cloudflarezerotrustoperatorconfigs.cfzt.cloudflare.com
> ```

---

## Values reference

### Operator

| Key | Default | Description |
|-----|---------|-------------|
| `image.registry` | `ghcr.io` | Container registry |
| `image.repository` | `wheetazlab/cloudflare-zero-trust-operator` | Image repository |
| `image.tag` | `""` | Image tag — defaults to `Chart.appVersion` when empty |
| `image.pullPolicy` | `Always` | Image pull policy |
| `imagePullSecrets` | `[]` | Pull secrets for private registries |
| `namespaceOverride` | `""` | Override the target namespace; defaults to `Release.Namespace` |
| `createNamespace` | `true` | Create the namespace as part of the release |
| `replicaCount` | `1` | Number of operator pod replicas |
| `operator.watchNamespaces` | `""` | Comma-separated namespaces to watch; empty = all namespaces |
| `operator.pollIntervalSeconds` | `60` | Reconciliation loop interval in seconds |
| `operator.logLevel` | `INFO` | Log verbosity: `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` |
| `operator.cloudflareApiBase` | `https://api.cloudflare.com/client/v4` | Cloudflare REST API base URL |
| `operator.extraEnv` | `[]` | Extra env vars injected into the operator container |
| `resources.requests.cpu` | `100m` | CPU request |
| `resources.requests.memory` | `256Mi` | Memory request |
| `resources.limits.cpu` | `500m` | CPU limit |
| `resources.limits.memory` | `512Mi` | Memory limit |
| `serviceAccount.create` | `true` | Create the ServiceAccount |
| `serviceAccount.name` | `""` | Override SA name; defaults to the full chart name |
| `serviceAccount.annotations` | `{}` | Annotations on the ServiceAccount |
| `rbac.create` | `true` | Create ClusterRole and ClusterRoleBinding |
| `nodeSelector` | `{}` | Node selector for the operator pod |
| `tolerations` | `[]` | Tolerations for the operator pod |
| `affinity` | `{}` | Affinity rules for the operator pod |
| `priorityClassName` | `""` | PriorityClass for the operator pod |
| `podAnnotations` | `{}` | Extra pod annotations |
| `podLabels` | `{}` | Extra pod labels |
| `podSecurityContext` | see values.yaml | Pod-level security context |
| `securityContext` | see values.yaml | Container-level security context |

### Tenant bootstrap

All of these are ignored when `tenant.create=false` (the default).

| Key | Default | Required when `create=true` | Description |
|-----|---------|------|-------------|
| `tenant.create` | `false` | — | Set to `true` to render the Tenant CR and optional Secret |
| `tenant.name` | `""` | **yes** | Name of the `CloudflareZeroTrustTenant` CR |
| `tenant.namespace` | `""` | no | Namespace for the CR and Secret; defaults to the release namespace |
| `tenant.accountId` | `""` | **yes** | Cloudflare Account ID (32-char hex) |
| `tenant.tunnelId` | `""` | **yes** | Cloudflare Tunnel ID (UUID) |
| `tenant.zoneId` | `""` | no† | Cloudflare Zone ID (32-char hex). Required for automatic DNS — tunnel CNAME in tunnel mode, A record in dns-only mode. Without it DNS must be managed manually. |
| `tenant.apiToken` | `""` | **yes\*** | Inline API token — Helm creates a `<name>-api-token` Secret |
| `tenant.existingSecret.name` | `""` | **yes\*** | Name of a pre-existing Secret containing the token |
| `tenant.existingSecret.key` | `"token"` | no | Key inside the existing Secret |
| `tenant.defaults.sessionDuration` | `"24h"` | no | Default Access session duration |
| `tenant.defaults.originService` | `""` | no | Default origin URL (scheme determines service type) |
| `tenant.defaults.httpRedirect` | `true` | no | Redirect HTTP→HTTPS at the Cloudflare edge |
| `tenant.defaults.originTLS.noTLSVerify` | `true` | no | Skip TLS verification on origin connection |
| `tenant.defaults.originTLS.tlsTimeout` | `10` | no | TLS handshake timeout in seconds |
| `tenant.defaults.originTLS.http2Origin` | `false` | no | Enable HTTP/2 to origin |
| `tenant.defaults.originTLS.matchSNIToHost` | `false` | no | Match SNI to the Host header |

\* Exactly one of `tenant.apiToken` or `tenant.existingSecret.name` must be provided.

† `tenant.zoneId` is optional but required for fully automatic DNS management. Without it the operator logs a warning and DNS records must be created manually.

---

## CRD reference

### CloudflareZeroTrustTenant

Represents a Cloudflare account + tunnel. All namespace-scoped resources reference a tenant by name.

| Field | Required | Description |
|-------|:--------:|-------------|
| `spec.accountId` | ✓ | 32-char hex Cloudflare Account ID |
| `spec.tunnelId` | ✓ | UUID of the Cloudflare Tunnel |
| `spec.credentialRef.name` | ✓ | Name of the Secret holding the API token |
| `spec.credentialRef.key` | | Key inside the Secret (default: `token`) |
| `spec.zoneId` | | Cloudflare Zone ID — required for automatic DNS management (CNAME in tunnel mode, A record in dns-only mode) |
| `spec.logLevel` | | Per-tenant log level override |
| `spec.defaults.sessionDuration` | | Default Access session duration (default: `24h`) |
| `spec.defaults.originService` | | Default origin service URL |
| `spec.defaults.httpRedirect` | | Redirect HTTP→HTTPS at the edge |
| `spec.defaults.originTLS.noTLSVerify` | | Skip TLS verification on origin connection |
| `spec.defaults.originTLS.tlsTimeout` | | TLS handshake timeout (seconds) |
| `spec.defaults.originTLS.http2Origin` | | Enable HTTP/2 to origin |
| `spec.defaults.originTLS.matchSNIToHost` | | Match SNI to the Host header |

### CloudflareZeroTrustTemplate

Reusable configuration template that `HTTPRoute` resources can reference to avoid repeating Access / service-token settings.

| Field | Description |
|-------|-------------|
| `spec.tenantRef` | Default tenant name for HTTPRoutes using this template |
| `spec.originService.*` | Origin URL and TLS settings (tunnel mode) |
| `spec.accessApplication.*` | Access Application settings (enabled, sessionDuration, policies, etc.) — tunnel mode only |
| `spec.serviceToken.*` | Service token settings (enabled, duration) — tunnel mode only |
| `spec.dnsOnly.enabled` | `false` — set to `true` to enable dns-only mode |
| `spec.dnsOnly.staticIp` | Static IPv4 address for the A record; takes precedence over `ingressServiceRef` |
| `spec.dnsOnly.ingressServiceRef.name` | Kubernetes Service to read LoadBalancer IP from |
| `spec.dnsOnly.ingressServiceRef.namespace` | Namespace of that Service (defaults to the HTTPRoute namespace) |
| `spec.dnsOnly.proxied` | `false` — enable Cloudflare proxy (unusual for internal routes) |
| `spec.dnsOnly.ttl` | `120` — DNS record TTL in seconds |

### CloudflareZeroTrustOperatorConfig

Allows runtime control of the operator Deployment without a Helm upgrade.

| Field | Default | Description |
|-------|---------|-------------|
| `spec.replicas` | `1` | Pod replicas |
| `spec.resources.*` | same as chart defaults | CPU/memory requests and limits |
| `spec.environmentVariables.pollIntervalSeconds` | `60` | Reconciliation interval (seconds) |
| `spec.environmentVariables.logLevel` | `INFO` | Log level |
| `spec.environmentVariables.watchNamespaces` | `""` | Namespaces to watch |
| `spec.imagePullPolicy` | `Always` | Image pull policy |
| `spec.nodeSelector` | | Node selector |
| `spec.tolerations` | | Tolerations |
| `spec.affinity` | | Affinity rules |
| `spec.priorityClassName` | | Priority class |
| `spec.podAnnotations` | | Pod annotations |
| `spec.podLabels` | | Pod labels |
