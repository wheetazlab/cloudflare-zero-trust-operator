# Role: `cloudflare_worker`

The **Cloudflare-side worker** in the three-tier operator architecture. Picks up `CloudflareTask` CRs created by `kube_worker`, claims them, executes all Cloudflare API operations (via the `cloudflare_api` role), and reports success or failure back to the task's status.

## Role in the architecture

```
CloudflareTask CR (Pending)
  └─▶ cloudflare_worker      (this role — Cloudflare-side)
        ├─ claims task:  phase → InProgress
        ├─ calls:        cloudflare_api role (tunnel, DNS, Access, tokens)
        └─ reports back: phase → Completed | Failed + result IDs
```

## When it runs

Invoked each poll cycle by the **cloudflare_worker** Deployment (a separate pod with `ROLE=cloudflare_worker`). Multiple `cloudflare_worker` pods can run simultaneously without conflict because each pod **claims** a task (patches status to `InProgress` with its own pod name) before executing it — tasks are processed at most once.

## Task-by-task flow

| Order | Task file | Description |
|-------|-----------|-------------|
| 1 | `main.yml` | Lists all `CloudflareTask` CRs; filters to `Pending` phase or those with no status yet |
| 2 | `claim_and_execute.yml` | Patches task status to `InProgress`; calls `execute_task.yml` inside a `block/rescue` |
| 3 | `execute_task.yml` | Calls `cloudflare_api` sub-tasks for each operation (tunnel route, CNAME DNS, Access app, policy, service token) based on task spec |
| 4 | `report_result.yml` | Patches task status to `Completed` with all returned Cloudflare resource IDs |
| rescue | `claim_and_execute.yml` | On any failure, patches status to `Failed` with the error message; does not retry |

## Claiming mechanism

Before executing, the worker patches the `CloudflareTask` status:

```yaml
status:
  phase: InProgress
  message: "Claimed by cloudflare-worker-xyz-abc"
  workerPod: "cloudflare-worker-xyz-abc"
```

This prevents two workers from executing the same task. Any task already in `InProgress` or `Completed` is skipped by `main.yml`'s filter.

## Variables

| Variable | Source | Description |
|----------|--------|-------------|
| `operator_namespace` | env `OPERATOR_NAMESPACE` | Namespace where `CloudflareTask` CRs live |
| `worker_pod_name` | env `POD_NAME` | This pod's name — written to the task claim so it's traceable |
| `cloudflare_api_base` | env `CLOUDFLARE_API_BASE` | Cloudflare API base URL |

## Completed task result

On success, the task status becomes:

```yaml
status:
  phase: Completed
  message: "Reconciliation complete"
  workerPod: "cloudflare-worker-xyz-abc"
  result:
    tunnelRouteId: "..."
    accessAppId: "..."
    accessPolicyId: "..."
    serviceTokenId: "..."
    cnameRecordId: "..."
```

The `kube_worker` role's `collect_results.yml` reads these IDs and writes them back as annotations on the original HTTPRoute.

## Error handling

- Cloudflare API errors are caught by the `rescue` block in `claim_and_execute.yml`
- The task status is patched to `Failed` with the error message
- `kube_worker` will re-create the task on the next cycle if the annotation hash still differs (i.e. it hasn't been marked as reconciled)
- Failed tasks are garbage-collected by `kube_worker`'s `cleanup_orphaned.yml`
