#!/bin/bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "======================================"
echo "Cloudflare Zero Trust Operator"
echo "Quick Start Installation Script"
echo "======================================"
echo ""

# Check prerequisites
echo -e "${YELLOW}Checking prerequisites...${NC}"

command -v kubectl >/dev/null 2>&1 || { echo -e "${RED}Error: kubectl is not installed${NC}"; exit 1; }
echo -e "${GREEN}✓ kubectl found${NC}"

command -v docker >/dev/null 2>&1 || { echo -e "${RED}Error: docker is not installed${NC}"; exit 1; }
echo -e "${GREEN}✓ docker found${NC}"

# Check if kubectl can access cluster
kubectl cluster-info >/dev/null 2>&1 || { echo -e "${RED}Error: Cannot access Kubernetes cluster${NC}"; exit 1; }
echo -e "${GREEN}✓ Kubernetes cluster accessible${NC}"

echo ""
echo -e "${YELLOW}Installing Cloudflare Zero Trust Operator...${NC}"
echo ""

# Step 1: Install CRD
echo "1. Installing CRD..."
kubectl apply -f config/crd/cfzt.cloudflare.com_cloudflarezerotrusttenants.yaml
echo -e "${GREEN}✓ CRD installed${NC}"
echo ""

# Step 2: Install RBAC
echo "2. Installing RBAC..."
kubectl apply -f config/rbac/rbac.yaml
echo -e "${GREEN}✓ RBAC installed${NC}"
echo ""

# Step 3: Build container image
echo "3. Building container image..."
make docker-build
echo -e "${GREEN}✓ Container image built${NC}"
echo ""

# Step 4: Deploy operator
echo "4. Deploying operator..."
kubectl apply -f config/deployment/operator.yaml
echo -e "${GREEN}✓ Operator deployed${NC}"
echo ""

# Wait for operator to be ready
echo "5. Waiting for operator to be ready..."
kubectl wait --for=condition=available --timeout=120s deployment/cloudflare-zero-trust-operator -n cloudflare-zero-trust
echo -e "${GREEN}✓ Operator is ready${NC}"
echo ""

echo "======================================"
echo -e "${GREEN}Installation complete!${NC}"
echo "======================================"
echo ""
echo "Next steps:"
echo "1. Create a Cloudflare API token secret:"
echo "   kubectl create secret generic cloudflare-api-token \\"
echo "     --from-literal=token=YOUR_API_TOKEN \\"
echo "     -n default"
echo ""
echo "2. Create a CloudflareZeroTrustTenant:"
echo "   kubectl apply -f examples/tenant.yaml"
echo ""
echo "3. Annotate your HTTPRoutes:"
echo "   kubectl apply -f examples/httproute.yaml"
echo ""
echo "Check operator logs with:"
echo "   kubectl logs -n cloudflare-zero-trust -l app=cloudflare-zero-trust-operator -f"
echo ""
