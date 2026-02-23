# TODO — Next Session

- [ ] Create `README.md` for each role explaining what it does and how
      (`operator_config`, `kube_worker`, `cloudflare_worker`, `cloudflare_api`)

- [ ] Update `docs/` with new three-tier architecture design and diagrams
      (manager → kube_worker → cloudflare_worker, CloudflareTask CRD flow)

- [ ] Update Helm chart docs / README under `charts/` if anything is stale
      (new env vars ROLE, POD_NAME; new worker Deployments; CloudflareTask RBAC)

- [ ] Update the main `README.md` to reflect the new architecture

- [ ] Check whether `config/` and `examples/` can be consolidated into one directory
