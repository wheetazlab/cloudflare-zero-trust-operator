<!-- markdownlint-disable -->
# Cloudflare Zero Trust Operator

A Kubernetes Operator for managing Cloudflare Zero Trust resources from your cluster using Ansible.

## Architecture

The operator consists of:

1. **Custom Resource Definitions (CRDs)**:
   - `CloudflareZeroTrustTenant` - Cloudflare account/zone/tunnel configuration with credentials
   - `CloudflareZeroTrustTemplate` - Reusable configuration templates for tunnel routes and Access applications
   - `CloudflareZeroTrustOperatorConfig` - Operator pod configuration (singleton)
2. **Controller**: Ansible-based reconciliation loop that watches Kubernetes resources and manages Cloudflare
3. **Template-driven configuration**: HTTPRoutes use minimal annotations to select templates with full configuration

### Component Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Kubernetes Cluster                        │
│                                                              │
│  ┌──────────────────────┐      ┌────────────────────────┐  │
│  │ CloudflareZeroTrust  │      │  Gateway API HTTPRoute  │  │
│  │      Tenant CR       │      │   (with annotations)   │  │
│  └──────────────────────┘      └────────────────────────┘  │
│            │                              │                  │
│            └──────────┬───────────────────┘                  │
│                       │                                      │
│            ┌──────────▼──────────┐                          │
│            │  Operator Pod       │                          │
│            │  (Ansible Runner)   │                          │
│            └──────────┬──────────┘                          │
│                       │                                      │
└───────────────────────┼──────────────────────────────────────┘
                        │
                        │ Cloudflare API
                        ▼
            ┌───────────────────────┐
            │  Cloudflare Zero      │
            │  Trust Platform       │
            │                       │
            │  • Tunnel Hostnames   │
            │  • Access Apps        │
            │  • Access Policies    │
            │  • Service Tokens     │
            └───────────────────────┘
```

### Reconciliation Flow

1. **Watch Phase**: List CloudflareZeroTrustTenant CRs and Gateway API HTTPRoute resources
2. **Analysis Phase**: For each HTTPRoute with cfzt annotations, determine desired Cloudflare state
3. **Sync Phase**: Call Cloudflare APIs to create/update/delete resources
4. **Update Phase**: Patch HTTPRoute annotations with Cloudflare resource IDs
5. **Status Phase**: Update CloudflareZeroTrustTenant status with sync results

## HTTPRoute Configuration

### Template-Based Approach (Recommended)

The operator uses **templates** to configure tunnel routes and Access applications. This keeps HTTPRoutes clean and enables reusable configurations.

#### Step 1: HTTPRoute Annotations (Minimal)

Only specify what's unique to each route:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: my-app
  namespace: my-app
  annotations:
    # Enable operator management
    cfzt.cloudflare.com/enabled: "true"
    
    # Public hostname (REQUIRED)
    cfzt.cloudflare.com/hostname: "my-app.example.com"
    
    # Template to use (optional)
    cfzt.cloudflare.com/template: "protected-adauth"
    
    # Tenant to use (required)
    cfzt.cloudflare.com/tenant: "my-tenant"
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

#### Step 2: Template Definition

Create reusable templates with full configuration. The operator resolves policy names to UUIDs at reconcile time — no need to look them up manually.

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
      - "ADAUTH"   # Cloudflare Access policy name — resolved to UUID at reconcile time
    autoRedirectToIdentity: true
    appLauncherVisible: true
    skipInterstitial: false
    httpOnlyCookieAttribute: true
    sameSiteCookieAttribute: "lax"
```

### Configuration Hierarchy

Settings are resolved through a **three-way merge**:

1. **Base template** (`base-<tenant-name>`) — auto-discovered by the operator; establishes origin/TLS defaults for every route under a tenant. Create a template named `base-<your-tenant-name>` and the operator picks it up automatically — no field on the tenant CR is needed.
2. **Per-route template** — referenced via `cfzt.cloudflare.com/template`; only fields specified here override the base.
3. **Annotation overrides** — fields set directly on the HTTPRoute that override both templates.

### Example Templates

The operator ships example templates (installed by the Helm chart when `exampleTemplates.install: true`):

| Template Name | Description | Use Case |
|---------------|-------------|----------|
| `base-<tenant-name>` | Origin/TLS baseline for all routes | Every tenant needs one — name must match `base-<tenant-name>` |
| `protected-adauth` | Identity-based auth via existing Access policy | Human/browser consumers (IdP login) |
| `unprotected-public` | No Access gate | Intentionally public services |
| `protected-service-cred` | M2M auth via service credential policy | APIs and CLI consumers |
| `internal-dnsonly` | DNS A record only, no tunnel | Point hostname at private cluster IP |

See [examples-templates.md](examples-templates.md) for complete template definitions.

### Core Annotations

| Annotation | Required | Description | Example |
|------------|----------|-------------|---------|
| `cfzt.cloudflare.com/enabled` | Yes | Enable operator management | `"true"` |
| `cfzt.cloudflare.com/hostname` | Yes | Public hostname to configure | `"app.example.com"` |
| `cfzt.cloudflare.com/tenant` | Yes | Name of the `CloudflareZeroTrustTenant` CR | `"my-tenant"` |
| `cfzt.cloudflare.com/template` | No | Template name | `"protected-adauth"` |
| `cfzt.cloudflare.com/dnsIp` | No | Private RFC 1918 IP for `internal-dnsonly` routes | `"192.168.1.50"` |

### Annotation Overrides

HTTPRoute annotations can override any field from the merged template for that specific route:

| Annotation | Description |
|---|---|
| `cfzt.cloudflare.com/origin.url` | Override origin URL |
| `cfzt.cloudflare.com/origin.noTLSVerify` | Override TLS verification skip |
| `cfzt.cloudflare.com/access.enabled` | Override Access Application enabled flag |
| `cfzt.cloudflare.com/access.existingPolicyNames` | Comma-separated policy names |
| `cfzt.cloudflare.com/access.sessionDuration` | Override session duration |
| `cfzt.cloudflare.com/access.autoRedirectToIdentity` | Override auto-redirect to IdP |
| `cfzt.cloudflare.com/access.appLauncherVisible` | Override App Launcher visibility |
| `cfzt.cloudflare.com/access.serviceAuth401Redirect` | Return 401 instead of browser redirect |
| `cfzt.cloudflare.com/access.skipInterstitial` | Override interstitial page |
| `cfzt.cloudflare.com/access.httpOnlyCookieAttribute` | Override HttpOnly cookie flag |
| `cfzt.cloudflare.com/access.sameSiteCookieAttribute` | Override SameSite cookie value (`none`/`lax`/`strict`) |
| `cfzt.cloudflare.com/serviceToken.enabled` | Override Service Token enabled flag |
| `cfzt.cloudflare.com/serviceToken.duration` | Override Service Token duration |

### State Tracking Annotations (Managed by Operator)

These annotations are set by the operator to track created resources:

- `cfzt.cloudflare.com/hostnameRouteId`: Tunnel hostname route ID
- `cfzt.cloudflare.com/accessAppId`: Access Application ID
- `cfzt.cloudflare.com/accessPolicyIds`: Comma-separated Access Policy IDs
- `cfzt.cloudflare.com/serviceTokenId`: Service Token ID
- `cfzt.cloudflare.com/serviceTokenSecretName`: K8s Secret name containing token credentials

## CloudflareZeroTrustTemplate CRD

### Template Spec

```yaml
apiVersion: cfzt.cloudflare.com/v1alpha1
kind: CloudflareZeroTrustTemplate
metadata:
  name: my-template
  namespace: cloudflare-zero-trust-operator
spec:
  # Origin service configuration
  # Typically defined only in the base-<tenant-name> template and inherited by per-route templates.
  originService:
    url: "https://traefik.traefik.svc.cluster.local:443"
    httpRedirect: true  # Auto-redirect HTTP to HTTPS at edge
    originTLS:
      noTLSVerify: true  # Skip TLS verification for self-signed certs
      originServerName: ""  # Custom SNI hostname (optional)
      caPool: ""  # Path to CA cert file (optional)
      tlsTimeout: 10  # TLS handshake timeout in seconds (1-300)
      http2Origin: false  # Use HTTP/2 for origin connection
      matchSNIToHost: false  # Match SNI to Host header
  
  # Access Application configuration
  accessApplication:
    enabled: true
    sessionDuration: "24h"
    
    # Policy names — operator resolves to UUIDs at reconcile time
    existingPolicyNames:
      - "My Policy Name"
    
    # Application settings
    autoRedirectToIdentity: false
    enableBindingCookie: false
    httpOnlyCookieAttribute: true
    sameSiteCookieAttribute: "lax"  # none, lax, strict
    logoUrl: ""
    skipInterstitial: false
    appLauncherVisible: true
    serviceAuth401Redirect: false  # Return 401 instead of browser redirect for M2M consumers
    customDenyMessage: ""
    customDenyUrl: ""
    customNonIdentityDenyUrl: ""
  
  # Service Token configuration
  serviceToken:
    enabled: false
    duration: "8760h"  # 1 year

  # DNS-only record (no tunnel) — supply target IP via cfzt.cloudflare.com/dnsIp annotation per route
  dnsOnly:
    enabled: false
    proxied: false
    ttl: 120
    # staticIp: "192.168.1.50"  # optional; prefer per-route annotation for flexibility
```

### Template Fields

#### originService
- **url** (string): Origin service URL (e.g., `https://my-ingress.namespace.svc:443`)
- **httpRedirect** (bool, default: true): Auto-redirect HTTP to HTTPS at Cloudflare edge
- **originTLS** (object): TLS configuration for HTTPS origins
  - **noTLSVerify** (bool, default: false): Skip certificate verification
  - **originServerName** (string): Custom SNI hostname
  - **caPool** (string): Path to CA certificate file
  - **tlsTimeout** (int, 1-300, default: 10): TLS handshake timeout in seconds
  - **http2Origin** (bool, default: false): Use HTTP/2 for origin
  - **matchSNIToHost** (bool, default: false): Match SNI to Host header

#### accessApplication
- **enabled** (bool, default: false): Create Cloudflare Access Application
- **sessionDuration** (string, default: "24h"): Session duration (e.g., "24h", "8h", "30m")
- **existingPolicyNames** (array of strings): Cloudflare Access policy names — operator resolves to UUIDs at reconcile time
- **autoRedirectToIdentity** (bool, default: false): Auto-redirect to IdP login
- **appLauncherVisible** (bool, default: true): Show in Cloudflare App Launcher
- **skipInterstitial** (bool, default: false): Skip interstitial page
- **serviceAuth401Redirect** (bool, default: false): Return HTTP 401 instead of browser redirect — use for M2M/API consumers
- **httpOnlyCookieAttribute** (bool, default: true): Set HttpOnly cookie flag
- **sameSiteCookieAttribute** (string): Cookie SameSite value (`none`, `lax`, `strict`)

#### serviceToken
- **enabled** (bool, default: false): Create service token for machine-to-machine auth
- **duration** (string, default: "8760h"): Token lifetime

#### dnsOnly
- **enabled** (bool, default: false): Create DNS A record only — no tunnel or Access Application
- **proxied** (bool, default: false): Proxy traffic through Cloudflare
- **ttl** (int, default: 120): DNS TTL in seconds
- **staticIp** (string, optional): Target IP address; alternatively use `cfzt.cloudflare.com/dnsIp` annotation per route. Must be RFC 1918 private address.

### Example HTTPRoute with Template

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: my-app
  namespace: my-app
  annotations:
    cfzt.cloudflare.com/enabled: "true"
    cfzt.cloudflare.com/hostname: "my-app.example.com"
    cfzt.cloudflare.com/tenant: "my-tenant"
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

See [examples-httproutes.md](examples-httproutes.md) for more complete examples including annotation-only and DNS-only routes.

## CloudflareZeroTrustTenant CRD

### Spec

```yaml
apiVersion: cfzt.cloudflare.com/v1alpha1
kind: CloudflareZeroTrustTenant
metadata:
  name: my-tenant
  namespace: cloudflare-zero-trust-operator
spec:
  accountId: "0123456789abcdef0123456789abcdef"
  tunnelId: "12345678-1234-1234-1234-123456789abc"
  zoneId: "0123456789abcdef0123456789abcdef"  # optional
  credentialRef:
    name: cloudflare-api-token
    key: token
```

**Spec Fields:**

- **accountId** (required): Cloudflare Account ID
- **tunnelId** (required): Cloudflare Tunnel ID
- **zoneId** (optional): Cloudflare Zone ID (for DNS/zone-specific operations)
- **credentialRef** (required): Reference to a Kubernetes Secret containing the Cloudflare API token
  - **name**: Secret name
  - **key**: Key within the secret containing the API token

Route defaults (origin URL, TLS settings, Access settings) are configured in a **base template** named `base-<tenant-name>` rather than on the tenant CR. See [Configuration Hierarchy](#configuration-hierarchy).

See [example-tenant.md](example-tenant.md) for a complete example.

### Status

```yaml
status:
  observedGeneration: 1
  lastSyncTime: "2026-02-18T10:00:00Z"
  conditions:
    - type: Ready
      status: "True"
      lastTransitionTime: "2026-02-18T10:00:00Z"
      reason: ReconcileSuccess
      message: "Successfully reconciled"
  summary:
    managedHTTPRoutes: 5
    hostnameRoutes: 5
    accessApplications: 3
    accessPolicies: 4
    serviceTokens: 2
```

## Cloudflare API Mapping

### Tunnel Hostname Routes

**Create/Update Route**
```
PUT https://api.cloudflare.com/client/v4/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations
```

Body includes hostname routes configuration.

### Access Applications

**Create Application**
```
POST https://api.cloudflare.com/client/v4/accounts/{account_id}/access/apps
```

**Update Application**
```
PUT https://api.cloudflare.com/client/v4/accounts/{account_id}/access/apps/{app_id}
```

**Delete Application**
```
DELETE https://api.cloudflare.com/client/v4/accounts/{account_id}/access/apps/{app_id}
```

### Access Policies

**Create Policy**
```
POST https://api.cloudflare.com/client/v4/accounts/{account_id}/access/apps/{app_id}/policies
```

**Update Policy**
```
PUT https://api.cloudflare.com/client/v4/accounts/{account_id}/access/apps/{app_id}/policies/{policy_id}
```

**Delete Policy**
```
DELETE https://api.cloudflare.com/client/v4/accounts/{account_id}/access/apps/{app_id}/policies/{policy_id}
```

### Service Tokens

**Create Service Token**
```
POST https://api.cloudflare.com/client/v4/accounts/{account_id}/access/service_tokens
```

**Delete Service Token**
```
DELETE https://api.cloudflare.com/client/v4/accounts/{account_id}/access/service_tokens/{token_id}
```

## Deployment

### Prerequisites

- Kubernetes cluster (1.23+)
- Any Gateway API-compatible ingress controller
- Cloudflare account with Zero Trust enabled
- Cloudflare API token with permissions:
  - Account.Cloudflare Tunnel:Edit
  - Account.Access:Edit

### Installation

1. **Create Cloudflare API token secret**:

```bash
kubectl create secret generic cloudflare-api-token \
  --from-literal=token=YOUR_API_TOKEN \
  -n cloudflare-zero-trust
```

2. **Install CRDs**:

```bash
# Install all CRDs
kubectl apply -f config/crd/cfzt.cloudflare.com_cloudflarezerotrusttenants.yaml
kubectl apply -f config/crd/cfzt.cloudflare.com_cloudflarezerotrusttemplates.yaml
kubectl apply -f config/crd/cfzt.cloudflare.com_cloudflarezerotrustoperatorconfigs.yaml
```

3. **Install RBAC and operator**:

```bash
kubectl apply -f config/rbac/
kubectl apply -f config/deployment/operator.yaml
```

4. **Install example templates** (optional — installed automatically if using Helm with `exampleTemplates.install: true`):

```bash
# Helm (recommended) — example templates are included and enabled by default
helm install cloudflare-zero-trust-operator ./charts/cloudflare-zero-trust-operator

# Or apply manually
kubectl apply -f charts/cloudflare-zero-trust-operator/templates/example-templates.yaml
```

   See [examples-templates.md](examples-templates.md) for template definitions and [examples-httproutes.md](examples-httproutes.md) for annotated HTTPRoute examples.

5. **Create a CloudflareZeroTrustTenant**:

   See [example-tenant.md](example-tenant.md) for a complete example including the required `base-<tenant-name>` template.

6. **Annotate your HTTPRoutes**:

```bash
kubectl annotate httproute my-app \
  cfzt.cloudflare.com/enabled="true" \
  cfzt.cloudflare.com/hostname="myapp.example.com" \
  cfzt.cloudflare.com/tenant="my-tenant" \
  cfzt.cloudflare.com/template="protected-adauth"
```

### Configuration

Environment variables for the operator:

| Variable | Default | Description |
|----------|---------|-------------|
| `WATCH_NAMESPACES` | `""` (all) | Comma-separated namespaces to watch |
| `POLL_INTERVAL_SECONDS` | `60` | Reconciliation loop interval |
| `LOG_LEVEL` | `INFO` | Log level (DEBUG, INFO, WARNING, ERROR) |
| `CLOUDFLARE_API_BASE` | `https://api.cloudflare.com/client/v4` | Cloudflare API base URL |

## Local Development

### Prerequisites

- Python 3.9+
- Ansible 2.14+
- kubectl configured with cluster access
- Docker (for container builds)

### Setup

1. **Install dependencies**:

```bash
pip install -r container/requirements.txt
ansible-galaxy collection install -r ansible/requirements.yml
```

2. **Set up test environment**:

```bash
export KUBECONFIG=~/.kube/config
export WATCH_NAMESPACES="default"
export POLL_INTERVAL_SECONDS="30"
export LOG_LEVEL="DEBUG"
```

3. **Run reconciliation locally**:

```bash
cd ansible
ansible-playbook playbooks/reconcile.yml -e "poll_interval=30" -e "watch_namespaces=default"
```

### Testing

Run Ansible lint:

```bash
cd ansible && ansible-lint playbooks/ roles/
```

Build container locally:

```bash
docker build -f container/Dockerfile -t ghcr.io/wheetazlab/cloudflare-zero-trust-operator:latest .
```

Deploy to kind cluster:

```bash
kubectl apply -f config/crd/
kubectl apply -f config/rbac/
kubectl apply -f config/deployment/
```

## Idempotency & Deletion

### Idempotent Operations

The operator is designed to be idempotent:
- Repeated reconciliation produces the same result
- Cloudflare resources are updated in place when configuration changes
- Resource IDs stored in annotations enable proper updates

### Deletion Handling

When an HTTPRoute is deleted or annotations are removed:

1. Operator detects the removal during next reconciliation
2. Retrieves Cloudflare resource IDs from stored state (if annotations still exist)
3. Calls Cloudflare APIs to delete:
   - Service tokens (and associated Secrets)
   - Access policies
   - Access applications
   - Hostname routes
4. Removes state annotations from HTTPRoute (if still exists)

### Finalizers

The operator uses Kubernetes finalizers on managed HTTPRoutes to ensure clean deletion of Cloudflare resources before the HTTPRoute is removed from etcd.

## Extension Points

The operator is designed to support additional Cloudflare Zero Trust features:

### Future Enhancements

- **Identity Provider Integrations**: Manage IdP configurations via annotations
- **Device Posture Checks**: Define device posture requirements
- **Gateway Policies**: DNS and HTTP filtering rules
- **DLP Profiles**: Data Loss Prevention configurations
- **Audit Logs**: Export audit logs to Kubernetes events or external systems

### Adding New Cloudflare Resources

To add support for new Cloudflare resources:

1. Extend annotation schema in docs
2. Add API interaction tasks in `ansible/roles/cloudflare_api/tasks/`
3. Update reconciliation logic in `ansible/roles/tenant_reconcile/tasks/`
4. Add state tracking annotations
5. Update examples

## Troubleshooting

### Check operator logs

```bash
kubectl logs -n cloudflare-zero-trust deployment/cloudflare-zero-trust-operator -f
```

### Check tenant status

```bash
kubectl get cloudflarezerotrusttenants -o yaml
```

### Verify annotations

```bash
kubectl get httproute my-app -o jsonpath='{.metadata.annotations}' | jq
```

### Common Issues

**Issue**: Operator not detecting HTTPRoute changes
- **Solution**: Check WATCH_NAMESPACES includes the HTTPRoute namespace
- **Solution**: Verify HTTPRoute has `cfzt.cloudflare.com/enabled: "true"`

**Issue**: Cloudflare API rate limiting
- **Solution**: Increase POLL_INTERVAL_SECONDS
- **Solution**: Reduce number of managed HTTPRoutes per tenant

**Issue**: Access Application not created
- **Solution**: Verify `cfzt.cloudflare.com/accessApp: "true"` annotation
- **Solution**: Check Cloudflare API token has Access:Edit permission
- **Solution**: Review operator logs for API errors

## Security Considerations

- **API Tokens**: Store in Kubernetes Secrets, never in annotations or ConfigMaps
- **Service Token Secrets**: Automatically created with generated names, use RBAC to restrict access
- **RBAC**: Operator requires read/write access to HTTPRoutes and tenant CRs, read access to Secrets
- **Namespace Isolation**: Use separate tenants per namespace for multi-tenancy

## License

MIT License - see LICENSE file for details
