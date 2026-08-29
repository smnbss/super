#!/usr/bin/env bash
# materialise-env-local.sh — rebuild ~/brain/.env.local ON THE VM from Secret Manager.
#
# ⚠️ WHY. setup_gcp.sh used to scp the operator's whole .env.local to every clone VM.
#    That file holds 62 keys, roughly 27 of them live secrets — including
#    POSTGRESQL_PRODUCTION_PASSWORD and three FusionAuth API keys. A production database
#    password on a throwaway dev box. See SIM-66.
#
#    SIM-64 had already rejected .env.local as a carrier for the Claude token, for the
#    same reason: the value should never sit in a laptop file that gets copied around.
#    This applies that verdict to the other 61.
#
# ⚠️ ENUMERATE, DO NOT CARRY A LIST. The secrets are named brain-env-<KEY> with the key
#    verbatim, so the set is discovered at run time. A hardcoded list of 62 names would be
#    a second source of truth that drifts the first time anyone adds a key — and the
#    failure is silent: the VM simply lacks a variable and something fails far away.
set -uo pipefail

PROJECT="${1:?usage: materialise-env-local.sh <gcp-project> [dest]}"
DEST="${2:-$HOME/brain/.env.local}"
PREFIX="brain-env-"

mkdir -p "$(dirname "$DEST")"

names="$(gcloud secrets list --project "$PROJECT" \
  --filter="name:${PREFIX}" --format='value(name)' 2>/dev/null | sort)"

if [[ -z "$names" ]]; then
  echo "FATAL: no ${PREFIX}* secrets in $PROJECT. Refusing to write an empty .env.local." >&2
  exit 1
fi

# ⚠️ Build in a temp file and move it into place. A fetch that fails part-way must not
#    leave a half-populated .env.local, which looks valid and fails far from the cause.
# ⚠️ umask 077 — this file ends up holding every credential the brain has.
umask 077
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

count=0
failed=0
for name in $names; do
  key="${name#"$PREFIX"}"
  # ⚠️ Never echo a value. Only names and counts reach the log.
  if value="$(gcloud secrets versions access latest --secret="$name" --project "$PROJECT" 2>/dev/null)"; then
    # Written exactly as stored: no re-quoting. Some values legitimately contain '=',
    # quotes or trailing spaces, and re-quoting corrupts them.
    printf '%s=%s\n' "$key" "$value" >> "$tmp"
    count=$((count + 1))
  else
    echo "ERROR: cannot read secret $name" >&2
    failed=$((failed + 1))
  fi
done

# ⚠️ Fail loudly. A partially-written env file produces failures nowhere near the cause.
if (( failed > 0 )); then
  echo "FATAL: $failed of $((count + failed)) secrets could not be read. Not writing $DEST." >&2
  exit 1
fi

mv "$tmp" "$DEST"
trap - EXIT
chmod 600 "$DEST"
echo "wrote $DEST from $count secrets"
