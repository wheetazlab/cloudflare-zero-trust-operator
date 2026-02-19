<!-- markdownlint-disable -->
# Cloudflare Zero Trust Operator

A Kubernetes Operator for managing Cloudflare Zero Trust resources from your cluster using Ansible.

## Architecture

The operator consists of:

1. **Custom Resource Definition (CRD)**: `CloudflareZeroTrustTenant` - represents a Cloudflare account/zone/tunnel configuration with credentials
2. **Controller**: Ansible-based reconciliation loop that watches Kubernetes resources and manages Cloudflare
3. **Annotation-driven configuration**: Traefik IngressRoute resources are annotated to trigger Cloudflare Zero Trust actions

### Component Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Kubernetes Cluster                        │
│                                                              │
│  ┌──────────────────────┐      ┌────────────────────────┐  │
│  │ CloudflareZeroTrust  │      │  Traefik IngressRoute  │  │
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

1. **Watch Phase**: List CloudflareZeroTrustTenant CRs and Traefik IngressRoute resources
2. **Analysis Phase**: For each IngressRoute with cfzt annotations, determine desired Cloudflare state
3. **Sync Phase**: Call Cloudflare APIs to create/update/delete resources
4. **Update Phase**: Patch IngressRoute annotations with Cloudflare resource IDs
5. **Status Phase**: Update CloudflareZeroTrustTenant status with sync results

## Annotation Contract

### CloudflareZeroTrustTenant Selection

IngressRoutes select which tenant to use via:

```yaml
annotations:
  cfzt.cloudflare.com/tenant: "my-tenant"
```

If omitted, the operator uses the only tenant in the namespace. Multiple tenants require explicit selection.

### Cloudflare Zero Trust Annotations

#### Core Configuration

| Annotation | Required | Description | Example |
|------------|----------|-------------|---------|
| `cfzt.cloudflare.com/enabled` | Yes | Enable operator management | `"true"` |
| `cfzt.cloudflare.com/hostname` | Yes | Public hostname to configure | `"app.example.com"` |
| `cfzt.cloudflare.com/originService` | No | Origin service URL (default: derive from IngressRoute) | `"http://myapp.mynamespace.svc:8080"` |
| `cfzt.cloudflare.com/tunnelId` | No | Override tunnel ID (default: from tenant) | `"uuid"` |

#### Access Application Configuration

| Annotation | Required | Description | Example |
|------------|----------|-------------|---------|
| `cfzt.cloudflare.com/accessApp` | No | Create Access Application | `"true"` |
| `cfzt.cloudflare.com/allowGroups` | No | Comma-separated Access Group names | `"Engineering,Admins"` |
| `cfzt.cloudflare.com/allowEmails` | No | Comma-separated email addresses | `"user@example.com"` |
| `cfzt.cloudflare.com/sessionDuration` | No | Session duration | `"8h"` (default: `24h`) |

#### Service Token

| Annotation | Required | Description | Example |
|------------|----------|-------------|---------|
| `cfzt.cloudflare.com/serviceToken` | No | Create service token for machine-to-machine auth | `"true"` |

#### State Tracking (Managed by Operator)

These annotations are set by the operator to track created resources:

- `cfzt.cloudflare.com/hostnameRouteId`: Tunnel hostname route ID
- `cfzt.cloudflare.com/accessAppId`: Access Application ID
- `cfzt.cloudflare.com/accessPolicyIds`: Comma-separated Access Policy IDs
- `cfzt.cloudflare.com/serviceTokenId`: Service Token ID
- `cfzt.cloudflare.com/serviceTokenSecretName`: K8s Secret name containing token credentials

### Example IngressRoute

```yaml
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: my-app
  namespace: default
  annotations:
    cfzt.cloudflare.com/enabled: "true"
    cfzt.cloudflare.com/tenant: "prod-tenant"
    cfzt.cloudflare.com/hostname: "myapp.example.com"
    cfzt.cloudflare.com/accessApp: "true"
    cfzt.cloudflare.com/allowGroups: "Engineering"
    cfzt.cloudflare.com/sessionDuration: "8h"
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
    originService: "http://traefik.traefik.svc:80"
```

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
    managedIngressRoutes: 5
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
- Traefik ingress controller with IngressRoute CRD installed
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

2. **Install CRDs and operator**:

```bash
kubectl apply -f config/crd/cfzt.cloudflare.com_cloudflarezerotrusttenants.yaml
kubectl apply -f config/rbac/
kubectl apply -f config/deployment/operator.yaml
```

3. **Create a CloudflareZeroTrustTenant**:

```bash
kubectl apply -f examples/tenant.yaml
```

4. **Annotate your IngressRoutes**:

```bash
kubectl annotate ingressroute my-app \
  cfzt.cloudflare.com/enabled="true" \
  cfzt.cloudflare.com/hostname="myapp.example.com" \
  cfzt.cloudflare.com/accessApp="true"
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
make lint
```

Build container locally:

```bash
make docker-build
```

Deploy to kind cluster:

```bash
make kind-deploy
```

## Idempotency & Deletion

### Idempotent Operations

The operator is designed to be idempotent:
- Repeated reconciliation produces the same result
- Cloudflare resources are updated in place when configuration changes
- Resource IDs stored in annotations enable proper updates

### Deletion Handling

When an IngressRoute is deleted or annotations are removed:

1. Operator detects the removal during next reconciliation
2. Retrieves Cloudflare resource IDs from stored state (if annotations still exist)
3. Calls Cloudflare APIs to delete:
   - Service tokens (and associated Secrets)
   - Access policies
   - Access applications
   - Hostname routes
4. Removes state annotations from IngressRoute (if still exists)

### Finalizers

The operator uses Kubernetes finalizers on managed IngressRoutes to ensure clean deletion of Cloudflare resources before the IngressRoute is removed from etcd.

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
kubectl get ingressroute my-app -o jsonpath='{.metadata.annotations}' | jq
```

### Common Issues

**Issue**: Operator not detecting IngressRoute changes
- **Solution**: Check WATCH_NAMESPACES includes the IngressRoute namespace
- **Solution**: Verify IngressRoute has `cfzt.cloudflare.com/enabled: "true"`

**Issue**: Cloudflare API rate limiting
- **Solution**: Increase POLL_INTERVAL_SECONDS
- **Solution**: Reduce number of managed IngressRoutes per tenant

**Issue**: Access Application not created
- **Solution**: Verify `cfzt.cloudflare.com/accessApp: "true"` annotation
- **Solution**: Check Cloudflare API token has Access:Edit permission
- **Solution**: Review operator logs for API errors

## Security Considerations

- **API Tokens**: Store in Kubernetes Secrets, never in annotations or ConfigMaps
- **Service Token Secrets**: Automatically created with generated names, use RBAC to restrict access
- **RBAC**: Operator requires read/write access to IngressRoutes and tenant CRs, read access to Secrets
- **Namespace Isolation**: Use separate tenants per namespace for multi-tenancy

## License

MIT License - see LICENSE file for details
