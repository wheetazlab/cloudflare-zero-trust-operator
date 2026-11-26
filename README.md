<!-- markdownlint-disable -->
# Cloudflare Zero Trust Operator

A Kubernetes Operator for managing Cloudflare Zero Trust resources directly from your cluster.

## Features

- 🚀 **Annotation-driven configuration** — Manage Cloudflare Zero Trust from Kubernetes `HTTPRoute` annotations
- 🔒 **Access Control** — Automatically create and manage Cloudflare Access Applications and Policies
- 🔑 **Service Tokens** — Generate service tokens for machine-to-machine authentication
- 🌐 **Tunnel Management** — Configure Cloudflare Tunnel hostname routes
- 🔗 **Automatic DNS** — Creates the tunnel CNAME (`hostname → <tunnel-id>.cfargotunnel.com`) automatically; zone is auto-discovered from the hostname via the Cloudflare API (optional `zoneId` on the tenant acts as a validation guard)
- 📡 **DNS-only mode** — Publish internal services via a Cloudflare A record pointing at your cluster VIP, with no tunnel required
- 🔄 **Idempotent** — Safe to run repeatedly; handles creates, updates, and deletions
- 🎯 **Multi-tenant** — Support multiple Cloudflare accounts in one cluster
- 📝 **GitOps-friendly** — Managed entirely through Kubernetes CRs and HTTPRoute annotations

## Documentation

- [Helm chart README](charts/cloudflare-zero-trust-operator/README.md) — full install guide, all values, CRD reference, dns-only mode, upgrade/uninstall
- [docs/](docs/) — documentation
- [Examples](examples/) — example template and HTTPRoute configurations

## Requirements

- Kubernetes 1.25+
- Gateway API CRDs installed (`HTTPRoute` must exist)
- Cloudflare account with Zero Trust enabled
- A Cloudflare API token (see below)

## Cloudflare API Token

The operator authenticates to the Cloudflare API using a scoped API token — **not** your Global API Key.

### Creating the Token

1. Log in to the [Cloudflare dashboard](https://dash.cloudflare.com)
2. Go to **My Profile → API Tokens → Create Token**
3. Click **Create Custom Token**
4. Add the following permissions:

| Permission | Resource | Access | When required |
|---|---|---|---|
| Cloudflare Tunnel | Account → *your account* | Edit | Always — creates/updates/deletes tunnel hostname routes |
| Access: Apps and Policies | Account → *your account* | Edit | Always — manages Access Applications and Policies |
| Access: Service Tokens | Account → *your account* | Edit | Always — creates and deletes service tokens |
| Zone: DNS | Zone → *All zones* (or specific zones) | Edit | Always — creates CNAME and A records |
| Zone: Zone | Zone → *All zones* (or specific zones) | Read | Always — auto-discovers zone ID from each hostname |

> **Zone: Read** is needed for automatic zone discovery (resolving a hostname like `myapp.example.com` to its Cloudflare Zone ID). If you prefer to supply `zoneId` explicitly on every tenant and don't want to grant Zone:Read, you can omit it — but reconciliation will fail on any hostname whose zone is not pre-set.

5. Set **TTL** if desired (recommended: no expiry, or align with your rotation policy)
6. Click **Continue to summary → Create Token** and copy the token

## Quick Start

### 1. The chart

The chart is published as an OCI artifact on GitHub's container registry, next to the operator image; no `helm repo add` is needed:

```bash
helm show chart oci://ghcr.io/wheetazlab/charts/cloudflare-zero-trust-operator
```

The old chart repository, `https://wheetazlab.github.io/cloudflare-zero-trust-operator`, gets new versions until **2027-02-26** and is then frozen (versions already there keep installing). See [Moving to the OCI chart](#moving-to-the-oci-chart).

### 2. Install with a values file

Create `my-values.yaml`:

```yaml
tenant:
  create: true
  instanceName: "prod-tenant"
  accountId: "abcdef1234567890abcdef1234567890"    # Cloudflare Account ID
  tunnelId:  "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" # Cloudflare Tunnel ID
  # zoneId: "fedcba0987654321fedcba0987654321"    # optional — auto-discovered from hostname
  apiToken:  "your-cloudflare-api-token"
```

```bash
helm install cloudflare-zero-trust-operator oci://ghcr.io/wheetazlab/charts/cloudflare-zero-trust-operator \
  --namespace cloudflare-zero-trust \
  --create-namespace \
  -f my-values.yaml
```

### 3. Annotate your HTTPRoutes

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: myapp
  namespace: default
  annotations:
    cfzt.cloudflare.com/enabled: "true"
    cfzt.cloudflare.com/tenant: "prod-tenant"
    cfzt.cloudflare.com/template: "my-template"
    cfzt.cloudflare.com/hostname: "myapp.example.com"
spec:
  # ... your HTTPRoute spec
```

The operator reconciles the annotation and:
- writes the hostname ingress rule to the Cloudflare Tunnel
- creates the DNS CNAME record (if `zoneId` is set on the tenant)
- creates the Cloudflare Access Application and policy
- stores all Cloudflare resource IDs back as annotations on the HTTPRoute

### Providing the Token to the Operator

**Option A — Inline via Helm values** (Helm creates the Secret for you):

```yaml
# my-values.yaml
tenant:
  create: true
  instanceName: "prod-tenant"
  accountId: "abcdef1234567890abcdef1234567890"
  tunnelId:  "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
  apiToken:  "your-cloudflare-api-token"   # stored in a K8s Secret at install time
```

**Option B — Pre-existing Secret** (token never passes through Helm):

```bash
kubectl create secret generic cfzt-api-token \
  --namespace cloudflare-zero-trust \
  --from-literal=token="your-cloudflare-api-token"
```

```yaml
# my-values.yaml
tenant:
  create: true
  instanceName: "prod-tenant"
  accountId: "abcdef1234567890abcdef1234567890"
  tunnelId:  "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
  existingSecret:
    name: cfzt-api-token
    key: token
```

**Option C — Manual `CloudflareZeroTrustTenant` CR** (full control, beyond Helm):

```yaml
apiVersion: cfzt.cloudflare.com/v1alpha1
kind: CloudflareZeroTrustTenant
metadata:
  name: prod-tenant
  namespace: cloudflare-zero-trust
spec:
  accountId: "abcdef1234567890abcdef1234567890"
  tunnelId:  "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
  credentialRef:
    name: cfzt-api-token   # name of an existing K8s Secret
    key: token
```

The token is read at reconcile time from the referenced Secret — it is never stored in annotations, logs, or state ConfigMaps.


## Moving to the OCI chart

The chart moved from the GitHub Pages chart repository (`https://wheetazlab.github.io/cloudflare-zero-trust-operator`) to OCI on GitHub's container registry (`oci://ghcr.io/wheetazlab/charts`). The chart name and versions are the same, so moving is an upgrade of the existing release, nothing is reinstalled.

| Date | Old repository (GitHub Pages) | OCI |
|---|---|---|
| Until 2027-02-26 | Gets every new version | Gets every new version |
| From 2027-02-27 | Frozen: versions already there keep installing | Gets every new version |

**Helm CLI**

```bash
helm upgrade cloudflare-zero-trust-operator \
  oci://ghcr.io/wheetazlab/charts/cloudflare-zero-trust-operator \
  --version <version> -n <namespace> --reuse-values
helm repo remove <name you gave the old repo>
```

**Argo CD**

1. In the Application, change only the source's address: `repoURL: ghcr.io/wheetazlab/charts` (no `oci://`), same `chart` and `targetRevision`.
2. If the AppProject limits `sourceRepos`, add `ghcr.io/wheetazlab/charts`.
3. Declare the OCI repository once (public, no credentials):

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: repo-ghcr-wheetazlab-charts
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: repository
stringData:
  name: ghcr-wheetazlab-charts
  type: helm
  url: ghcr.io/wheetazlab/charts
  enableOCI: "true"
```

**Flux**

```yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: HelmRepository
metadata:
  name: wheetazlab
spec:
  type: oci
  url: oci://ghcr.io/wheetazlab/charts
  interval: 1h
```

Keep the HelmRelease's `chart: cloudflare-zero-trust-operator` and point its `sourceRef` at this HelmRepository.

## What It Does

The operator watches `HTTPRoute` resources for annotations and automatically manages:

1. **Cloudflare Tunnel hostname routes** — routes public hostnames through your tunnel to origin services
2. **Automatic CNAME DNS** — creates `hostname CNAME <tunnel-id>.cfargotunnel.com` (proxied, TTL auto); zone ID is auto-discovered from the hostname via the Cloudflare Zones API — no `zoneId` required. If `tenant.zoneId` is set it is validated against the discovered value as a safety check
3. **Cloudflare Access Applications** — protects your applications with Cloudflare Access
4. **Access Policies** — configures who can access your applications (email, groups, etc.)
5. **Service Tokens** — creates tokens for machine-to-machine authentication
6. **DNS-only A records** — for internal services reachable via DNS but not tunnelled (see [DNS-only mode](charts/cloudflare-zero-trust-operator/README.md#dns-only-mode-internal--direct-to-cluster-routing))
7. **State tracking** — uses per-HTTPRoute ConfigMaps (`cfzt-{namespace}-{name}`) to detect annotation changes via SHA256 hash (avoiding unnecessary API calls), and writes result Cloudflare resource IDs back to HTTPRoute annotations for idempotent updates and clean deletion

## Architecture

The operator runs as a single **kopf**-based Python controller in one Deployment. It watches `HTTPRoute` resources for `cfzt.cloudflare.com/*` annotations and reconciles Cloudflare Zero Trust resources (tunnel routes, DNS CNAMEs, Access applications, Access policies, service tokens) via the Cloudflare Python SDK.

State is tracked in per-HTTPRoute ConfigMaps (`cfzt-{namespace}-{name}`) using a SHA256 hash to detect annotation changes and avoid unnecessary API calls. An orphan cleanup timer detects and removes Cloudflare resources for deleted HTTPRoutes.

## Development

```bash
git clone https://github.com/wheetazlab/cloudflare-zero-trust-operator.git
cd cloudflare-zero-trust-operator

# Install dependencies
pip install -r container/requirements.txt

# Deploy via Helm (local chart)
helm install cloudflare-zero-trust-operator ./charts/cloudflare-zero-trust-operator \
  --namespace cloudflare-zero-trust \
  --create-namespace \
  -f my-values.yaml
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

MIT License — see [LICENSE](LICENSE) for details. 
