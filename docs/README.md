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
  name: longhorn
  annotations:
    # Enable operator management
    cfzt.cloudflare.com/enabled: "true"
    
    # Public hostname (REQUIRED)
    cfzt.cloudflare.com/hostname: "longhorn.wheethome.com"
    
    # Template to use (optional, defaults to 'default')
    cfzt.cloudflare.com/template: "secure-internal-app"
    
    # Tenant to use (optional if only one tenant in namespace)
    cfzt.cloudflare.com/tenant: "prod-tenant"
spec:
  # ... Gateway API routing config ...
```

#### Step 2: Template Definition

Create reusable templates with full configuration:

```yaml
apiVersion: cfzt.cloudflare.com/v1alpha1
kind: CloudflareZeroTrustTemplate
metadata:
  name: secure-internal-app
  namespace: default
spec:
  # Origin service settings
  originService:
    url: "https://traefik.traefik.svc.cluster.local:443"
    httpRedirect: true
    originTLS:
      noTLSVerify: true  # Self-signed certs in cluster
      tlsTimeout: 10
  
  # Access Application settings
  accessApplication:
    enabled: true
    sessionDuration: "24h"
    
    # Use existing policies created in Cloudflare UI
    existingPolicyIds:
      - "73badfbd-c825-4bf3-a543-e2882627969d"  # Your ADAUTH policy
    
    # Application settings
    autoRedirectToIdentity: false
    appLauncherVisible: true
    skipInterstitial: false
```

### Configuration Hierarchy

Settings are resolved in this order:

1. **Template** - Defines all configuration (origin TLS, Access application, service tokens)
2. **Tenant defaults** - Fallback for any settings not in template
3. **Default values** - Built-in defaults if not in template or tenant

Templates are **not overridable** by HTTPRoute annotations - annotations only select tenant and template.

### Built-in Templates

The operator includes several templates:

| Template Name | Description | Use Case |
|---------------|-------------|----------|
| `default` | Public tunnel route with HTTPS origin | Basic public applications |
| `secure-internal-app` | Access app with existing Azure AD policy | Internal tools requiring authentication |
| `grpc-backend` | HTTP/2 enabled for gRPC | gRPC services |
| `api-with-service-token` | Service token for machine-to-machine auth | APIs and webhooks |
| `admin-panel` | Short session, strict security settings | Administrative interfaces |

See [examples/templates.yaml](../examples/templates.yaml) for complete template definitions.

### Core Annotations

| Annotation | Required | Description | Example |
|------------|----------|-------------|---------|
| `cfzt.cloudflare.com/enabled` | Yes | Enable operator management | `"true"` |
| `cfzt.cloudflare.com/hostname` | Yes | Public hostname to configure | `"app.example.com"` |
| `cfzt.cloudflare.com/template` | No | Template name (default: `"default"`) | `"secure-internal-app"` |
| `cfzt.cloudflare.com/tenant` | No | Tenant name (default: only tenant in namespace) | `"prod-tenant"` |
| `cfzt.cloudflare.com/tunnelId` | No | Override tunnel ID (default: from tenant) | `"uuid"` |

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
  name: secure-internal-app
  namespace: default
spec:
  # Optional: Default tenant reference (can be overridden in HTTPRoute)
  tenantRef: "prod-tenant"
  
  # Origin service configuration
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
    
    # Reference existing policies (operator won't create policies)
    existingPolicyIds:
      - "policy-id-1"
      - "policy-id-2"
    
    # OR create simple policies (backward compatible)
    # allowEmails:
    #   - "user@example.com"
    # allowGroups:
    #   - "Engineering"
    
    # Application settings
    autoRedirectToIdentity: false
    enableBindingCookie: false
    httpOnlyCookieAttribute: true
    sameSiteCookieAttribute: "lax"  # none, lax, strict
    logoUrl: ""
    skipInterstitial: false
    appLauncherVisible: true
    serviceAuth401Redirect: false  # Return 401 instead of redirect
    customDenyMessage: ""
    customDenyUrl: ""
    customNonIdentityDenyUrl: ""
  
  # Service Token configuration
  serviceToken:
    enabled: false
    duration: "8760h"  # 1 year
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
- **existingPolicyIds** (array of strings): List of existing policy IDs (operator won't create policies)
- **allowEmails** (array of strings): Email addresses for simple policy (creates policy)
- **allowGroups** (array of strings): Access Group names for simple policy (creates policy)
- **Application settings**: See [Cloudflare Access Application API](https://developers.cloudflare.com/) for details

#### serviceToken
- **enabled** (bool, default: false): Create service token for machine-to-machine auth
- **duration** (string, default: "8760h"): Token lifetime

### Example HTTPRoute with Template

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: longhorn
  namespace: default
  annotations:
    cfzt.cloudflare.com/enabled: "true"
    cfzt.cloudflare.com/hostname: "longhorn.wheethome.com"
    cfzt.cloudflare.com/template: "secure-internal-app"
spec:
  entryPoints:
    - web
  routes:
    - match: Host(`myapp.example.com`)
      kind: Rule
      services:
        - name: myapp
          port: 8080
```

## CloudflareZeroTrustTenant CRD

### Spec

```yaml
apiVersion: cfzt.cloudflare.com/v1alpha1
kind: CloudflareZeroTrustTenant
metadata:
  name: prod-tenant
  namespace: default
spec:
  accountId: "cloudflare-account-id"
  tunnelId: "default-tunnel-uuid"
  zoneId: "optional-zone-id"  # optional
  credentialRef:
    name: cloudflare-api-token
    key: token
  defaults:
    sessionDuration: "24h"
    originService: "https://traefik.traefik.svc.cluster.local:443"
    httpRedirect: true  # Default: auto-redirect HTTP to HTTPS at edge
    originTLS:
      noTLSVerify: true  # Skip TLS verification (useful for self-signed certs)
      originServerName: ""  # Custom SNI hostname (optional)
      caPool: ""  # Path to CA cert file (optional)
      tlsTimeout: 10  # TLS handshake timeout in seconds (1-300)
      http2Origin: false  # Use HTTP/2 for origin connection
      matchSNIToHost: false  # Match SNI to Host header
```

**Spec Fields:**

- **accountId** (required): Cloudflare Account ID
- **tunnelId** (required): Default Cloudflare Tunnel ID for routes
- **zoneId** (optional): Cloudflare Zone ID (for DNS/zone-specific operations)
- **credentialRef** (required): Reference to Kubernetes Secret containing API token
  - **name**: Secret name
  - **key**: Key within the secret containing the API token
- **defaults**: Default values for HTTPRoutes (overridable via annotations)
  - **sessionDuration**: Default Access Application session duration (e.g., "24h", "8h")
  - **originService**: Default origin service URL (auto-detects HTTP/HTTPS from scheme)
  - **httpRedirect**: Automatically redirect HTTP to HTTPS at Cloudflare edge (default: true)
  - **originTLS**: TLS configuration for HTTPS origin connections
    - **noTLSVerify**: Skip certificate verification (default: false) - useful for self-signed certs
    - **originServerName**: Custom SNI hostname for TLS handshake (optional)
    - **caPool**: Path to CA certificate file for validation (optional)
    - **tlsTimeout**: TLS handshake timeout in seconds, 1-300 (default: 10)
    - **http2Origin**: Use HTTP/2 for origin connection (default: false) - useful for gRPC
    - **matchSNIToHost**: Match SNI to Host header automatically (default: false)

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

4. **Create default templates**:

```bash
# Install built-in templates (default, secure-internal-app, grpc-backend, etc.)
kubectl apply -f examples/templates.yaml
```

5. **Create a CloudflareZeroTrustTenant**:

```bash
kubectl apply -f examples/tenant.yaml
```

6. **Annotate your HTTPRoutes**:

```bash
# Simple: Just enable with hostname (uses 'default' template)
kubectl annotate httproute my-app \
  cfzt.cloudflare.com/enabled="true" \
  cfzt.cloudflare.com/hostname="myapp.example.com"

# With template: Use a specific template
kubectl annotate httproute secure-app \
  cfzt.cloudflare.com/enabled="true" \
  cfzt.cloudflare.com/hostname="secure.example.com" \
  cfzt.cloudflare.com/template="secure-internal-app"
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
