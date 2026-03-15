FROM python:3.13-slim

LABEL org.opencontainers.image.version="0.2.3"
LABEL org.opencontainers.image.description="kopf-based Kubernetes operator that watches HTTPRoute resources and reconciles them with the Cloudflare API to manage tunnel routing, Access Applications, and service tokens."
LABEL org.opencontainers.image.source="https://github.com/wheetazlab/cloudflare-zero-trust-operator"
LABEL org.opencontainers.image.licenses="MIT"

WORKDIR /app

# Install dependencies first for better layer caching
COPY container/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy operator source
COPY python/*.py /app/

# Copy entrypoint
COPY container/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Run as non-root
RUN useradd --create-home --uid 1000 --no-user-group operator
USER operator

ENTRYPOINT ["/entrypoint.sh"]
