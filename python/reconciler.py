"""Core reconciliation and deletion logic.

Orchestrates calls between ``config``, ``cloudflare_api``, and ``k8s_helpers``
to implement the full lifecycle of an HTTPRoute → Cloudflare resource mapping.
"""
from __future__ import annotations

import datetime
import ipaddress
import logging

import kopf # pyright: ignore[reportMissingImports]

from config import (
    ANNOTATION_PREFIX,
    ReconcileSettings,
    compute_annotation_hash,
    merge_settings,
)
import cloudflare_api as cfapi
import k8s_helpers as k8s

logger = logging.getLogger("cfzt.reconciler")


# ---------------------------------------------------------------------------
# Reconcile
# ---------------------------------------------------------------------------

def reconcile_httproute(
    name: str,
    namespace: str,
    body: dict,
    log: logging.Logger | None = None,
) -> None:
    """Full reconciliation for a single HTTPRoute.

    1. Merge settings from annotations / templates / tenant
    2. Check annotation hash: skip if unchanged
    3. Resolve zone ID
    4. Create / update Cloudflare resources
    5. Persist state + patch annotations
    """
    log = log or logger
    annotations = body.get("metadata", {}).get("annotations", {})

    # --- Basic pre-checks -------------------------------------------------
    tenant_name = annotations.get(f"{ANNOTATION_PREFIX}tenant")
    hostname = annotations.get(f"{ANNOTATION_PREFIX}hostname")
    if not tenant_name or not hostname:
        log.warning(
            "HTTPRoute %s/%s missing tenant or hostname annotation, skipping",
            namespace, name,
        )
        return

    # --- Tenant lookup (HTTPRoute namespace, then operator namespace) -----
    op_ns = k8s.operator_namespace()
    tenant = k8s.get_tenant(tenant_name, namespace)
    if not tenant and namespace != op_ns:
        tenant = k8s.get_tenant(tenant_name, op_ns)
    if not tenant:
        raise kopf.TemporaryError(
            f"Tenant '{tenant_name}' not found in namespace "
            f"'{namespace}' or '{op_ns}'",
            delay=30,
        )

    # --- Template lookup (HTTPRoute namespace, then operator namespace) ---
    per_route_tpl_name = annotations.get(f"{ANNOTATION_PREFIX}template")
    per_route_tpl = None
    if per_route_tpl_name:
        per_route_tpl = k8s.get_template(per_route_tpl_name, namespace)
        if not per_route_tpl and namespace != op_ns:
            per_route_tpl = k8s.get_template(per_route_tpl_name, op_ns)
    base_tpl_name = f"base-{tenant_name}"
    base_tpl = k8s.get_template(base_tpl_name, namespace)
    if not base_tpl and namespace != op_ns:
        base_tpl = k8s.get_template(base_tpl_name, op_ns)

    # --- Merge settings ---------------------------------------------------
    settings = merge_settings(
        annotations,
        body,
        tenant,
        per_route_tpl.get("spec", {}) if per_route_tpl else None,
        base_tpl.get("spec", {}) if base_tpl else None,
    )

    # --- Change detection -------------------------------------------------
    per_route_spec = per_route_tpl.get("spec", {}) if per_route_tpl else None
    base_spec = base_tpl.get("spec", {}) if base_tpl else None
    new_hash = compute_annotation_hash(annotations, per_route_spec, base_spec)
    existing_state = k8s.get_state(namespace, name) or {}
    if existing_state.get("annotation_hash") == new_hash:
        log.info("No annotation change for %s/%s — skipping", namespace, name)
        return

    # --- Cloudflare client ------------------------------------------------
    api_token = k8s.read_secret_key(
        settings.credential_secret_namespace,
        settings.credential_secret_name,
        settings.credential_secret_key,
    )
    client = cfapi.make_client(api_token)

    # --- Resolve zone ID --------------------------------------------------
    zone_id = settings.zone_id or cfapi.resolve_zone_id(
        client, hostname, settings.zone_id,
    )
    if not zone_id:
        raise kopf.TemporaryError(
            f"Unable to resolve zone for {hostname}", delay=60,
        )

    # State dict we'll persist at the end
    state: dict[str, str] = {
        "annotation_hash": new_hash,
        "hostname": hostname,
        "tenant_name": tenant_name,
        "tunnel_id": settings.tunnel_id,
        "zone_id": zone_id,
        "httproute_namespace": namespace,
        "httproute_name": name,
    }
    result_annotations: dict[str, str] = {}

    # --- Stale resource cleanup (template change) -------------------------
    # If the annotation hash changed, the template or settings may have
    # changed type (e.g. tunnel → dns-only, or access removed).  Delete any
    # CF resources tracked in the previous state that are no longer required
    # by the new settings — before creating any new resources.
    _cleanup_stale_resources(client, settings, existing_state, namespace, log)

    # --- DNS-only vs tunnel mode ------------------------------------------
    if settings.dns_only.enabled:
        _reconcile_dns_only(client, settings, zone_id, existing_state,
                            state, result_annotations, namespace, log)
    else:
        _reconcile_tunnel(client, settings, zone_id, existing_state,
                          state, result_annotations, log)

    # --- Access Application -----------------------------------------------
    if settings.access.enabled:
        _reconcile_access(client, settings, zone_id, existing_state,
                          state, result_annotations, log)

    # --- Service Token ----------------------------------------------------
    if settings.service_token.enabled:
        _reconcile_service_token(client, settings, existing_state,
                                 state, result_annotations, namespace, name, log)

    # --- Persist ----------------------------------------------------------
    state["last_reconcile"] = datetime.datetime.now(
        tz=datetime.timezone.utc
    ).isoformat()
    k8s.update_state(namespace, name, tenant_name, state)
    # NOTE: lastReconcile is intentionally NOT written to the HTTPRoute
    # annotations. Writing a timestamp annotation on every reconcile would
    # cause kopf to fire an UPDATE event, which would re-trigger the handler
    # in an infinite loop. The timestamp lives in the state ConfigMap only.
    try:
        k8s.patch_httproute_annotations(namespace, name, result_annotations)
    except Exception as exc:
        if "404" in str(exc) or "Not Found" in str(exc):
            log.info("HTTPRoute %s/%s was deleted mid-reconcile — skipping annotation patch", namespace, name)
        else:
            raise
    log.info("Reconciled %s/%s  hostname=%s", namespace, name, hostname)


# ---------------------------------------------------------------------------
# Sub-reconcilers
# ---------------------------------------------------------------------------

def _cleanup_stale_resources(
    client,
    settings: ReconcileSettings,
    existing_state: dict,
    namespace: str,
    log: logging.Logger,
) -> None:
    """Delete CF resources from a previous reconcile that are no longer
    needed under the current settings after a template or annotation change.

    Handles these transitions gracefully:
    - tunnel → dns-only : remove tunnel ingress rule + CNAME record
    - dns-only → tunnel : remove A record
    - access removed    : delete Access Application (+ policies cascade in CF)
    - service token removed : delete Service Token + K8s Secret

    All CF delete calls are idempotent (404 is silently ignored).
    """
    account_id = settings.account_id
    zone_id = existing_state.get("zone_id", "")

    # --- Revoke access controls first (before any DNS/routing changes) ----
    # Removing auth before changing routing ensures there is never a window
    # where a route is live but unprotected.

    # Access App no longer needed
    if not settings.access.enabled and existing_state.get("access_app_id"):
        log.info(
            "Template change: removing Access App %s",
            existing_state["access_app_id"],
        )
        cfapi.delete_access_app(client, account_id, existing_state["access_app_id"])

    # Service Token no longer needed
    if not settings.service_token.enabled and existing_state.get("service_token_id"):
        log.info(
            "Template change: removing Service Token %s",
            existing_state["service_token_id"],
        )
        cfapi.delete_service_token(
            client, account_id, existing_state["service_token_id"]
        )
        svc_secret = existing_state.get("service_token_secret_name", "")
        if svc_secret:
            k8s.delete_secret(namespace, svc_secret)

    # --- DNS / routing changes --------------------------------------------
    # Cloudflare rejects creating a CNAME when an A record exists for the
    # same hostname (and vice-versa), so stale records must be removed before
    # the new-mode sub-reconciler creates the replacement record.

    # Tunnel → DNS-only: remove stale tunnel ingress rule and CNAME
    if settings.dns_only.enabled and existing_state.get("cname_record_id"):
        old_tunnel_id = existing_state.get("tunnel_id", "") or settings.tunnel_id
        old_hostname = existing_state.get("hostname", "") or settings.hostname
        log.info(
            "Template change → dns-only: removing tunnel route + CNAME for %s",
            old_hostname,
        )
        cfapi.delete_tunnel_route(client, account_id, old_tunnel_id, old_hostname)
        cfapi.delete_dns_record(client, zone_id, existing_state["cname_record_id"])

    # DNS-only → tunnel: remove stale A record before CNAME is created
    if not settings.dns_only.enabled and existing_state.get("dns_record_id"):
        log.info(
            "Template change → tunnel: removing A record %s",
            existing_state["dns_record_id"],
        )
        cfapi.delete_dns_record(client, zone_id, existing_state["dns_record_id"])


def _reconcile_tunnel(
    client,
    settings: ReconcileSettings,
    zone_id: str,
    existing_state: dict,
    state: dict,
    result_annotations: dict,
    log: logging.Logger,
) -> None:
    """Upsert tunnel hostname route + CNAME."""
    origin_uses_https = settings.origin_service.startswith("https://")
    cfapi.upsert_tunnel_route(
        client,
        settings.account_id,
        settings.tunnel_id,
        settings.hostname,
        settings.origin_service,
        origin_uses_https=origin_uses_https,
        no_tls_verify=settings.origin_tls.no_tls_verify,
        origin_server_name=settings.origin_tls.origin_server_name,
        ca_pool=settings.origin_tls.ca_pool,
        tls_timeout=settings.origin_tls.tls_timeout,
        http2_origin=settings.origin_tls.http2_origin,
        match_sni_to_host=settings.origin_tls.match_sni_to_host,
    )
    state["hostname_route_id"] = settings.tunnel_id
    result_annotations[f"{ANNOTATION_PREFIX}hostnameRouteId"] = settings.tunnel_id

    cname = cfapi.upsert_cname_record(
        client, zone_id, settings.hostname, settings.tunnel_id,
        existing_record_id=existing_state.get("cname_record_id", ""),
    )
    state["cname_record_id"] = cname["record_id"]
    result_annotations[f"{ANNOTATION_PREFIX}cnameRecordId"] = cname["record_id"]


def _reconcile_dns_only(
    client,
    settings: ReconcileSettings,
    zone_id: str,
    existing_state: dict,
    state: dict,
    result_annotations: dict,
    namespace: str,
    log: logging.Logger,
) -> None:
    """Upsert DNS A record for dns-only mode."""
    ip_addr = settings.dns_only.static_ip

    # Resolve from a LoadBalancer Service if ingressServiceRef is provided
    if not ip_addr and settings.dns_only.ingress_service_ref:
        ref = settings.dns_only.ingress_service_ref
        svc_ns = ref.get("namespace", namespace)
        ip_addr = k8s.get_service_ip(svc_ns, ref["name"])
        if not ip_addr:
            raise kopf.TemporaryError(
                f"LoadBalancer IP not yet assigned for {svc_ns}/{ref['name']}",
                delay=30,
            )

    if not ip_addr:
        raise kopf.PermanentError(
            "dns-only mode requires either dnsOnly.staticIp or "
            "dnsOnly.ingressServiceRef"
        )

    # Validate IP
    try:
        ipaddress.ip_address(ip_addr)
    except ValueError as exc:
        raise kopf.PermanentError(f"Invalid IP for dns-only: {exc}") from exc

    a_rec = cfapi.upsert_a_record(
        client, zone_id, settings.hostname, ip_addr,
        proxied=settings.dns_only.proxied,
        ttl=settings.dns_only.ttl,
        existing_record_id=existing_state.get("dns_record_id", ""),
    )
    state["dns_record_id"] = a_rec["record_id"]
    state["dns_record_ip"] = a_rec["ip_address"]
    result_annotations[f"{ANNOTATION_PREFIX}dnsRecordId"] = a_rec["record_id"]
    result_annotations[f"{ANNOTATION_PREFIX}dnsRecordIp"] = a_rec["ip_address"]


def _reconcile_access(
    client,
    settings: ReconcileSettings,
    zone_id: str,
    existing_state: dict,
    state: dict,
    result_annotations: dict,
    log: logging.Logger,
) -> None:
    """Upsert Access Application and policy."""
    # Resolve reusable policy names → IDs
    reusable_ids = cfapi.resolve_policy_ids(
        client, settings.account_id, settings.access.existing_policy_names,
    )

    app_name = f"cfzt-{settings.hostname}"
    app_result = cfapi.upsert_access_app(
        client,
        settings.account_id,
        app_name,
        settings.hostname,
        existing_app_id=existing_state.get("access_app_id", ""),
        session_duration=settings.access.session_duration,
        auto_redirect_to_identity=settings.access.auto_redirect_to_identity,
        enable_binding_cookie=settings.access.enable_binding_cookie,
        http_only_cookie_attribute=settings.access.http_only_cookie_attribute,
        same_site_cookie_attribute=settings.access.same_site_cookie_attribute,
        logo_url=settings.access.logo_url,
        skip_interstitial=settings.access.skip_interstitial,
        app_launcher_visible=settings.access.app_launcher_visible,
        service_auth_401_redirect=settings.access.service_auth_401_redirect,
        custom_deny_message=settings.access.custom_deny_message,
        custom_deny_url=settings.access.custom_deny_url,
        custom_non_identity_deny_url=settings.access.custom_non_identity_deny_url,
        policy_ids=reusable_ids,
    )
    state["access_app_id"] = app_result["app_id"]
    result_annotations[f"{ANNOTATION_PREFIX}accessAppId"] = app_result["app_id"]

    # Create/update allow policy when groups or emails are specified
    if settings.access.allow_groups or settings.access.allow_emails:
        policy_name = f"cfzt-{settings.hostname}-allow"
        existing_policy_ids = existing_state.get("access_policy_ids", "")
        first_existing = existing_policy_ids.split(",")[0] if existing_policy_ids else ""

        pol = cfapi.upsert_access_policy(
            client,
            settings.account_id,
            app_result["app_id"],
            policy_name,
            settings.access.allow_groups,
            settings.access.allow_emails,
            existing_policy_id=first_existing,
        )
        state["access_policy_ids"] = pol["policy_id"]
        result_annotations[f"{ANNOTATION_PREFIX}accessPolicyIds"] = pol["policy_id"]


def _reconcile_service_token(
    client,
    settings: ReconcileSettings,
    existing_state: dict,
    state: dict,
    result_annotations: dict,
    namespace: str,
    route_name: str,
    log: logging.Logger,
) -> None:
    """Create service token + K8s Secret (skip if already exists)."""
    existing_token_id = existing_state.get("service_token_id", "")
    if existing_token_id:
        # Token already exists — carry forward
        state["service_token_id"] = existing_token_id
        state["service_token_secret_name"] = existing_state.get(
            "service_token_secret_name", ""
        )
        return

    token_name = f"cfzt-{settings.hostname}"
    tok = cfapi.create_service_token(
        client,
        settings.account_id,
        token_name,
        settings.service_token.duration,
    )
    secret_name = f"cfzt-svctoken-{route_name}"
    k8s.create_service_token_secret(
        namespace, secret_name, tok["client_id"], tok["client_secret"],
    )
    state["service_token_id"] = tok["token_id"]
    state["service_token_secret_name"] = secret_name
    result_annotations[f"{ANNOTATION_PREFIX}serviceTokenId"] = tok["token_id"]
    result_annotations[f"{ANNOTATION_PREFIX}serviceTokenSecretName"] = secret_name


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

def delete_httproute_resources(
    name: str,
    namespace: str,
    log: logging.Logger | None = None,
) -> None:
    """Remove all Cloudflare resources tracked by the state ConfigMap.

    Called from the kopf delete handler or orphan cleanup.
    """
    log = log or logger
    state = k8s.get_state(namespace, name)
    if not state:
        log.info("No state for %s/%s — nothing to delete", namespace, name)
        return

    tenant_name = state.get("tenant_name", "")
    tenant_ns = state.get("httproute_namespace", namespace)
    op_ns = k8s.operator_namespace()
    tenant = k8s.get_tenant(tenant_name, tenant_ns) if tenant_name else None
    if not tenant and tenant_name and tenant_ns != op_ns:
        tenant = k8s.get_tenant(tenant_name, op_ns)

    if not tenant:
        log.warning(
            "Tenant '%s' not found — deleting state without CF cleanup "
            "for %s/%s", tenant_name, namespace, name,
        )
        k8s.delete_state(namespace, name)
        return

    # Read CF credentials
    cred_ref = tenant["spec"]["credentialRef"]
    try:
        api_token = k8s.read_secret_key(
            tenant["metadata"]["namespace"],
            cred_ref["name"],
            cred_ref.get("key", "token"),
        )
    except Exception:
        log.exception(
            "Failed to read credentials for tenant '%s' — deleting state "
            "without CF cleanup for %s/%s", tenant_name, namespace, name,
        )
        k8s.delete_state(namespace, name)
        return

    client = cfapi.make_client(api_token)
    account_id = tenant["spec"]["accountId"]

    cfapi.delete_all_resources(
        client,
        account_id,
        app_id=state.get("access_app_id", ""),
        token_id=state.get("service_token_id", ""),
        tunnel_id=state.get("tunnel_id", ""),
        hostname=state.get("hostname", ""),
        dns_record_id=state.get("dns_record_id", "")
                      or state.get("cname_record_id", ""),
        zone_id=state.get("zone_id", ""),
    )

    # Delete K8s service-token secret
    svc_secret = state.get("service_token_secret_name", "")
    if svc_secret:
        k8s.delete_secret(namespace, svc_secret)

    # Delete the state ConfigMap itself
    k8s.delete_state(namespace, name)
    log.info("Deleted resources for %s/%s", namespace, name)


# ---------------------------------------------------------------------------
# Orphan cleanup
# ---------------------------------------------------------------------------

def cleanup_orphaned_states(
    tenant_name: str,
    log: logging.Logger | None = None,
) -> None:
    """Find state ConfigMaps whose HTTPRoute no longer exists and clean up.

    Scoped to a single tenant — called from the per-tenant timer.
    """
    log = log or logger
    all_states = k8s.list_state_configmaps()
    tenant_states = [
        s for s in all_states
        if s["labels"].get("cfzt.cloudflare.com/tenant") == tenant_name
    ]
    if not tenant_states:
        return

    for s in tenant_states:
        rt_ns = s["labels"].get("cfzt.cloudflare.com/httproute-namespace", "")
        rt_name = s["labels"].get("cfzt.cloudflare.com/httproute-name", "")
        if not rt_ns or not rt_name:
            continue

        # Check if the HTTPRoute still exists and is still enabled
        from kubernetes import client as k8s_client # pyright: ignore[reportMissingImports]
        from kubernetes.client.rest import ApiException as K8sApiException # pyright: ignore[reportMissingImports]
        crd_api = k8s_client.CustomObjectsApi()
        try:
            route = crd_api.get_namespaced_custom_object(
                k8s.HTTPROUTE_GROUP, k8s.HTTPROUTE_VERSION,
                rt_ns, "httproutes", rt_name,
            )
            ann = route.get("metadata", {}).get("annotations", {})
            if ann.get("cfzt.cloudflare.com/enabled") == "true":
                continue  # still active
        except K8sApiException as exc:
            if exc.status != 404:
                log.warning("Error checking HTTPRoute %s/%s: %s",
                            rt_ns, rt_name, exc)
                continue

        # Orphaned — delete CF resources and state
        log.info("Orphaned state detected: %s/%s — cleaning up",
                 rt_ns, rt_name)
        delete_httproute_resources(rt_name, rt_ns, log)
