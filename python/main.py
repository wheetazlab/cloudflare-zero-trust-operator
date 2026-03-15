"""kopf operator — event handlers and entry point.

Watches HTTPRoutes annotated with ``cfzt.cloudflare.com/enabled: "true"``
and reconciles them against the Cloudflare API.  Periodic orphan cleanup
runs via a timer on each CloudflareZeroTrustTenant resource.
"""
from __future__ import annotations

import logging
import os

import kopf

import reconciler

logger = logging.getLogger("cfzt.operator")

# ---------------------------------------------------------------------------
# Namespace filtering
# ---------------------------------------------------------------------------

_WATCH_NAMESPACES_RAW = os.environ.get("WATCH_NAMESPACES", "")
WATCH_NAMESPACES: list[str] = [
    ns.strip() for ns in _WATCH_NAMESPACES_RAW.split(",") if ns.strip()
]


def _ns_filter(namespace: str, **_) -> bool:  # noqa: ANN003
    """Return True when the namespace should be handled."""
    if not WATCH_NAMESPACES:
        return True
    return namespace in WATCH_NAMESPACES


# ---------------------------------------------------------------------------
# Startup / settings
# ---------------------------------------------------------------------------

@kopf.on.startup()
def configure(settings: kopf.OperatorSettings, **_) -> None:
    # Keep kopf's own annotations separate from our cfzt annotations
    settings.persistence.progress_storage = kopf.AnnotationsProgressStorage(
        prefix="kopf.cfzt.cloudflare.com",
    )
    settings.persistence.diffbase_storage = kopf.AnnotationsDiffBaseStorage(
        prefix="kopf.cfzt.cloudflare.com",
    )
    # Suppress noisy k8s event posting for routine handler runs
    settings.posting.level = logging.WARNING
    # Faster retries on transient errors (default max is 60s)
    settings.networking.error_backoffs = [1, 5, 15]
    logger.info("Cloudflare Zero-Trust operator started")
    if WATCH_NAMESPACES:
        logger.info("Watching namespaces: %s", WATCH_NAMESPACES)
    else:
        logger.info("Watching all namespaces")


# ---------------------------------------------------------------------------
# HTTPRoute handlers
# ---------------------------------------------------------------------------

HTTPROUTE_KWARGS = dict(
    group="gateway.networking.k8s.io",
    version="v1",
    plural="httproutes",
    annotations={"cfzt.cloudflare.com/enabled": "true"},
    when=_ns_filter,
    backoff=15,  # max 15s retry on handler failure (default 60s)
)


@kopf.on.resume(**HTTPROUTE_KWARGS)
@kopf.on.create(**HTTPROUTE_KWARGS)
@kopf.on.update(**HTTPROUTE_KWARGS)
def on_httproute_reconcile(
    body: dict,
    meta: dict,
    name: str,
    namespace: str,
    logger: logging.Logger,
    **_,
) -> dict:
    """Reconcile an HTTPRoute against Cloudflare."""
    reconciler.reconcile_httproute(name, namespace, body, logger)
    return {"message": f"Reconciled {namespace}/{name}"}


@kopf.on.delete(**HTTPROUTE_KWARGS)
def on_httproute_delete(
    name: str,
    namespace: str,
    logger: logging.Logger,
    **_,
) -> None:
    """Clean up Cloudflare resources when an HTTPRoute is deleted."""
    reconciler.delete_httproute_resources(name, namespace, logger)


# ---------------------------------------------------------------------------
# Template change → re-reconcile affected HTTPRoutes
# ---------------------------------------------------------------------------

@kopf.on.update(
    "cloudflarezerotrusttemplates",
    group="cfzt.cloudflare.com",
    version="v1alpha1",
)
def on_template_update(
    name: str,
    namespace: str,
    logger: logging.Logger,
    **_,
) -> dict:
    """When a template changes, re-reconcile all HTTPRoutes that use it."""
    import k8s_helpers as k8s

    routes = k8s.list_httproutes()
    matched = 0
    for route in routes:
        ann = route.get("metadata", {}).get("annotations", {})
        rt_name = route["metadata"]["name"]
        rt_ns = route["metadata"]["namespace"]
        # Match per-route template or base template (base-<tenant>)
        tpl_name = ann.get("cfzt.cloudflare.com/template", "")
        tenant_name = ann.get("cfzt.cloudflare.com/tenant", "")
        base_tpl_name = f"base-{tenant_name}" if tenant_name else ""
        if name not in (tpl_name, base_tpl_name):
            continue
        logger.info(
            "Template '%s' changed — re-reconciling %s/%s",
            name, rt_ns, rt_name,
        )
        try:
            reconciler.reconcile_httproute(rt_name, rt_ns, route, logger)
            matched += 1
        except Exception:
            logger.exception(
                "Failed to re-reconcile %s/%s after template change",
                rt_ns, rt_name,
            )
    return {"message": f"Re-reconciled {matched} HTTPRoute(s) for template {name}"}


# ---------------------------------------------------------------------------
# Periodic orphan cleanup — per tenant
# ---------------------------------------------------------------------------

@kopf.timer(
    "cloudflarezerotrusttenants",
    group="cfzt.cloudflare.com",
    version="v1alpha1",
    interval=300,
    initial_delay=60,
)
def orphan_cleanup(
    name: str,
    namespace: str,
    logger: logging.Logger,
    **_,
) -> None:
    """Scan for state ConfigMaps whose HTTPRoute no longer exists."""
    reconciler.cleanup_orphaned_states(name, logger)
