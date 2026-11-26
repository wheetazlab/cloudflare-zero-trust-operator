## Cloudflare Zero Trust Operator

A Kubernetes operator that manages Cloudflare Zero Trust tunnel routing by watching HTTPRoute resources and reconciling them with the Cloudflare API.

### This chart repository is moving

The chart is now published as an OCI artifact: `oci://ghcr.io/wheetazlab/charts/cloudflare-zero-trust-operator`.
This repository (`https://wheetazlab.github.io/cloudflare-zero-trust-operator`) gets new versions until **2027-02-26**; after that it is frozen: versions already here keep installing, new ones are only on OCI.
How to move (Helm, Argo CD, Flux): [Moving to the OCI chart](https://github.com/wheetazlab/cloudflare-zero-trust-operator#moving-to-the-oci-chart).

### Install via Helm (OCI)

```bash
helm install cloudflare-zero-trust-operator oci://ghcr.io/wheetazlab/charts/cloudflare-zero-trust-operator \
  --namespace cloudflare-zero-trust --create-namespace -f my-values.yaml
```

### Source

[github.com/wheetazlab/cloudflare-zero-trust-operator](https://github.com/wheetazlab/cloudflare-zero-trust-operator)
