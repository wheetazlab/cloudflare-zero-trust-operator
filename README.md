<!-- markdownlint-disable -->
# Cloudflare Zero Trust Operator

A Kubernetes Operator for managing Cloudflare Zero Trust resources directly from your cluster using Ansible.

## Features

- 🚀 **Annotation-driven configuration** - Manage Cloudflare Zero Trust from Traefik HTTPRoute annotations
- 🔒 **Access Control** - Automatically create and manage Cloudflare Access Applications and Policies
- 🔑 **Service Tokens** - Generate service tokens for machine-to-machine authentication
- 🌐 **Tunnel Management** - Configure Cloudflare Tunnel hostname routes
- 🔄 **Idempotent** - Safe to run repeatedly, handles updates and deletions
- 🎯 **Multi-tenant** - Support multiple Cloudflare accounts in one cluster
- 📝 **GitOps-friendly** - Managed entirely through Kubernetes CRs and annotations

## Quick Start

1. **Install the operator:**

```bash
kubectl apply -f https://raw.githubusercontent.com/wheetazlab/cloudflare-zero-trust-operator/main/config/crd/cfzt.cloudflare.com_cloudflarezerotrusttenants.yaml
kubectl apply -f https://raw.githubusercontent.com/wheetazlab/cloudflare-zero-trust-operator/main/config/rbac/rbac.yaml
kubectl apply -f https://raw.githubusercontent.com/wheetazlab/cloudflare-zero-trust-operator/main/config/deployment/operator.yaml
```

2. **Create a Cloudflare API token secret:**

```bash
kubectl create secret generic cloudflare-api-token \
  --from-literal=token=YOUR_API_TOKEN \
  -n cloudflare-zero-trust
```

3. **Create a CloudflareZeroTrustTenant:**

```yaml
apiVersion: cfzt.cloudflare.com/v1alpha1
kind: CloudflareZeroTrustTenant
metadata:
  name: prod-tenant
  namespace: default
spec:
  accountId: "your-account-id"
  tunnelId: "your-tunnel-id"
  credentialRef:
    name: cloudflare-api-token
    key: token
```

4. **Annotate your HTTPRoutes:**

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: myapp
  annotations:
    cfzt.cloudflare.com/enabled: "true"
    cfzt.cloudflare.com/hostname: "myapp.example.com"
    cfzt.cloudflare.com/accessApp: "true"
    cfzt.cloudflare.com/allowEmails: "user@example.com"
spec:
  # ... your HTTPRoute spec
```

## Documentation

- [Full Documentation](docs/README.md) - Architecture, API reference, deployment guide
- [Examples](examples/) - Example configurations for various use cases

## What It Does

The operator watches your Traefik HTTPRoute resources for specific annotations and automatically:

1. **Creates Cloudflare Tunnel hostname routes** - Routes public hostnames through your Cloudflare Tunnel to origin services
2. **Creates Access Applications** - Protects your applications with Cloudflare Access
3. **Creates Access Policies** - Configures who can access your applications (email, groups, etc.)
4. **Generates Service Tokens** - Creates tokens for machine-to-machine authentication
5. **Tracks state** - Stores Cloudflare resource IDs in HTTPRoute annotations for updates/deletions

## Requirements

- Kubernetes 1.23+
- Gateway API-compatible ingress controller with HTTPRoute CRD
- Cloudflare account with Zero Trust enabled
- Cloudflare API token with:
  - Account.Cloudflare Tunnel:Edit
  - Account.Access:Edit

## Architecture

```
┌─────────────────┐      ┌──────────────────┐      ┌─────────────────┐
│  HTTPRoute   │─────▶│  CFZT Operator   │─────▶│   Cloudflare    │
│  (annotations)  │      │   (Ansible)      │      │   Zero Trust    │
└─────────────────┘      └──────────────────┘      └─────────────────┘
        │                         │
        │                         ▼
        │                ┌──────────────────┐
        └───────────────▶│  Tenant CR       │
                         │  (credentials)   │
                         └──────────────────┘
```

## Development

```bash
# Clone the repository
git clone https://github.com/wheetazlab/cloudflare-zero-trust-operator.git
cd cloudflare-zero-trust-operator

# Install dependencies
pip install -r container/requirements.txt
ansible-galaxy collection install -r ansible/requirements.yml

# Run locally
cd ansible
ansible-playbook playbooks/reconcile.yml

# Build container
docker build -f container/Dockerfile -t ghcr.io/wheetazlab/cloudflare-zero-trust-operator:latest .

# Deploy to kind cluster
kind create cluster --name cfzt-operator
kubectl apply -f config/crd/
kubectl apply -f config/rbac/
kubectl apply -f config/deployment/
```

## Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `WATCH_NAMESPACES` | `""` (all) | Comma-separated list of namespaces to watch |
| `POLL_INTERVAL_SECONDS` | `60` | Reconciliation interval in seconds |
| `LOG_LEVEL` | `INFO` | Log level (DEBUG, INFO, WARNING, ERROR) |
| `CLOUDFLARE_API_BASE` | `https://api.cloudflare.com/client/v4` | Cloudflare API base URL |

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Support

- 📖 [Documentation](docs/README.md)
- 🐛 [Issue Tracker](https://github.com/wheetazlab/cloudflare-zero-trust-operator/issues)
- 💬 [Discussions](https://github.com/wheetazlab/cloudflare-zero-trust-operator/discussions) 
