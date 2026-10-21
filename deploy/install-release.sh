#!/usr/bin/env bash
# One-time installation ON THE TARGET SERVER. Does not restart the backend.
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Run this installer with sudo on the target server.' >&2; exit 77; }
[[ $# -ge 1 && $# -le 2 ]] || { echo 'Usage: sudo bash deploy/install-release.sh DEPLOY_PUBLIC_KEY [PROJECT_DIR]' >&2; exit 64; }
public_key_file=$(realpath -e "$1")
project_dir=$(realpath -e "${2:-/home/ubuntu/geo-backend}")
[[ "$project_dir" =~ ^/[A-Za-z0-9_./-]+$ && -f "$project_dir/compose.yaml" && -f "$project_dir/.env" ]] || exit 64
ssh-keygen -lf "$public_key_file" >/dev/null
[[ $(wc -l < "$public_key_file") -le 1 ]] || { echo 'Supply exactly one public key.' >&2; exit 64; }
public_key=$(cat "$public_key_file")
[[ "$public_key" =~ ^ssh-ed25519[[:space:]][A-Za-z0-9+/=]+([[:space:]].*)?$ && "$public_key" != *$'\r'* && "$public_key" != *$'\n'* ]] || { echo 'Use one Ed25519 public key, never a private key.' >&2; exit 64; }
cd "$project_dir"
compose=(docker compose -p geo-backend -f compose.yaml)
if [[ -f .deploy/compose.release.yaml ]]; then compose+=(-f .deploy/compose.release.yaml); fi
# Old supervisors must be upgraded once in a planned maintenance window first.
"${compose[@]}" exec -T backend python3 tools/deploy_control.py probe >/dev/null || {
  echo 'Deployment-gate support is missing. Complete the one-time maintenance upgrade before enabling automation.' >&2
  exit 69
}
install -d -m 755 /usr/local/libexec
install -o root -g root -m 755 deploy/release-deploy.sh /usr/local/libexec/signal-geo-release-deploy
wrapper=$(mktemp)
sudoers=$(mktemp)
trap 'rm -f "$wrapper" "$sudoers"' EXIT
cat > "$wrapper" <<WRAPPER
#!/usr/bin/env bash
export SIGNAL_DEPLOY_PROJECT_DIR='$project_dir'
exec /usr/local/libexec/signal-geo-release-deploy "\$@"
WRAPPER
install -o root -g root -m 755 "$wrapper" /usr/local/sbin/signal-geo-deploy
install -o root -g root -m 755 deploy/ssh-release-command.py /usr/local/libexec/signal-geo-ssh-command
if ! id signal-deploy >/dev/null 2>&1; then useradd --create-home --shell /bin/bash signal-deploy; fi
user_home=$(getent passwd signal-deploy | cut -d: -f6)
[[ "$user_home" == /home/signal-deploy && ! -L "$user_home" ]] || { echo 'Unexpected deployment user home.' >&2; exit 69; }
install -d -o signal-deploy -g signal-deploy -m 700 "$user_home/.ssh"
authorized="$user_home/.ssh/authorized_keys"
[[ ! -L "$authorized" ]] || exit 69
touch "$authorized";chown signal-deploy:signal-deploy "$authorized";chmod 600 "$authorized"
python3 - "$authorized" "$public_key" <<'PY_AUTHORIZED'
import pathlib,re,sys
path=pathlib.Path(sys.argv[1]);key=sys.argv[2];ident=' '.join(key.split()[:2])
lines=[line for line in path.read_text().splitlines() if not re.search(r'(?<!\S)'+re.escape(ident)+r'(?=\s|$)',line)]
lines.append('restrict,command="/usr/local/libexec/signal-geo-ssh-command" '+key)
path.write_text('\n'.join(lines)+'\n')
PY_AUTHORIZED
printf 'signal-deploy ALL=(root) NOPASSWD: /usr/local/sbin/signal-geo-deploy\n' > "$sudoers"
visudo -cf "$sudoers" >/dev/null
install -o root -g root -m 440 "$sudoers" /etc/sudoers.d/signal-geo-release
echo 'Release deploy entry installed. Configure the production GitHub environment and registry access next.'
