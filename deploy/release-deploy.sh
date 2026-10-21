#!/usr/bin/env bash
# Installed through a root-owned wrapper; arguments contain no credentials.
set -euo pipefail
[[ $# == 5 ]] || { echo 'Usage: signal-geo-deploy IMAGE_DIGEST RELEASE_COMMIT RELEASE_ID PUBLISHED_AT TAG' >&2; exit 64; }
release_image=$1
release_revision=$2
release_id=$3
release_published=$4
release_tag=$5
[[ "$release_image" =~ ^ghcr\.io/saml1nhchen-ops/money-coming/backend@sha256:[a-f0-9]{64}$ ]] || { echo 'Unexpected image repository or digest.' >&2; exit 64; }
[[ "$release_revision" =~ ^[a-f0-9]{40}$ ]] || { echo 'Invalid release commit.' >&2; exit 64; }
[[ "$release_id" =~ ^[1-9][0-9]{0,18}$ && "$release_published" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ && "$release_tag" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]] || { echo 'Invalid release identity.' >&2; exit 64; }
project_dir=${SIGNAL_DEPLOY_PROJECT_DIR:-/home/ubuntu/geo-backend}
[[ "$project_dir" == /* && -d "$project_dir" && ! -L "$project_dir" ]] || { echo 'Invalid deployment directory.' >&2; exit 64; }
cd "$project_dir"
[[ -f compose.yaml && -f .env ]] || { echo 'Server installation is incomplete.' >&2; exit 69; }
mkdir -p .deploy
chmod 700 .deploy
exec 9>.deploy/release.lock
flock -w "${SIGNAL_DEPLOY_LOCK_TIMEOUT:-1800}" 9 || { echo 'Another deployment is still running.' >&2; exit 75; }
if [[ -f .deploy/release-status.json ]]; then
  python3 - .deploy/release-status.json <<'PY_STATUS'
import json,sys
try:state=json.load(open(sys.argv[1]))
except (OSError,ValueError):raise SystemExit('Deployment status is unreadable; manual recovery required')
if state.get('status') not in ('healthy','rolled_back','blocked'):raise SystemExit('Prior deployment is incomplete or failed recovery; manual verification required')
PY_STATUS
fi
mkdir -p .deploy/releases
python3 - "$release_image" "$release_revision" "$release_id" "$release_published" "$release_tag" <<'PY_MANIFEST'
import datetime,json,os,pathlib,sys
image,revision,ident,published,tag=sys.argv[1:]
ident=int(ident)
if not 0<ident<2**63:raise SystemExit('Invalid release ID')
datetime.datetime.strptime(published,'%Y-%m-%dT%H:%M:%SZ')
incoming={'schema':1,'image':image,'revision':revision,'release_id':ident,'published_at':published,'tag':tag}
current_path=pathlib.Path('.deploy/current-release.json')
try:
 if current_path.exists():
  current=json.loads(current_path.read_text())
  if (published,ident)<(current['published_at'],current['release_id']):raise SystemExit('A newer release has already been deployed')
 path=pathlib.Path('.deploy/releases')/(str(ident)+'.json')
 if path.exists():
  if json.loads(path.read_text())!=incoming:raise SystemExit('This release already has a different immutable manifest')
 else:
  tmp=path.with_suffix('.tmp')
  with tmp.open('w') as out:json.dump(incoming,out,sort_keys=True);out.flush();os.fsync(out.fileno())
  os.replace(tmp,path)
except (OSError,ValueError,KeyError,TypeError):raise SystemExit('Release evidence is unreadable; manual verification required')
PY_MANIFEST
project=geo-backend
base=(docker compose -p "$project" -f compose.yaml)
override=.deploy/compose.release.yaml
compose=("${base[@]}")
if [[ -f "$override" ]]; then compose+=(-f "$override"); fi
current_id=$("${compose[@]}" ps -q backend)
[[ -n "$current_id" && "$current_id" != *$'\n'* ]] || { echo 'Expected one existing backend container.' >&2; exit 69; }
old_image=$(docker inspect --format '{{.Image}}' "$current_id")
[[ "$old_image" =~ ^sha256:[a-f0-9]{64}$ ]] || exit 69
old_volume=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/app/runtime"}}{{.Name}}{{end}}{{end}}' "$current_id")
[[ -n "$old_volume" && "$old_volume" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]+$ ]] || { echo 'Persistent runtime volume missing.' >&2; exit 69; }
helper() { "${compose[@]}" exec -T backend python3 tools/deploy_control.py "$@"; }
signal_service() {
  "${compose[@]}" exec -T backend python3 - "$1" <<'PY'
import os, pathlib, signal, sys
name=sys.argv[1]
if name not in ('SIGUSR1','SIGUSR2'):raise SystemExit('Invalid signal')
found=[]
for item in pathlib.Path('/proc').iterdir():
 if not item.name.isdigit():continue
 try:args=(item/'cmdline').read_bytes().split(b'\0')
 except (OSError,PermissionError):continue
 if len(args)>1 and pathlib.PurePath(os.fsdecode(args[0])).name.startswith('python') and args[1] in (b'tools/remote_service.py',b'/app/tools/remote_service.py'):found.append(int(item.name))
if len(found)!=1:raise SystemExit('Expected exactly one backend supervisor')
os.kill(found[0],getattr(signal,name))
PY
}
# Check capability before sending a signal: older supervisors would terminate.
helper probe > .deploy/probe.json
host=$(python3 - .deploy/probe.json <<'PY'
import json,re,sys
host=json.load(open(sys.argv[1])).get('host','')
if not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?',host) or '.' not in host:raise SystemExit('Invalid HTTPS host')
print(host)
PY
)
# Pull while the existing application can still accept work. Never use latest.
docker pull "$release_image"
image_revision=$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$release_image")
[[ "$image_revision" == "$release_revision" ]] || { echo 'Image commit does not match release.' >&2; exit 65; }
new_image_id=$(docker image inspect --format '{{.Id}}' "$release_image")
[[ "$new_image_id" =~ ^sha256:[a-f0-9]{64}$ ]] || exit 65
old_revision=$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$old_image")
if [[ ! "$old_revision" =~ ^[a-f0-9]{40}$ ]]; then old_revision=unknown; fi
prior_current=.deploy/previous-current.json
if [[ -f .deploy/current-release.json ]]; then cp -p .deploy/current-release.json "$prior_current"; else rm -f "$prior_current"; fi
prior_override=.deploy/previous-compose.yaml
if [[ -f "$override" ]]; then cp -p "$override" "$prior_override"; else rm -f "$prior_override"; fi
write_override() {
  local image=$1
  deployment_nonce=$(python3 -c 'import secrets;print(secrets.token_hex(16))')
  mkdir -p .deploy/admission
  chmod 755 .deploy/admission
  python3 - "$override" "$image" "$deployment_nonce" <<'PY'
import os,pathlib,sys
path=pathlib.Path(sys.argv[1]);tmp=path.with_suffix('.tmp')
# Image input has been validated by the caller; JSON quotes are valid YAML.
import json
with tmp.open('w') as out:
 out.write('services:\n  backend:\n    image: '+json.dumps(sys.argv[2])+'\n    pull_policy: never\n    environment:\n      SIGNAL_DEPLOY_MAINTENANCE: "1"\n      SIGNAL_DEPLOY_NONCE: '+json.dumps(sys.argv[3])+'\n    volumes:\n      - type: bind\n        source: '+json.dumps(str(path.resolve().parent/'admission'))+'\n        target: /run/signal-deploy\n        read_only: true\n')
 out.flush();os.fsync(out.fileno())
os.replace(tmp,path)
PY
  compose=("${base[@]}" -f "$override")
}
write_receipt() {
  python3 - "$deployment_nonce" "$1" <<'PY_RECEIPT'
import datetime,json,os,pathlib,sys
path=pathlib.Path('.deploy/admission/healthy.json');tmp=path.with_suffix('.tmp')
with tmp.open('w') as f:
 json.dump({'status':'healthy','nonce':sys.argv[1],'revision':sys.argv[2]},f);f.flush();os.fsync(f.fileno())
os.chmod(tmp,0o644);os.replace(tmp,path)
PY_RECEIPT
}
maintenance=false
switched=false
rollback_failed=false
status_file=.deploy/release-status.json
write_status() {
  python3 - "$status_file" "$1" "$release_image" "$release_revision" "$old_image" "$old_volume" "$release_id" "$release_published" "$release_tag" <<'PY'
import datetime,json,os,pathlib,sys
path=pathlib.Path(sys.argv[1]);tmp=path.with_suffix('.tmp')
data=dict(zip(['status','image','revision','previous_image','runtime_volume','release_id','published_at','tag'],sys.argv[2:]));data['at']=datetime.datetime.now(datetime.timezone.utc).isoformat()
with tmp.open('w') as f:json.dump(data,f);f.flush();os.fsync(f.fileno())
os.replace(tmp,path)
PY
}
write_current() {
  python3 - "$release_id" <<'PY_CURRENT'
import os,pathlib,sys
source=pathlib.Path('.deploy/releases')/(sys.argv[1]+'.json');path=pathlib.Path('.deploy/current-release.json');tmp=path.with_suffix('.tmp')
with tmp.open('wb') as out:out.write(source.read_bytes());out.flush();os.fsync(out.fileno())
os.replace(tmp,path)
PY_CURRENT
}
check_health() {
  local expected_revision=$1 expected_image=$2 timeout=$3
  local deadline=$((SECONDS+timeout))
  helper health --timeout "$timeout" > .deploy/private-health.json || return 1
  while (( SECONDS < deadline )); do
    local id actual_image actual_volume
    id=$("${compose[@]}" ps -q backend 2>/dev/null) || id=''
    actual_image=$(docker inspect --format '{{.Image}}' "$id" 2>/dev/null) || actual_image=''
    actual_volume=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/app/runtime"}}{{.Name}}{{end}}{{end}}' "$id" 2>/dev/null) || actual_volume=''
    if [[ "$actual_image" == "$expected_image" && "$actual_volume" == "$old_volume" ]] && \
       curl --silent --show-error --fail --proto '=https' --tlsv1.2 --max-time 10 "https://$host/healthz" -o .deploy/public-health.json 2>/dev/null && \
       python3 - "$expected_revision" .deploy/private-health.json .deploy/public-health.json <<'PY'
import json,sys
private=json.load(open(sys.argv[2]));public=json.load(open(sys.argv[3]))
if private.get('revision','unknown')!=sys.argv[1] or public.get('revision','unknown')!=sys.argv[1] or public.get('ok') is not True:raise SystemExit(1)
PY
    then return 0; fi
    sleep 2
  done
  return 1
}
cleanup() {
  local result=$?
  trap - EXIT INT TERM HUP
  if [[ "$result" != 0 && "$switched" == true ]]; then
    echo 'Deployment failed; restoring the previous local image, preserving the data volume.' >&2
    write_override "$old_image"
    if "${compose[@]}" up -d --no-build --no-deps backend && check_health "$old_revision" "$old_image" "${SIGNAL_DEPLOY_ROLLBACK_TIMEOUT:-120}"; then
      if write_receipt "$old_revision" && signal_service SIGUSR2; then
        maintenance=false
        if [[ -f "$prior_current" ]]; then cp -p "$prior_current" .deploy/current-release.json; else rm -f .deploy/current-release.json; fi
        write_status rolled_back
        echo 'Previous version restored. This release remains failed.' >&2
      else rollback_failed=true; fi
    else rollback_failed=true; fi
    if [[ "$rollback_failed" == true ]]; then
      write_status rollback_failed
      echo 'Rollback health could not be confirmed. Admission remains closed; manual recovery required.' >&2
    fi
  elif [[ "$result" != 0 && "$maintenance" == true ]]; then
    signal_service SIGUSR2 || true
    write_status blocked
  fi
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
if [[ "$old_image" == "$new_image_id" ]] && python3 - .deploy/probe.json "$status_file" "$release_image" "$release_revision" <<'PY_SKIP'
import json,sys
try:
 probe=json.load(open(sys.argv[1]));saved=json.load(open(sys.argv[2]))
 assert probe.get('model_ready') is True and probe.get('maintenance') is False
 assert saved.get('status')=='healthy' and saved.get('image')==sys.argv[3] and saved.get('revision')==sys.argv[4]
except (OSError,ValueError,AssertionError):raise SystemExit(1)
PY_SKIP
then
  if curl --silent --show-error --fail --proto '=https' --tlsv1.2 --max-time 10 "https://$host/healthz" -o .deploy/public-health.json && python3 - "$release_revision" .deploy/public-health.json <<'PY_HEALTH'
import json,sys
p=json.load(open(sys.argv[2]))
if p.get('ok') is not True or p.get('revision','unknown')!=sys.argv[1]:raise SystemExit(1)
PY_HEALTH
  then write_current; write_status healthy; echo 'This exact release is already healthy; no restart needed.'; exit 0; fi
fi
write_status preparing
# From this point every error must attempt to restore admission or roll back.
maintenance=true
signal_service SIGUSR1
helper wait-idle --timeout "${SIGNAL_DEPLOY_IDLE_TIMEOUT:-1800}"
write_override "$release_image"
switched=true
"${compose[@]}" up -d --no-build --no-deps backend
check_health "$release_revision" "$new_image_id" "${SIGNAL_DEPLOY_HEALTH_TIMEOUT:-180}"
write_current
write_receipt "$release_revision"
write_status healthy
signal_service SIGUSR2
maintenance=false
switched=false
printf 'Release deployed: %s; original runtime volume retained.\n' "$release_revision"
