#!/bin/bash
set -e

# Display startup banner
echo "======================================"
echo "Cloudflare Zero Trust Operator"
echo "======================================"
echo "Watch Namespaces: ${WATCH_NAMESPACES:-ALL}"
echo "Poll Interval: ${POLL_INTERVAL_SECONDS:-60}s"
echo "Log Level: ${LOG_LEVEL:-INFO}"
echo "======================================"

# Set defaults
export POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-60}"
export WATCH_NAMESPACES="${WATCH_NAMESPACES:-}"
export LOG_LEVEL="${LOG_LEVEL:-INFO}"
export CLOUDFLARE_API_BASE="${CLOUDFLARE_API_BASE:-https://api.cloudflare.com/client/v4}"
export OPERATOR_NAMESPACE="${OPERATOR_NAMESPACE:-cloudflare-zero-trust}"

# Set Ansible environment
export ANSIBLE_CONFIG="/ansible/ansible.cfg"
export ANSIBLE_FORCE_COLOR="true"
export ANSIBLE_HOST_KEY_CHECKING="False"
export ANSIBLE_RETRY_FILES_ENABLED="False"
export ANSIBLE_STDOUT_CALLBACK="yaml"

# Set log level for Ansible
case "${LOG_LEVEL}" in
    DEBUG)
        export ANSIBLE_VERBOSITY=2
        ;;
    INFO)
        export ANSIBLE_VERBOSITY=1
        ;;
    WARNING|ERROR)
        export ANSIBLE_VERBOSITY=0
        ;;
    *)
        export ANSIBLE_VERBOSITY=1
        ;;
esac

# Function to run reconciliation
run_reconciliation() {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Starting reconciliation cycle..."
    
    ansible-playbook /ansible/playbooks/reconcile.yml \
        -e "poll_interval=${POLL_INTERVAL_SECONDS}" \
        -e "watch_namespaces=${WATCH_NAMESPACES}" \
        -e "log_level=${LOG_LEVEL}" \
        -e "cloudflare_api_base=${CLOUDFLARE_API_BASE}"
    
    reconcile_rc=$?
    
    if [ $reconcile_rc -eq 0 ]; then
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Reconciliation completed successfully"
    else
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Reconciliation failed with exit code: $reconcile_rc"
    fi
    
    return $reconcile_rc
}

# Handle shutdown signals
shutdown() {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Received shutdown signal, exiting..."
    exit 0
}

trap shutdown SIGTERM SIGINT

# Main loop
while true; do
    run_reconciliation || true
    
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Waiting ${POLL_INTERVAL_SECONDS}s before next reconciliation..."
    sleep "${POLL_INTERVAL_SECONDS}" &
    wait $!
done
