"""Settings dataclasses and template-merge logic.

Replicates the Ansible create_task.yml merge chain:
    annotation override → per-route template → base template → hardcoded default
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Dataclasses for reconcile settings
# ---------------------------------------------------------------------------

@dataclass
class OriginTLS:
    no_tls_verify: bool = False
    origin_server_name: str = ""
    ca_pool: str = ""
    tls_timeout: int = 10
    http2_origin: bool = False
    match_sni_to_host: bool = False


@dataclass
class AccessSettings:
    enabled: bool = False
    session_duration: str = "24h"
    allow_groups: list[str] = field(default_factory=list)
    allow_emails: list[str] = field(default_factory=list)
    existing_policy_names: list[str] = field(default_factory=list)
    auto_redirect_to_identity: bool = False
    enable_binding_cookie: bool = False
    http_only_cookie_attribute: bool = True
    same_site_cookie_attribute: str = "lax"
    logo_url: str = ""
    skip_interstitial: bool = False
    app_launcher_visible: bool = True
    service_auth_401_redirect: bool = False
    custom_deny_message: str = ""
    custom_deny_url: str = ""
    custom_non_identity_deny_url: str = ""


@dataclass
class ServiceTokenSettings:
    enabled: bool = False
    duration: str = "8760h"


@dataclass
class DnsOnlySettings:
    enabled: bool = False
    proxied: bool = False
    ttl: int = 120
    static_ip: str = ""
    ingress_service_ref: dict | None = None


@dataclass
class ReconcileSettings:
    hostname: str
    tenant_name: str
    tenant_namespace: str
    account_id: str
    tunnel_id: str
    credential_secret_name: str
    credential_secret_namespace: str
    credential_secret_key: str = "token"
    zone_id: str = ""
    origin_service: str = ""
    http_redirect: bool = True
    origin_tls: OriginTLS = field(default_factory=OriginTLS)
    access: AccessSettings = field(default_factory=AccessSettings)
    service_token: ServiceTokenSettings = field(default_factory=ServiceTokenSettings)
    dns_only: DnsOnlySettings = field(default_factory=DnsOnlySettings)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ANNOTATION_PREFIX = "cfzt.cloudflare.com/"


def _bool(val, default: bool = False) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes")
    return default


def _split_csv(val: str) -> list[str]:
    """Split a comma-separated string, strip whitespace, drop empties."""
    if not val:
        return []
    return [s.strip() for s in val.split(",") if s.strip()]


def _deep_get(d: dict, *keys, default=None):
    """Safely traverse nested dicts."""
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k, default)
    return d


def compute_annotation_hash(
    annotations: dict,
    per_route_template_spec: dict | None = None,
    base_template_spec: dict | None = None,
) -> str:
    """SHA-256 of cfzt annotations + template specs (sorted JSON).

    Including template specs ensures that a template change invalidates
    the cached hash even when annotations haven't changed.
    """
    cfzt = {k: v for k, v in (annotations or {}).items()
            if k.startswith(ANNOTATION_PREFIX)}
    hashable: dict = {"annotations": cfzt}
    if per_route_template_spec:
        hashable["per_route_template"] = per_route_template_spec
    if base_template_spec:
        hashable["base_template"] = base_template_spec
    return hashlib.sha256(
        json.dumps(hashable, sort_keys=True).encode()
    ).hexdigest()


# ---------------------------------------------------------------------------
# Template merge
# ---------------------------------------------------------------------------

def merge_settings(
    annotations: dict,
    httproute_body: dict,
    tenant_spec: dict,
    per_route_template_spec: dict | None,
    base_template_spec: dict | None,
) -> ReconcileSettings:
    """Build ReconcileSettings from the full merge chain.

    Priority (highest wins): annotation → per-route template → base template → default.
    """
    ann = annotations or {}
    tpl = per_route_template_spec or {}
    base = base_template_spec or {}

    # --- Identity / tenant ------------------------------------------------
    hostname = ann.get(f"{ANNOTATION_PREFIX}hostname", "")
    tenant_name = tenant_spec["metadata"]["name"]
    tenant_ns = tenant_spec["metadata"]["namespace"]
    account_id = tenant_spec["spec"]["accountId"]
    tunnel_id = ann.get(f"{ANNOTATION_PREFIX}tunnelId",
                        tenant_spec["spec"].get("tunnelId", ""))

    cred_ref = tenant_spec["spec"]["credentialRef"]

    # --- DNS-only mode ----------------------------------------------------
    dns_only_enabled = _bool(_deep_get(tpl, "dnsOnly", "enabled",
                                       default=_deep_get(base, "dnsOnly", "enabled", default=False)))
    dns_only = DnsOnlySettings(
        enabled=dns_only_enabled,
        proxied=_bool(_deep_get(tpl, "dnsOnly", "proxied",
                                default=_deep_get(base, "dnsOnly", "proxied", default=False))),
        ttl=int(_deep_get(tpl, "dnsOnly", "ttl",
                          default=_deep_get(base, "dnsOnly", "ttl", default=120))),
        static_ip=_deep_get(tpl, "dnsOnly", "staticIp",
                            default=_deep_get(base, "dnsOnly", "staticIp", default="")),
        ingress_service_ref=_deep_get(tpl, "dnsOnly", "ingressServiceRef",
                                      default=_deep_get(base, "dnsOnly", "ingressServiceRef")),
    )

    # --- Origin service ---------------------------------------------------
    origin_service = ann.get(
        f"{ANNOTATION_PREFIX}origin.url",
        _deep_get(tpl, "originService", "url",
                  default=_deep_get(base, "originService", "url", default="")),
    )
    # Auto-derive from backendRefs when not set
    if not origin_service:
        rules = httproute_body.get("spec", {}).get("rules", [])
        if rules:
            refs = rules[0].get("backendRefs", [])
            if refs:
                ns = httproute_body["metadata"]["namespace"]
                origin_service = (
                    f"http://{refs[0]['name']}.{ns}"
                    f".svc.cluster.local:{refs[0]['port']}"
                )

    http_redirect = _bool(
        _deep_get(tpl, "originService", "httpRedirect",
                  default=_deep_get(base, "originService", "httpRedirect", default=True)),
        default=True,
    )

    # --- Origin TLS -------------------------------------------------------
    def _tls_val(key, default):
        return _deep_get(tpl, "originService", "originTLS", key,
                         default=_deep_get(base, "originService", "originTLS", key,
                                           default=default))

    # Template variable substitution: {{ hostname }} → actual hostname
    def _subst(val):
        return val.replace("{{ hostname }}", hostname) if isinstance(val, str) else val

    origin_tls = OriginTLS(
        no_tls_verify=_bool(ann.get(f"{ANNOTATION_PREFIX}origin.noTLSVerify",
                                    _tls_val("noTLSVerify", False))),
        origin_server_name=_subst(_tls_val("originServerName", "")),
        ca_pool=_tls_val("caPool", ""),
        tls_timeout=int(_tls_val("tlsTimeout", 10)),
        http2_origin=_bool(_tls_val("http2Origin", False)),
        match_sni_to_host=_bool(_tls_val("matchSNIToHost", False)),
    )

    # --- Access Application -----------------------------------------------
    def _access_val(key, default):
        return _deep_get(tpl, "accessApplication", key,
                         default=_deep_get(base, "accessApplication", key,
                                           default=default))

    access = AccessSettings(
        enabled=_bool(ann.get(f"{ANNOTATION_PREFIX}access.enabled",
                              _access_val("enabled", False))),
        session_duration=ann.get(f"{ANNOTATION_PREFIX}access.sessionDuration",
                                 _access_val("sessionDuration", "24h")),
        allow_groups=_split_csv(ann.get(f"{ANNOTATION_PREFIX}access.allowGroups",
                                        ",".join(_access_val("allowGroups", [])))),
        allow_emails=_split_csv(ann.get(f"{ANNOTATION_PREFIX}access.allowEmails",
                                        ",".join(_access_val("allowEmails", [])))),
        existing_policy_names=_split_csv(
            ann.get(f"{ANNOTATION_PREFIX}access.existingPolicyNames",
                    ",".join(_access_val("existingPolicyNames", [])))),
        auto_redirect_to_identity=_bool(
            ann.get(f"{ANNOTATION_PREFIX}access.autoRedirectToIdentity",
                    _access_val("autoRedirectToIdentity", False))),
        enable_binding_cookie=_bool(
            ann.get(f"{ANNOTATION_PREFIX}access.enableBindingCookie",
                    _access_val("enableBindingCookie", False))),
        http_only_cookie_attribute=_bool(
            ann.get(f"{ANNOTATION_PREFIX}access.httpOnlyCookieAttribute",
                    _access_val("httpOnlyCookieAttribute", True)),
            default=True),
        same_site_cookie_attribute=ann.get(
            f"{ANNOTATION_PREFIX}access.sameSiteCookieAttribute",
            _access_val("sameSiteCookieAttribute", "lax")),
        logo_url=_access_val("logoUrl", ""),
        skip_interstitial=_bool(
            ann.get(f"{ANNOTATION_PREFIX}access.skipInterstitial",
                    _access_val("skipInterstitial", False))),
        app_launcher_visible=_bool(
            ann.get(f"{ANNOTATION_PREFIX}access.appLauncherVisible",
                    _access_val("appLauncherVisible", True)),
            default=True),
        service_auth_401_redirect=_bool(
            ann.get(f"{ANNOTATION_PREFIX}access.serviceAuth401Redirect",
                    _access_val("serviceAuth401Redirect", False))),
        custom_deny_message=_access_val("customDenyMessage", ""),
        custom_deny_url=_access_val("customDenyUrl", ""),
        custom_non_identity_deny_url=_access_val("customNonIdentityDenyUrl", ""),
    )

    # --- Service Token ----------------------------------------------------
    def _svc_val(key, default):
        return _deep_get(tpl, "serviceToken", key,
                         default=_deep_get(base, "serviceToken", key, default=default))

    service_token = ServiceTokenSettings(
        enabled=_bool(ann.get(f"{ANNOTATION_PREFIX}serviceToken.enabled",
                              _svc_val("enabled", False))),
        duration=ann.get(f"{ANNOTATION_PREFIX}serviceToken.duration",
                         _svc_val("duration", "8760h")),
    )

    # --- Zone ID ----------------------------------------------------------
    zone_id = tenant_spec["spec"].get("zoneId", "")

    return ReconcileSettings(
        hostname=hostname,
        tenant_name=tenant_name,
        tenant_namespace=tenant_ns,
        account_id=account_id,
        tunnel_id=tunnel_id,
        credential_secret_name=cred_ref["name"],
        credential_secret_namespace=tenant_ns,
        credential_secret_key=cred_ref.get("key", "token"),
        zone_id=zone_id,
        origin_service=origin_service,
        http_redirect=http_redirect,
        origin_tls=origin_tls,
        access=access,
        service_token=service_token,
        dns_only=dns_only,
    )
