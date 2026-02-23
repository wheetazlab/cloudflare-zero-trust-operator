<!-- markdownlint-disable -->
# Contributing to Cloudflare Zero Trust Operator

Thank you for your interest in contributing! This document provides guidelines and instructions for contributing to the project.

## Code of Conduct

Be respectful, inclusive, and professional in all interactions.

## Getting Started

### Prerequisites

- Python 3.9+
- Ansible 2.14+
- Docker
- kubectl
- Access to a Kubernetes cluster (kind, minikube, or cloud-based)
- Cloudflare account with Zero Trust enabled

### Development Setup

1. **Clone the repository:**

```bash
git clone https://github.com/wheetazlab/cloudflare-zero-trust-operator.git
cd cloudflare-zero-trust-operator
```

2. **Install Python dependencies:**

```bash
pip install -r container/requirements.txt
```

3. **Install Ansible collections:**

```bash
ansible-galaxy collection install -r ansible/requirements.yml
```

4. **Set up test environment:**

```bash
# Create a kind cluster
kind create cluster --name cfzt-operator

# Set environment variables
export KUBECONFIG=~/.kube/config
export WATCH_NAMESPACES="default"
export POLL_INTERVAL_SECONDS="30"
export LOG_LEVEL="DEBUG"
```

## Development Workflow

### Running Locally

You can run the operator locally without building a container:

```bash
cd ansible
ansible-playbook playbooks/reconcile.yml \
  -e "poll_interval=30" \
  -e "watch_namespaces=default" \
  -e "log_level=DEBUG"
```

### Building and Testing

```bash
# Run linting
cd ansible && ansible-lint playbooks/ roles/

# Build container image
docker build -f container/Dockerfile -t ghcr.io/wheetazlab/cloudflare-zero-trust-operator:latest .

# Deploy to kind cluster
kind load docker-image ghcr.io/wheetazlab/cloudflare-zero-trust-operator:latest --name cfzt-operator
kubectl apply -f config/crd/
kubectl apply -f config/rbac/
kubectl apply -f config/deployment/

# View logs
kubectl logs -n cloudflare-zero-trust -l app=cloudflare-zero-trust-operator -f
```

### Making Changes

1. Create a feature branch:
   ```bash
   git checkout -b feature/my-feature
   ```

2. Make your changes

3. Test your changes locally

4. Commit with clear messages:
   ```bash
   git commit -m "Add feature: description of feature"
   ```

5. Push and create a pull request

## Project Structure

```
.
├── ansible/                    # Ansible playbooks and roles
│   ├── playbooks/             # Main reconciliation playbook
│   ├── roles/                 # Ansible roles
│   │   ├── cloudflare_api/    # Cloudflare API interactions
│   │   ├── k8s_watch/         # Kubernetes resource watching
│   │   ├── tenant_reconcile/  # Main reconciliation logic
│   │   └── reconciliation_loop/ # Continuous reconciliation loop
│   ├── ansible.cfg            # Ansible configuration
│   └── requirements.yml       # Ansible collection dependencies
├── config/                    # Kubernetes manifests
│   ├── crd/                   # Custom Resource Definitions
│   ├── rbac/                  # RBAC manifests
│   └── deployment/            # Operator deployment
├── container/                 # Container build files
│   ├── Dockerfile             # Container image definition
│   ├── entrypoint.sh          # Container entrypoint script
│   └── requirements.txt       # Python dependencies
├── docs/                      # Documentation
├── charts/                    # Helm chart for operator deployment
├── examples/                  # Example CR configurations
└── .github/workflows/         # CI/CD workflows
```

## Adding New Features

### Adding Cloudflare API Support

To add support for a new Cloudflare API:

1. Create a new task file in `ansible/roles/cloudflare_api/tasks/`:
   ```yaml
   # manage_new_resource.yml
   ---
   - name: Create/Update New Resource
     ansible.builtin.uri:
       url: "{{ cf_api_base }}/accounts/{{ cf_account_id }}/path/to/resource"
       method: POST
       headers:
         Authorization: "Bearer {{ cf_api_token }}"
         Content-Type: "application/json"
       body_format: json
       body: "{{ resource_payload }}"
       status_code: [200, 201]
       return_content: true
     register: create_response
   ```

2. Update the reconciliation logic in `ansible/roles/tenant_reconcile/tasks/reconcile_httproute.yml`

3. Add new annotations to documentation

4. Add examples

### Adding New Annotations

1. Document the annotation in `docs/README.md`
2. Parse the annotation in `ansible/roles/tenant_reconcile/tasks/reconcile_httproute.yml`
3. Implement the logic
4. Add examples

## Testing

### Unit Testing

Currently, the project uses ansible-lint for linting:

```bash
cd ansible && ansible-lint playbooks/ roles/
```

### Integration Testing

Test against a real Kubernetes cluster:

1. Deploy to kind:
   ```bash
   kind create cluster --name cfzt-operator
   kubectl apply -f config/crd/
   kubectl apply -f config/rbac/
   kubectl apply -f config/deployment/
   ```

2. Create test resources:
   ```bash
   kubectl apply -f examples/tenant.yaml
   kubectl apply -f examples/httproute.yaml
   ```

3. Verify behavior:
   ```bash
   kubectl get cloudflarezerotrusttenants
   kubectl get httproutes
   kubectl logs -n cloudflare-zero-trust -l app=cloudflare-zero-trust-operator -f
   ```

## Pull Request Guidelines

### Before Submitting

- [ ] Code follows project structure and conventions
- [ ] All tests pass (`cd ansible && ansible-lint playbooks/ roles/`)
- [ ] Documentation is updated
- [ ] Examples are added/updated if applicable
- [ ] Commit messages are clear and descriptive

### PR Description

Include in your PR description:

- What: Brief description of the change
- Why: Reason for the change
- How: How the change was implemented
- Testing: How you tested the change

## Documentation

When adding features or making changes:

1. Update `docs/README.md` with new annotations/features
2. Update `README.md` if the change affects quick start
3. Add examples in `examples/`
4. Update `CHANGELOG.md`

## Release Process

Releases are handled by maintainers:

1. Update `VERSION` file
2. Update `CHANGELOG.md`
3. Create and push a git tag:
   ```bash
   git tag -a v0.2.0 -m "Release v0.2.0"
   git push origin v0.2.0
   ```
4. GitHub Actions will automatically build and push the container image

## Questions?

- Open an issue for bugs or feature requests
- Start a discussion for questions or ideas

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
