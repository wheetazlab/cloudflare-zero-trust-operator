# Role: `operator_config`

Watches the `CloudflareZeroTrustOperatorConfig` Custom Resource and applies its settings to the operator's own Kubernetes `Deployment` — allowing the operator to reconfigure itself without a Helm upgrade.

## When it runs

Called at the start of every reconciliation cycle by the **manager** before tenant reconciliation begins. If no `CloudflareZeroTrustOperatorConfig` exists, the role skips silently and the operator continues with its current deployment settings.

## What it does

| Step | Task file | Description |
|------|-----------|-------------|
| 1 | `main.yml` | Fetches the `CloudflareZeroTrustOperatorConfig` CR in `operator_namespace` |
| 2 | `apply_config.yml` | Patches the operator `Deployment` with replicas, resources, nodeSelector, tolerations, and env vars from the CR spec |
| 3 | `update_status.yml` | Writes a `Ready` condition and `observedGeneration` back to the CR status |
| 4 | `manage_worker_deployments.yml` | Ensures the `kube_worker` and `cloudflare_worker` Deployments exist in `operator_namespace` |

## Three-tier worker management

This role is responsible for creating the **kube_worker** and **cloudflare_worker** Deployments that the manager spawns. Both workers run from the same container image as the manager but with `ROLE=kube_worker` and `ROLE=cloudflare_worker` respectively.

## Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `operator_namespace` | yes | Namespace where the operator and its CRs live |
| `operator_config` | set by role | The fetched `CloudflareZeroTrustOperatorConfig` resource (set as a fact internally) |

## CRD: `CloudflareZeroTrustOperatorConfig`

```yaml
apiVersion: cfzt.cloudflare.com/v1alpha1
kind: CloudflareZeroTrustOperatorConfig
metadata:
  name: operator-config
  namespace: cloudflare-zero-trust
spec:
  replicas: 1
  resources:
    requests:
      cpu: "200m"
      memory: "512Mi"
    limits:
      cpu: "1000m"
      memory: "1Gi"
  nodeSelector:
    node-role.kubernetes.io/infra: ""
  tolerations:
    - key: "dedicated"
      operator: "Equal"
      value: "infrastructure"
      effect: "NoSchedule"
  environmentVariables:
    pollIntervalSeconds: 30
    logLevel: "DEBUG"
    watchNamespaces: "default,production"
```

## Notes

- **Singleton**: Only one `CloudflareZeroTrustOperatorConfig` per operator namespace is honoured.
- **Self-update**: When the role patches the Deployment, Kubernetes will roll the pod. The new pod will pick up the new config on its first cycle.
- **No-op when absent**: Missing CR is not an error — the operator keeps running with its original Helm values.

See also: [`config/samples/operator_config.yaml`](../../../config/samples/operator_config.yaml)
