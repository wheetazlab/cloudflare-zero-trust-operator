#!/bin/bash
# Health check script for Cloudflare Zero Trust Operator
# Can be run manually or as a Kubernetes probe

set -e

# Configuration
NAMESPACE="${OPERATOR_NAMESPACE:-cloudflare-zero-trust}"
DEPLOYMENT="cloudflare-zero-trust-operator"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Check if running in Kubernetes pod
if [ -f "/var/run/secrets/kubernetes.io/serviceaccount/token" ]; then
    IN_POD=true
else
    IN_POD=false
fi

# Function to check deployment
check_deployment() {
    if ! kubectl get deployment "${DEPLOYMENT}" -n "${NAMESPACE}" &>/dev/null; then
        echo -e "${RED}✗ Deployment not found${NC}"
        return 1
    fi
    
    ready=$(kubectl get deployment "${DEPLOYMENT}" -n "${NAMESPACE}" -o jsonpath='{.status.readyReplicas}')
    desired=$(kubectl get deployment "${DEPLOYMENT}" -n "${NAMESPACE}" -o jsonpath='{.spec.replicas}')
    
    if [ "${ready}" != "${desired}" ]; then
        echo -e "${RED}✗ Deployment not ready (${ready}/${desired} replicas)${NC}"
        return 1
    fi
    
    echo -e "${GREEN}✓ Deployment is ready (${ready}/${desired} replicas)${NC}"
    return 0
}

# Function to check CRD
check_crd() {
    if ! kubectl get crd cloudflarezerotrusttenants.cfzt.cloudflare.com &>/dev/null; then
        echo -e "${RED}✗ CRD not installed${NC}"
        return 1
    fi
    
    echo -e "${GREEN}✓ CRD is installed${NC}"
    return 0
}

# Function to check recent logs for errors
check_logs() {
    if [ "$IN_POD" = true ]; then
        # Skip log check if running inside pod
        return 0
    fi
    
    # Get recent logs
    logs=$(kubectl logs -n "${NAMESPACE}" -l app=cloudflare-zero-trust-operator --tail=50 2>/dev/null || echo "")
    
    if [ -z "$logs" ]; then
        echo -e "${YELLOW}⚠ No logs available${NC}"
        return 0
    fi
    
    # Check for common error patterns
    if echo "$logs" | grep -i "error\|failed\|exception" | grep -v "ignore" &>/dev/null; then
        echo -e "${YELLOW}⚠ Errors found in recent logs${NC}"
        return 0
    fi
    
    echo -e "${GREEN}✓ No errors in recent logs${NC}"
    return 0
}

# Function to check tenant status
check_tenants() {
    tenants=$(kubectl get cloudflarezerotrusttenants --all-namespaces -o json 2>/dev/null | jq -r '.items | length' 2>/dev/null || echo "0")
    
    if [ "${tenants}" -eq 0 ]; then
        echo -e "${YELLOW}⚠ No CloudflareZeroTrustTenant resources found${NC}"
        return 0
    fi
    
    echo -e "${GREEN}✓ Found ${tenants} CloudflareZeroTrustTenant resource(s)${NC}"
    return 0
}

# Main health check
main() {
    echo "======================================"
    echo "Cloudflare Zero Trust Operator"
    echo "Health Check"
    echo "======================================"
    echo ""
    
    exit_code=0
    
    check_crd || exit_code=1
    check_deployment || exit_code=1
    check_tenants || exit_code=0  # Not critical
    check_logs || exit_code=0      # Not critical
    
    echo ""
    if [ $exit_code -eq 0 ]; then
        echo -e "${GREEN}======================================"
        echo "Health check PASSED"
        echo "======================================${NC}"
    else
        echo -e "${RED}======================================"
        echo "Health check FAILED"
        echo "======================================${NC}"
    fi
    
    exit $exit_code
}

main
