"""Kubernetes helper functions — state ConfigMaps, secrets, resource lookups.

All functions use the ``kubernetes`` Python client.  kopf loads the kube
config automatically, so CoreV1Api / CustomObjectsApi will work out of
the box inside kopf handlers.
"""
from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any

from kubernetes import client as k8s  # pyright: ignore[reportMissingImports]
from kubernetes.client.rest import ApiException # pyright: ignore[reportMissingImports]

logger = logging.getLogger("cfzt.k8s_helpers")

# CRD coordinates
CRD_GROUP = "cfzt.cloudflare.com"
CRD_VERSION = "v1alpha1"
HTTPROUTE_GROUP = "gateway.networking.k8s.io"
HTTPROUTE_VERSION = "v1"
MANAGED_BY_LABEL = "app.kubernetes.io/managed-by"
MANAGED_BY_VALUE = "cfzt-operator"


# ---------------------------------------------------------------------------
# Namespace detection
# ---------------------------------------------------------------------------

def operator_namespace() -> str:
    """Return the namespace the operator pod is running in."""
    try:
        with open(
            "/var/run/secrets/kubernetes.io/serviceaccount/namespace"
        ) as fh:
            return fh.read().strip()
    except FileNotFoundError:
        return os.environ.get("OPERATOR_NAMESPACE", "cfzt-system")


# ---------------------------------------------------------------------------
# State ConfigMap helpers
# ---------------------------------------------------------------------------

def _state_cm_name(route_namespace: str, route_name: str) -> str:
    return f"cfzt-{route_namespace}-{route_name}"


def _state_labels(
    route_namespace: str,
    route_name: str,
    tenant_name: str,
) -> dict[str, str]:
    return {
        MANAGED_BY_LABEL: MANAGED_BY_VALUE,
        "cfzt.cloudflare.com/httproute-name": route_name,
        "cfzt.cloudflare.com/httproute-namespace": route_namespace,
        "cfzt.cloudflare.com/tenant": tenant_name,
    }


def get_state(route_namespace: str, route_name: str) -> dict[str, str] | None:
    """Read the state ConfigMap.  Returns data dict or None if absent."""
    core = k8s.CoreV1Api()
    cm_name = _state_cm_name(route_namespace, route_name)
    try:
        cm = core.read_namespaced_config_map(cm_name, operator_namespace())
        return cm.data or {}
    except ApiException as exc:
        if exc.status == 404:
            return None
        raise


def update_state(
    route_namespace: str,
    route_name: str,
    tenant_name: str,
    data: dict[str, str],
) -> None:
    """Create or update the state ConfigMap with *data*."""
    core = k8s.CoreV1Api()
    ns = operator_namespace()
    cm_name = _state_cm_name(route_namespace, route_name)
    labels = _state_labels(route_namespace, route_name, tenant_name)

    body = k8s.V1ConfigMap(
        metadata=k8s.V1ObjectMeta(name=cm_name, namespace=ns, labels=labels),
        data=data,
    )
    try:
        core.read_namespaced_config_map(cm_name, ns)
        core.replace_namespaced_config_map(cm_name, ns, body)
    except ApiException as exc:
        if exc.status == 404:
            core.create_namespaced_config_map(ns, body)
        else:
            raise
    logger.debug("State updated: %s/%s", ns, cm_name)


def delete_state(route_namespace: str, route_name: str) -> None:
    """Delete the state ConfigMap.  Ignores 404."""
    core = k8s.CoreV1Api()
    cm_name = _state_cm_name(route_namespace, route_name)
    try:
        core.delete_namespaced_config_map(cm_name, operator_namespace())
        logger.info("State ConfigMap deleted: %s", cm_name)
    except ApiException as exc:
        if exc.status == 404:
            pass
        else:
            raise


def list_state_configmaps() -> list[dict[str, Any]]:
    """List all state ConfigMaps managed by the operator."""
    core = k8s.CoreV1Api()
    cms = core.list_namespaced_config_map(
        operator_namespace(),
        label_selector=f"{MANAGED_BY_LABEL}={MANAGED_BY_VALUE}",
    )
    return [
        {
            "name": cm.metadata.name,
            "labels": cm.metadata.labels or {},
            "data": cm.data or {},
        }
        for cm in cms.items
    ]


# ---------------------------------------------------------------------------
# Secret helpers
# ---------------------------------------------------------------------------

def read_secret_key(namespace: str, name: str, key: str) -> str:
    """Read a single key from a K8s Secret, base64-decoded."""
    core = k8s.CoreV1Api()
    secret = core.read_namespaced_secret(name, namespace)
    raw = (secret.data or {}).get(key)
    if raw is None:
        raise KeyError(f"Key '{key}' not found in secret {namespace}/{name}")
    return base64.b64decode(raw).decode()


def create_service_token_secret(
    namespace: str,
    secret_name: str,
    client_id: str,
    client_secret: str,
) -> None:
    """Create a K8s Secret holding service-token credentials.

    If the secret already exists it is replaced.
    """
    core = k8s.CoreV1Api()
    body = k8s.V1Secret(
        metadata=k8s.V1ObjectMeta(
            name=secret_name,
            namespace=namespace,
            labels={MANAGED_BY_LABEL: MANAGED_BY_VALUE},
        ),
        type="Opaque",
        string_data={
            "CF_ACCESS_CLIENT_ID": client_id,
            "CF_ACCESS_CLIENT_SECRET": client_secret,
        },
    )
    try:
        core.read_namespaced_secret(secret_name, namespace)
        core.replace_namespaced_secret(secret_name, namespace, body)
    except ApiException as exc:
        if exc.status == 404:
            core.create_namespaced_secret(namespace, body)
        else:
            raise
    logger.info("Service token secret written: %s/%s", namespace, secret_name)


def delete_secret(namespace: str, name: str) -> None:
    """Delete a K8s Secret.  Ignores 404."""
    if not name:
        return
    core = k8s.CoreV1Api()
    try:
        core.delete_namespaced_secret(name, namespace)
    except ApiException as exc:
        if exc.status == 404:
            pass
        else:
            raise


# ---------------------------------------------------------------------------
# CRD lookups
# ---------------------------------------------------------------------------

def get_tenant(name: str, namespace: str) -> dict | None:
    """Fetch a CloudflareZeroTrustTenant CR.  Returns None if absent."""
    crd = k8s.CustomObjectsApi()
    try:
        return crd.get_namespaced_custom_object(
            CRD_GROUP, CRD_VERSION, namespace,
            "cloudflarezerotrusttenants", name,
        )
    except ApiException as exc:
        if exc.status == 404:
            return None
        raise


def get_template(name: str, namespace: str) -> dict | None:
    """Fetch a CloudflareZeroTrustTemplate CR.  Returns None if absent."""
    crd = k8s.CustomObjectsApi()
    try:
        return crd.get_namespaced_custom_object(
            CRD_GROUP, CRD_VERSION, namespace,
            "cloudflarezerotrusttemplates", name,
        )
    except ApiException as exc:
        if exc.status == 404:
            return None
        raise


# ---------------------------------------------------------------------------
# HTTPRoute helpers
# ---------------------------------------------------------------------------

def list_httproutes(namespace: str = "") -> list[dict]:
    """List HTTPRoutes with the cfzt enabled annotation.

    If *namespace* is empty, searches all namespaces.
    """
    crd = k8s.CustomObjectsApi()
    if namespace:
        result = crd.list_namespaced_custom_object(
            HTTPROUTE_GROUP, HTTPROUTE_VERSION, namespace, "httproutes",
        )
    else:
        result = crd.list_cluster_custom_object(
            HTTPROUTE_GROUP, HTTPROUTE_VERSION, "httproutes",
        )
    routes = []
    for item in result.get("items", []):
        ann = item.get("metadata", {}).get("annotations", {})
        if ann.get("cfzt.cloudflare.com/enabled") == "true":
            routes.append(item)
    return routes


def patch_httproute_annotations(
    namespace: str,
    name: str,
    annotations: dict[str, str],
) -> None:
    """Merge *annotations* into the HTTPRoute's existing annotations."""
    crd = k8s.CustomObjectsApi()
    crd.patch_namespaced_custom_object(
        HTTPROUTE_GROUP, HTTPROUTE_VERSION, namespace, "httproutes", name,
        body={"metadata": {"annotations": annotations}},
    )


def get_service_ip(namespace: str, name: str) -> str:
    """Return the first LoadBalancer ingress IP for a Service.

    Used for dns-only mode when ingressServiceRef is set.
    """
    core = k8s.CoreV1Api()
    svc = core.read_namespaced_service(name, namespace)
    ingresses = (svc.status and svc.status.load_balancer
                 and svc.status.load_balancer.ingress) or []
    if ingresses:
        return ingresses[0].ip or ""
    return ""
