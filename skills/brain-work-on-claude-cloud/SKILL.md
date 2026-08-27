---
name: brain-work-on-claude-cloud
description: >
  Use when the user wants a WeRoad jungle stack running inside a Claude Cloud
  (wr-cloud) remote environment — "bring up the jungle in wr-cloud", "start the
  partner stack in the cloud sandbox", "/brain-work-on-claude-cloud <preset>",
  "run the jungle in Claude Cloud". Also use when a jungle stack inside wr-cloud
  shows any of these symptoms: every endpoint returns 000, every laravel.* service
  returns 502, pnpm sits at "downloaded 0", composer reports "self-signed
  certificate in certificate chain", `docker compose config` fails on a missing
  dbt/ or dlt-pipelines/ compose file, a route loads with a near-empty DOM and a
  504 "Outdated Optimize Dep", or a host returns 403 with x-deny-reason.
---

# Brain — Work On Claude Cloud

Bring up a WeRoad jungle stack inside a **wr-cloud** container and leave it running.

wr-cloud is **credential-rich and tooling-poor**. The environment setup script
already placed every credential. What is missing is host tooling, plus the laptop
assumptions inside the jungle scripts. Do not follow the jungle README literally.
Use the jungle's own scripts. Do not write your own.

Source of truth for this skill: Linear **HD-17** and the runbook
[wr-cloud — Environment & Partner Stack](https://beye.weroad.com/view/1df503af-b59a-4d90-bcff-91b02c2d8c2f).

## Input

One preset name, passed as the skill argument. Examples:

```
/brain-work-on-claude-cloud partner
/brain-work-on-claude-cloud catalog
/brain-work-on-claude-cloud my
```

If the caller gives no preset, or leaves `<PRESET>` as a placeholder, **stop and
ask**. Do not guess a preset.

⚠️ This skill runs **inside** the wr-cloud container, not on the laptop. Start a
Claude Code session on the wr-cloud environment first. The jungle is at
`/home/user/jungle`.

## What the setup script already did — do not repeat it

| Item | State |
|---|---|
| ADC (`~/.config/gcloud/application_default_credentials.json`) | written |
| `~/.npmrc`, `~/.composer/auth.json` | written |
| Docker credential helper for `europe-docker.pkg.dev` | installed, re-mints tokens |
| `gcloud` on PATH (`/usr/local/bin/gcloud`) | symlinked |
| `jungle-ca-inject` on PATH | installed |
| `dockerd` | started, **not supervised** |
| The two compose `extends:` stubs (`dbt/`, `dlt-pipelines/`) | written, gitignored |

Private images, npm and composer need no further authentication. There is no
`docker login` step and no `gcloud auth` step.

## Step 1 — Health first

`dockerd` is not supervised, and `/etc/hosts` gets wiped. Both faults give the
**same symptom**: every endpoint returns `000`. Check both, every time.

```bash
docker info >/dev/null || (dockerd >/tmp/dockerd.log 2>&1 &)
source bin/hosts.sh
for d in "${DOMAINS[@]}"; do
  grep -qE "^0\.0\.0\.0[[:space:]]+$d\$" /etc/hosts \
    || echo "0.0.0.0 $d" >> /etc/hosts
done
```

Three rules for this step:

1. Write `0.0.0.0`, not `127.0.0.1`. `bin/hosts.init.sh:25` writes and greps for
   `0.0.0.0`. A mismatch makes a later run append a duplicate entry for all 86
   domains.
2. Use `bin/hosts.sh`. Never use `bin/hosts.init.sh` — that script rewrites
   tracked compose files.
3. Save the block as an idempotent recovery script. You will need it again.

A ready copy ships beside this skill as `health-check.sh`.

## Step 2 — Network and reverse proxy

```bash
./bin/jungle.up.sh reverseproxy.wr
```

⚠️ **Never pass `--remove-orphans`, in either direction.** reverseproxy lives in
`compose.jungle.yaml`, not in the merged `compose.yaml`, but both share the
`jungle` compose project name. Every compose call therefore warns about orphan
containers and recommends that flag. Docker's advice is wrong here.
`-f compose.yaml` names reverseproxy as the orphan. `bin/jungle.up.sh` names all
your app containers as the orphans. Taking the advice deletes half the stack and
returns you to `000` on every endpoint.

## Step 3 — Derive the stack from compose

Do not guess the service list.

```bash
docker compose -f compose.yaml config --services | grep <preset>
```

One logical service is often several compose entries:

- A Laravel API is **both** `api-x.weroad.wr` (nginx) **and**
  `laravel.api-x.weroad.wr` (php-fpm). nginx alone returns 502.
- A Nest API is `nest-api-x` **or** `nest.api-x`. The naming is inconsistent.

Follow `depends_on` into `postgres`, `redis`, `rabbitmq` and `meilisearch`. Stop
there.

## Step 4 — Clone the repos those services build from

Clone over **HTTPS**, into the jungle root. Build contexts are relative paths.

There is no `ssh` binary, it cannot be installed, and `github.com:22` is blocked.
`bin/repo.init.sh` therefore cannot run here. Clone one repo at a time.

Then merge:

```bash
node scripts/compose.merge.js --target=development --no-deps=true
docker compose -f compose.yaml config --services | wc -l    # expect 88
```

If the merge fails on a missing `dbt/` or `dlt-pipelines/` compose file, the setup
script's stubs are gone. Two 4-line stubs fix it. **Do not write a compose slicing
tool.** `--no-deps` is the service selector.

## Step 5 — Build the override in /tmp

Build every override under `/tmp`, never in the working tree. Run `git status`
before you finish.

### 5a — CA trust

Containers do not trust the egress-proxy CA. pnpm then sits at `downloaded 0`
forever, and composer reports `self-signed certificate in certificate chain`. It
reads as a network stall. It is not.

```bash
jungle-ca-inject compose.yaml > /tmp/override.yaml
```

### 5b — IPv4 php-fpm pool for every `laravel.*` service

There is no IPv6 here. The shipped `zz-apko.conf` listens on `[::]:9000`, php-fpm
never starts, and nginx returns 502. Copy `zz-apko.conf` from beside this skill to
`/tmp/zz-apko.conf`, then mount it on each `laravel.*` service:

```yaml
volumes:
  - "/tmp/zz-apko.conf:/etc/php/php-fpm.d/zz-apko.conf:ro"
```

⚠️ **Keep the `[global]` and `[www]` headers.** The image also ships
`zz-weroad-fpm.conf`. That file loads after this one and has no section header of
its own. It inherits `[www]` positionally. If you trim the headers, its `pm.*`
directives land in `[global]` and php-fpm refuses to start.

Upstream fix: **DVO-419**, draft PR `weroad/infrastructure#613`.

### 5c — Layer `local.env` where a repo ships one

Read **every** env file a repo ships (`ls <repo>/deploy/`), not only
`development.env`. Where a `local.env` exists, layer it on top. That is the
documented convention, and its values are the local `.wr` ones. Without it a
frontend whose `development.env` points at a staging API keeps talking to staging.

```yaml
env_file:
  - { path: ./<repo>/deploy/development.env, required: false }
  - { path: ./<repo>/deploy/local.env,       required: false }
```

Where `local.env` points at a sibling service you did not clone, override that one
variable back to its staging URL. Do not clone another repo for it.

`staging-auth.weroad.io` (FusionAuth SSO) and `staging-mailcarrier.weroad.io` are
staging **by design**. Do not build a local identity provider.

## Step 6 — Infra, then data

```bash
docker compose -f compose.yaml -f /tmp/override.yaml up -d --no-deps \
  postgresql.weroad.wr redis.weroad.wr rabbitmq.weroad.wr
```

Postgres creates about 84 databases on first boot and restarts part-way through.
A passing `pg_isready` therefore proves nothing. Gate with the jungle's own script,
which checks every expected name and creates any that are missing:

```bash
./resources/postgres/assert_databases_exist.sh
```

Then restore. If you skip the restore you get empty screens.

`./bin/database.restore.sh <db>` is the documented path. Its groot image installs
packages with apt. The apt hosts were allowlisted on 2026-08-27, so try it first.
Two caveats apply. An allowlist edit only reaches containers created **after** the
edit. And `packages.cloud.google.com` is still **not** on the allowlist, so
anything in groot's build that pulls the Google Cloud apt repository still fails.

If the build fails, fetch the dump directly. GCS and the ADC both work:

```bash
TOKEN=$(node -e "const j=require('/root/.config/gcloud/application_default_credentials.json');
  const b=new URLSearchParams({client_id:j.client_id,client_secret:j.client_secret,
  refresh_token:j.refresh_token,grant_type:'refresh_token'});
  fetch('https://oauth2.googleapis.com/token',{method:'POST',body:b})
    .then(r=>r.json()).then(t=>console.log(t.access_token))")
BUCKET=weroad-eu-infrastructure-production

# list the available dump dates instead of guessing one, newest last
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://storage.googleapis.com/storage/v1/b/$BUCKET/o?prefix=anonymization/databases/&delimiter=/&fields=prefixes"

curl -H "Authorization: Bearer $TOKEN" -o dump.sql.gz \
  "https://storage.googleapis.com/storage/v1/b/$BUCKET/o/anonymization%2Fdatabases%2F<date>%2F<db>.sql.gz?alt=media"

gunzip -c dump.sql.gz | docker exec -i jungle-postgresql.weroad.wr-1 psql -U admin -d <db>
```

⚠️ Verify afterwards. A restore can report success and leave an empty database.
Count tables **and** rows, not tables alone.

## Step 7 — Start the services

```bash
docker compose -f compose.yaml -f /tmp/override.yaml up -d --build --no-deps <services>
```

Facts to expect:

1. Services self-bootstrap at runtime. They run `pnpm install` or `composer
   install`, then migrations. Quiet logs are normal, not a hang.
2. From a cold container the whole run takes about 10 to 15 minutes. pnpm and
   composer filling empty caches dominate that time, not the stack itself. After
   the caches are warm the stack serves about a minute after `compose up`.
3. Sibling APIs in `depends_on` resolve to private `:staging` images. They pull.
   You do not need them running.
4. If you recreate a `laravel.*` container, restart its `api-*` nginx too. nginx
   caches the upstream IP at startup and otherwise returns 502.

## Diagnose a blocked domain against an untrusted CA

Run `curl -D -` against the host **from inside a container**.

⚠️ **A blocked domain does not time out.** The sandbox answers `403` itself, with
the header `x-deny-reason: host_not_allowed` and a body reading
`Host not in allowlist: <host>.`

**Read the header, not the status.** A `403` without that header came from the
origin, which means the domain **is** allowed. Judging by status alone reports a
blocked host as reachable.

## Verification — the frontend must render

Finish by loading the frontend in a browser and confirming it **renders**. A `200`
can be an empty shell. Three traps sit in that check:

1. **The first load of any route is a false failure.** Vite is still optimizing
   newly discovered dependencies and aborts the in-flight module requests. You see
   `504 (Outdated Optimize Dep)`, or aborted `/_nuxt/…/deps/*` requests, and a DOM
   of about 19 elements with no text. Reload once and it renders. This recurs on
   the first visit to each deeper route.
2. **An SSO-gated route redirects to `staging-auth.weroad.io`**, which headless
   Chromium here cannot reach. A `chrome-error` on a protected route is usually
   correct behaviour. Trace the navigation before you call it a fault.
3. **Headless Chromium cannot complete TLS to any external host.** CDN images and
   webfonts look broken in a screenshot even though containers reach them. Verify
   an external host with `curl` from a container, never from the browser.

To prove the frontend uses your **local** API, do not wait for an API call that an
auth guard prevents. Do two things instead:

1. Grep the served HTML for the API base. Expect `http://api-<preset>.weroad.wr/…`
   and zero `staging-api-` hits.
2. `fetch` that base from the page context. Expect the API's own `401` JSON body.

## Report and leave it running

Report which dependencies resolved **locally** and which resolved to **staging**.
Leave the stack running.

## Trap quick reference

| Symptom | Cause | Fix |
|---|---|---|
| Every endpoint returns `000` | dockerd died | restart dockerd (Step 1) |
| Every endpoint returns `000` | `/etc/hosts` wiped | re-seed from `bin/hosts.sh` (Step 1) |
| Every endpoint returns `000` | someone passed `--remove-orphans` | rebuild the deleted half (Step 2) |
| `compose config` fails on missing `dbt/` | the `extends:` stubs are gone | rewrite the two 4-line stubs (Step 4) |
| pnpm at `downloaded 0`, composer self-signed error | container does not trust the proxy CA | `jungle-ca-inject` (Step 5a) |
| Every `laravel.*` service returns 502 | php-fpm cannot bind `[::]:9000` | mount the IPv4 pool (Step 5b) |
| One `laravel.*` service returns 502 after a recreate | nginx cached the old upstream IP | restart its `api-*` nginx (Step 7) |
| Frontend calls a `staging-api-` host | `local.env` not layered | layer it (Step 5c) |
| Route renders an empty DOM, `504 Outdated Optimize Dep` | Vite is still optimizing | reload once (Verification) |
| Host returns `403` | read `x-deny-reason` before you conclude | see Diagnose section |
| Restore "succeeded", screens empty | dump did not land | count tables **and** rows (Step 6) |

## Red flags — stop

- You are about to pass `--remove-orphans` because Docker suggested it.
- You are about to write a compose slicing tool.
- You are about to run `bin/hosts.init.sh`.
- You are about to run `bin/repo.init.sh`, or clone over ssh.
- You are about to write an override file into the working tree.
- You are about to trim the `[global]` or `[www]` header out of `zz-apko.conf`.
- You are about to call a host reachable because it returned a status code.
- You are about to build a local FusionAuth.
- You are about to clone a third repo to satisfy one variable in `local.env`.

## Open items — state them, do not assume them

- **DVO-419** is the upstream php-fpm IPv6 bug. The mount in Step 5b is a
  workaround. The upstream patch should add an explicit `[www]` beside its
  `listen` line, so it does not depend on file ordering it cannot control.
- `packages.cloud.google.com` is **not** allowlisted. Confirm groot does not need
  it before you call `./bin/database.restore.sh` fixed.
- An allowlist edit only reaches containers created after the edit. Start a fresh
  session before you test a new entry.
- `compose.merge.js --target=staging` resolves refs to `project/<name>/staging:latest`.
  That tag does not exist — real tags are timestamps. `--target=staging` was never
  exercised in the spike.
- The Docker Hub `429` on the first pull burst is **not corroborated**. Six images
  pulled with no `429`.
- `partner/admin/deploy/development.env` is the one env-file outlier in the repo.
  The permanent fix adds `./partner/admin/deploy/local.env` to that service's
  `env_file` list, matching the `weflight-radar` pattern in `compose.com.yaml`, then
  checks the other 42 services for repos that ship a `local.env`. That fix helps
  laptops too.

## Worked examples

| Preset | Resolves to |
|---|---|
| `partner` | 4 services across 2 repos, on postgres/redis/rabbitmq |
| `catalog` | 3 services, and pulls in **meilisearch**, which partner never needed |
| `my` | 5 entries from 2 names — an admin frontend, plus one API fronted by nginx with **both** a Laravel and a Nest runtime behind it |

Nothing downstream of the preset name needs maintaining. Derive the compose
services from the preset, the repos from each build context, and the infra by
following `depends_on`. Add a service to the jungle and the preset updates itself.
