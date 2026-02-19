.PHONY: help lint test docker-build docker-push install uninstall deploy undeploy kind-deploy kind-undeploy

# Variables
IMAGE_REGISTRY ?= ghcr.io
IMAGE_OWNER ?= wheetazlab
IMAGE_NAME ?= cloudflare-zero-trust-operator
IMAGE_TAG ?= latest
IMAGE ?= $(IMAGE_REGISTRY)/$(IMAGE_OWNER)/$(IMAGE_NAME):$(IMAGE_TAG)

NAMESPACE ?= cloudflare-zero-trust
KUBECONFIG ?= ~/.kube/config

help: ## Display this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

##@ Development

lint: ## Run ansible-lint on playbooks and roles
	cd ansible && ansible-lint playbooks/ roles/

test: lint ## Run tests (currently just lint)
	@echo "Running tests..."
	@echo "✓ Ansible lint passed"

##@ Build

docker-build: ## Build container image
	docker build -f container/Dockerfile -t $(IMAGE) .

docker-push: docker-build ## Build and push container image
	docker push $(IMAGE)

##@ Deployment

install: ## Install CRDs and RBAC
	kubectl apply -f config/crd/
	kubectl apply -f config/rbac/

uninstall: ## Uninstall CRDs and RBAC
	kubectl delete -f config/rbac/ --ignore-not-found=true
	kubectl delete -f config/crd/ --ignore-not-found=true

deploy: install ## Deploy operator to cluster
	kubectl apply -f config/deployment/

undeploy: ## Remove operator from cluster
	kubectl delete -f config/deployment/ --ignore-not-found=true

##@ Kind (Local Development)

kind-create: ## Create kind cluster
	kind create cluster --name cfzt-operator

kind-delete: ## Delete kind cluster
	kind delete cluster --name cfzt-operator

kind-load: docker-build ## Load image into kind cluster
	kind load docker-image $(IMAGE) --name cfzt-operator

kind-deploy: kind-load install ## Deploy to kind cluster
	kubectl apply -f config/deployment/
	kubectl set image deployment/cloudflare-zero-trust-operator operator=$(IMAGE) -n $(NAMESPACE)
	kubectl rollout status deployment/cloudflare-zero-trust-operator -n $(NAMESPACE)

kind-undeploy: undeploy uninstall ## Remove from kind cluster

##@ Examples

create-example-tenant: ## Create example tenant
	kubectl apply -f examples/tenant.yaml

create-example-ingressroute: ## Create example IngressRoute
	kubectl apply -f examples/ingressroute.yaml

delete-examples: ## Delete example resources
	kubectl delete -f examples/ --ignore-not-found=true

##@ Utilities

logs: ## Show operator logs
	kubectl logs -n $(NAMESPACE) -l app=cloudflare-zero-trust-operator -f

status: ## Show operator status
	kubectl get pods -n $(NAMESPACE)
	kubectl get cloudflarezerotrusttenants --all-namespaces

watch: ## Watch operator and managed resources
	watch -n 2 'kubectl get pods -n $(NAMESPACE) && echo && kubectl get cloudflarezerotrusttenants --all-namespaces && echo && kubectl get ingressroutes --all-namespaces'

clean: ## Clean build artifacts
	rm -rf build/ dist/ *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name '*.pyc' -delete
