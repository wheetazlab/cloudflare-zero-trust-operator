FROM python:3.11-slim

LABEL org.opencontainers.image.description="Ansible-based Kubernetes operator that watches HTTPRoute resources and reconciles them with the Cloudflare API to manage tunnel routing, Access Applications, and service tokens."
LABEL org.opencontainers.image.source="https://github.com/wheetazlab/cloudflare-zero-trust-operator"
LABEL org.opencontainers.image.licenses="MIT"

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /ansible

# Copy requirements
COPY container/requirements.txt /tmp/requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Copy Ansible requirements
COPY ansible/requirements.yml /tmp/requirements.yml

# Install Ansible collections
RUN ansible-galaxy collection install -r /tmp/requirements.yml

# Copy Ansible content
COPY ansible/ /ansible/

# Copy entrypoint
COPY container/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Symlink python3 to /usr/bin so both /usr/bin/python3 and /usr/local/bin/python3 work
RUN ln -sf /usr/local/bin/python3 /usr/bin/python3

# Create non-root user
RUN useradd -m -u 1000 ansible && \
    chown -R ansible:ansible /ansible && \
    mkdir -p /runner && \
    chown -R ansible:ansible /runner

USER ansible

# Redirect Ansible dirs to /tmp (writable even with read-only root filesystem)
ENV ANSIBLE_LOCAL_TEMP=/tmp/ansible \
    ANSIBLE_REMOTE_TMP=/tmp/ansible \
    ANSIBLE_HOME=/tmp/ansible-home

# Set entrypoint
ENTRYPOINT ["/entrypoint.sh"]
