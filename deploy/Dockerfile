# syntax=docker/dockerfile:1
FROM node:22-bookworm-slim AS node
FROM python:3.12-slim-bookworm
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN --mount=type=secret,id=build_ca \
    if [ -f /run/secrets/build_ca ]; then cp /run/secrets/build_ca /usr/local/share/ca-certificates/build-proxy.crt; update-ca-certificates; fi \
    && ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt npm install --global pnpm@10.11.0 \
    && useradd --create-home --uid 10001 signal
WORKDIR /app
COPY dist/ dist/
COPY tools/ tools/
COPY tests/ tests/
COPY server.py server.py
COPY deploy/ deploy/
RUN NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt python deploy/install_generator.py \
    && mkdir -p runtime/jobs runtime/ai-api-runs runtime/bai-runs runtime/geo-flows \
    && chown -R signal:signal /app
USER signal
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD ["python", "deploy/run_services.py", "--check"]
CMD ["python", "deploy/run_services.py"]
