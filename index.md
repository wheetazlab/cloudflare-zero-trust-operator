## Cloudflare Zero Trust Operator

A Kubernetes operator that manages Cloudflare Zero Trust tunnel routing by watching HTTPRoute resources and reconciling them with the Cloudflare API.

### Install via Helm

```bash
helm repo add wheetazlab https://wheetazlab.github.io/cloudflare-zero-trust-operator
helm repo update
helm install cloudflare-zero-trust-operator wheetazlab/cloudflare-zero-trust-operator \
  --set tenant.create=true \
  --set tenant.instanceName=mycluster \
  --set tenant.accountId=<your-account-id> \
  --set tenant.tunnelId=<your-tunnel-id> \
  --set tenant.apiToken=<your-api-token>
```

### Source

[github.com/wheetazlab/cloudflare-zero-trust-operator](https://github.com/wheetazlab/cloudflare-zero-trust-operator)
