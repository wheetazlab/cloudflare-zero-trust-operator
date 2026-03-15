<!-- markdownlint-disable -->
# Contributing to Cloudflare Zero Trust Operator

Thank you for your interest in contributing! This document provides guidelines and instructions for contributing to the project.

## Code of Conduct

Be respectful, inclusive, and professional in all interactions.

## Getting Started

### Prerequisites

- Python 3.9+
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

3. **Set up test environment:**

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

The operator is a kopf-based Python controller. Run it locally with:

```bash
python python/main.py
```

### Building and Testing

```bash
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
├── python/                    # kopf-based operator source
│   ├── main.py               # Entry point and kopf handlers
│   ├── reconciler.py         # Core reconciliation and deletion logic
│   ├── cloudflare_api.py     # Cloudflare SDK wrapper functions
│   ├── config.py             # Settings dataclasses and template merge
│   └── k8s.py                # Kubernetes API helpers
├── container/                 # Container build files
│   ├── Dockerfile             # Container image definition
│   ├── entrypoint.sh          # Container entrypoint script
│   └── requirements.txt       # Python dependencies
├── charts/                    # Helm chart for operator deployment
├── docs/                      # Documentation
└── .github/workflows/         # CI/CD workflows
```

## Adding New Features

### Adding Cloudflare API Support

To add support for a new Cloudflare API:

1. Add API interaction functions in `python/cloudflare_api.py`
2. Update reconciliation logic in `python/reconciler.py`
3. Add new annotations to documentation
4. Add examples

### Adding New Annotations

1. Document the annotation in `docs/README.md`
2. Parse the annotation in `python/config.py`
3. Implement the logic in `python/reconciler.py`
4. Add examples

## Testing

### Unit Testing

Run linting:

```bash
pylint python/
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
- [ ] All tests pass
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
