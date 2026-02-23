# cloudflare-zero-trust-operator Helm Chart

Installs the **Cloudflare Zero Trust Operator** — an Ansible-based Kubernetes operator that watches `HTTPRoute` resources and reconciles them with the Cloudflare API to manage tunnel routing, Access Applications, and service tokens.

## How it works

The operator container ships Ansible roles internally. The Helm chart's job is to:

1. Install the three CRDs (from `crds/` — Helm applies these before any templates)
2. Create the namespace, ServiceAccount, and ClusterRole/Binding RBAC
3. Deploy the operator container with the correct runtime switches as environment variables

## Prerequisites

- Kubernetes 1.25+
- [Gateway API CRDs](https://gateway-api.sigs.k8s.io/guides/#installing-gateway-api) installed in the cluster (`httproutes.gateway.networking.k8s.io`)
- A Cloudflare API token with **Cloudflare Tunnel** and **Access** permissions
- An existing Cloudflare tunnel (you need the tunnel ID and account ID)

## Install

```bash
# From the repo root
helm install cloudflare-zero-trust-operator ./charts/cloudflare-zero-trust-operator \
  --namespace cloudflare-zero-trust \
  --create-namespace
```

To override values inline:

```bash
helm install cloudflare-zero-trust-operator ./charts/cloudflare-zero-trust-operator \
  --namespace cloudflare-zero-trust \
  --create-namespace \
  --set operator.logLevel=DEBUG \
  --set operator.pollIntervalSeconds=30 \
  --set operator.watchNamespaces="default,production"
```

## Uninstall

```bash
helm uninstall cloudflare-zero-trust-operator -n cloudflare-zero-trust
```

> **Note:** CRDs are not deleted on uninstall (Helm never auto-deletes CRDs). Remove them manually if needed:
> ```bash
> kubectl delete crd cloudflarezerotrusttenants.cfzt.cloudflare.com \
>   cloudflarezerotrusttemplates.cfzt.cloudflare.com \
>   cloudflarezerotrustoperatorconfigs.cfzt.cloudflare.com
> ```

## Quick start after install

### 1. Create the credential Secret

```bash
kubectl create secret generic my-cf-token \
  --from-literal=token=<YOUR_CLOUDFLARE_API_TOKEN> \
  -n cloudflare-zero-trust
```

### 2. Create a CloudflareZeroTrustTenant

```yaml
apiVersion: cfzt.cloudflare.com/v1alpha1
kind: CloudflareZeroTrustTenant
metadata:
  name: my-tenant
  namespace: cloudflare-zero-trust
spec:
  accountId: "abcdef1234567890abcdef1234567890"  # 32-char hex
  tunnelId:  "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
  credentialRef:
    name: my-cf-token   # Secret name
    key: token          # Key inside the Secret (default: token)
  logLevel: INFO
  defaults:
    sessionDuration: "24h"
```

### 3. Annotate HTTPRoutes

Add the tenant annotation to any `HTTPRoute` you want the operator to manage:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: my-app
  annotations:
    cfzt.cloudflare.com/tenant: my-tenant
```

## Values reference

| Key | Default | Description |
|-----|---------|-------------|
| `image.registry` | `ghcr.io` | Container registry |
| `image.repository` | `wheetazlab/cloudflare-zero-trust-operator` | Image repository |
| `image.tag` | `""` | Image tag — defaults to `Chart.appVersion` |
| `image.pullPolicy` | `Always` | Image pull policy |
| `imagePullSecrets` | `[]` | Pull secrets for private registries |
| `namespaceOverride` | `""` | Override the target namespace (defaults to `Release.Namespace`) |
| `createNamespace` | `true` | Create the namespace as part of the release |
| `operator.watchNamespaces` | `""` | Comma-separated namespaces to watch; empty = all |
| `operator.pollIntervalSeconds` | `60` | How often the reconciliation loop runs |
| `operator.logLevel` | `INFO` | Log verbosity: `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` |
| `operator.cloudflareApiBase` | `https://api.cloudflare.com/client/v4` | Cloudflare REST API base URL |
| `operator.extraEnv` | `[]` | Extra env vars injected into the container |
| `replicaCount` | `1` | Number of operator pod replicas |
| `resources.requests.cpu` | `100m` | CPU request |
| `resources.requests.memory` | `256Mi` | Memory request |
| `resources.limits.cpu` | `500m` | CPU limit |
| `resources.limits.memory` | `512Mi` | Memory limit |
| `serviceAccount.create` | `true` | Create the ServiceAccount |
| `serviceAccount.name` | `""` | Override SA name (defaults to the full chart name) |
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

## CRD reference

### CloudflareZeroTrustTenant

Represents a Cloudflare account + tunnel. All namespace-scoped resources reference a tenant.

| Field | Required | Description |
|-------|----------|-------------|
| `spec.accountId` | ✓ | 32-char hex Cloudflare account ID |
| `spec.tunnelId` | ✓ | UUID of the Cloudflare tunnel |
| `spec.credentialRef.name` | ✓ | Name of the Secret holding the API token |
| `spec.credentialRef.key` | | Key inside the Secret (default: `token`) |
| `spec.zoneId` | | Cloudflare zone ID (optional) |
| `spec.logLevel` | | Per-tenant log level override |
| `spec.defaults.sessionDuration` | | Default Access session duration (default: `24h`) |
| `spec.defaults.originService` | | Default origin URL |
| `spec.defaults.httpRedirect` | | Redirect HTTP→HTTPS at the edge |
| `spec.defaults.originTLS.*` | | TLS settings for origin connection |

### CloudflareZeroTrustTemplate

Reusable configuration template that HTTPRoutes can reference to avoid repeating Access / service-token settings.

| Field | Description |
|-------|-------------|
| `spec.tenantRef` | Default tenant name for HTTPRoutes using this template |
| `spec.originService.*` | Origin URL and TLS settings |
| `spec.accessApplication.*` | Access Application settings (enabled, sessionDuration, policies…) |
| `spec.serviceToken.*` | Service token settings (enabled, duration) |

### CloudflareZeroTrustOperatorConfig

Controls the operator's own Deployment without a Helm upgrade.

| Field | Default | Description |
|-------|---------|-------------|
| `spec.replicas` | `1` | Pod replicas |
| `spec.resources.*` | same as chart defaults | CPU/memory requests & limits |
| `spec.environmentVariables.pollIntervalSeconds` | `60` | Reconciliation interval |
| `spec.environmentVariables.logLevel` | `INFO` | Log level |
| `spec.environmentVariables.watchNamespaces` | `""` | Namespaces to watch |
| `spec.imagePullPolicy` | `Always` | Image pull policy |
| `spec.nodeSelector` | | Node selector |
| `spec.tolerations` | | Tolerations |
| `spec.affinity` | | Affinity rules |
| `spec.priorityClassName` | | Priority class |
| `spec.podAnnotations` | | Pod annotations |
| `spec.podLabels` | | Pod labels |
