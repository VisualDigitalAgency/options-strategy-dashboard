#!/usr/bin/env bash
# Deploy the current main to Coolify and wait for it, then smoke-test the live site.
# Run by .github/workflows/ci.yml; works by hand too:
#   COOLIFY_URL=https://coolify.example.com COOLIFY_TOKEN=... COOLIFY_APP_UUID=... \
#   PUBLIC_URL=https://theta.example.com EXPECT_SHA=<commit> scripts/ci_deploy.sh
#
#   scripts/ci_deploy.sh --live-commit   print the commit of Coolify's last finished deployment
set -euo pipefail

: "${COOLIFY_URL:?}" "${COOLIFY_TOKEN:?}" "${COOLIFY_APP_UUID:?}"
API="${COOLIFY_URL%/}/api/v1"
auth=(-H "Authorization: Bearer ${COOLIFY_TOKEN}" -H "Accept: application/json")

api() { curl -fsS --retry 3 --retry-all-errors --max-time 30 "${auth[@]}" "$@"; }

if [[ "${1:-}" == "--live-commit" ]]; then
  api "$API/deployments/applications/$COOLIFY_APP_UUID?skip=0&take=10" |
    jq -r '[.deployments[] | select(.status == "finished")][0].commit // ""'
  exit 0
fi
: "${PUBLIC_URL:?}" "${EXPECT_SHA:?}"

resp=$(api -X POST "$API/deploy?uuid=$COOLIFY_APP_UUID&force=false")
dep=$(jq -r '.deployments[0].deployment_uuid // empty' <<<"$resp")
if [[ -z "$dep" ]]; then
  echo "::error::Coolify did not queue a deployment: $(jq -r '.deployments[0].message // .message // .' <<<"$resp")"
  exit 1
fi
echo "Queued Coolify deployment $dep"

# Builds take ~3-6 minutes on the server; give it 20.
status=""
for _ in $(seq 1 120); do
  sleep 10
  d=$(api "$API/deployments/$dep") || continue
  status=$(jq -r '.status' <<<"$d")
  case "$status" in
    finished) commit=$(jq -r '.commit // ""' <<<"$d"); break ;;
    failed|cancelled*) echo "::error::Coolify deployment $dep $status. Logs: ${COOLIFY_URL%/} → theta-desk → Deployments"; exit 1 ;;
  esac
done
[[ "$status" == "finished" ]] || { echo "::error::Deployment $dep still '$status' after 20 minutes"; exit 1; }
echo "Deployed commit ${commit:-?}"
if [[ -n "${commit:-}" && "$commit" != "HEAD" && "$commit" != "$EXPECT_SHA" ]]; then
  echo "::warning::Coolify deployed $commit, not $EXPECT_SHA (a newer push landed meanwhile)."
fi

# Smoke test. The new worker takes over the leader lock within ~40 s of the old one stopping.
url="${PUBLIC_URL%/}"
for i in $(seq 1 18); do
  health=$(curl -fsS --max-time 10 "$url/healthz" || true)
  if [[ "$(jq -r '.postgres and .redis and .worker' <<<"${health:-null}" 2>/dev/null)" == "true" ]]; then break; fi
  [[ $i == 18 ]] && { echo "::error::/healthz not healthy after 3 minutes: ${health:-no response}"; exit 1; }
  sleep 10
done
echo "healthz: $health"

check() {  # name, expected, actual
  if [[ "$2" == "$3" ]]; then echo "ok   $1 ($3)"; else echo "::error::$1: expected $2, got $3"; fail=1; fi
}
fail=0
check "home page" 200 "$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$url/")"
check "cross-site /rpc refused" 403 "$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 -X POST \
  -H 'Origin: https://evil.example' -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"auth_me"}' "$url/rpc")"
check "same-origin /rpc answers" 200 "$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 -X POST \
  -H "Origin: $url" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"auth_me"}' "$url/rpc")"
check "GET /rpc" 405 "$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$url/rpc")"
check "CSP header" 1 "$(curl -sI --max-time 15 "$url/" | grep -ci '^content-security-policy:')"
exit $fail
