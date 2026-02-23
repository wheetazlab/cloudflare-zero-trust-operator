<!-- markdownlint-disable -->
# Architecture

Complete architecture documentation for the Cloudflare Zero Trust Operator, from build to runtime.

## Table of Contents

- [Overview](#overview)
- [System Architecture](#system-architecture)
- [Three-Tier Architecture](#three-tier-architecture)
- [Build Process](#build-process)
- [Deployment Architecture](#deployment-architecture)
- [Runtime Architecture](#runtime-architecture)
- [Component Details](#component-details)
- [Data Flow](#data-flow)
- [Security Architecture](#security-architecture)

## Overview

The Cloudflare Zero Trust Operator is a Kubernetes-native operator that manages Cloudflare Zero Trust resources (tunnel routes, Access applications, policies, and service tokens) by watching Traefik HTTPRoute annotations.

**Key Design Principles:**

- **Annotation-driven**: Configuration through HTTPRoute annotations
- **Idempotent**: Safe to run repeatedly
- **Multi-tenant**: Support multiple Cloudflare accounts
- **Declarative**: Desired state defined in Kubernetes
- **Ansible-based**: Built with Ansible for simplicity and maintainability

## System Architecture

```mermaid
graph TB
    subgraph "Development"
        SRC[Source Code]
        ANSIBLE[Ansible Playbooks/Roles]
        DOCKER[Dockerfile]
        SRC --> BUILD[docker build]
        ANSIBLE --> BUILD
        DOCKER --> BUILD
        BUILD --> IMG[Container Image]
    end
    
    subgraph "CI/CD Pipeline"
        GH[GitHub Push/Tag]
        GHA[GitHub Actions]
        GH --> GHA
        GHA --> BUILD2[Build Multi-Arch Image]
        BUILD2 --> GHCR[ghcr.io Registry]
    end
    
    subgraph "Kubernetes Cluster"
        CRD[CRDs]
        RBAC[RBAC]
        MGR_DEP[manager Deployment]
        KW_DEP[kube_worker Deployment]
        CW_DEP[cloudflare_worker Deployment]
        
        CRD --> MGR_DEP
        RBAC --> MGR_DEP
        MGR_DEP --> MGR_POD[manager pod<br/>ROLE=manager]
        KW_DEP --> KW_POD[kube_worker pod<br/>ROLE=kube_worker]
        CW_DEP --> CW_POD[cloudflare_worker pod<br/>ROLE=cloudflare_worker]
        
        MGR_POD -.ensures exist.-> KW_DEP
        MGR_POD -.ensures exist.-> CW_DEP
        
        subgraph "Kubernetes Resources"
            TENANT[CloudflareZeroTrustTenant CR]
            IR[HTTPRoute]
            TASK[CloudflareTask CR]
            SECRET[Secrets]
            CFGMAP[State ConfigMaps]
        end
        
        KW_POD --> TENANT
        KW_POD --> IR
        KW_POD --> TASK
        KW_POD --> CFGMAP
        CW_POD --> TASK
    end
    
    subgraph "Cloudflare"
        API[Cloudflare API]
        TUNNEL[Tunnel Config]
        ACCESS[Access Apps/Policies]
        TOKENS[Service Tokens]
        
        CW_POD --> API
        API --> TUNNEL
        API --> ACCESS
        API --> TOKENS
    end
    
    IMG --> GHCR
    GHCR --> MGR_DEP
```

## Build Process

### Container Build Flow

```mermaid
flowchart TD
    START([Start Build]) --> BASE[Pull python:3.11-slim]
    BASE --> DEPS[Install System Dependencies]
    DEPS --> PYREQ[Install Python Packages]
    PYREQ --> ANSREQ[Install Ansible Collections]
    ANSREQ --> COPY[Copy Ansible Content]
    COPY --> SCRIPT[Copy entrypoint.sh]
    SCRIPT --> USER[Create Non-Root User]
    USER --> PERMS[Set Permissions]
    PERMS --> IMG([Container Image])
    
    style START fill:#4CAF50
    style IMG fill:#2196F3
```

### Build Steps Detail

1. **Base Image**: `python:3.11-slim`
   - Minimal Debian-based Python runtime
   - Small attack surface
   - Multi-architecture support

2. **System Dependencies**:
   ```bash
   apt-get install git openssh-client
   ```

3. **Python Dependencies** (`container/requirements.txt`):
   - `ansible>=2.14.0`
   - `ansible-runner>=2.3.0`
   - `kubernetes>=25.0.0`
   - `jmespath` (for JSON parsing)

4. **Ansible Collections**:
   - `kubernetes.core>=2.4.0` (K8s API)
   - `community.general>=6.0.0` (URI modules)
   - `ansible.utils>=2.0.0` (Utilities)

5. **Content Copy**:
   - All Ansible playbooks → `/ansible/playbooks/`
   - All roles → `/ansible/roles/`
   - Configuration → `/ansible/ansible.cfg`
   - Entrypoint script → `/entrypoint.sh`

6. **Security Hardening**:
   - Non-root user (UID 1000)
   - Read-only root filesystem (runtime)
   - Dropped capabilities

### Build Commands

```bash
# Local build
docker build -f container/Dockerfile -t ghcr.io/wheetazlab/cloudflare-zero-trust-operator:latest .

# Multi-arch build (CI/CD)
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  --push \
  -t ghcr.io/wheetazlab/cloudflare-zero-trust-operator:latest
```

## Deployment Architecture

```mermaid
graph TB
    subgraph "Kubernetes Cluster"
        subgraph "cloudflare-zero-trust Namespace"
            SA[ServiceAccount]
            MGR_DEP[manager Deployment]
            KW_DEP[kube_worker Deployment]
            CW_DEP[cloudflare_worker Deployment]
            
            SA --> MGR_DEP
            SA --> KW_DEP
            SA --> CW_DEP
            MGR_DEP --> MGR[manager pod]
            KW_DEP --> KW[kube_worker pod]
            CW_DEP --> CW[cloudflare_worker pod]
            
            MGR -.ensures exist.-> KW_DEP
            MGR -.ensures exist.-> CW_DEP
        end
        
        subgraph "Cluster-Wide"
            CRD1[CloudflareZeroTrustTenant CRD]
            CRD2[CloudflareTask CRD]
            CR1[ClusterRole]
            CRB1[ClusterRoleBinding]
            
            CR1 --> CRB1
            CRB1 --> SA
        end
        
        subgraph "Application Namespaces"
            TENANT1[Tenant CR]
            SEC1[API Token Secret]
            IR1[HTTPRoute 1]
            IR2[HTTPRoute 2]
            IR3[HTTPRoute 3]
            
            TENANT1 -.references.-> SEC1
        end
        
        subgraph "Operator Namespace"
            TASK[CloudflareTask CR]
            CFGMAP[State ConfigMaps]
        end
        
        KW -.lists.-> TENANT1
        KW -.lists.-> IR1
        KW -.lists.-> IR2
        KW -.lists.-> IR3
        KW -.reads.-> SEC1
        KW -.patches.-> IR1
        KW -.patches.-> IR2
        KW -.patches.-> IR3
        KW -.creates/reads.-> TASK
        KW -.reads/writes.-> CFGMAP
        CW -.claims/completes.-> TASK
    end
    
    style CRD1 fill:#E91E63
    style CRD2 fill:#E91E63
    style CR1 fill:#E91E63
    style CRB1 fill:#E91E63
    style MGR fill:#4CAF50
    style KW fill:#2196F3
    style CW fill:#FF9800
```

### Deployment Components

#### 1. Custom Resource Definition (CRD)

```yaml
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: cloudflarezerotrusttenants.cfzt.cloudflare.com
spec:
  group: cfzt.cloudflare.com
  scope: Namespaced
  names:
    kind: CloudflareZeroTrustTenant
    plural: cloudflarezerotrusttenants
    shortNames: [cfzt, cfzttenant]
```

**Purpose**: Defines the schema for tenant configuration resources (one per Cloudflare account)

**Second CRD**:

```yaml
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: cloudflarezerotrustoperatorconfigs.cfzt.cloudflare.com
spec:
  group: cfzt.cloudflare.com
  scope: Namespaced
  names:
    kind: CloudflareZeroTrustOperatorConfig
    plural: cloudflarezerotrustoperatorconfigs
    shortNames: [cfztconfig, operatorconfig]
```

**Purpose**: Configures operator pod scheduling, resources, and behavior (singleton per cluster)

#### 2. RBAC Configuration

```mermaid
graph LR
    SA[ServiceAccount] --> CRB[ClusterRoleBinding]
    CRB --> CR[ClusterRole]
    
    subgraph "Permissions"
        CR --> P1[Read/Write: CloudflareZeroTrustTenant]
        CR --> P1B[Read/Write: OperatorConfig]
        CR --> P2[Read/Write/Patch: HTTPRoute]
        CR --> P3[Read: Secrets]
        CR --> P4[Create/Update: Secrets]
        CR --> P5[Create: Events]
        CR --> P6[Update: Own Deployment]
    end
```

**ClusterRole Permissions**:
- CloudflareZeroTrustTenant: get, list, watch, update status
- CloudflareZeroTrustOperatorConfig: get, list, watch, update status (for self-configuration)
- HTTPRoute: get, list, watch, patch, update
- Secrets: get, list, watch, create, update, delete
- ConfigMaps: get, list, watch, create, update, patch, delete (for state tracking)
- Deployments: get, list, patch, update (restricted to operator's own deployment)
- Events: create, patch

#### 3. Operator Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cloudflare-zero-trust-operator
  namespace: cloudflare-zero-trust
spec:
  replicas: 1  # Single instance (leader election not implemented)
  selector:
    matchLabels:
      app: cloudflare-zero-trust-operator
  template:
    spec:
      serviceAccountName: cloudflare-zero-trust-operator
      containers:
      - name: operator
        image: ghcr.io/wheetazlab/cloudflare-zero-trust-operator:latest
        env:
        - name: WATCH_NAMESPACES
          value: ""  # Watch all namespaces
        - name: POLL_INTERVAL_SECONDS
          value: "60"
        - name: LOG_LEVEL
          value: "INFO"
```

**Configuration Options**:
- `WATCH_NAMESPACES`: Comma-separated list or empty for all
- `POLL_INTERVAL_SECONDS`: How often to reconcile (default: 60)
- `LOG_LEVEL`: Global log level - DEBUG, INFO, WARNING, ERROR (can be overridden per-tenant in CR)
- `CLOUDFLARE_API_BASE`: API endpoint (default: https://api.cloudflare.com/client/v4)
- `OPERATOR_NAMESPACE`: Namespace where operator runs and stores state ConfigMaps (default: cloudflare-zero-trust)

**Per-Tenant Configuration** (in CloudflareZeroTrustTenant CR):
- `spec.logLevel`: Override global log level for this tenant's reconciliation
- `spec.defaults.sessionDuration`: Default Access Application session duration
- `spec.defaults.originService`: Default origin service URL (auto-detects HTTP/HTTPS from URL scheme)
- `spec.defaults.httpRedirect`: Automatically redirect HTTP to HTTPS at Cloudflare edge (default: true)
- `spec.defaults.originTLS`: TLS configuration for HTTPS origin connections
  - `noTLSVerify`: Skip TLS certificate verification (default: false) - useful for self-signed certificates
  - `originServerName`: Custom SNI hostname for TLS handshake (optional)
  - `caPool`: Path to CA certificate file for validation (optional)
  - `tlsTimeout`: TLS handshake timeout in seconds, 1-300 (default: 10)
  - `http2Origin`: Use HTTP/2 for origin connection (default: false) - useful for gRPC backends
  - `matchSNIToHost`: Match SNI to Host header automatically (default: false)

**Note**: TLS settings can be overridden per-HTTPRoute using annotations (e.g., `cfzt.cloudflare.com/no-tls-verify`, `cfzt.cloudflare.com/tls-timeout`, etc.)

**Operator Pod Configuration** (via CloudflareZeroTrustOperatorConfig CR):
- Dynamically controls operator pod scheduling and resources without redeployment
- **Singleton**: Only one OperatorConfig should exist in the operator namespace
- Applied during each reconciliation loop

Available configuration:
- `spec.replicas`: Number of operator replicas (default: 1, recommended to keep at 1)
- `spec.resources.requests/limits`: CPU and memory resources
- `spec.affinity`: Pod affinity and anti-affinity rules for node placement
- `spec.nodeSelector`: Node selector labels for pod placement
- `spec.tolerations`: Tolerations for node taints
- `spec.priorityClassName`: Priority class for pod scheduling
- `spec.imagePullPolicy`: Image pull policy (Always, IfNotPresent, Never)
- `spec.environmentVariables`: Override poll interval, log level, watch namespaces
- `spec.podLabels`: Additional labels for operator pod
- `spec.podAnnotations`: Additional annotations for operator pod

**How it works**:
1. Operator watches its own OperatorConfig CR during reconciliation
2. If OperatorConfig changes (generation increments), operator updates its own Deployment
3. Kubernetes rolls out the updated Deployment
4. Operator updates OperatorConfig status with applied generation and readiness

Example usage:
```yaml
apiVersion: cfzt.cloudflare.com/v1alpha1
kind: CloudflareZeroTrustOperatorConfig
metadata:
  name: operator-config
  namespace: cloudflare-zero-trust
spec:
  replicas: 1
  resources:
    requests:
      cpu: "200m"
      memory: "512Mi"
    limits:
      cpu: "1000m"
      memory: "1Gi"
  nodeSelector:
    node-role.kubernetes.io/infra: ""
  tolerations:
    - key: "dedicated"
      operator: "Equal"
      value: "infrastructure"
      effect: "NoSchedule"
```

## Three-Tier Architecture

The operator runs as **three separate Deployments**, each handling a distinct concern. All three use the same container image but switch behaviour based on the `ROLE` environment variable.

```
ROLE=manager
  └─▶ operator_config role  (syncs OperatorConfig CR → own Deployment)
  └─▶ ensures kube_worker   Deployment exists
  └─▶ ensures cloudflare_worker Deployment exists

ROLE=kube_worker
  └─▶ kube_worker role      (reads K8s; creates CloudflareTask CRs)

ROLE=cloudflare_worker
  └─▶ cloudflare_worker role (claims tasks; calls Cloudflare API)
```

### Tier diagram

```mermaid
graph TD
    subgraph "Tier 1 — Manager"
        MGR[manager pod<br/>ROLE=manager]
        MGR -->|watches| OC[CloudflareZeroTrustOperatorConfig CR]
        MGR -->|patches| SELF[own Deployment]
        MGR -->|ensures exist| KW_DEP[kube_worker Deployment]
        MGR -->|ensures exist| CW_DEP[cloudflare_worker Deployment]
    end

    subgraph "Tier 2 — Kubernetes worker"
        KW[kube_worker pod<br/>ROLE=kube_worker]
        KW -->|lists| TENANTS[CloudflareZeroTrustTenant CRs]
        KW -->|lists| HR[HTTPRoutes]
        KW -->|reads| SECRETS[API token Secrets]
        KW -->|reads/writes| CM[State ConfigMaps<br/>cfzt-namespace-name]
        KW -->|creates| TASK[CloudflareTask CR<br/>phase: Pending]
        KW -->|reads completed tasks| TASK
        KW -->|writes IDs back| HR
    end

    subgraph "Tier 3 — Cloudflare worker"
        CW[cloudflare_worker pod<br/>ROLE=cloudflare_worker]
        CW -->|claims| TASK
        CW -->|calls| CFAPI[Cloudflare REST API]
        CFAPI --> TUNNEL[Tunnel ingress rule]
        CFAPI --> DNS[DNS CNAME / A record]
        CFAPI --> ACCESS[Access Application + Policy]
        CFAPI --> TOKEN[Service Token]
        CW -->|writes result IDs| TASK
    end

    KW_DEP -.spawns.-> KW
    CW_DEP -.spawns.-> CW
```

### CloudflareTask CRD — the decoupling mechanism

`CloudflareTask` is an internal work-queue CR. It decouples the Kubernetes-watching concern (Tier 2) from the Cloudflare API calling concern (Tier 3).

**Lifecycle**:

```
Created (no status)
    │
    ▼
Pending          ← kube_worker sets this after creation
    │
    ▼
InProgress       ← cloudflare_worker claims task, writes its pod name
    │
    ├──▶ Completed  ← result IDs stored in status; kube_worker writes back to HTTPRoute
    └──▶ Failed     ← error message in status; kube_worker retries next cycle
```

**Change detection** (kube_worker):
1. SHA256 hash of all `cfzt.cloudflare.com/*` annotations on an HTTPRoute
2. Compare against hash stored in state ConfigMap `cfzt-{namespace}-{name}`
3. If match → skip (no changes, no new task created)
4. If mismatch or ConfigMap absent → create a new `CloudflareTask`

### Environment variables by role

| Variable | manager | kube_worker | cloudflare_worker |
|---|---|---|---|
| `ROLE` | `manager` | `kube_worker` | `cloudflare_worker` |
| `OPERATOR_NAMESPACE` | ✅ | ✅ | ✅ |
| `POD_NAME` | ✅ | — | ✅ (claim identity) |
| `WATCH_NAMESPACES` | — | ✅ | — |
| `POLL_INTERVAL_SECONDS` | ✅ | ✅ | ✅ |
| `LOG_LEVEL` | ✅ | ✅ | ✅ |
| `CLOUDFLARE_API_BASE` | — | ✅ | ✅ |

---

## Runtime Architecture

### Three-pod runtime flow

```mermaid
sequenceDiagram
    participant MGR as manager pod
    participant KW as kube_worker pod
    participant CW as cloudflare_worker pod
    participant K8s as Kubernetes API
    participant CFAPI as Cloudflare API

    loop Every POLL_INTERVAL_SECONDS (manager)
        MGR->>K8s: Get OperatorConfig CR
        MGR->>K8s: Patch own Deployment if config changed
        MGR->>K8s: Ensure kube_worker Deployment exists
        MGR->>K8s: Ensure cloudflare_worker Deployment exists
    end

    loop Every POLL_INTERVAL_SECONDS (kube_worker)
        KW->>K8s: List CloudflareZeroTrustTenant CRs
        KW->>K8s: List HTTPRoutes (filtered by cfzt/enabled)
        KW->>K8s: Read state ConfigMaps (annotation hashes)
        KW->>K8s: Create CloudflareTask CRs for changed HTTPRoutes
        KW->>K8s: Read Completed CloudflareTask CRs
        KW->>K8s: Write Cloudflare IDs back to HTTPRoute annotations
        KW->>K8s: Delete processed tasks + cleanup orphaned ConfigMaps
    end

    loop Every POLL_INTERVAL_SECONDS (cloudflare_worker)
        CW->>K8s: List Pending CloudflareTask CRs
        CW->>K8s: Claim task (patch phase → InProgress)
        CW->>CFAPI: Write tunnel hostname route
        CW->>CFAPI: Create CNAME / A DNS record
        CW->>CFAPI: Create Access Application
        CW->>CFAPI: Attach policy / create service token
        CW->>K8s: Patch task phase → Completed (with result IDs)
    end
```

### Container Runtime Flow

### Entrypoint Script Responsibilities

```bash
#!/bin/bash
# container/entrypoint.sh

# 1. Display startup banner
echo "Cloudflare Zero Trust Operator"

# 2. Set default environment variables
export POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-60}"
export WATCH_NAMESPACES="${WATCH_NAMESPACES:-}"
export LOG_LEVEL="${LOG_LEVEL:-INFO}"
export OPERATOR_NAMESPACE="${OPERATOR_NAMESPACE:-cloudflare-zero-trust}"

# 3. Configure Ansible environment with colored output
export ANSIBLE_CONFIG="/ansible/ansible.cfg"
export ANSIBLE_FORCE_COLOR="true"
export ANSIBLE_NOCOLOR="false"
export ANSIBLE_STDOUT_CALLBACK="default"
export ANSIBLE_STDOUT_CALLBACK_COLORS="bright"
export ANSIBLE_DIFF_ALWAYS="True"

# 4. Set Ansible verbosity based on LOG_LEVEL
case "${LOG_LEVEL}" in
    DEBUG)
        export ANSIBLE_VERBOSITY=2
        export ANSIBLE_DEBUG="True"
        ;;
    INFO) export ANSIBLE_VERBOSITY=1 ;;
    *) export ANSIBLE_VERBOSITY=0 ;;
esac

# 5. Main reconciliation loop
while true; do
    ansible-playbook /ansible/playbooks/reconcile.yml
    sleep "${POLL_INTERVAL_SECONDS}"
done
```

**Log Output Features**:
- **Colored output**: ANSI color codes enabled for better readability in container logs
- **Callback plugin**: Uses "default" callback with bright colors for task status
- **Per-tenant verbosity**: Can override global LOG_LEVEL in CloudflareZeroTrustTenant CR
- **Diff output**: Shows changes when updating resources

### Pod Resource Usage

```mermaid
graph LR
    subgraph "Operator Pod Resources"
        CPU[CPU]
        MEM[Memory]
        FS[Filesystem]
        
        subgraph "Requests"
            CPU_REQ[100m]
            MEM_REQ[256Mi]
        end
        
        subgraph "Limits"
            CPU_LIM[500m]
            MEM_LIM[512Mi]
        end
        
        subgraph "Volumes"
            TMP[tmp - emptyDir]
            RUNNER[runner - emptyDir]
        end
    end
    
    CPU --> CPU_REQ
    CPU --> CPU_LIM
    MEM --> MEM_REQ
    MEM --> MEM_LIM
    FS --> TMP
    FS --> RUNNER
```

**Resource Profile**:
- **CPU**: 100m request, 500m limit (0.1 - 0.5 cores)
- **Memory**: 256Mi request, 512Mi limit
- **Storage**: EmptyDir volumes (ephemeral)
- **Read-only root filesystem**: Yes
- **Run as non-root**: Yes (UID 1000)

## Component Details

### 1. Ansible Playbook Structure

```
ansible/
├── playbooks/
│   └── reconcile.yml              # Role dispatcher (reads ROLE env var)
├── roles/
│   ├── operator_config/           # Self-manage operator Deployment; create worker Deployments
│   ├── kube_worker/               # K8s state manager; creates CloudflareTask CRs
│   ├── cloudflare_worker/         # Claims CloudflareTask CRs; calls Cloudflare API
│   └── cloudflare_api/            # Library: individual Cloudflare REST API operations
├── ansible.cfg                    # Ansible configuration
├── inventory                      # Localhost inventory
└── requirements.yml               # Collection dependencies
```

### 2. Kubernetes API Interaction

```mermaid
graph TB
    subgraph "Operator Pod"
        CODE[Ansible kubernetes.core]
    end
    
    subgraph "Kubernetes API Server"
        API[kube-apiserver]
    end
    
    subgraph "Authentication"
        SA_TOKEN[ServiceAccount Token]
        SA_CA[CA Certificate]
    end
    
    CODE -. reads .-> SA_TOKEN
    CODE -. reads .-> SA_CA
    CODE -->|HTTPS + Token Auth| API
    API -->|List/Watch/Patch| RESOURCES[K8s Resources]
    
    SA_TOKEN -. mounted at .-> TOKEN_PATH[serviceaccount/token]
    SA_CA -. mounted at .-> CA_PATH[serviceaccount/ca.crt]
```

**Authentication Method**:
- ServiceAccount token automatically mounted by Kubernetes
- Token used by `kubernetes.core` collection
- TLS verification using cluster CA certificate

### 3. Cloudflare API Interaction

```mermaid
sequenceDiagram
    participant CW as cloudflare_worker
    participant K8s as Kubernetes API
    participant Secret as API Token Secret
    participant CF as Cloudflare API
    
    CW->>K8s: Claim CloudflareTask CR (phase → InProgress)
    K8s-->>CW: CloudflareTask spec (hostname, operations, credentialRef)
    
    CW->>K8s: Get Secret (credentialRef.name)
    K8s-->>CW: Secret with API token
    
    CW->>CW: Extract & decode token
    
    loop For each operation in CloudflareTask.spec.operations
        CW->>CF: HTTPS + Bearer Token
        CF-->>CW: JSON Response
        
        alt API Error (429 Rate Limit)
            CW->>CW: Exponential backoff
            CW->>CF: Retry request
        else API Error (Other)
            CW->>CW: Rescue block catches error
            CW->>K8s: Patch task phase → Failed (error message)
        else Success
            CW->>CW: Collect result IDs
        end
    end
    
    CW->>K8s: Patch task phase → Completed (result IDs in status)
```

**API Interaction Pattern**:
- Bearer token authentication
- Retry logic with exponential backoff (3 retries, 5s delay)
- Rate limit handling
- Error propagation to Tenant status

## Data Flow

### Complete Reconciliation Flow

```mermaid
flowchart TD
    subgraph KW["kube_worker loop (every POLL_INTERVAL_SECONDS)"]
        KW_START([kube_worker wakes]) --> COLLECT[collect_results.yml<br/>Completed/Failed tasks → patch HTTPRoutes → delete tasks]
        COLLECT --> LIST_T[list_tenants.yml<br/>fetch CloudflareZeroTrustTenant CRs]
        LIST_T --> LIST_HR[list_httproutes.yml<br/>fetch HTTPRoutes with cfzt/enabled=true]
        LIST_HR --> TENANT_LOOP{For Each Tenant}
        TENANT_LOOP -->|next| RECONCILE[reconcile_tenant.yml × each HTTPRoute]
        RECONCILE --> CHECK[check_state.yml<br/>compare annotation SHA256 to ConfigMap hash]
        CHECK -->|no change| SKIP[skip — no task created]
        CHECK -->|changed or new| CREATE_TASK[create_task.yml<br/>build + apply CloudflareTask CR<br/>phase: Pending]
        SKIP --> TENANT_LOOP
        CREATE_TASK --> TENANT_LOOP
        TENANT_LOOP -->|done| CLEANUP[cleanup_orphaned.yml]
        CLEANUP --> KW_SLEEP[sleep]
        KW_SLEEP --> KW_START
    end

    subgraph CW["cloudflare_worker loop (every POLL_INTERVAL_SECONDS)"]
        CW_START([cloudflare_worker wakes]) --> FIND_TASKS[List Pending CloudflareTask CRs]
        FIND_TASKS --> CLAIM[Claim task — patch phase → InProgress]
        CLAIM --> EXEC[execute_task.yml<br/>call Cloudflare API operations]
        EXEC -->|all ok| COMPLETE[patch phase → Completed<br/>result IDs in status]
        EXEC -->|any error| FAILED[patch phase → Failed<br/>error message in status]
        COMPLETE --> CW_SLEEP[sleep]
        FAILED --> CW_SLEEP
        CW_SLEEP --> CW_START
    end

    CREATE_TASK -.CloudflareTask CR.-> FIND_TASKS
    COMPLETE -.Completed task.-> COLLECT

    style KW_START fill:#2196F3
    style CW_START fill:#FF9800
    style CREATE_TASK fill:#4CAF50
    style COMPLETE fill:#4CAF50
    style FAILED fill:#E53935
```

### State Management

```mermaid
graph TB
    subgraph "State ConfigMap cfzt-namespace-name"
        CM1[annotation_hash: sha256 of cfzt annotations]
        CM2[cloudflare_ids: JSON map of resource IDs]
        CM3[last_sync_time: ISO timestamp]
    end

    subgraph "HTTPRoute Annotations"
        A1[cfzt.cloudflare.com/enabled: true — user]
        A2[cfzt.cloudflare.com/hostname: app.example.com — user]
        A3[cfzt.cloudflare.com/hostnameRouteId — operator]
        A4[cfzt.cloudflare.com/accessAppId — operator]
        A5[cfzt.cloudflare.com/accessPolicyIds — operator]
        A6[cfzt.cloudflare.com/serviceTokenId — operator]
    end

    subgraph "kube_worker"
        KW_CHECK[check_state.yml]
        KW_PROC[process_completed_task.yml]
    end

    subgraph "cloudflare_worker"
        CW_EXEC[execute_task.yml]
    end

    KW_CHECK -->|reads annotation hash| CM1
    KW_CHECK -->|writes updated hash| CM1
    KW_CHECK -->|reads desired state| A1
    KW_CHECK -->|reads desired state| A2
    CW_EXEC -->|returns IDs via CloudflareTask status| KW_PROC
    KW_PROC -->|patches result IDs| A3
    KW_PROC -->|patches result IDs| A4
    KW_PROC -->|patches result IDs| A5
    KW_PROC -->|patches result IDs| A6
    KW_PROC -->|writes IDs| CM2
```

**State Tracking Strategy**:
- **State ConfigMap** (`cfzt-{namespace}-{name}`): Primary change-detection store — holds SHA256 annotation hash and Cloudflare resource IDs
- **User annotations**: Define desired state (`enabled`, `hostname`, `template`, etc.)
- **Operator annotations**: Result IDs written back after `cloudflare_worker` completes a task
- **Idempotency**: Stored IDs used to PATCH existing resources instead of creating duplicates
- **Deletion**: Stored IDs used to clean up Cloudflare resources when HTTPRoute is deleted

## Security Architecture

### Secrets Management

```mermaid
graph TB
    subgraph "Input Secrets"
        USER_SECRET[Cloudflare API Token Secret]
        USER_SECRET -.contains.-> API_TOKEN[token: xxxxxxxx]
    end
    
    subgraph "Operator Pod"
        OP[Operator Process]
        OP -.reads via K8s API.-> USER_SECRET
        OP -.never logs.-> API_TOKEN
        OP -.creates.-> GEN_SECRETS
    end
    
    subgraph "Generated Secrets"
        GEN_SECRETS[Service Token Secrets]
        GEN_SECRETS -.contains.-> CLIENT_ID[client_id: xxxx]
        GEN_SECRETS -.contains.-> CLIENT_SECRET[client_secret: xxxx]
    end
    
    subgraph "Applications"
        APP[Your Application Pods]
        APP -.reads.-> GEN_SECRETS
    end
    
    style USER_SECRET fill:#E91E63
    style GEN_SECRETS fill:#E91E63
    style API_TOKEN fill:#E53935
    style CLIENT_SECRET fill:#E53935
```

**Security Boundaries**:

1. **API Token Secret** (User-provided):
   - Contains Cloudflare API token
   - Referenced by CloudflareZeroTrustTenant CR
   - Read by operator via Kubernetes API
   - Never logged or exposed

2. **Service Token Secrets** (Operator-generated):
   - Created when `serviceToken: true`
   - Contains `client_id` and `client_secret`
   - Named: `{httproute-name}-cfzt-service-token`
   - Used by applications for machine-to-machine auth

3. **Annotations** (Public metadata):
   - Only store resource IDs, never credentials
   - Visible to anyone with HTTPRoute read access

### RBAC Security Model

```mermaid
graph TB
    subgraph "ServiceAccount Permissions"
        SA[cloudflare-zero-trust-operator SA]
    end

    subgraph "Can Read"
        R1[CloudflareZeroTrustTenant]
        R2[CloudflareZeroTrustOperatorConfig]
        R3[HTTPRoute]
        R4[Secrets - referenced by tenant]
        R5[Deployments - own only]
    end

    subgraph "Can Write"
        W1[CloudflareZeroTrustTenant status]
        W2[CloudflareTask CRs - create/patch/delete]
        W3[HTTPRoute annotations]
        W4[Service Token Secrets]
        W5[Events]
        W6[ConfigMaps - State Tracking]
        W7[Own Deployment - patch - manager only]
    end

    subgraph "Cannot Access"
        X1[Other Secrets - not referenced by tenant]
        X2[Other Deployments]
        X3[Other Resources]
    end

    SA --> R1
    SA --> R2
    SA --> R3
    SA --> R4
    SA --> R5
    SA --> W1
    SA --> W2
    SA --> W3
    SA --> W4
    SA --> W5
    SA --> W6
    SA --> W7

    style X1 fill:#E53935
    style X2 fill:#E53935
    style X3 fill:#E53935
```

**Principle of Least Privilege**:
- Operator only has permissions for resources it manages
- Cannot read arbitrary secrets (only those referenced)
- Cannot modify other workloads
- No cluster-admin privileges required

### Container Security

```yaml
securityContext:
  # Pod-level
  runAsNonRoot: true
  fsGroup: 1000
  seccompProfile:
    type: RuntimeDefault
  
  # Container-level
  allowPrivilegeEscalation: false
  runAsUser: 1000
  capabilities:
    drop:
      - ALL
  readOnlyRootFilesystem: true
```

**Security Hardening**:
- Non-root user (UID 1000)
- Read-only root filesystem (writable volumes: /tmp, /runner)
- All capabilities dropped
- No privilege escalation
- Seccomp profile enabled

### Network Security

```mermaid
graph LR
    subgraph "Operator Pod"
        OP[Operator Process]
    end
    
    subgraph "Allowed Connections"
        K8S[Kubernetes API Server<br/>HTTPS:6443]
        CF[Cloudflare API<br/>HTTPS:443]
    end
    
    subgraph "Blocked"
        OTHER[Other Services]
    end
    
    OP -->|TLS 1.2+| K8S
    OP -->|TLS 1.2+| CF
    OP -.-x|No Access| OTHER
    
    style OTHER fill:#E53935
```

**Network Policy Recommendations**:
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: cloudflare-zero-trust-operator
spec:
  podSelector:
    matchLabels:
      app: cloudflare-zero-trust-operator
  policyTypes:
  - Egress
  egress:
  - to:
    - namespaceSelector: {}  # kube-system for API server
    ports:
    - protocol: TCP
      port: 6443  # Kubernetes API
  - to:
    - namespaceSelector: {}
    ports:
    - protocol: TCP
      port: 53  # DNS
  - to: []  # Allow to internet for Cloudflare API
    ports:
    - protocol: TCP
      port: 443  # HTTPS
```

## Performance & Scalability

### Resource Scaling

| Metric | Single Tenant | 10 Tenants | 100 Tenants |
|--------|---------------|------------|-------------|
| Memory | ~100MB | ~200MB | ~400MB |
| CPU | ~50m | ~100m | ~200m |
| Reconciliation Time | 5-10s | 30-60s | 5-10min |

**Scaling Considerations**:
- Operator runs as single replica (no leader election)
- Reconciliation is sequential per tenant
- Cloudflare API rate limits apply
- Consider increasing `POLL_INTERVAL_SECONDS` for large deployments

### Optimization Strategies

```mermaid
graph TB
    OPT[Optimization Strategies]
    
    OPT --> O1[Increase Poll Interval]
    OPT --> O2[Selective Namespace Watching]
    OPT --> O3[Resource Requests/Limits Tuning]
    OPT --> O4[Parallel Reconciliation]
    
    O1 -.-> E1[Reduce API calls<br/>Trade: Higher staleness]
    O2 -.-> E2[Watch specific namespaces<br/>Reduce processing overhead]
    O3 -.-> E3[Right-size pod resources<br/>Avoid OOM/throttling]
    O4 -.-> E4[Future: Async reconciliation<br/>Faster for many tenants]
```

## Troubleshooting Architecture

### Logging Flow

```mermaid
graph LR
    subgraph "Operator Pod"
        ANSIBLE[Ansible Playbook]
        STDOUT[stdout/stderr]
    end
    
    subgraph "Kubernetes"
        LOGS[Pod Logs]
        EVENTS[Events API]
    end
    
    subgraph "Observability"
        KUBECTL[kubectl logs]
        STERN[stern]
        LENS[Lens/K9s]
    end
    
    ANSIBLE --> STDOUT
    STDOUT --> LOGS
    ANSIBLE -.creates.-> EVENTS
    
    LOGS --> KUBECTL
    LOGS --> STERN
    LOGS --> LENS
    EVENTS --> KUBECTL
    EVENTS --> LENS
```

**Log Levels**:
- `DEBUG`: All Ansible task details (ANSIBLE_VERBOSITY=2)
- `INFO`: High-level reconciliation events (ANSIBLE_VERBOSITY=1)
- `WARNING/ERROR`: Only errors (ANSIBLE_VERBOSITY=0)

### Health Check Points

```mermaid
graph TB
    START([Health Check]) --> CHECK1{CRD Installed?}
    CHECK1 -->|No| FAIL1[FAIL: Install CRD]
    CHECK1 -->|Yes| CHECK2{Deployment Ready?}
    
    CHECK2 -->|No| FAIL2[FAIL: Check pod status]
    CHECK2 -->|Yes| CHECK3{Tenants Exist?}
    
    CHECK3 -->|No| WARN1[WARN: No tenants configured]
    CHECK3 -->|Yes| CHECK4{Recent Errors in Logs?}
    
    CHECK4 -->|Yes| WARN2[WARN: Review logs]
    CHECK4 -->|No| SUCCESS[SUCCESS: Healthy]
    
    WARN1 --> SUCCESS
    WARN2 --> SUCCESS
    
    style FAIL1 fill:#E53935
    style FAIL2 fill:#E53935
    style WARN1 fill:#E91E63
    style WARN2 fill:#E91E63
    style SUCCESS fill:#4CAF50
```

## Summary

The Cloudflare Zero Trust Operator follows a straightforward architecture:

1. **Build**: Container with Ansible + Python dependencies
2. **Deploy**: Kubernetes Deployment with RBAC
3. **Runtime**: Continuous reconciliation loop watching HTTPRoutes
4. **Integrate**: Call Cloudflare APIs to create/update/delete resources
5. **Track**: Store state in HTTPRoute annotations

The entire system is designed for simplicity, maintainability, and GitOps workflows.
