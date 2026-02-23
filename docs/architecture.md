<!-- markdownlint-disable -->
# Architecture

Complete architecture documentation for the Cloudflare Zero Trust Operator, from build to runtime.

## Table of Contents

- [Overview](#overview)
- [System Architecture](#system-architecture)
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
        DEPLOY[Deployment]
        POD[Operator Pod]
        
        CRD --> DEPLOY
        RBAC --> DEPLOY
        DEPLOY --> POD
        
        subgraph "Operator Pod"
            ENTRY[entrypoint.sh]
            LOOP[Reconciliation Loop]
            PB[Ansible Playbooks]
            
            ENTRY --> LOOP
            LOOP --> PB
        end
        
        subgraph "Kubernetes Resources"
            TENANT[CloudflareZeroTrustTenant CR]
            IR[HTTPRoute]
            SECRET[Secrets]
        end
        
        POD --> TENANT
        POD --> IR
        POD --> SECRET
    end
    
    subgraph "Cloudflare"
        API[Cloudflare API]
        TUNNEL[Tunnel Config]
        ACCESS[Access Apps/Policies]
        TOKENS[Service Tokens]
        
        POD --> API
        API --> TUNNEL
        API --> ACCESS
        API --> TOKENS
    end
    
    IMG --> GHCR
    GHCR --> DEPLOY
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
            CM[ConfigMap]
            DEP[Deployment]
            POD1[Operator Pod]
            
            SA --> DEP
            CM --> DEP
            DEP --> POD1
        end
        
        subgraph "Cluster-Wide"
            CRD[CloudflareZeroTrustTenant CRD]
            CR1[ClusterRole]
            CRB1[ClusterRoleBinding]
            
            CRD -.defines.-> TENANT1
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
        
        POD1 -.watches.-> TENANT1
        POD1 -.watches.-> IR1
        POD1 -.watches.-> IR2
        POD1 -.watches.-> IR3
        POD1 -.reads.-> SEC1
        POD1 -.patches.-> IR1
        POD1 -.patches.-> IR2
        POD1 -.patches.-> IR3
        POD1 -.updates status.-> TENANT1
    end
    
    style CRD fill:#E91E63
    style CR1 fill:#E91E63
    style CRB1 fill:#E91E63
    style POD1 fill:#4CAF50
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

## Runtime Architecture

### Container Runtime Flow

```mermaid
sequenceDiagram
    participant K8s as Kubernetes
    participant Pod as Operator Pod
    participant Entry as entrypoint.sh
    participant PollLoop as Reconciliation Loop
    participant Ansible as Ansible Playbook
    
    K8s->>Pod: Start Container
    Pod->>Entry: Execute entrypoint.sh
    Entry->>Entry: Set Environment Variables
    Entry->>Entry: Configure Ansible
    Entry->>PollLoop: Start Infinite Loop
    
    loop Every POLL_INTERVAL_SECONDS
        PollLoop->>Ansible: ansible-playbook reconcile.yml
        Ansible->>Ansible: List Tenants
        Ansible->>Ansible: List HTTPRoutes
        Ansible->>Ansible: Reconcile Each Tenant
        Ansible-->>PollLoop: Return (success/failure)
        PollLoop->>PollLoop: Log Result
        PollLoop->>PollLoop: Sleep POLL_INTERVAL_SECONDS
    end
    
    Note over PollLoop: Continues until SIGTERM/SIGINT
```

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
│   └── reconcile.yml          # Main entry point
├── roles/
│   ├── reconciliation_loop/   # Continuous loop wrapper
│   ├── k8s_watch/             # Kubernetes resource discovery
│   ├── tenant_reconcile/      # Per-tenant orchestration
│   └── cloudflare_api/        # Cloudflare API interactions
├── ansible.cfg                # Ansible configuration
├── inventory                  # Localhost inventory
└── requirements.yml           # Collection dependencies
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
    participant Operator
    participant K8s as Kubernetes API
    participant Secret as API Token Secret
    participant CF as Cloudflare API
    
    Operator->>K8s: Get CloudflareZeroTrustTenant
    K8s-->>Operator: Tenant with credentialRef
    
    Operator->>K8s: Get Secret (credentialRef.name)
    K8s-->>Operator: Secret with API token
    
    Operator->>Operator: Extract & decode token
    
    loop For each Cloudflare operation
        Operator->>CF: HTTPS + Bearer Token
        CF-->>Operator: JSON Response
        
        alt API Error (429 Rate Limit)
            Operator->>Operator: Exponential backoff
            Operator->>CF: Retry request
        else API Error (Other)
            Operator->>Operator: Log error
            Operator->>K8s: Update Tenant status (Error condition)
        else Success
            Operator->>Operator: Process response
        end
    end
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
    START([Reconciliation Triggered]) --> LIST_TENANTS[List CloudflareZeroTrustTenant CRs]
    LIST_TENANTS --> LIST_IR[List HTTPRoutes with cfzt.cloudflare.com/enabled=true]
    
    LIST_IR --> TENANT_LOOP{For Each Tenant}
    
    TENANT_LOOP -->|Next Tenant| GET_CREDS[Get API Token from Secret]
    TENANT_LOOP -->|Done| UPDATE_STATUS[Update All Tenant Statuses]
    
    GET_CREDS --> FILTER_IR[Filter HTTPRoutes for This Tenant]
    
    FILTER_IR --> IR_LOOP{For Each HTTPRoute}
    
    IR_LOOP -->|Next IR| PARSE_ANNO[Parse Annotations]
    IR_LOOP -->|Done| TENANT_LOOP
    
    PARSE_ANNO --> HOSTNAME[Create/Update Hostname Route]
    HOSTNAME --> ACCESS_CHECK{accessApp=true?}
    
    ACCESS_CHECK -->|Yes| CREATE_APP[Create/Update Access App]
    CREATE_APP --> CREATE_POLICY[Create/Update Access Policy]
    CREATE_POLICY --> TOKEN_CHECK{serviceToken=true?}
    
    ACCESS_CHECK -->|No| TOKEN_CHECK
    
    TOKEN_CHECK -->|Yes| CREATE_TOKEN[Create Service Token]
    CREATE_TOKEN --> CREATE_SECRET[Create K8s Secret with Token]
    CREATE_SECRET --> PATCH_IR[Patch HTTPRoute Annotations]
    
    TOKEN_CHECK -->|No| PATCH_IR
    
    PATCH_IR --> INCREMENT[Increment Counters]
    INCREMENT --> IR_LOOP
    
    UPDATE_STATUS --> SLEEP[Sleep POLL_INTERVAL_SECONDS]
    SLEEP --> START
    
    style START fill:#4CAF50
    style SLEEP fill:#E91E63
```

### State Management

```mermaid
graph TB
    subgraph "HTTPRoute Annotations (State Storage)"
        A1[cfzt.cloudflare.com/enabled: 'true']
        A2[cfzt.cloudflare.com/hostname: 'app.example.com']
        A3[cfzt.cloudflare.com/hostnameRouteId: 'tunnel-id']
        A4[cfzt.cloudflare.com/accessAppId: 'app-uuid']
        A5[cfzt.cloudflare.com/accessPolicyIds: 'policy-uuid']
        A6[cfzt.cloudflare.com/serviceTokenId: 'token-uuid']
        A7[cfzt.cloudflare.com/serviceTokenSecretName: 'app-cfzt-token']
        A8[cfzt.cloudflare.com/lastReconcile: '2026-02-18T10:00:00Z']
    end
    
    subgraph "User-Provided"
        UP[A1, A2]
    end
    
    subgraph "Operator-Managed"
        OM[A3, A4, A5, A6, A7, A8]
    end
    
    UP -.input.-> OPERATOR[Operator]
    OPERATOR -.updates.-> OM
    OM -.used for.-> UPDATE[Updates/Deletions]
```

**State Tracking Strategy**:
- **User annotations**: Define desired state (enabled, hostname, accessApp, etc.)
- **Operator annotations**: Track Cloudflare resource IDs for updates/deletions
- **Idempotency**: Use stored IDs to update existing resources instead of creating duplicates
- **Deletion**: Use stored IDs to clean up Cloudflare resources when HTTPRoute is deleted

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
        R2[HTTPRoute]
        R3[Secrets]
    end
    
    subgraph "Can Write"
        W1[CloudflareZeroTrustTenant status]
        W2[HTTPRoute annotations]
        W3[Service Token Secrets]
        W4[Events]
        W5[ConfigMaps - State Tracking]
    end
    
    subgraph "Cannot Access"
        X1[Other Secrets - not referenced by tenant]
        X2[Deployments]
        X3[Other Resources]
    end
    
    SA --> R1
    SA --> R2
    SA --> R3
    SA --> W1
    SA --> W2
    SA --> W3
    SA --> W4
    SA --> W5
    SA --> W3
    SA --> W4
    
    style X1 fill:#E53935
    style X2 fill:#E53935
    style X3 fill:#E53935
    style X4 fill:#E53935
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
