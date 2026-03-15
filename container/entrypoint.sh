#!/bin/bash
set -e

# Set defaults
export WATCH_NAMESPACES="${WATCH_NAMESPACES:-}"
export LOG_LEVEL="${LOG_LEVEL:-INFO}"
export OPERATOR_NAMESPACE="${OPERATOR_NAMESPACE:-cloudflare-zero-trust}"

# Map LOG_LEVEL to Python logging levels for kopf
case "${LOG_LEVEL}" in
    DEBUG)   KOPF_VERBOSE="--verbose --debug" ;;
    WARNING) KOPF_VERBOSE="--quiet" ;;
    ERROR)   KOPF_VERBOSE="--quiet" ;;
    *)       KOPF_VERBOSE="--verbose" ;;
esac

# Display startup banner
echo "======================================"
echo "Cloudflare Zero Trust Operator (kopf)"
echo "======================================"
echo "Watch Namespaces: ${WATCH_NAMESPACES:-ALL}"
echo "Log Level: ${LOG_LEVEL}"
echo "Operator Namespace: ${OPERATOR_NAMESPACE}"
echo "======================================"

# Build namespace args for kopf
NAMESPACE_ARGS=""
if [ -n "${WATCH_NAMESPACES}" ]; then
    IFS=',' read -ra NS_ARRAY <<< "${WATCH_NAMESPACES}"
    for ns in "${NS_ARRAY[@]}"; do
        ns=$(echo "$ns" | xargs)  # trim whitespace
        NAMESPACE_ARGS="${NAMESPACE_ARGS} --namespace=${ns}"
    done
else
    NAMESPACE_ARGS="--all-namespaces"
fi

# Run kopf operator
exec kopf run /app/main.py ${KOPF_VERBOSE} ${NAMESPACE_ARGS}
