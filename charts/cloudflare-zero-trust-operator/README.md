# cloudflare-zero-trust-operator Helm Chart

Installs the **Cloudflare Zero Trust Operator** — an Ansible-based Kubernetes operator that watches `HTTPRoute` resources and reconciles them with the Cloudflare API to manage tunnel routing, Access Applications, and service tokens.

## How it works

The operator container ships Ansible roles internally. The Helm chart's job is to:

1. Install the three CRDs (from `crds/` — Helm applies these before any templates)
2. Create the namespace, ServiceAccount, and ClusterRole/ClusterRoleBinding
3. Deploy the operator container with runtime configuration via environment variables
4. Optionally create the `CloudflareZeroTrustTenant` CR (and its API token Secret) if `tenant.create=true`

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

> **Important:** If you use Option A (`apiToken`), Helm will create a Secret named `<tenant.name>-api-token`
> in the tenant namespace containing your token in plaintext in the cluster etcd.
> For production, prefer Option B with a pre-created Secret managed outside of Helm (e.g. via Infisical,
> Vault, or Sealed Secrets).

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

## Manual tenant setup (without Helm bootstrap)

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
| `tenant.zoneId` | `""` | no | Cloudflare Zone ID (32-char hex) |
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
| `spec.zoneId` | | Cloudflare Zone ID (optional) |
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
| `spec.originService.*` | Origin URL and TLS settings |
| `spec.accessApplication.*` | Access Application settings (enabled, sessionDuration, policies, etc.) |
| `spec.serviceToken.*` | Service token settings (enabled, duration) |

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
