# python/

This directory contains the entire operator runtime — five Python modules that implement the kopf-based Kubernetes controller for managing Cloudflare Zero Trust resources.

## Module Overview

```
python/
├── main.py           # kopf event handlers and entry point
├── reconciler.py     # Reconciliation and deletion orchestration
├── config.py         # Settings dataclasses and template merge logic
├── cloudflare_api.py # Cloudflare SDK wrapper functions
└── k8s_helpers.py    # Kubernetes API helper functions
```

Call graph (top-down):

```
main.py (kopf handlers)
  └── reconciler.py (orchestration)
        ├── config.py (merge_settings, compute_annotation_hash)
        ├── cloudflare_api.py (CF SDK calls)
        └── k8s_helpers.py (K8s API calls)
```

---

## `main.py` — kopf Event Handlers

**Logger:** `cfzt.operator`

The operator entry point. Registers all kopf event handlers and configures operator-wide runtime settings. This module contains no business logic — it translates kopf events into calls to `reconciler.py`.

### Startup

```python
@kopf.on.startup()
def configure(settings: kopf.OperatorSettings, **_) -> None:
```

Runs once when the operator starts. Sets:

| Setting | Value | Reason |
|---------|-------|--------|
| `persistence.progress_storage` | `AnnotationsProgressStorage(prefix="kopf.cfzt.cloudflare.com")` | Keeps kopf's internal annotations separate from cfzt annotations |
| `persistence.diffbase_storage` | `AnnotationsDiffBaseStorage(prefix="kopf.cfzt.cloudflare.com")` | Same prefix isolation |
| `posting.level` | `logging.WARNING` | Suppresses routine K8s event spam |
| `networking.error_backoffs` | `[1, 5, 15]` | Faster retries than kopf's default 60s cap |

### Namespace Filtering

The module reads `WATCH_NAMESPACES` (comma-separated, from `entrypoint.sh`) at import time and builds a Python list. The `_ns_filter()` function is passed as the `when=` predicate to all HTTPRoute handlers — if the list is empty all namespaces pass.

### HTTPRoute Handlers

All three create/update/resume handlers share `HTTPROUTE_KWARGS`:

```python
HTTPROUTE_KWARGS = dict(
    group="gateway.networking.k8s.io",
    version="v1",
    plural="httproutes",
    annotations={"cfzt.cloudflare.com/enabled": "true"},
    when=_ns_filter,
    backoff=15,
)
```

| Handler | Decorator(s) | Calls |
|---------|-------------|-------|
| `on_httproute_reconcile()` | `@kopf.on.resume`, `@kopf.on.create`, `@kopf.on.update` | `reconciler.reconcile_httproute()` |
| `on_httproute_delete()` | `@kopf.on.delete(optional=True)` | `reconciler.delete_httproute_resources()` |
| `on_template_update()` | `@kopf.on.update` on `cloudflarezerotrusttemplates` | Lists all enabled HTTPRoutes, calls `reconciler.reconcile_httproute()` for each that references the changed template |
| `orphan_cleanup()` | `@kopf.timer` on `cloudflarezerotrusttenants`, interval=300s, initial_delay=60s | `reconciler.cleanup_orphaned_states()` |

**`optional=True` on the delete handler** — the operator does not own HTTPRoutes and must not add a finalizer. Delete events are best-effort; the orphan cleanup timer provides the safety net for missed deletes.

**Template matching** in `on_template_update()` — an HTTPRoute is re-reconciled if the updated template name equals either:
- The route's `cfzt.cloudflare.com/template` annotation (per-route template)
- `base-{tenant}` where `tenant` is the route's `cfzt.cloudflare.com/tenant` annotation (base template)

---

## `reconciler.py` — Reconciliation Orchestration

**Logger:** `cfzt.reconciler`

Contains all reconciliation logic. No kopf decorators — pure Python functions called by `main.py`. Three public entry points and four private sub-reconcilers.

### Public Functions

---

#### `reconcile_httproute(name, namespace, body, log=None)`

Full create/update lifecycle for a single HTTPRoute. Called on every create, update, and resume event.

**Steps:**

1. **Pre-check** — Reads `cfzt.cloudflare.com/tenant` and `cfzt.cloudflare.com/hostname` from annotations. Logs a warning and returns if either is missing.

2. **Tenant lookup** — Calls `k8s.get_tenant(name, namespace)`. If not found and the HTTPRoute namespace differs from the operator namespace, tries the operator namespace. Raises `kopf.TemporaryError(delay=30)` if still not found.

3. **Template lookup** — Resolves two templates:
   - **Per-route**: name from `cfzt.cloudflare.com/template` annotation, same namespace-fallback logic
   - **Base**: `base-{tenant_name}`, same namespace-fallback logic
   Both are optional — `None` is passed to `merge_settings()` if absent.

4. **Settings merge** — Calls `config.merge_settings()` to build a `ReconcileSettings` object from the 3-way merge chain.

5. **Change detection** — Calls `config.compute_annotation_hash(annotations, per_route_spec, base_spec)` and compares against `existing_state["annotation_hash"]`. Returns immediately if unchanged.

6. **Cloudflare client** — Reads the API token via `k8s.read_secret_key()` using the tenant's `spec.credentialRef`. Constructs a `cloudflare.Cloudflare` client via `cfapi.make_client()`.

7. **Zone resolution** — Uses `tenant.spec.zoneId` if set, otherwise calls `cfapi.resolve_zone_id()`. Raises `kopf.TemporaryError(delay=60)` if unresolvable.

8. **Sub-reconcilers** — Runs in order:
   - `_reconcile_dns_only()` **or** `_reconcile_tunnel()` (mutually exclusive)
   - `_reconcile_access()` (if `settings.access.enabled`)
   - `_reconcile_service_token()` (if `settings.service_token.enabled`)

9. **Persist** — Calls `k8s.update_state()` to write all resource IDs + hash + timestamp to the state ConfigMap. Then patches result annotations back onto the HTTPRoute. A 404 on the annotation patch (HTTPRoute deleted mid-reconcile) is caught and logged.

---

#### `delete_httproute_resources(name, namespace, log=None)`

Tears down all Cloudflare resources tracked in the state ConfigMap and removes the ConfigMap itself. Called from the kopf delete handler and from `cleanup_orphaned_states()`.

**Steps:**

1. Reads the state ConfigMap via `k8s.get_state()`. Returns immediately if no state exists.

2. Looks up the tenant (route namespace, then operator namespace fallback).

3. If tenant not found: deletes the state ConfigMap and returns (no CF cleanup possible — logs a warning).

4. Reads the API token from the tenant's `credentialRef`. If credential read fails: deletes state ConfigMap and returns (logs exception).

5. Calls `cfapi.delete_all_resources()` with all IDs from state. Deletion order: Access App → Service Token → Tunnel Route → DNS Record. Each step ignores 404.

6. Deletes the K8s service-token Secret (if one was created).

7. Deletes the state ConfigMap.

---

#### `cleanup_orphaned_states(tenant_name, log=None)`

Scans all state ConfigMaps labeled for `tenant_name` and deletes any whose HTTPRoute no longer exists or is no longer enabled. Called from the per-tenant timer (every 300s).

**Steps:**

1. Lists all state ConfigMaps via `k8s.list_state_configmaps()`, filters to those labeled with the given `tenant_name`.

2. For each, reads `cfzt.cloudflare.com/httproute-namespace` and `cfzt.cloudflare.com/httproute-name` from labels.

3. Attempts to fetch the HTTPRoute. Considers it orphaned if:
   - Kubernetes returns 404
   - The route exists but `cfzt.cloudflare.com/enabled` ≠ `"true"`

4. For orphaned routes, calls `delete_httproute_resources()`.

### Private Sub-Reconcilers

---

#### `_reconcile_tunnel(client, settings, zone_id, existing_state, state, result_annotations, log)`

Called when `settings.dns_only.enabled` is `False`.

1. Calls `cfapi.upsert_tunnel_route()` with all TLS settings from `settings.origin_tls`.
2. Stores `tunnel_id` in `state["hostname_route_id"]`.
3. Calls `cfapi.upsert_cname_record()`, passing `existing_state.get("cname_record_id")` for idempotent updates.
4. Stores the resulting `record_id` in `state["cname_record_id"]`.

---

#### `_reconcile_dns_only(client, settings, zone_id, existing_state, state, result_annotations, namespace, log)`

Called when `settings.dns_only.enabled` is `True`.

1. Resolves IP: uses `settings.dns_only.static_ip` if set; otherwise calls `k8s.get_service_ip()` using `settings.dns_only.ingress_service_ref`. Raises `kopf.TemporaryError(delay=30)` if the LoadBalancer IP isn't assigned yet.
2. Raises `kopf.PermanentError` if neither IP source is configured.
3. Validates the IP via `ipaddress.ip_address()`. Raises `kopf.PermanentError` on invalid input.
4. Calls `cfapi.upsert_a_record()`, stores `record_id` and `ip_address` in state.

---

#### `_reconcile_access(client, settings, zone_id, existing_state, state, result_annotations, log)`

Called when `settings.access.enabled` is `True`.

1. Resolves reusable policy names → UUIDs via `cfapi.resolve_policy_ids()`.
2. Upserts the Access Application (`cfzt-{hostname}`) via `cfapi.upsert_access_app()`, passing all session/cookie/UI settings and the resolved policy IDs.
3. If `settings.access.allow_groups` or `settings.access.allow_emails` are set, upserts an inline allow policy (`cfzt-{hostname}-allow`) via `cfapi.upsert_access_policy()`.
4. Stores `access_app_id` and `access_policy_ids` in state.

---

#### `_reconcile_service_token(client, settings, existing_state, state, result_annotations, namespace, route_name, log)`

Called when `settings.service_token.enabled` is `True`.

**Important:** Service tokens are created once and never re-created. If `existing_state["service_token_id"]` is already set, the existing values are carried forward. The `client_secret` is only available at creation time — if the K8s Secret is lost the token must be manually rotated.

1. If token already exists: copies `service_token_id` and `service_token_secret_name` from existing state and returns.
2. Otherwise: calls `cfapi.create_service_token()`, then `k8s.create_service_token_secret()` to write a K8s Secret named `cfzt-svctoken-{route_name}` with `CF_ACCESS_CLIENT_ID` and `CF_ACCESS_CLIENT_SECRET`.

---

## `config.py` — Settings Dataclasses and Merge Logic

**No logger** — pure data and computation, no side effects.

### Dataclasses

#### `OriginTLS`
TLS configuration for the origin connection:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `no_tls_verify` | `bool` | `False` | Skip TLS certificate verification |
| `origin_server_name` | `str` | `""` | Custom SNI hostname for TLS handshake |
| `ca_pool` | `str` | `""` | Path to CA certificate bundle |
| `tls_timeout` | `int` | `10` | TLS handshake timeout in seconds |
| `http2_origin` | `bool` | `False` | Use HTTP/2 to origin |
| `match_sni_to_host` | `bool` | `False` | Set SNI to match `Host` header |

#### `AccessSettings`
Cloudflare Access Application configuration:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | `bool` | `False` | Whether to create an Access Application |
| `session_duration` | `str` | `"24h"` | User session lifetime |
| `allow_groups` | `list[str]` | `[]` | CF Access Group names for inline policy |
| `allow_emails` | `list[str]` | `[]` | Email addresses for inline policy |
| `existing_policy_names` | `list[str]` | `[]` | Existing policy names to attach (resolved to UUIDs) |
| `auto_redirect_to_identity` | `bool` | `False` | Redirect to IdP automatically |
| `enable_binding_cookie` | `bool` | `False` | Enable binding cookie |
| `http_only_cookie_attribute` | `bool` | `True` | HTTP-only cookies |
| `same_site_cookie_attribute` | `str` | `"lax"` | SameSite policy (`none`/`lax`/`strict`) |
| `logo_url` | `str` | `""` | App launcher logo |
| `skip_interstitial` | `bool` | `False` | Skip CF loading page |
| `app_launcher_visible` | `bool` | `True` | Show in App Launcher |
| `service_auth_401_redirect` | `bool` | `False` | Return 401 instead of redirect for service auth |
| `custom_deny_message` | `str` | `""` | Custom denied-access message |
| `custom_deny_url` | `str` | `""` | Custom denied-access URL |
| `custom_non_identity_deny_url` | `str` | `""` | Non-identity denied-access URL |

#### `ServiceTokenSettings`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | `bool` | `False` | Whether to create a service token |
| `duration` | `str` | `"8760h"` | Token lifetime (default: 1 year) |

#### `DnsOnlySettings`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | `bool` | `False` | Use DNS A-record mode instead of tunnel |
| `proxied` | `bool` | `False` | Enable Cloudflare proxy (orange cloud) |
| `ttl` | `int` | `120` | DNS record TTL in seconds |
| `static_ip` | `str` | `""` | Hardcoded IP for the A record |
| `ingress_service_ref` | `dict \| None` | `None` | K8s Service to read LoadBalancer IP from |

#### `ReconcileSettings`
Top-level settings object passed between reconciler functions:

| Field | Type | Source |
|-------|------|--------|
| `hostname` | `str` | `cfzt.cloudflare.com/hostname` annotation |
| `tenant_name` | `str` | Tenant CR `metadata.name` |
| `tenant_namespace` | `str` | Tenant CR `metadata.namespace` |
| `account_id` | `str` | Tenant `spec.accountId` |
| `tunnel_id` | `str` | Annotation override or tenant `spec.tunnelId` |
| `credential_secret_name` | `str` | Tenant `spec.credentialRef.name` |
| `credential_secret_namespace` | `str` | Tenant namespace |
| `credential_secret_key` | `str` | Tenant `spec.credentialRef.key` (default `"token"`) |
| `zone_id` | `str` | Tenant `spec.zoneId` (may be empty → auto-discovered) |
| `origin_service` | `str` | Merged from annotation / template / backendRefs auto-derive |
| `http_redirect` | `bool` | Merged from template |
| `origin_tls` | `OriginTLS` | Merged from template |
| `access` | `AccessSettings` | Merged from annotation + template |
| `service_token` | `ServiceTokenSettings` | Merged from annotation + template |
| `dns_only` | `DnsOnlySettings` | Merged from template |

### `compute_annotation_hash(annotations, per_route_template_spec, base_template_spec) -> str`

Returns the SHA-256 hex digest of:

```python
{
    "annotations": { k: v for k,v in annotations if k.startswith("cfzt.cloudflare.com/") },
    "per_route_template": per_route_template_spec,   # omitted if None
    "base_template": base_template_spec,             # omitted if None
}
```

Serialised as `json.dumps(..., sort_keys=True)` before hashing. Including template specs means a template change invalidates the hash for all dependent routes — even if the HTTPRoute annotations haven't changed.

### `merge_settings(annotations, httproute_body, tenant_spec, per_route_template_spec, base_template_spec) -> ReconcileSettings`

Implements the 3-way merge chain with this priority (highest wins):

```
annotation override → per-route template → base template → hardcoded default
```

**`{{ hostname }}` substitution** — Any template field value containing the literal string `{{ hostname }}` is replaced with the actual hostname from the `cfzt.cloudflare.com/hostname` annotation. This is most commonly used so a single `originServerName: "{{ hostname }}"` template works correctly for every route.

**Origin URL auto-derivation** — When no origin URL is found anywhere in the chain, the function derives one from `spec.rules[0].backendRefs[0]`:

```python
f"http://{ref_name}.{route_namespace}.svc.cluster.local:{ref_port}"
```

**Boolean coercion** — The `_bool()` helper accepts Python `bool`, or strings `"true"`, `"1"`, `"yes"` (case-insensitive). This lets annotations like `cfzt.cloudflare.com/access.enabled: "true"` work naturally.

**CSV splitting** — Annotations like `cfzt.cloudflare.com/access.allowGroups: "group-a,group-b"` are split and trimmed by `_split_csv()`.

---

## `cloudflare_api.py` — Cloudflare SDK Wrapper

**Logger:** `cfzt.cloudflare_api` (via module-level `logging.getLogger`)

All functions are stateless. They accept a `cloudflare.Cloudflare` client as their first argument and return plain dicts or `None`. No state is held at module level.

### Client

#### `make_client(api_token: str) -> Cloudflare`

Constructs and returns a `cloudflare.Cloudflare` SDK client using the given token.

### Zone

#### `resolve_zone_id(client, hostname, explicit_zone_id="") -> str`

1. If `explicit_zone_id` is non-empty, returns it immediately.
2. Otherwise, extracts the registrable domain from `hostname` (e.g. `sub.example.com` → `example.com`) and queries `client.zones.list(name=domain)`.
3. Returns the first matching zone's ID, or `""` if none found.

### Tunnel Routes

#### `upsert_tunnel_route(client, account_id, tunnel_id, hostname, origin_service, *, origin_uses_https, no_tls_verify, origin_server_name, ca_pool, tls_timeout, http2_origin, match_sni_to_host)`

Writes (creates or replaces) a hostname route on the given tunnel. Builds the `originRequest` block from the TLS parameters. If `origin_server_name` is empty and `origin_uses_https` is `True`, the hostname is used as the default SNI.

Uses `PUT /accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations`.

#### `delete_tunnel_route(client, account_id, tunnel_id, hostname)`

Removes the hostname entry from the tunnel's ingress configuration by fetching the full configuration, filtering out the target hostname, and writing it back. Silently ignores 404.

### DNS Records

#### `upsert_cname_record(client, zone_id, hostname, tunnel_id, existing_record_id="") -> dict`

Creates or updates a proxied CNAME record: `hostname → {tunnel_id}.cfargotunnel.com`.

- If `existing_record_id` is set, calls `UPDATE` directly.
- Otherwise, searches for an existing CNAME with the same name via `_find_dns_record()`.
- Returns `{"record_id": str, "created": bool}`.

#### `upsert_a_record(client, zone_id, hostname, ip, *, proxied, ttl, existing_record_id="") -> dict`

Creates or updates an A record pointing at `ip`.

- Same find-or-create logic as `upsert_cname_record()`.
- Returns `{"record_id": str, "ip_address": str, "created": bool}`.

#### `delete_dns_record(client, zone_id, record_id)`

Deletes a DNS record by ID. Silently ignores 404.

#### `_find_dns_record(client, zone_id, hostname, record_type) -> str` *(private)*

Lists DNS records for the zone filtered by name and type, returns the first match's ID or `""`.

### Access Applications

#### `upsert_access_app(client, account_id, app_name, domain, existing_app_id="", **kwargs) -> dict`

Creates or updates a `self_hosted` Access Application.

- If `existing_app_id` is set, updates it directly.
- Otherwise, lists all apps and matches on `domain`.
- All UI/session settings are passed through `_build_access_app_payload()`.
- Returns `{"app_id": str, "created": bool}`.

#### `delete_access_app(client, account_id, app_id)`

Deletes an Access Application by ID. Silently ignores 404.

#### `upsert_access_policy(client, account_id, app_id, policy_name, allow_groups, allow_emails, existing_policy_id="") -> dict`

Creates or updates an app-level Access Policy with decision `allow`.

- Include rules are built from `allow_groups` (as `{"group": {"id": gid}}`) and `allow_emails` (as `{"email": {"email": addr}}`).
- Falls back to `[{"everyone": {}}]` if both lists are empty.
- Returns `{"policy_id": str, "created": bool}`.

#### `resolve_policy_ids(client, account_id, policy_names: list[str]) -> list[str]`

Resolves a list of Access Policy names to UUIDs by listing all policies in the account. Logs a warning for any name that can't be resolved. Returns the resolved UUIDs.

### Service Tokens

#### `create_service_token(client, account_id, token_name, duration="8760h") -> dict`

Creates a new Access Service Token. Returns `{"token_id": str, "client_id": str, "client_secret": str}`.

> The `client_secret` is only available in this response. Store it immediately.

#### `delete_service_token(client, account_id, token_id)`

Deletes a service token by ID. Silently ignores 404.

### Bulk Deletion

#### `delete_all_resources(client, account_id, *, app_id, token_id, tunnel_id, hostname, dns_record_id, zone_id)`

Deletes all Cloudflare resources for a route in dependency order:

1. Access Application (`app_id`)
2. Service Token (`token_id`)
3. Tunnel Hostname Route (`tunnel_id` + `hostname`)
4. DNS Record (`dns_record_id` + `zone_id`)

Steps with empty IDs are silently skipped. All deletions ignore 404.

---

## `k8s_helpers.py` — Kubernetes API Helpers

**Logger:** `cfzt.k8s_helpers`

All Kubernetes API calls go through this module. kopf loads the in-cluster kube config automatically, so `CoreV1Api` and `CustomObjectsApi` work without any manual config.

### Constants

| Constant | Value |
|----------|-------|
| `CRD_GROUP` | `cfzt.cloudflare.com` |
| `CRD_VERSION` | `v1alpha1` |
| `HTTPROUTE_GROUP` | `gateway.networking.k8s.io` |
| `HTTPROUTE_VERSION` | `v1` |
| `MANAGED_BY_LABEL` | `app.kubernetes.io/managed-by` |
| `MANAGED_BY_VALUE` | `cfzt-operator` |

### Namespace Detection

#### `operator_namespace() -> str`

Reads `"/var/run/secrets/kubernetes.io/serviceaccount/namespace"` (in-cluster). Falls back to the `OPERATOR_NAMESPACE` environment variable, then `"cfzt-system"`.

### State ConfigMap Helpers

State ConfigMaps are named `cfzt-{route_namespace}-{route_name}` and live in the operator namespace.

**Labels applied to every state ConfigMap:**

```yaml
app.kubernetes.io/managed-by: cfzt-operator
cfzt.cloudflare.com/httproute-name: <name>
cfzt.cloudflare.com/httproute-namespace: <namespace>
cfzt.cloudflare.com/tenant: <tenant_name>
```

#### `get_state(route_namespace, route_name) -> dict[str, str] | None`

Reads the ConfigMap and returns its `.data` dict, or `None` if the ConfigMap doesn't exist (404).

#### `update_state(route_namespace, route_name, tenant_name, data)`

Creates the ConfigMap if absent, replaces it if present. Always sets the correct labels.

#### `delete_state(route_namespace, route_name)`

Deletes the ConfigMap. Ignores 404.

#### `list_state_configmaps() -> list[dict]`

Lists all ConfigMaps in the operator namespace with `app.kubernetes.io/managed-by=cfzt-operator`. Returns a list of `{"name": str, "labels": dict, "data": dict}`.

### Secret Helpers

#### `read_secret_key(namespace, name, key) -> str`

Reads `Secret.data[key]` and base64-decodes it. Raises `KeyError` if the key doesn't exist in the secret.

#### `create_service_token_secret(namespace, secret_name, client_id, client_secret)`

Creates (or replaces) an `Opaque` Secret with:

```yaml
data:
  CF_ACCESS_CLIENT_ID: <client_id>
  CF_ACCESS_CLIENT_SECRET: <client_secret>
```

Labeled `app.kubernetes.io/managed-by: cfzt-operator`.

#### `delete_secret(namespace, name)`

Deletes a Secret. Ignores empty names and 404.

### CRD Lookups

#### `get_tenant(name, namespace) -> dict | None`

Fetches a `CloudflareZeroTrustTenant` CR. Returns the full object dict or `None` on 404.

#### `get_template(name, namespace) -> dict | None`

Fetches a `CloudflareZeroTrustTemplate` CR. Returns the full object dict or `None` on 404.

### HTTPRoute Helpers

#### `list_httproutes(namespace="") -> list[dict]`

Lists HTTPRoutes with `cfzt.cloudflare.com/enabled: "true"`. Searches a single namespace if `namespace` is given, otherwise searches cluster-wide.

#### `patch_httproute_annotations(namespace, name, annotations)`

Merges the given annotations into the HTTPRoute's existing annotations using a JSON merge-patch.

### Service Helpers

#### `get_service_ip(namespace, name) -> str`

Returns `status.loadBalancer.ingress[0].ip` for the named Service, or `""` if not yet assigned.

---

## Error Handling Summary

| Condition | Exception | Behaviour |
|-----------|-----------|-----------|
| Tenant not found | `kopf.TemporaryError(delay=30)` | Retried after 30 s |
| Zone unresolvable | `kopf.TemporaryError(delay=60)` | Retried after 60 s |
| LB IP not assigned | `kopf.TemporaryError(delay=30)` | Retried after 30 s |
| No IP configured (dns-only) | `kopf.PermanentError` | Not retried — config fix required |
| Invalid IP address | `kopf.PermanentError` | Not retried — config fix required |
| HTTPRoute 404 on annotation patch | Caught, logged | Skipped — route was deleted mid-reconcile |
| Tenant/credentials missing on delete | Caught, logged | State ConfigMap deleted, no CF cleanup |
| CF 404 on any delete operation | Silently ignored | Resource already gone |
| Unhandled exception in handler | Propagated to kopf | Retried with backoffs: 1 s, 5 s, 15 s |

---

## Adding a New Feature

To add a new operator capability (e.g., a new Cloudflare resource type):

1. **`config.py`** — Add fields to the relevant dataclass (or create a new one). Add merge logic in `merge_settings()`. Include the new fields in `compute_annotation_hash()` if they affect change detection.

2. **`cloudflare_api.py`** — Add `upsert_*` and `delete_*` functions wrapping the Cloudflare SDK. Follow the existing patterns: return a plain dict with resource IDs, ignore 404 on deletes, log at `INFO` level on create/update/delete.

3. **`reconciler.py`** — Add a `_reconcile_<feature>()` sub-reconciler. Call it from `reconcile_httproute()` when the feature is enabled (check `settings.<feature>.enabled`). Store resulting IDs in `state` dict. Add cleanup to `delete_all_resources()` call in `delete_httproute_resources()`.

4. **`k8s_helpers.py`** — Add any new K8s API helpers needed (e.g., new Secret types, new CRD lookups).

5. **`main.py`** — Only changes needed if adding a new CRD watch or timer. HTTPRoute-level features don't require changes here.

6. **CRD YAML** — Add the new fields to the `CloudflareZeroTrustTemplate` CRD in `charts/cloudflare-zero-trust-operator/templates/`.
