# Cloudflare Zero Trust Operator Examples

This directory contains example configurations for the operator.

## Quick Start

### 1. Create Tenant

First, create a CloudflareZeroTrustTenant with your Cloudflare account credentials:

```bash
# Edit tenant.yaml with your account ID, tunnel ID, and API token
kubectl apply -f tenant.yaml
```

### 2. Deploy Templates

Deploy the built-in templates to your cluster:

```bash
kubectl apply -f templates.yaml
```

This creates 7 templates:

- **default**: Public tunnel route with HTTPS origin (no Access)
- **secure-internal-app**: Access application with existing Azure AD policy
- **grpc-backend**: HTTP/2 enabled for gRPC services
- **api-with-service-token**: Service token for machine-to-machine auth
- **admin-panel**: Short session, strict security for admin interfaces
- **simple-email-allow**: Creates simple policy with email allowlist (backward compatible)
- **custom-origin**: Custom backend service with specific TLS settings

### 3. Create IngressRoutes

Use simplified annotations to reference templates:

```bash
kubectl apply -f ingressroute-with-templates.yaml
```

## Template Architecture

### Why Templates?

**Before templates** (annotation-heavy):

```yaml
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  annotations:
    cfzt.cloudflare.com/enabled: "true"
    cfzt.cloudflare.com/hostname: "app.example.com"
    cfzt.cloudflare.com/accessApp: "true"
    cfzt.cloudflare.com/sessionDuration: "24h"
    cfzt.cloudflare.com/no-tls-verify: "true"
    cfzt.cloudflare.com/tls-timeout: "10"
    cfzt.cloudflare.com/http-redirect: "true"
    cfzt.cloudflare.com/autoRedirectToIdentity: "false"
    # ... many more annotations ...
```

**With templates** (clean):

```yaml
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  annotations:
    cfzt.cloudflare.com/enabled: "true"
    cfzt.cloudflare.com/hostname: "app.example.com"
    cfzt.cloudflare.com/template: "secure-internal-app"  # That's it!
```

### Configuration Hierarchy

Settings are resolved in this order:

1. **Template** (`CloudflareZeroTrustTemplate` spec)
2. **Tenant defaults** (`CloudflareZeroTrustTenant` spec.defaults)
3. **Built-in defaults**

Annotations only select **which** tenant and template to use - they don't override template settings.

## Using Existing Cloudflare Policies

The key feature for your use case: **reference existing policies** instead of creating them.

### In Cloudflare UI

1. Create your policies with Azure AD, Google Workspace, etc.
2. Configure login methods, MFA requirements, etc.
3. Copy the policy IDs from the URL or API

### In Template

```yaml
apiVersion: cfzt.cloudflare.com/v1alpha1
kind: CloudflareZeroTrustTemplate
metadata:
  name: azure-ad-auth
spec:
  originService:
    url: "https://traefik.traefik.svc.cluster.local:443"
    httpRedirect: true
    originTLS:
      noTLSVerify: true
  
  accessApplication:
    enabled: true
    sessionDuration: "24h"
    
    # Reference your existing policies - operator won't create policies
    existingPolicyIds:
      - "73badfbd-c825-4bf3-a543-e2882627969d"  # Your ADAUTH policy
      - "another-policy-id-here"  # Optional: multiple policies
```

### In IngressRoute

```yaml
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: longhorn
  annotations:
    cfzt.cloudflare.com/enabled: "true"
    cfzt.cloudflare.com/hostname: "longhorn.wheethome.com"
    cfzt.cloudflare.com/template: "azure-ad-auth"
```

The operator will:

- Create the Access Application
- **NOT** create policies (you already have them)
- **NOT** modify your existing policies

## Creating Custom Templates

### Example: Production HTTPS Backend

```yaml
apiVersion: cfzt.cloudflare.com/v1alpha1
kind: CloudflareZeroTrustTemplate
metadata:
  name: prod-https
  namespace: production
spec:
  originService:
    url: "https://backend.production.svc:8443"
    httpRedirect: true
    originTLS:
      noTLSVerify: false  # Verify TLS in production
      originServerName: "backend.internal.corp"
      caPool: "/etc/cloudflared/certs/ca.pem"
      tlsTimeout: 15
      http2Origin: false
  
  accessApplication:
    enabled: true
    sessionDuration: "8h"  # Shorter for production
    existingPolicyIds:
      - "prod-policy-id"
    autoRedirectToIdentity: true
    appLauncherVisible: true
```

### Example: Public API with Service Token

```yaml
apiVersion: cfzt.cloudflare.com/v1alpha1
kind: CloudflareZeroTrustTemplate
metadata:
  name: api-token
  namespace: default
spec:
  originService:
    url: "https://api-gateway.default.svc:443"
    httpRedirect: false  # APIs don't need redirect
    originTLS:
      noTLSVerify: true
      tlsTimeout: 10
  
  accessApplication:
    enabled: true
    sessionDuration: "1h"
    serviceAuth401Redirect: true  # Return 401 for APIs
    appLauncherVisible: false  # Don't show in app launcher
  
  serviceToken:
    enabled: true
    duration: "8760h"  # 1 year
```

## File Reference

- **tenant.yaml**: CloudflareZeroTrustTenant example with full configuration
- **templates.yaml**: 7 built-in templates for common use cases
- **ingressroute-with-templates.yaml**: Example IngressRoutes using templates
- **ingressroute.yaml**: Old-style examples with many annotations (deprecated)

## Migration Guide

### From Annotation-Heavy to Templates

1. Identify common patterns in your IngressRoute annotations
2. Create templates for each pattern
3. Update IngressRoutes to reference templates:
   - Remove: all config annotations (originService, TLS settings, Access settings)
   - Keep: enabled, hostname, template, tenant
4. Deploy templates before updating IngressRoutes

### Backward Compatibility

The operator still supports the old annotation-based approach, but templates are **strongly recommended** for:

- Cleaner IngressRoutes
- Consistent configuration
- Easier updates (change template, all apps update)
- DRY principle

## Getting Policy IDs

### From Cloudflare UI

1. Go to Zero Trust → Access → Applications
2. Click your application
3. Click "Policies" tab
4. Policy ID is in the URL: `...policies/<POLICY_ID>`

### From Cloudflare API

```bash
# List all policies for an application
curl -X GET "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/access/apps/$APP_ID/policies" \
  -H "Authorization: Bearer $API_TOKEN" \
  | jq '.result[].id'
```

## Questions?

See [docs/README.md](../docs/README.md) for complete documentation.
