#!/usr/bin/env bash
# refresh-db.sh — run ON the session VM. Re-downloads and restores only the databases
# the session's own services use, instead of all 84.
#
# Argument 1 is the repo-or-preset pattern. Any further arguments are explicit database
# names, which SKIP derivation entirely.
#
# ⚠️ Why this exists: `golden build` is the ONLY thing that ever restored databases, so
#    a session VM served data frozen at image-build time and the only cure was a 1-2 hour
#    rebuild. Repo code is refreshed per session by ensure-repos.sh; the databases were
#    not. See SIM-63.
#
# ⚠️ THE SERVICE-TO-DATABASE MAPPING IS NOT IN THE RESOLVED COMPOSE CONFIG. Measured
#    2026-08-29: only 5 of ~88 services expose any DB variable through
#    `docker compose config`, because the jungle declares env with the LONG-FORM
#    `env_file: [{path: ...}]`, which compose does not inline into `environment`. So the
#    name is read from each repo's own deploy env file instead. Two spellings exist and
#    both are needed:
#      DB_NAME     — the NestJS services (beye -> api_beye)
#      DB_DATABASE — the Laravel services (api-partner -> api_partner)
set -uo pipefail

PATTERN="${1:?usage: refresh-db.sh <repo-or-preset> [db...]}"
shift || true
EXPLICIT=("$@")
JUNGLE="$HOME/jungle"

say() { printf '  %s\n' "$*" >&2; }

cd "$JUNGLE" || { printf 'error: no %s\n' "$JUNGLE" >&2; exit 1; }

if [[ ${#EXPLICIT[@]} -gt 0 ]]; then
  DBS="$(printf '%s\n' "${EXPLICIT[@]}")"
  say "using the databases you named"
else
  SERVICES="$(docker compose -f compose.yaml config --services 2>/dev/null | grep -- "$PATTERN")"
  [[ -n "$SERVICES" ]] || { printf 'error: no compose service matches %s\n' "$PATTERN" >&2; exit 1; }

  # Same derivation as ensure-repos.sh: service -> build context -> top-level directory.
  DIRS="$(docker compose -f compose.yaml config --format json 2>/dev/null \
    | jq -r --arg p "$PATTERN" '
        .services | to_entries
        | map(select(.key | contains($p)))
        | map(select(.value.build != null))
        | map(.value.build.context) | unique[]' \
    | sed -e "s#^${JUNGLE}/##" -e 's#/.*##' | sort -u)"
  [[ -d "$JUNGLE/$PATTERN" ]] && DIRS="$DIRS
$PATTERN"

  DBS=""
  for dir in $(printf '%s\n' $DIRS | sort -u); do
    [[ -n "$dir" ]] || continue
    found="$(grep -rhE '^(DB_NAME|DB_DATABASE)=' \
      "$JUNGLE/$dir"/deploy/development.env \
      "$JUNGLE/$dir"/*/deploy/development.env 2>/dev/null \
      | cut -d= -f2- | tr -d "\"' \r" | sort -u)"
    [[ -n "$found" ]] && DBS="$DBS
$found" || say "no database found for $dir"
  done
fi

DBS="$(printf '%s\n' $DBS | grep . | sort -u)"
if [[ -z "$DBS" ]]; then
  printf 'error: derived no database for %s. Pass names explicitly: refresh-db.sh %s <db>\n' \
    "$PATTERN" "$PATTERN" >&2
  exit 1
fi

# ⚠️ RESTORING REPLACES THE DATABASE. Any data created on this VM since the image was
#    built is DESTROYED — uploaded dashboards, test fixtures, everything. There is no
#    merge. `--list` previews the derivation so nobody discovers this after the fact.
if [[ "${REFRESH_DB_LIST:-}" == "1" ]]; then
  say "would refresh (nothing changed):"
  printf '%s\n' $DBS
  exit 0
fi

say "refreshing: $(printf '%s ' $DBS)"
say "WARNING: this REPLACES those databases. Data created on this VM will be lost."

# ⚠️ Download BEFORE restore. database.restore.sh reads whatever dump is on disk, so
#    restoring without downloading first silently re-restores the STALE dump baked into
#    the golden image — the exact staleness this verb exists to fix.
say "downloading dumps"
./bin/database.download.sh $DBS >&2 || { printf 'error: download failed\n' >&2; exit 1; }

say "restoring"
./bin/database.restore.sh $DBS >&2 || { printf 'error: restore failed\n' >&2; exit 1; }

say "done"
printf '%s\n' $DBS
