#!/bin/bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "======================================"
echo "Cloudflare Zero Trust Operator"
echo "Uninstall Script"
echo "======================================"
echo ""

echo -e "${YELLOW}WARNING: This will remove the operator and all managed resources${NC}"
echo -ne "Are you sure you want to continue? [y/N]: "
read -r response
if [[ ! "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
    echo "Uninstall cancelled"
    exit 0
fi

echo ""
echo -e "${YELLOW}Uninstalling Cloudflare Zero Trust Operator...${NC}"
echo ""

# Step 1: Delete operator deployment
echo "1. Removing operator deployment..."
kubectl delete -f config/deployment/operator.yaml --ignore-not-found=true
echo -e "${GREEN}✓ Operator deployment removed${NC}"
echo ""

# Step 2: Delete RBAC
echo "2. Removing RBAC..."
kubectl delete -f config/rbac/rbac.yaml --ignore-not-found=true
echo -e "${GREEN}✓ RBAC removed${NC}"
echo ""

# Step 3: Delete CRD (this will delete all tenant CRs)
echo "3. Removing CRD (this will delete all CloudflareZeroTrustTenant resources)..."
kubectl delete -f config/crd/cfzt.cloudflare.com_cloudflarezerotrusttenants.yaml --ignore-not-found=true
echo -e "${GREEN}✓ CRD removed${NC}"
echo ""

echo "======================================"
echo -e "${GREEN}Uninstall complete!${NC}"
echo "======================================"
echo ""
echo -e "${YELLOW}Note: HTTPRoute annotations are NOT automatically removed${NC}"
echo "You may want to manually clean up annotations on your HTTPRoutes."
echo ""
