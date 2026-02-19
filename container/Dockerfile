FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /ansible

# Copy requirements
COPY requirements.txt /tmp/requirements.txt

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

# Create non-root user
RUN useradd -m -u 1000 ansible && \
    chown -R ansible:ansible /ansible && \
    mkdir -p /runner && \
    chown -R ansible:ansible /runner

USER ansible

# Set entrypoint
ENTRYPOINT ["/entrypoint.sh"]
