#!/usr/bin/env bash
# Run on the intended cloud server, in the repository root. Secrets stay there.
set -euo pipefail
cd "$(dirname "$0")/.."
command -v docker >/dev/null || { echo 'Install Docker and the Compose plugin first.' >&2; exit 1; }
docker compose version >/dev/null
if [[ -e .env ]]; then
  echo '.env already exists; edit it on the server to change settings. Nothing overwritten.' >&2
  exit 1
fi
read -r -p 'HTTPS backend hostname (no https:// or path): ' signal_public_host
if [[ ! "$signal_public_host" =~ ^[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?$ || "$signal_public_host" != *.* ]]; then
  echo 'Enter a valid public hostname.' >&2; exit 1
fi
read -r -s -p 'B.AI API key (hidden): ' signal_provider_key; echo
read -r -s -p 'Team login password, at least 16 characters (hidden): ' signal_team_password; echo
[[ -n "$signal_provider_key" && ${#signal_team_password} -ge 16 ]] || { echo 'Key or password is missing/too short.' >&2; exit 1; }
# Restrict to unambiguous dotenv single-line strings; do not evaluate shell input.
for signal_input in "$signal_provider_key" "$signal_team_password"; do
  if [[ "$signal_input" == *"'"* || "$signal_input" == *$'\r'* || "$signal_input" == *$'\n'* ]]; then
    echo 'Use a single-line value without single quotes.' >&2; exit 1
  fi
done
umask 077
(set -o noclobber; printf "SIGNAL_PUBLIC_HOST='%s'\nSIGNAL_BAI_API_KEY='%s'\nSIGNAL_WORKSPACE_PASSWORD='%s'\nSIGNAL_DAILY_CALL_LIMIT=126\n" "$signal_public_host" "$signal_provider_key" "$signal_team_password" > .env)
unset signal_provider_key signal_team_password signal_input
printf 'Saved .env on this server with private permissions. Next: docker compose up -d --build\n'
