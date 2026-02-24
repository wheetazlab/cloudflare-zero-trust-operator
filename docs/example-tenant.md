# Example: CloudflareZeroTrustTenant

A `CloudflareZeroTrustTenant` represents your Cloudflare account, tunnel, and credential configuration. The operator watches for HTTPRoutes in the tenant's namespace and reconciles them against Cloudflare.

The example templates installed by the Helm chart (see [examples-templates.md](examples-templates.md)) are automatically discovered by the operator using the `base-<tenant-name>` naming convention — no field on the tenant CR is needed.

## Tenant CR

```yaml
apiVersion: cfzt.cloudflare.com/v1alpha1
kind: CloudflareZeroTrustTenant
metadata:
  name: my-tenant
  namespace: default
spec:
  # Your Cloudflare account ID (32-character hex)
  accountId: "0123456789abcdef0123456789abcdef"

  # Your Cloudflare Tunnel ID (UUID format)
  tunnelId: "12345678-1234-1234-1234-123456789abc"

  # Optional: Your Cloudflare Zone ID (32-character hex)
  # zoneId: "0123456789abcdef0123456789abcdef"

  # Reference to Secret containing Cloudflare API token
  credentialRef:
    name: cloudflare-api-token
    key: token
```

## API Token Secret

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: cloudflare-api-token
  namespace: default
type: Opaque
stringData:
  # Replace with your actual Cloudflare API token
  # Token needs: Account.Cloudflare Tunnel:Edit, Account.Access:Edit
  token: "YOUR_CLOUDFLARE_API_TOKEN_HERE"
```

Or create it imperatively:

```bash
kubectl create secret generic cloudflare-api-token \
  --from-literal=token=YOUR_TOKEN \
  -n default
```
