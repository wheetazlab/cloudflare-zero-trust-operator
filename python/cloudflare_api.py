"""Cloudflare API operations — all reusable, stateless functions.

Every public function takes a ``cloudflare.Cloudflare`` client as the first
argument so callers control authentication and retry configuration.

Covers: zone lookup, tunnel routes, DNS (CNAME + A), Access apps, Access
policies (app-level and reusable), service tokens, and resource deletion.
"""
from __future__ import annotations

import logging
from typing import Any

import cloudflare as cf_errors # type: ignore
from cloudflare import Cloudflare # type: ignore

logger = logging.getLogger("cfzt.cloudflare_api")


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------

def make_client(api_token: str) -> Cloudflare:
    """Create a Cloudflare SDK client with sensible retry defaults."""
    return Cloudflare(api_token=api_token, max_retries=3)


# ---------------------------------------------------------------------------
# Zone lookup
# ---------------------------------------------------------------------------

def resolve_zone_id(
    client: Cloudflare,
    hostname: str,
    tenant_zone_id: str = "",
) -> str:
    """Auto-discover Cloudflare Zone ID from a hostname.

    Tries 2-label then 3-label apex (handles ccSLDs like .co.uk).
    Validates against *tenant_zone_id* if provided.
    Returns zone ID or empty string on failure.
    """
    labels = hostname.split(".")
    candidates = [".".join(labels[-2:])]
    if len(labels) >= 3:
        candidates.append(".".join(labels[-3:]))

    discovered_id = ""
    for apex in candidates:
        try:
            page = client.zones.list(name=apex)
            results = list(page)
            if results:
                discovered_id = results[0].id
                break
        except cf_errors.APIError:
            continue

    if not discovered_id:
        logger.warning("Could not resolve zone ID for hostname %s", hostname)
        return ""

    if tenant_zone_id and discovered_id != tenant_zone_id:
        raise ValueError(
            f"Zone ID mismatch for '{hostname}': tenant has '{tenant_zone_id}' "
            f"but API returned '{discovered_id}'"
        )
    return discovered_id


# ---------------------------------------------------------------------------
# Reusable-policy name → UUID resolution
# ---------------------------------------------------------------------------

def resolve_policy_ids(
    client: Cloudflare,
    account_id: str,
    policy_names: list[str],
) -> list[str]:
    """Resolve account-level reusable Access policy names to UUIDs."""
    if not policy_names:
        return []

    all_policies = list(client.zero_trust.access.policies.list(account_id=account_id))
    name_to_id = {p.name: p.id for p in all_policies}
    missing = [n for n in policy_names if n not in name_to_id]
    if missing:
        raise ValueError(
            f"Unresolved Access policy names: {missing}. "
            f"Available: {list(name_to_id.keys())}"
        )
    return [name_to_id[n] for n in policy_names]


# ---------------------------------------------------------------------------
# Tunnel hostname route management
# ---------------------------------------------------------------------------

def upsert_tunnel_route(
    client: Cloudflare,
    account_id: str,
    tunnel_id: str,
    hostname: str,
    origin_service: str,
    *,
    origin_uses_https: bool = False,
    no_tls_verify: bool = False,
    origin_server_name: str = "",
    ca_pool: str = "",
    tls_timeout: int = 10,
    http2_origin: bool = False,
    match_sni_to_host: bool = False,
) -> str:
    """Add or update a hostname rule in the tunnel ingress config.

    Returns the tunnel ID (used as the hostnameRouteId).
    """
    # Fetch existing config
    try:
        existing = client.zero_trust.tunnels.cloudflared.configurations.get(
            tunnel_id=tunnel_id, account_id=account_id,
        )
        ingress = list(existing.config.ingress) if existing.config and existing.config.ingress else []
    except cf_errors.NotFoundError:
        ingress = []

    # Normalise: ensure ingress is a list of dicts
    ingress_dicts = []
    for rule in ingress:
        if isinstance(rule, dict):
            ingress_dicts.append(rule)
        else:
            ingress_dicts.append(rule.model_dump() if hasattr(rule, "model_dump") else dict(rule))

    # Build the new hostname rule
    rule: dict[str, Any] = {"hostname": hostname, "service": origin_service}

    if origin_uses_https:
        origin_request: dict[str, Any] = {
            "httpHostHeader": hostname,
            "noTLSVerify": no_tls_verify,
            "keepAliveConnections": 100,
        }
        if origin_server_name:
            origin_request["originServerName"] = origin_server_name
        if ca_pool:
            origin_request["caPool"] = ca_pool
        origin_request["tlsTimeout"] = tls_timeout
        origin_request["http2Origin"] = http2_origin
        rule["originRequest"] = origin_request

    # Remove existing rule for this hostname, preserve catch-all separately
    filtered = [r for r in ingress_dicts
                if r.get("hostname") and r["hostname"] != hostname]
    catch_all = [r for r in ingress_dicts if not r.get("hostname")]

    updated = [rule] + filtered
    # Ensure exactly one catch-all at the end
    if not any("http_status" in str(r.get("service", "")) for r in catch_all):
        catch_all = [{"service": "http_status:404"}]
    updated += catch_all

    # PUT the full config
    client.zero_trust.tunnels.cloudflared.configurations.update(
        tunnel_id=tunnel_id,
        account_id=account_id,
        config={"ingress": updated},
    )
    logger.info("Tunnel route upserted: %s → %s", hostname, origin_service)
    return tunnel_id


def delete_tunnel_route(
    client: Cloudflare,
    account_id: str,
    tunnel_id: str,
    hostname: str,
) -> None:
    """Remove a hostname from the tunnel ingress config."""
    if not tunnel_id or not hostname:
        return
    try:
        existing = client.zero_trust.tunnels.cloudflared.configurations.get(
            tunnel_id=tunnel_id, account_id=account_id,
        )
        ingress = list(existing.config.ingress) if existing.config and existing.config.ingress else []
    except cf_errors.NotFoundError:
        return

    ingress_dicts = []
    for rule in ingress:
        if isinstance(rule, dict):
            ingress_dicts.append(rule)
        else:
            ingress_dicts.append(rule.model_dump() if hasattr(rule, "model_dump") else dict(rule))

    updated = [r for r in ingress_dicts
               if r.get("hostname") != hostname]
    if not updated:
        updated = [{"service": "http_status:404"}]

    client.zero_trust.tunnels.cloudflared.configurations.update(
        tunnel_id=tunnel_id,
        account_id=account_id,
        config={"ingress": updated},
    )
    logger.info("Tunnel route removed: %s", hostname)


# ---------------------------------------------------------------------------
# DNS record management (CNAME for tunnels, A for dns-only)
# ---------------------------------------------------------------------------

def _find_dns_record(
    client: Cloudflare,
    zone_id: str,
    record_type: str,
    name: str,
) -> dict | None:
    """Look up a DNS record by type and name.  Returns dict or None."""
    records = list(client.dns.records.list(
        zone_id=zone_id, type=record_type, name=name,
    ))
    if records:
        r = records[0]
        return {
            "id": r.id,
            "content": r.content,
        }
    return None


def upsert_cname_record(
    client: Cloudflare,
    zone_id: str,
    hostname: str,
    tunnel_id: str,
    existing_record_id: str = "",
) -> dict:
    """Create or update a CNAME record pointing hostname → <tunnel>.cfargotunnel.com.

    Returns ``{"record_id": ..., "created": bool}``.
    """
    target = f"{tunnel_id}.cfargotunnel.com"

    if existing_record_id:
        client.dns.records.update(
            dns_record_id=existing_record_id,
            zone_id=zone_id,
            type="CNAME",
            name=hostname,
            content=target,
            ttl=1,
            proxied=True,
        )
        return {"record_id": existing_record_id, "created": False}

    existing = _find_dns_record(client, zone_id, "CNAME", hostname)
    if existing:
        if existing["content"] != target:
            client.dns.records.update(
                dns_record_id=existing["id"],
                zone_id=zone_id,
                type="CNAME",
                name=hostname,
                content=target,
                ttl=1,
                proxied=True,
            )
        return {"record_id": existing["id"], "created": False}

    record = client.dns.records.create(
        zone_id=zone_id,
        type="CNAME",
        name=hostname,
        content=target,
        ttl=1,
        proxied=True,
    )
    logger.info("CNAME created: %s → %s", hostname, target)
    return {"record_id": record.id, "created": True}


def upsert_a_record(
    client: Cloudflare,
    zone_id: str,
    hostname: str,
    ip_address: str,
    *,
    proxied: bool = False,
    ttl: int = 120,
    existing_record_id: str = "",
) -> dict:
    """Create or update a DNS A record.

    Returns ``{"record_id": ..., "ip_address": ..., "created": bool}``.
    """
    if existing_record_id:
        client.dns.records.update(
            dns_record_id=existing_record_id,
            zone_id=zone_id,
            type="A",
            name=hostname,
            content=ip_address,
            ttl=ttl,
            proxied=proxied,
        )
        return {"record_id": existing_record_id, "ip_address": ip_address, "created": False}

    existing = _find_dns_record(client, zone_id, "A", hostname)
    if existing:
        if existing["content"] != ip_address:
            client.dns.records.update(
                dns_record_id=existing["id"],
                zone_id=zone_id,
                type="A",
                name=hostname,
                content=ip_address,
                ttl=ttl,
                proxied=proxied,
            )
        return {"record_id": existing["id"], "ip_address": ip_address, "created": False}

    record = client.dns.records.create(
        zone_id=zone_id,
        type="A",
        name=hostname,
        content=ip_address,
        ttl=ttl,
        proxied=proxied,
    )
    logger.info("DNS A record created: %s → %s", hostname, ip_address)
    return {"record_id": record.id, "ip_address": ip_address, "created": True}


def delete_dns_record(
    client: Cloudflare,
    zone_id: str,
    record_id: str,
) -> None:
    """Delete a DNS record (CNAME or A).  Ignores 404."""
    if not zone_id or not record_id:
        return
    try:
        client.dns.records.delete(dns_record_id=record_id, zone_id=zone_id)
        logger.info("DNS record deleted: %s", record_id)
    except cf_errors.NotFoundError:
        pass


# ---------------------------------------------------------------------------
# Access Application management
# ---------------------------------------------------------------------------

def _build_access_app_payload(
    name: str,
    domain: str,
    *,
    session_duration: str = "24h",
    auto_redirect_to_identity: bool = False,
    enable_binding_cookie: bool = False,
    http_only_cookie_attribute: bool = True,
    same_site_cookie_attribute: str = "lax",
    logo_url: str = "",
    skip_interstitial: bool = False,
    app_launcher_visible: bool = True,
    service_auth_401_redirect: bool = False,
    custom_deny_message: str = "",
    custom_deny_url: str = "",
    custom_non_identity_deny_url: str = "",
    policy_ids: list[str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": name,
        "domain": domain,
        "type": "self_hosted",
        "session_duration": session_duration,
        "auto_redirect_to_identity": auto_redirect_to_identity,
        "enable_binding_cookie": enable_binding_cookie,
        "http_only_cookie_attribute": http_only_cookie_attribute,
        "same_site_cookie_attribute": same_site_cookie_attribute,
        "skip_interstitial": skip_interstitial,
        "app_launcher_visible": app_launcher_visible,
        "service_auth_401_redirect": service_auth_401_redirect,
    }
    if logo_url:
        payload["logo_url"] = logo_url
    if custom_deny_message:
        payload["custom_deny_message"] = custom_deny_message
    if custom_deny_url:
        payload["custom_deny_url"] = custom_deny_url
    if custom_non_identity_deny_url:
        payload["custom_non_identity_deny_url"] = custom_non_identity_deny_url
    if policy_ids:
        payload["policies"] = [{"id": pid} for pid in policy_ids]
    return payload


def upsert_access_app(
    client: Cloudflare,
    account_id: str,
    app_name: str,
    domain: str,
    existing_app_id: str = "",
    **kwargs,
) -> dict:
    """Create or update a Cloudflare Access Application.

    Returns ``{"app_id": ..., "created": bool}``.
    """
    payload = _build_access_app_payload(app_name, domain, **kwargs)

    # Resolve existing app
    resolved_id = existing_app_id
    if not resolved_id:
        apps = list(client.zero_trust.access.applications.list(account_id=account_id))
        for app in apps:
            if getattr(app, "domain", None) == domain:
                resolved_id = app.id
                break

    if resolved_id:
        client.zero_trust.access.applications.update(
            app_id=resolved_id,
            account_id=account_id,
            **payload,
        )
        logger.info("Access app updated: %s (%s)", app_name, resolved_id)
        return {"app_id": resolved_id, "created": False}

    result = client.zero_trust.access.applications.create(
        account_id=account_id,
        **payload,
    )
    logger.info("Access app created: %s (%s)", app_name, result.id)
    return {"app_id": result.id, "created": True}


def delete_access_app(
    client: Cloudflare,
    account_id: str,
    app_id: str,
) -> None:
    """Delete a Cloudflare Access Application.  Ignores 404."""
    if not app_id:
        return
    try:
        client.zero_trust.access.applications.delete(
            app_id=app_id, account_id=account_id,
        )
        logger.info("Access app deleted: %s", app_id)
    except cf_errors.NotFoundError:
        pass


# ---------------------------------------------------------------------------
# Access Policy management (app-level)
# ---------------------------------------------------------------------------

def _build_include_rules(
    allow_groups: list[str],
    allow_emails: list[str],
) -> list[dict]:
    rules: list[dict] = []
    for gid in allow_groups:
        rules.append({"group": {"id": gid}})
    for email in allow_emails:
        rules.append({"email": {"email": email}})
    return rules or [{"everyone": {}}]


def upsert_access_policy(
    client: Cloudflare,
    account_id: str,
    app_id: str,
    policy_name: str,
    allow_groups: list[str],
    allow_emails: list[str],
    existing_policy_id: str = "",
) -> dict:
    """Create or update an app-level Access Policy.

    Returns ``{"policy_id": ..., "created": bool}``.
    """
    include = _build_include_rules(allow_groups, allow_emails)
    payload = {
        "name": policy_name,
        "decision": "allow",
        "include": include,
        "precedence": 1,
    }

    if existing_policy_id:
        client.zero_trust.access.applications.policies.update(
            policy_id=existing_policy_id,
            app_id=app_id,
            account_id=account_id,
            **payload,
        )
        return {"policy_id": existing_policy_id, "created": False}

    result = client.zero_trust.access.applications.policies.create(
        app_id=app_id,
        account_id=account_id,
        **payload,
    )
    logger.info("Access policy created: %s (%s)", policy_name, result.id)
    return {"policy_id": result.id, "created": True}


# ---------------------------------------------------------------------------
# Service Token management
# ---------------------------------------------------------------------------

def create_service_token(
    client: Cloudflare,
    account_id: str,
    token_name: str,
    duration: str = "8760h",
) -> dict:
    """Create a new service token.

    Returns ``{"token_id": ..., "client_id": ..., "client_secret": ...}``.
    """
    result = client.zero_trust.access.service_tokens.create(
        account_id=account_id,
        name=token_name,
        duration=duration,
    )
    logger.info("Service token created: %s (%s)", token_name, result.id)
    return {
        "token_id": result.id,
        "client_id": result.client_id,
        "client_secret": result.client_secret,
    }


def delete_service_token(
    client: Cloudflare,
    account_id: str,
    token_id: str,
) -> None:
    """Delete a service token.  Ignores 404."""
    if not token_id:
        return
    try:
        client.zero_trust.access.service_tokens.delete(
            service_token_id=token_id, account_id=account_id,
        )
        logger.info("Service token deleted: %s", token_id)
    except cf_errors.NotFoundError:
        pass


# ---------------------------------------------------------------------------
# Bulk deletion (mirrors ansible delete_resources.yml)
# ---------------------------------------------------------------------------

def delete_all_resources(
    client: Cloudflare,
    account_id: str,
    *,
    app_id: str = "",
    token_id: str = "",
    tunnel_id: str = "",
    hostname: str = "",
    dns_record_id: str = "",
    zone_id: str = "",
) -> None:
    """Delete all Cloudflare resources associated with a route.

    Silently skips resources with empty IDs.  Order: app → token → tunnel
    route → DNS record (mirrors Ansible delete_resources.yml).
    """
    if app_id:
        delete_access_app(client, account_id, app_id)
    if token_id:
        delete_service_token(client, account_id, token_id)
    if tunnel_id and hostname:
        delete_tunnel_route(client, account_id, tunnel_id, hostname)
    if dns_record_id and zone_id:
        delete_dns_record(client, zone_id, dns_record_id)
