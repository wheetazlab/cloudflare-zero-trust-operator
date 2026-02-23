# Role: `cloudflare_api`

A pure **library role** — a thin dispatcher that delegates to specific Cloudflare REST API task files. It does not contain reconciliation logic; it is always called by `cloudflare_worker` during task execution.

## How it works

The role has a single entry point (`main.yml`) that calls the task file specified by the `task_file` variable:

```yaml
- name: Include appropriate task file
  ansible.builtin.include_tasks: "{{ task_file }}"
  when: task_file is defined
```

`cloudflare_worker`'s `execute_task.yml` calls this role multiple times — once per Cloudflare operation required by the task.

## Available task files

| Task file | Operation | Required variables |
|-----------|-----------|-------------------|
| `lookup_zone_id.yml` | Resolve a zone name to its Cloudflare Zone ID | `cf_api_token`, `cf_account_id`, `cf_zone_name`, `cf_api_base` |
| `manage_hostname_route.yml` | Create or update a Cloudflare Tunnel ingress rule (publishes the hostname through the tunnel) | `cf_api_token`, `cf_account_id`, `cf_tunnel_id`, `cf_hostname`, `cf_origin_service`, `cf_api_base` |
| `manage_tunnel_cname.yml` | Create the DNS CNAME record pointing `hostname → <tunnel-id>.cfargotunnel.com` | `cf_api_token`, `cf_zone_id`, `cf_hostname`, `cf_tunnel_id`, `cf_api_base` |
| `manage_dns_record.yml` | Create or update a DNS A record (dns-only mode — no tunnel) | `cf_api_token`, `cf_zone_id`, `cf_hostname`, `cf_dns_record_ip`, `cf_api_base` |
| `manage_access_app.yml` | Create or update a Cloudflare Access Application | `cf_api_token`, `cf_account_id`, `cf_app_name`, `cf_app_domain`, `cf_app_id` (optional, for updates), various optional Access settings |
| `manage_access_policy.yml` | Attach an existing policy/group to an Access Application | `cf_api_token`, `cf_account_id`, `cf_app_id`, `cf_policy_id` or `cf_policy_group_ids` |
| `manage_service_token.yml` | Create a service token for machine-to-machine auth | `cf_api_token`, `cf_account_id`, `cf_token_name`, `cf_api_base` |
| `delete_resources.yml` | Delete all Cloudflare resources for an HTTPRoute (tunnel route, DNS, Access app, service token) | `cf_api_token`, `cf_account_id`, `cf_zone_id`, stored Cloudflare IDs from state |

## Common variables

All task files share these base variables:

| Variable | Description |
|----------|-------------|
| `cf_api_token` | Cloudflare API token (from the tenant's credential Secret) |
| `cf_account_id` | Cloudflare Account ID (from the `CloudflareZeroTrustTenant` spec) |
| `cf_api_base` | Cloudflare API base URL — usually `https://api.cloudflare.com/client/v4` |

## Retry behaviour

All HTTP calls use `retries: 3` / `delay: 5` to handle transient Cloudflare API failures. Permanent failures (4xx) bubble up to `cloudflare_worker`'s rescue block and set the `CloudflareTask` status to `Failed`.

## Example: calling from cloudflare_worker

```yaml
- name: Write tunnel hostname route
  ansible.builtin.include_role:
    name: cloudflare_api
  vars:
    task_file: manage_hostname_route.yml
    cf_api_token: "{{ api_token }}"
    cf_account_id: "{{ tenant_account_id }}"
    cf_tunnel_id: "{{ tenant_tunnel_id }}"
    cf_hostname: "{{ ct_hostname }}"
    cf_origin_service: "{{ resolved_origin_service }}"
    cf_api_base: "{{ cloudflare_api_base }}"
```

## Notes

- This role **never reads Kubernetes resources** — it is Cloudflare-only.
- Task files are idempotent: they check for existing resource IDs before creating to avoid duplicates.
- `delete_resources.yml` is called when an HTTPRoute has `cfzt.cloudflare.com/enabled: "false"` set or the HTTPRoute is deleted.
