# Role: `kube_worker`

The **Kubernetes-side worker** in the three-tier operator architecture. Watches `CloudflareZeroTrustTenant` CRs and `HTTPRoute` resources, detects annotation changes, and creates `CloudflareTask` CRs as work items for the `cloudflare_worker` to execute.

## Role in the architecture

```
manager
  └─▶ kube_worker            (this role — Kubernetes-side)
        ├─ reads: Tenants, HTTPRoutes, Secrets
        ├─ writes: CloudflareTask CRs  (work queue)
        ├─ writes: ConfigMaps          (annotation hash / state)
        └─ writes: HTTPRoute annotations (Cloudflare IDs written back)
```

## When it runs

Invoked each poll cycle by the **kube_worker** Deployment (a separate pod with `ROLE=kube_worker`). It does **not** call the Cloudflare API directly — it only creates `CloudflareTask` CRs and reads back the results.

## Task-by-task flow

| Order | Task file | Description |
|-------|-----------|-------------|
| 1 | `list_tenants.yml` | Fetches all `CloudflareZeroTrustTenant` CRs across the cluster |
| 2 | `list_httproutes.yml` | Lists `HTTPRoute` resources in configured namespaces (or all, if `WATCH_NAMESPACES` is empty); filters to those with `cfzt.cloudflare.com/enabled: "true"` |
| 3 | `reconcile_tenant.yml` | For each tenant, filters HTTPRoutes by namespace and `cfzt.cloudflare.com/tenant` annotation; calls `create_task.yml` per changed HTTPRoute |
| 4 | `create_task.yml` | Computes SHA256 hash of `cfzt.cloudflare.com/*` annotations; skips if hash matches the stored ConfigMap; otherwise creates a `CloudflareTask` CR |
| 5 | `check_state.yml` | Called within `create_task.yml` to read the state ConfigMap for the HTTPRoute |
| 6 | `update_state.yml` | Saves the new annotation hash to the state ConfigMap after task creation |
| 7 | `collect_results.yml` | Reads `Completed` CloudflareTask CRs; writes Cloudflare resource IDs (tunnel hostname ID, Access app ID, etc.) back as annotations on the originating HTTPRoute |
| 8 | `process_completed_task.yml` | Deletes processed `CloudflareTask` CRs and updates the state ConfigMap with the returned IDs |
| 9 | `cleanup_orphaned.yml` | Deletes ConfigMaps whose corresponding HTTPRoute no longer exists, and removes stale CloudflareTask CRs |

## Change detection

The role avoids unnecessary Cloudflare API calls by tracking annotation state:

1. Compute SHA256 of all `cfzt.cloudflare.com/*` annotations on the HTTPRoute
2. Look up the state ConfigMap `cfzt-{namespace}-{name}` in `operator_namespace`
3. If the hash matches → **skip** (no changes)
4. If the hash differs or the ConfigMap is absent → **create** a `CloudflareTask` CR

## Variables

| Variable | Source | Description |
|----------|--------|-------------|
| `operator_namespace` | env `OPERATOR_NAMESPACE` | Namespace where operator and CloudflareTask CRs live |
| `namespaces` | env `WATCH_NAMESPACES` | Comma-separated list of namespaces to watch; empty = all |
| `cloudflare_api_base` | env `CLOUDFLARE_API_BASE` | Cloudflare API base URL (default: `https://api.cloudflare.com/client/v4`) |

## State ConfigMap structure

One ConfigMap per HTTPRoute, named `cfzt-{namespace}-{httproute-name}`, stored in `operator_namespace`:

```yaml
data:
  annotation_hash: "sha256:..."         # hash of cfzt.cloudflare.com/* annotations
  cloudflare_ids: '{"tunnel_route_id": "...", "access_app_id": "...", ...}'
  last_sync_time: "2026-02-23T10:00:00Z"
  httproute_namespace: "default"
  httproute_name: "myapp"
```

## CloudflareTask CR it creates

```yaml
apiVersion: cfzt.cloudflare.com/v1alpha1
kind: CloudflareTask
metadata:
  name: cfzt-default-myapp-<hash>
  namespace: cloudflare-zero-trust
spec:
  hostname: myapp.example.com
  httprouteRef:
    name: myapp
    namespace: default
  tenantRef:
    name: prod-tenant
    namespace: default
  # ... all resolved Cloudflare operation params
status:
  phase: Pending   # → InProgress → Completed / Failed
```
