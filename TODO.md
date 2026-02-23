# TODO — Next Session

- [x] Create `README.md` for each role explaining what it does and how
      (`operator_config`, `kube_worker`, `cloudflare_worker`, `cloudflare_api`)
      → Done: `ansible/roles/{operator_config,kube_worker,cloudflare_worker,cloudflare_api}/README.md`

- [x] Update `docs/` with new three-tier architecture design and diagrams
      (manager → kube_worker → cloudflare_worker, CloudflareTask CRD flow)
      → Done: Added `## Three-Tier Architecture` section to `docs/architecture.md` with
        mermaid diagram, CloudflareTask lifecycle, per-role env var table, and
        updated Runtime Architecture sequence diagram to show all three pods.

- [x] Update Helm chart docs / README under `charts/` if anything is stale
      (new env vars ROLE, POD_NAME; new worker Deployments; CloudflareTask RBAC)
      → Done: Updated `charts/.../README.md` "How it works" section with three-tier table.
        ClusterRole already has correct CloudflareTask + worker Deployment RBAC.
        ROLE / POD_NAME are deployment-internal and correctly not exposed as values.

- [x] Update the main `README.md` to reflect the new architecture
      → Done: Replaced single-pod ASCII diagram with three-tier diagram explaining
        manager / kube_worker / cloudflare_worker responsibilities.

- [x] Check whether `config/` and `examples/` can be consolidated into one directory
      → N/A: `config/` no longer exists on disk (workspace index was stale).
        `examples/` remains the single directory for all user-facing YAML samples.
