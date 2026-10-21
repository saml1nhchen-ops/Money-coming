# syntax=docker/dockerfile:1
FROM node:22-bookworm-slim AS dependencies

# Optional CA mounts support managed build proxies without persisting their CA.
RUN --mount=type=secret,id=system_ca \
    set -eu; if [ -f /run/secrets/system_ca ]; then \
      apt-get -o Acquire::https::CaInfo=/run/secrets/system_ca update; \
      apt-get -o Acquire::https::CaInfo=/run/secrets/system_ca install -y --no-install-recommends python3 git ca-certificates tini; \
    else \
      apt-get update && apt-get install -y --no-install-recommends python3 git ca-certificates tini; \
    fi && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY tools/upstreams.lock.json /app/tools/upstreams.lock.json
RUN --mount=type=secret,id=proxy_ca \
    --mount=type=secret,id=system_ca \
    if [ -f /run/secrets/system_ca ]; then export GIT_SSL_CAINFO=/run/secrets/system_ca; fi; \
    if [ -f /run/secrets/proxy_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/proxy_ca; fi; \
    python3 - <<'PY'
import json, pathlib, subprocess
spec = next(item for item in json.loads(pathlib.Path('tools/upstreams.lock.json').read_text()) if item['id'] == 'niubigeo')
dest = pathlib.Path('/opt/niubigeo')
subprocess.run(['git', 'init', str(dest)], check=True)
subprocess.run(['git', '-C', str(dest), 'remote', 'add', 'origin', 'https://github.com/' + spec['repository'] + '.git'], check=True)
subprocess.run(['git', '-C', str(dest), 'fetch', '--depth', '1', 'origin', spec['commit']], check=True)
subprocess.run(['git', '-C', str(dest), 'checkout', '--detach', 'FETCH_HEAD'], check=True)
assert subprocess.check_output(['git', '-C', str(dest), 'rev-parse', 'HEAD'], text=True).strip() == spec['commit']
subprocess.run(['npm', 'ci', '--no-audit', '--no-fund'], cwd=dest, check=True)
assert (dest / 'node_modules/tsx/dist/cli.mjs').is_file()
PY

FROM dependencies AS runtime
COPY tools /app/tools
COPY dist /app/dist
COPY server.py /app/server.py
RUN chmod -R a+rX /app/tools /app/dist && chmod a+r /app/server.py \
    && groupadd --gid 10001 signal && useradd --uid 10001 --gid signal --create-home signal \
    && mkdir -p /app/runtime /app/work && chown -R signal:signal /app/runtime /app/work
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    NODE_ENV=production PORT=8080 SIGNAL_UPSTREAM_SEED=/opt/niubigeo
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python3 -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8080')+'/healthz',timeout=4).read()"
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python3", "tools/remote_service.py"]
