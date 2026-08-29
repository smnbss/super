#!/usr/bin/env bash
# golden-build-remote.sh — the LONG half of `golden build`, run ON the VM under nohup.
#
# ⚠️ WHY THIS EXISTS. The golden build used to be a sequence of `gcloud compute ssh`
#    calls issued FROM THE LAPTOP. Every one of them is a live SSH session, so the whole
#    build depended on the operator's laptop staying awake, online, and on the same IP for
#    one to two hours. It died three times on 2026-08-29:
#      1. the driving process exited with the terminal, mid-restore;
#      2. the instance was stopped underneath it;
#      3. the operator changed wifi, which both changed the firewall-allowed IP and broke
#         every open SSH pipe — the laptop then hung for 1h42m on a dead connection while
#         the VM sat idle.
#    Each failure cost 30+ minutes of database restores. See SIM-63.
#
#    So the heavy steps run HERE, detached. The laptop only polls, and a dropped laptop
#    is now survivable: reconnect and read the log. The quick final steps — scrub, stop,
#    capture — stay on the laptop, because capturing needs the instance stopped.
set -uo pipefail

JUNGLE="$HOME/jungle"
LOG="$HOME/golden-build.log"
DONE="$HOME/golden-build.done"
JUNGLE_GIT_URL="${1:?usage: golden-build-remote.sh <jungle-git-url>}"

rm -f "$DONE"

# ⚠️ Postgres creates ~84 databases on first boot and RESTARTS part-way through, so a
#    passing pg_isready proves nothing. Gate on the database count, the same way the
#    laptop-side wait_for_databases does.
wait_for_databases() {
  local i count
  for (( i = 0; i < 90; i++ )); do
    count="$(docker exec jungle-postgresql.weroad.wr-1 \
      psql -U admin -tAc 'select count(*) from pg_database' 2>/dev/null | tr -d '[:space:]')"
    if [[ "$count" =~ ^[0-9]+$ ]] && (( count >= 80 )); then
      echo "postgres reports $count databases"
      return 0
    fi
    sleep 10
  done
  echo "FATAL: postgres never reported at least 80 databases"
  return 1
}

{
  echo "=== remote build started $(date -u +%FT%TZ) ==="

  if [[ ! -d "$JUNGLE/.git" ]]; then
    echo "--- cloning the jungle ---"
    git clone "$JUNGLE_GIT_URL" "$JUNGLE" || { echo "FATAL: jungle clone failed"; exit 1; }
  fi
  cd "$JUNGLE" || { echo "FATAL: no $JUNGLE"; exit 1; }

  echo "--- repo.init.sh ---"
  ./bin/repo.init.sh || echo "WARNING: repo.init.sh failed. Sessions clone what they need."
  echo "repos on disk: $(find "$JUNGLE" -mindepth 2 -maxdepth 2 -name .git | wc -l)"

  echo "--- jungle deps ---"
  source /tmp/vm-bootstrap.sh 2>/dev/null && install_jungle_deps || echo "WARNING: install_jungle_deps failed"

  # compose.merge.js resolves an extends: reference into every repo, including two that a
  # partial clone never fetches. Both directories are gitignored.
  mkdir -p dbt dlt-pipelines
  [ -e dbt/compose.yaml ] || printf 'services:\n  dbt:\n    image: alpine:3.20\n' > dbt/compose.yaml
  [ -e dlt-pipelines/compose.yaml ] || printf 'services:\n  pipelines:\n    image: alpine:3.20\n' > dlt-pipelines/compose.yaml
  echo "--- compose.merge ---"
  node scripts/compose.merge.js --target=development --no-deps=true || echo "WARNING: compose.merge failed"

  # hosts.init.sh rewrites tracked compose files. Forbidden on a laptop, correct here.
  echo "--- hosts.init ---"
  ./bin/hosts.init.sh || echo "WARNING: hosts.init failed"

  # ⚠️ --development is REQUIRED: gcloud on this VM authenticates as the default compute
  #    service account, which cannot read weroad-eu-production's artifact registry.
  echo "--- staging images (--development) ---"
  ./bin/staging-images.update.sh --development || echo "WARNING: staging-images failed"

  echo "--- reverse proxy + databases up ---"
  ./bin/jungle.up.sh reverseproxy.wr || echo "WARNING: reverseproxy failed"
  ./bin/database.up.sh || echo "WARNING: database.up failed"
  wait_for_databases || exit 1

  echo "--- database.restore.sh (all) ---"
  ./bin/database.restore.sh
  echo "restore exit=$?"

  echo "--- final database state ---"
  restored=0; total=0
  for db in $(docker exec jungle-postgresql.weroad.wr-1 psql -U admin -tAc \
      "select datname from pg_database where datname not in ('postgres','template0','template1')"); do
    total=$((total+1))
    n=$(docker exec jungle-postgresql.weroad.wr-1 psql -U admin -d "$db" -tAc \
      "select count(*) from information_schema.tables where table_schema='public'" 2>/dev/null | tr -d '[:space:]')
    [ "${n:-0}" -gt 0 ] 2>/dev/null && restored=$((restored+1))
  done
  echo "databases restored: $restored of $total"

  echo "=== remote build finished $(date -u +%FT%TZ) ==="
} >> "$LOG" 2>&1

touch "$DONE"
