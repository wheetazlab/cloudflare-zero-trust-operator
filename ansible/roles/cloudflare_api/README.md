# cloudflare_api

Library role for all Cloudflare API interactions. Called exclusively by the `cloudflare_worker` role (via `execute_task.yml`) using `include_role: … tasks_from:`. Each task file is a focused, idempotent unit that makes one class of Cloudflare API call and returns a structured result fact.

This role does **not** touch Kubernetes. All Kubernetes reads and writes are handled by `kube_worker`.

---

## Caller pattern

```yaml
- name: Manage tunnel hostname route
  include_role:
    name: cloudflare_api
    tasks_from: manage_hostname_route.yml
  vars:
    cf_api_token:      "{{ cf_api_token }}"
    cf_tunnel_id:      "{{ cf_tunnel_id }}"
    cf_hostname:       "example.internal.company.com"
    cf_origin_service: "https://my-service.namespace.svc.cluster.local:8443"
    # ... additional vars per task
```

`main.yml` can also be used as a dispatcher:

```yaml
- include_role:
    name: cloudflare_api
  vars:
    task_file: "manage_hostname_route.yml"
    # ... task vars
```

---

## Task: `main.yml`

Dispatcher. Calls `include_tasks: "{{ task_file }}"`. Used when the caller selects the task file dynamically.

```mermaid
flowchart TD
    START(["main.yml called"])
    DISPATCH["include_tasks: task_file<br/>(variable set by caller)"]
    END(["done"])
    START --> DISPATCH --> END
```

---

## Task: `lookup_zone_id.yml`

Auto-discovers the Cloudflare Zone ID for a hostname using the Zones API. Tries a 2-label apex first (`example.com`), then falls back to 3-label for country-code second-level domains (`example.co.uk`). Optionally validates the discovered zone matches `tenant.spec.zoneId`.

```mermaid
flowchart TD
    START(["lookup_zone_id.yml called"])
    SPLIT["set_fact: _zone_labels<br/>= cf_hostname.split('.')"]
    APEX2["set_fact: _zone_apex_2<br/>= labels[-2] + '.' + labels[-1]"]
    QUERY2["uri: GET /zones?name=_zone_apex_2<br/>(Bearer token)"]
    FOUND2{"result.count<br/>> 0?"}
    SET2["set_fact: _discovered_zone_id<br/>= result[0].id"]

    APEX3{"len >= 3?"}
    APEX3L["set_fact: _zone_apex_3<br/>= labels[-3]+'.'+labels[-2]+'.'+labels[-1]"]
    QUERY3["uri: GET /zones?name=_zone_apex_3"]
    FOUND3{"result.count<br/>> 0?"}
    SET3["set_fact: _discovered_zone_id<br/>= result[0].id"]

    VALIDATE{"tenant_zone_id<br/>set AND<br/>discovered != tenant?"}
    FAIL_MISMATCH["fail: Zone ID mismatch —<br/>tenant.zoneId does not match<br/>discovered zone for hostname"]

    WARN_FAIL{"No zone<br/>discovered?"}
    WARN["debug: WARNING — zone lookup failed,<br/>DNS management will be skipped"]

    SET_OUT["set_fact: resolved_zone_id<br/>= _discovered_zone_id | default('')"]
    END(["done"])

    START --> SPLIT --> APEX2 --> QUERY2 --> FOUND2
    FOUND2 -->|Yes| SET2 --> VALIDATE
    FOUND2 -->|No| APEX3
    APEX3 -->|Yes| APEX3L --> QUERY3 --> FOUND3
    FOUND3 -->|Yes| SET3 --> VALIDATE
    FOUND3 -->|No| WARN_FAIL
    APEX3 -->|No| WARN_FAIL
    VALIDATE -->|Mismatch| FAIL_MISMATCH
    VALIDATE -->|OK| SET_OUT --> END
    WARN_FAIL -->|No zone| WARN --> SET_OUT
    WARN_FAIL -->|Zone found| VALIDATE
```

**Inputs:**

| Variable | Required | Description |
|---|---|---|
| `cf_api_token` | Yes | Cloudflare Bearer token |
| `cf_hostname` | Yes | Full hostname (e.g. `app.example.com`) |
| `cf_api_base` | Yes | API base URL |
| `cf_tenant_zone_id` | No | Optional validation: must match discovered zone |

**Outputs:**

| Fact | Description |
|---|---|
| `resolved_zone_id` | Zone ID string, or `""` if lookup failed (caller should skip DNS ops) |

---

## Task: `manage_hostname_route.yml`

Adds or updates the hostname ingress rule in a Cloudflare Tunnel's configuration. The entire tunnel config is fetched (GET), the rule for this hostname is inserted/replaced, and the full config is PUT back. A catch-all `http_status:404` rule is always preserved at the end.

```mermaid
flowchart TD
    START(["manage_hostname_route.yml called"])
    GET["uri: GET /tunnels/{tunnel_id}/configurations<br/>register: current_config"]
    EXISTING["set_fact: existing_rules<br/>= current_config.ingress (minus this hostname)<br/>minus http_status:404 catch-all"]
    HTTPS{"origin_service<br/>starts with https://?"}
    BUILD_OR["set_fact: origin_request<br/>= { noTLSVerify, originServerName,<br/>    caPool, tlsTimeout,<br/>    http2Origin, tcpKeepAlive }"]
    BUILD_RULE["set_fact: hostname_rule<br/>= { hostname, originRequest? }<br/>+ service: cf_origin_service"]
    REDIRECT{"http_redirect<br/>enabled?"}
    ADD_REDIRECT["set_fact: new_rules += <br/>redirect rule for HTTP→HTTPS"]
    CATCHALL["set_fact: catchall_rule = {http_status:404}"]
    NEW_CONFIG["set_fact: new_tunnel_config<br/>= { config: { ingress: existing + [rule] + [catchall] } }"]
    PUT["uri: PUT /tunnels/{tunnel_id}/configurations<br/>body: new_tunnel_config<br/>retries: 3, delay: 5"]
    RESULT["set_fact: hostname_route_result<br/>= { success, hostname, tunnel_id,<br/>    config_version }"]
    END(["done"])

    START --> GET --> EXISTING
    EXISTING --> HTTPS
    HTTPS -->|Yes| BUILD_OR --> BUILD_RULE
    HTTPS -->|No| BUILD_RULE
    BUILD_RULE --> REDIRECT
    REDIRECT -->|Yes| ADD_REDIRECT --> CATCHALL
    REDIRECT -->|No| CATCHALL
    CATCHALL --> NEW_CONFIG --> PUT --> RESULT --> END
```

**Inputs:**

| Variable | Required | Description |
|---|---|---|
| `cf_api_token` | Yes | Bearer token |
| `cf_tunnel_id` | Yes | Cloudflare Tunnel UUID |
| `cf_hostname` | Yes | Hostname for this rule |
| `cf_origin_service` | Yes | Origin URL (e.g. `https://svc.ns.svc.cluster.local:8443`) |
| `cf_http_redirect` | No (default false) | Add HTTP→HTTPS redirect rule |
| `cf_no_tls_verify` | No | Skip TLS verification at origin |
| `cf_origin_server_name` | No | Override SNI for origin TLS |
| `cf_ca_pool` | No | Custom CA pool for origin TLS |
| `cf_tls_timeout` | No (default 10) | TLS handshake timeout (seconds) |
| `cf_http2_origin` | No | Enable HTTP/2 to origin |
| `cf_match_sni_to_host` | No | Match SNI to hostname |
| `cf_api_base` | Yes | API base URL |

**Output:**

| Fact | Description |
|---|---|
| `hostname_route_result.success` | `true` |
| `hostname_route_result.hostname` | Hostname configured |
| `hostname_route_result.tunnel_id` | Tunnel UUID |
| `hostname_route_result.config_version` | Returned config version |

---

## Task: `manage_tunnel_cname.yml`

Creates or updates a proxied DNS CNAME record pointing `hostname` → `{tunnel-id}.cfargotunnel.com`. Three code-paths: create (no existing ID), update (target changed), no-op (already correct).

```mermaid
flowchart TD
    START(["manage_tunnel_cname.yml called"])
    TARGET["set_fact: cname_target<br/>= {cf_tunnel_id}.cfargotunnel.com"]
    KNOWN{"cf_existing_cname_id<br/>set?"}
    GET["uri: GET /zones/{zone_id}/dns_records/{existing_id}"]
    EXISTING_CONTENT["set_fact: existing_cname_content<br/>= record.content"]

    NEED_CREATE{"existing_cname_id<br/>== '' ?"}
    CREATE["uri: POST /zones/{zone_id}/dns_records<br/>{ type:CNAME, name:cf_hostname,<br/>  content:cname_target,<br/>  proxied:true, ttl:1 }"]
    SET_CREATED["set_fact: tunnel_cname_result<br/>= { record_id: new_id, created: true }"]

    NEED_UPDATE{"content !=<br/>cname_target?"}
    UPDATE["uri: PATCH /zones/{zone_id}/dns_records/{id}<br/>{ content: cname_target }"]
    SET_UPDATED["set_fact: tunnel_cname_result<br/>= { record_id: existing_id, created: false }"]

    NOOP["debug: CNAME already correct"]
    SET_NOOP["set_fact: tunnel_cname_result<br/>= { record_id: existing_id, created: false }"]
    END(["done"])

    START --> TARGET --> KNOWN
    KNOWN -->|No existing ID| NEED_CREATE
    KNOWN -->|Has existing ID| GET --> EXISTING_CONTENT --> NEED_CREATE
    NEED_CREATE -->|Yes| CREATE --> SET_CREATED --> END
    NEED_CREATE -->|No| NEED_UPDATE
    NEED_UPDATE -->|Yes| UPDATE --> SET_UPDATED --> END
    NEED_UPDATE -->|No| NOOP --> SET_NOOP --> END
```

**Inputs:**

| Variable | Required | Description |
|---|---|---|
| `cf_api_token` | Yes | Bearer token |
| `cf_zone_id` | Yes | Zone ID (from `lookup_zone_id.yml`) |
| `cf_tunnel_id` | Yes | Tunnel UUID (determines CNAME target) |
| `cf_hostname` | Yes | DNS name to configure |
| `cf_existing_cname_id` | No | Skip lookup if record ID already known |
| `cf_api_base` | Yes | API base URL |

**Output:**

| Fact | Description |
|---|---|
| `tunnel_cname_result.record_id` | DNS record ID |
| `tunnel_cname_result.created` | `true` if newly created |

---

## Task: `manage_dns_record.yml`

Creates or updates a DNS A record for dns-only mode (no tunnel). Three code-paths: create, update (IP changed), no-op.

```mermaid
flowchart TD
    START(["manage_dns_record.yml called"])
    KNOWN{"cf_existing_record_id<br/>set?"}
    GET["uri: GET /zones/{zone_id}/dns_records/{id}"]
    EXISTING_IP["set_fact: existing_dns_record_ip<br/>= record.content"]

    NEED_CREATE{"existing_record_id<br/>== '' ?"}
    CREATE["uri: POST /zones/{zone_id}/dns_records<br/>{ type:A, name:cf_hostname,<br/>  content:cf_ip_address,<br/>  proxied:cf_proxied, ttl:cf_ttl }"]
    SET_CREATED["set_fact: dns_record_result<br/>= { record_id: new_id, ip_address, created: true }"]

    NEED_UPDATE{"existing_ip !=<br/>cf_ip_address?"}
    UPDATE["uri: PATCH /zones/{zone_id}/dns_records/{id}<br/>{ content: cf_ip_address }"]
    SET_UPDATED["set_fact: dns_record_result<br/>= { record_id, ip_address, created: false }"]
    SET_NOOP["set_fact: dns_record_result<br/>= { record_id, ip_address, created: false }"]
    END(["done"])

    START --> KNOWN
    KNOWN -->|No existing ID| NEED_CREATE
    KNOWN -->|Has existing ID| GET --> EXISTING_IP --> NEED_CREATE
    NEED_CREATE -->|Yes| CREATE --> SET_CREATED --> END
    NEED_CREATE -->|No| NEED_UPDATE
    NEED_UPDATE -->|Yes| UPDATE --> SET_UPDATED --> END
    NEED_UPDATE -->|No| SET_NOOP --> END
```

**Inputs:**

| Variable | Required | Description |
|---|---|---|
| `cf_api_token` | Yes | Bearer token |
| `cf_zone_id` | Yes | Zone ID |
| `cf_hostname` | Yes | DNS name to configure |
| `cf_ip_address` | Yes | IP address for A record |
| `cf_proxied` | No (default false) | Proxy through Cloudflare |
| `cf_ttl` | No (default 120) | TTL in seconds (1 = auto) |
| `cf_existing_record_id` | No | Skip lookup if ID already known |
| `cf_api_base` | Yes | API base URL |

**Output:**

| Fact | Description |
|---|---|
| `dns_record_result.record_id` | DNS record ID |
| `dns_record_result.ip_address` | Configured IP |
| `dns_record_result.created` | `true` if newly created |

---

## Task: `manage_access_app.yml`

Creates or updates a Cloudflare Access Application for the hostname. Performs a GET to check if an app already exists under this account for the exact hostname, then issues POST (new) or PUT (update).

```mermaid
flowchart TD
    START(["manage_access_app.yml called"])
    EXISTING{"cf_existing_app_id<br/>set?"}
    GET["uri: GET /accounts/{account_id}/access/apps<br/>filter by hostname"]
    BUILD["set_fact: access_app_payload<br/>{ name, domain: cf_hostname,<br/>  type: self_hosted,<br/>  session_duration,<br/>  auto_redirect_to_identity,<br/>  enable_binding_cookie,<br/>  http_only_cookie_attribute,<br/>  same_site_cookie_attribute,<br/>  logo_url, skip_interstitial,<br/>  app_launcher_visible,<br/>  service_auth_401_redirect,<br/>  custom_deny_message/url/non_identity_url }"]
    CREATE{"app_id<br/>exists?"}
    POST["uri: POST /accounts/{account_id}/access/apps<br/>body: payload"]
    PUT["uri: PUT /accounts/{account_id}/access/apps/{id}<br/>body: payload"]
    RESULT["set_fact: access_app_result<br/>= { app_id, created }"]
    END(["done"])

    START --> EXISTING
    EXISTING -->|No| GET --> BUILD
    EXISTING -->|Yes| BUILD
    BUILD --> CREATE
    CREATE -->|No existing| POST --> RESULT --> END
    CREATE -->|Has existing| PUT --> RESULT --> END
```

**Inputs:**

| Variable | Required | Description |
|---|---|---|
| `cf_api_token` | Yes | Bearer token |
| `cf_account_id` | Yes | Cloudflare account ID |
| `cf_hostname` | Yes | Hostname = Access app domain |
| `cf_existing_app_id` | No | Skip lookup if ID known |
| `cf_session_duration` | No (default `24h`) | Session duration |
| `cf_allow_groups` | No | Comma-separated Access group IDs |
| `cf_allow_emails` | No | Comma-separated allowed emails |
| `cf_auto_redirect_to_identity` | No (false) | Redirect to IdP immediately |
| `cf_enable_binding_cookie` | No (false) | Cloudflare binding cookie |
| `cf_http_only_cookie_attribute` | No (true) | HttpOnly cookie flag |
| `cf_same_site_cookie_attribute` | No (`lax`) | SameSite cookie setting |
| `cf_logo_url` | No | Custom logo URL |
| `cf_skip_interstitial` | No (false) | Skip auth interstitial |
| `cf_app_launcher_visible` | No (true) | Show in app launcher |
| `cf_service_auth_401_redirect` | No (false) | Redirect 401 to service auth |
| `cf_custom_deny_message` | No | Custom deny message |
| `cf_custom_deny_url` | No | Custom deny redirect URL |
| `cf_custom_non_identity_deny_url` | No | Deny URL for non-identity requests |
| `cf_api_base` | Yes | API base URL |

**Output:**

| Fact | Description |
|---|---|
| `access_app_result.app_id` | Access Application UUID |
| `access_app_result.created` | `true` if newly created |

---

## Task: `manage_access_policy.yml`

Creates or updates an Access Policy attached to an Access Application. Builds an `include` rules array from group IDs and/or emails. Falls back to `{"everyone": {}}` if neither is specified.

```mermaid
flowchart TD
    START(["manage_access_policy.yml called"])
    BUILD_RULES["set_fact: include_rules<br/>= groups (each {group: {id: gid}})<br/>  + emails (each {email: {email: addr}})"]
    FALLBACK{"include_rules<br/>empty?"}
    EVERYONE["set_fact: include_rules<br/>= [{everyone: {}}]"]
    PAYLOAD["set_fact: policy_payload<br/>{ name: 'Allow {hostname}',<br/>  decision: allow,<br/>  precedence: 1,<br/>  include: include_rules }"]
    EXISTING{"cf_existing_policy_id<br/>set?"}
    POST["uri: POST /accounts/{account_id}/<br/>access/apps/{app_id}/policies"]
    PUT["uri: PUT /accounts/{account_id}/<br/>access/apps/{app_id}/policies/{id}"]
    RESULT["set_fact: access_policy_result<br/>= { policy_id, created }"]
    END(["done"])

    START --> BUILD_RULES --> FALLBACK
    FALLBACK -->|Yes| EVERYONE --> PAYLOAD
    FALLBACK -->|No| PAYLOAD
    PAYLOAD --> EXISTING
    EXISTING -->|No existing| POST --> RESULT --> END
    EXISTING -->|Has existing| PUT --> RESULT --> END
```

**Inputs:**

| Variable | Required | Description |
|---|---|---|
| `cf_api_token` | Yes | Bearer token |
| `cf_account_id` | Yes | Account ID |
| `cf_app_id` | Yes | Access Application ID (from `manage_access_app.yml`) |
| `cf_hostname` | Yes | Used in policy name |
| `cf_allow_groups` | No | Comma-separated Access group IDs |
| `cf_allow_emails` | No | Comma-separated email addresses |
| `cf_existing_policy_id` | No | Update existing policy by ID |
| `cf_api_base` | Yes | API base URL |

**Output:**

| Fact | Description |
|---|---|
| `access_policy_result.policy_id` | Policy UUID |
| `access_policy_result.created` | `true` if newly created |

---

## Task: `manage_service_token.yml`

Creates a Cloudflare Access Service Token. **Create-only** — service tokens cannot be updated via API. The `client_id` and `client_secret` are returned only at creation time; subsequent runs skip if a token ID already exists.

```mermaid
flowchart TD
    START(["manage_service_token.yml called"])
    SKIP{"cf_existing_token_id<br/>set?"}
    NOOP["debug: Service token<br/>already exists — skip"]
    POST["uri: POST /accounts/{account_id}/<br/>access/service_tokens<br/>{ name: cfzt-{hostname},<br/>  duration: cf_service_token_duration }"]
    RESULT["set_fact: service_token_result<br/>= { token_id,<br/>    client_id,<br/>    client_secret,<br/>    created: true }"]
    END(["done"])

    START --> SKIP
    SKIP -->|Already exists| NOOP --> END
    SKIP -->|New| POST --> RESULT --> END
```

> **Security note:** `client_secret` is only available in the POST response. Once the result is stored in the `CloudflareTask` status, `kube_worker` creates a Kubernetes `Secret` containing `client_id` and `client_secret`. The values are never stored in git or ConfigMaps.

**Inputs:**

| Variable | Required | Description |
|---|---|---|
| `cf_api_token` | Yes | Bearer token |
| `cf_account_id` | Yes | Account ID |
| `cf_hostname` | Yes | Used to name the token (`cfzt-{hostname}`) |
| `cf_existing_token_id` | No | Skip creation if token already exists |
| `cf_service_token_duration` | No (default `8760h`) | Token validity duration |
| `cf_api_base` | Yes | API base URL |

**Output:**

| Fact | Description |
|---|---|
| `service_token_result.token_id` | Service token ID |
| `service_token_result.client_id` | Client ID (only if newly created) |
| `service_token_result.client_secret` | Client secret (only if newly created) |
| `service_token_result.created` | `true` if newly created |

---

## Task: `delete_resources.yml`

Deletes all Cloudflare resources associated with an HTTPRoute in safe dependency order. Uses `status_code: [200, 204, 404]` — a 404 response is treated as success (resource already gone).

```mermaid
flowchart TD
    START(["delete_resources.yml called"])
    POL["1. DELETE access policies<br/>× each id in delete_policy_ids<br/>DELETE /accounts/{id}/access/apps/{app_id}/policies/{pid}"]
    APP["2. DELETE access application<br/>DELETE /accounts/{id}/access/apps/{delete_app_id}"]
    TOK["3. DELETE service token<br/>DELETE /accounts/{id}/access/service_tokens/{delete_token_id}"]
    GET_TUNNEL["4a. GET tunnel config<br/>/tunnels/{tunnel_id}/configurations"]
    FILTER["4b. filter out ingress rule<br/>for delete_hostname"]
    ADD_CATCHALL["4c. ensure http_status:404 catchall"]
    PUT_TUNNEL["4d. PUT updated config<br/>(retries:3, delay:5)"]
    DNS["5. DELETE DNS record<br/>DELETE /zones/{delete_zone_id}/dns_records/{delete_dns_record_id}"]
    END(["done"])

    START --> POL --> APP --> TOK --> GET_TUNNEL --> FILTER --> ADD_CATCHALL --> PUT_TUNNEL --> DNS --> END
```

**Deletion order (dependency-safe):**

| Step | Resource | Guard |
|---|---|---|
| 1 | Access Policies | `delete_policy_ids` is a list; skip if empty |
| 2 | Access Application | `delete_app_id != ''` |
| 3 | Service Token | `delete_token_id != ''` |
| 4 | Tunnel ingress rule | GET/filter/PUT; `delete_hostname` must be set |
| 5 | DNS record | `delete_dns_record_id != ''` in `delete_zone_id` |

**Inputs:**

| Variable | Required | Description |
|---|---|---|
| `cf_api_token` | Yes | Bearer token |
| `cf_account_id` | Yes | Account ID |
| `cf_tunnel_id` | Yes | Tunnel UUID |
| `delete_hostname` | Yes | Hostname rule to remove from tunnel |
| `delete_zone_id` | Yes* | Zone for DNS deletion |
| `delete_dns_record_id` | No | DNS record to delete |
| `delete_app_id` | No | Access Application to delete |
| `delete_policy_ids` | No | List of policy IDs to delete |
| `delete_token_id` | No | Service token to delete |
| `cf_api_base` | Yes | API base URL |

---

## Summary: task inputs/outputs

| Task | Key inputs | Key output fact |
|---|---|---|
| `lookup_zone_id.yml` | `cf_hostname`, `cf_tenant_zone_id` | `resolved_zone_id` |
| `manage_hostname_route.yml` | `cf_tunnel_id`, `cf_hostname`, `cf_origin_service` | `hostname_route_result` |
| `manage_tunnel_cname.yml` | `cf_zone_id`, `cf_hostname`, `cf_tunnel_id` | `tunnel_cname_result` |
| `manage_dns_record.yml` | `cf_zone_id`, `cf_hostname`, `cf_ip_address` | `dns_record_result` |
| `manage_access_app.yml` | `cf_account_id`, `cf_hostname` | `access_app_result` |
| `manage_access_policy.yml` | `cf_account_id`, `cf_app_id`, `cf_allow_groups/emails` | `access_policy_result` |
| `manage_service_token.yml` | `cf_account_id`, `cf_hostname` | `service_token_result` |
| `delete_resources.yml` | `delete_*` vars | none (side-effects only) |
