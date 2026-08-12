---
name: brain-rebuild-services
description: >-
  Generate deep technical `.agent.md` service documentation from cloned GitHub
  repos. Use when service architecture docs need to be created or updated.
---

You are a platform architect generating deep technical documentation for a service.
Your output is a `.agent.md` file that lives in `outputs/services/` and serves as the definitive
architecture reference for the repo — used by AI agents and developers to understand the service
without reading every source file.

## Input

The user provides a repo name. Resolve it, checking these locations in order and
using the first that exists:
- `github/weroad/jungle/<repo>/`  ← jungle-managed repos (the local dev stack) live nested here
- `github/<org>/<repo>/`          ← brain-only repos cloned flat (default `<org>` is `weroad`)

So `community` → try `github/weroad/jungle/community/` first, then `github/weroad/community/`.
A `<org>/repo-name` input maps to `github/<org>/repo-name/` (and, for weroad, its jungle nesting).

Prefer the jungle-nested copy when both exist (it's the one pull_sources keeps fresh).
Record the actual resolved path in the doc's `Source:`/`source:` fields.

If the repo directory exists in neither location, stop and tell the user.

## Step 0 — Change gate (MANDATORY, before you read a single source file)

**A repo whose HEAD has not moved gets no work at all.** Not a re-read, not a
re-count, not a bumped `verified:` date. This gate is the difference between a
morning that costs a few hundred model requests and one that costs a few
thousand, and it must be run *before* the "read the repo thoroughly" step below —
which, taken unconditionally, re-reads every migration and controller in the repo
to rediscover what the existing doc already says.

### 0.1 Prefer the ledger over guessing

`pull_sources` writes `.github-changed-repos.tsv` at the brain root — one TSV line
per repo whose HEAD moved during that export, truncated per run:

```
<owner>/<repo>	<reldir>	<before_sha>	<after_sha>
```

- Invoked **without** a repo name (a full refresh wave): read the ledger and
  process exactly the repos listed, using each line's `before_sha` as the delta
  base. **An empty ledger is a complete answer** — report "no repos moved, 0 docs
  regenerated" and stop. Do not fall back to scanning all clones.
- Invoked **with** a repo name: honour it even if it isn't in the ledger (the user
  asked), but still run 0.2 — the answer is usually "unchanged, nothing to do".
- Ledger absent (a standalone run, or `pull_sources` predates it): fall back to
  0.2 per repo. Never treat a missing ledger as "everything changed".

### 0.2 Compare recorded HEAD against actual HEAD

Every doc records the commit it was generated from, in its `verified:` comment:

```markdown
<!-- verified: 2026-08-05 | source: github/weroad/jungle/airflow/ | head: 015f2dd2 -->
```

Resolve **both sides to full SHAs before comparing** — the doc stamps a short sha,
the ledger carries a full one, and a bare string compare of the two forms reports a
change that isn't there (harmless but pays for a full pass every single day, which
is exactly the cost this gate exists to avoid):

```bash
REPO=github/weroad/jungle/<repo>
DOC=outputs/services/weroad/jungle/<repo>.agent.md
RECORDED=$(sed -n 's/.*| head: \([0-9a-f]\{7,\}\).*/\1/p' "$DOC" | head -1)
RECORDED_FULL=$(git -C "$REPO" rev-parse -q --verify "${RECORDED:-none}^{commit}" 2>/dev/null || echo unknown)
ACTUAL_FULL=$(git -C "$REPO" rev-parse HEAD)
```

| Situation | What to do |
|---|---|
| `RECORDED_FULL` == `ACTUAL_FULL` | **Stop. Write nothing.** Report `<repo>: unchanged at <sha> — skipped`. Do **not** touch the `verified:` date: a bumped date on unexamined content is a lie the freshness system then trusts. |
| Both resolve, and differ | Incremental pass — go to 0.3. |
| No doc yet | First generation — full read (the `## Process` below as written). |
| `RECORDED_FULL` == `unknown` (no `head:` stamped, or the commit is gone after a force-push / re-clone) | Full read once, and emit `head:` this time so the next run can gate. |

### 0.3 Read the diff, not the repo

```bash
git -C <repo-path> log  --oneline "$RECORDED..HEAD"
git -C <repo-path> diff --name-only "$RECORDED..HEAD"
```

Those two outputs define the entire input for an incremental pass, alongside the
existing doc. **Read only files in the changed set**, plus any file you must open
to explain a changed one (the entity a new migration alters, the module a new
controller registers into).

**Inventory claims are carried forward, not recounted.** A count or list in the
doc ("312 database table configs", "36 gsheet configs", "9 CI workflows", "96
consumer classes", "0 AMQP usages") may only be restated or changed when the diff
touched the paths that produce it. If `git diff --name-only` shows nothing under
`database_configs/`, then the config count *cannot* have changed — copy the number
through and say nothing about it. Do not write "re-verified, unchanged": that
sentence is only earned by a re-read, so it invites one, and the re-read is the
single most expensive thing this skill does. Verify by absence-in-diff instead.

Then follow `## Process` for the changed surfaces only, and write the doc with the
new `head:`, today's `verified:` date, and the changelog discipline in
[Changelog & size discipline](#changelog--size-discipline).

### 0.4 Inert diff — HEAD moved, but nothing a doc can describe

Step 0.2 skips a repo when HEAD is **unchanged**. That is not the common case.
The common case is HEAD moved by a commit that cannot change any sentence in the
doc, and until now those got a full incremental pass. Classify the changed set
from 0.3 **before** reading anything:

```bash
git -C <repo-path> diff --name-only "$RECORDED..HEAD" \
  | grep -vE '(^|/)(CHANGELOG\.md|\.release-please-manifest\.json|pnpm-lock\.yaml|package-lock\.json|composer\.lock|poetry\.lock|uv\.lock|yarn\.lock|LICENSE|\.gitignore|\.editorconfig)$' \
  | grep -vE '^\.github/(gemini|copilot|dependabot)' \
  | grep -vE '^(docs|\.claude)/.*\.md$'
```

**Empty output → INERT.** Stamp the new `head:` and today's `verified:` date on the
existing doc and change **nothing else**. Report `<repo>: inert diff (<n> commits,
release/lockfile/CI only) — stamped, not regenerated`.

Two extra checks before declaring inert, because a version bump *is* a fact the doc
carries: if `package.json`/`composer.json`/`VERSION` changed, diff them and confirm
only the `version` field moved — then update the doc's version number and the
release-narrative bullet, still without re-reading source. If a `deploy/*.env`
changed, confirm the diff is only `${HELMSECRET}:` ciphertext (a secret rotation) —
that is inert for architecture, and worth one changelog line.

This rung is the single largest saving available to this skill, and the evidence is
in the docs it already wrote: `doc-sync.agent.md` records that **1.7.1 was "no code
whatsoever"** — one `chore: add github-token` plus the release-please bump. A human
established that by re-reading the repo. `git diff --name-only` establishes it for
free. Repo HEADs move on `chore: add Gemini config`, `chore(main): release X.Y.Z`
and Dependabot bumps far more often than on architecture.

## Step 0.5 — Is this a docs-first repo?

Teams now maintain first-party documentation **inside their repos** under
`docs/domain/`, which `doc-sync` mirrors to an Outline collection on
docs.weroad.com (and which lands in the brain twice over: in the clone, and in
`src/outline/<Collection>/`, gbrain-indexed). Where that tree exists it is
better than anything this skill can generate — it is written by the people who
own the code, it carries a Feature map, a Glossary and per-feature pages, and it
is reviewed. Duplicating it here is both waste and a second version to go stale.

```bash
find <repo-path>/docs/domain -name '*.md' 2>/dev/null | wc -l
```

**≥ 10 pages → docs-first repo.** (Verified 2026-08-05: 36 jungle repos qualify —
api-catalog 63, coordinators 53, kaioh 48, api-partner 48, booking 41, buynana 37,
…. The in-repo tree is byte-authoritative; the Outline copy only reformats
markdown, so read the clone, never the export.)

### A docs-first repo gets NO `.agent.md` at all

**Decided 2026-08-12: do not generate, and do not keep, an `.agent.md` for a repo
whose documentation lives in Outline.** Not a slimmer doc, not a stub — no file. The
26 that existed were deleted in that run (8,732 lines). If you find yourself about to
create one for a docs-first repo, stop: the deletion was the point.

The replacement is strictly richer. Measured on the deleted set: dbt **1,597** Outline
pages replaced a 266-line doc, buynana **251** replaced 251 lines, coordinators **146**
replaced 354, booking **146** replaced 218, kaioh **81** replaced 238. The wiki is
written by the owning team, reviewed, and gbrain-indexed at `src/outline/<Collection>
Wiki/`; the clone's `docs/domain/` is the byte-authoritative side of the same content.

**Mapping a repo to its collection is done by document overlap, never by name.**
Collection titles do not reliably carry the repo name — verified 2026-08-12: two
collections are both titled `Partner Portal.md`, several name the repo only in
backticks, most not at all. Match `basename` sets between `<repo>/docs/domain/**` and
`src/outline/*/**` and take the best overlap; 26 of 27 docs-first repos mapped
unambiguously that way (`n8n-workflows`, 331 pages, matched **nothing** — it has no
collection, so it keeps its doc).

Two things still have to exist, and neither is the per-repo narrative:

- **`.db.agent.md` stays, in full.** The wikis do not document columns. 34 survive.
- **The `cross/` RabbitMQ topology files stay**, and Step 4 still runs for docs-first
  repos — read exchange/queue/routing-key **names** from source for that purpose only.
  Do not let it become a pretext for re-reading controllers.

The facts a deleted doc used to carry now resolve as follows — check here before
concluding something was lost:

| Fact the old doc carried | Where it lives now |
|---|---|
| Architecture, Domain Model, Request Flows, Features | `docs/domain/` + `src/outline/<Collection> Wiki/` — written and reviewed by the owning team |
| API Surface | the wiki's own generated spec, e.g. `Payments Backend Wiki/Tech/Api/api-payments — OpenAPI.md` |
| Glossary / domain vocabulary | `docs/domain/tech/glossary.md` + the wiki's Glossary page |
| Source Structure, Key Files, Testing, Configuration | the repo — cheap to `ls`/read on demand, worthless to snapshot daily |
| Database columns, enums, status lifecycles | **`{repo}.db.agent.md`** — kept, no substitute |
| Exchange / queue / routing keys | the **`cross/`** topology files, maintained by Step 4 |
| Stack per repo | `memory/L2/technologies.md`, which aggregates from manifests directly |
| Team ownership | `CODEOWNERS` + `memory/L1/teams.md` |
| **Traps / corrections** | **`outputs/services/TRAPS-from-deleted-docs.md`** — see below |

Do not grep `@Controller`/`@Resolver`/`@Cron`/`@RabbitSubscribe` and do not walk `src/`
for a docs-first repo. That enumeration was the single most expensive thing this skill
did, and it produced the worse copy of something the team already maintains.

⚠️ **Traps are the one thing a wiki structurally cannot hold**, because they are
statements that *a source is wrong* — doc-sync's live PostgreSQL column COMMENTs naming
enum values that no longer exist; `?demo=1` in wemeet-hosted-ops rendering synthetic
data; a metric that must not be quoted. A wiki documents what a service does, not the
ways its own artefacts mislead. 39 such markers across 9 of the 26 deleted docs were
extracted verbatim into **`outputs/services/TRAPS-from-deleted-docs.md`** before
deletion. Rules:

- That file is **append-only and never regenerated**. Nothing derives it; losing it
  loses knowledge that cost real debugging to find.
- A new trap discovered about a **docs-first** repo goes there, not into a resurrected
  `.agent.md`.
- On a **surviving** doc, carry its `## Traps` section forward verbatim on every pass.
  If the diff did not touch what a trap describes, the trap is still true.

**Consequence that is now live, not hypothetical:** `brain-rebuild-memory` lists
`outputs/services/**/*.agent.md` among its inputs, and `memory/L1/data-model.md` derived
specifically from `outputs/services/weroad/jungle/dbt.agent.md` — **which no longer
exists.** Its input globs must resolve to the Outline mirror instead
(`src/outline/BI Wiki/**` for data-model; `src/outline/<Collection> Wiki/**` generally),
and the surviving `.db.agent.md` set still covers schema. A memory rebuild run against
the old globs will quietly lose detail rather than fail, so treat the glob update as
part of this change, not a follow-up.

If the repo has **no** `docs/domain/` tree (or fewer than 10 pages), generate every
section as before — that knowledge exists nowhere else. Measured 2026-08-12 across
the day's 16 changed repos, the split was **6 docs-first** (api-myweroad 38,
buynana 64, coordinators 55, dbt 1196, kaioh 68, wemeet 21) and **10 not**
(actions, airflow, coordi-app, doc-sync, helm-charts, idp, infrastructure,
mailcarrier, terraform, wemeet-hosted-ops — each 0 pages under `docs/domain/`), so
expect the stub path to cover roughly a third of a typical morning and the full
path to remain the default.

## Step 0.6 — On an incremental pass, PATCH the doc; never re-emit it

Steps 0.2–0.5 cut what you **read**. This step cuts what you **write**, which on a
gated run is the larger half of the bill: these docs are 200–400 lines, and a
regeneration that changes two facts still costs 350 lines of output. Sixteen docs at
~350 lines is ~5,600 lines of generated markdown per morning, the overwhelming
majority of it retyped verbatim from the version already on disk.

**Rule: a repo that existed in the last run is edited, not rewritten.** Use targeted
`Edit` calls against the sections the diff actually touched. Reserve a whole-file
`Write` for first generation, for a repo whose `head:` was never stamped, and for an
archive rotation.

This also removes a whole class of silent regression. Retyping a 350-line doc from
context is a lossy copy: it is exactly how a `## Traps` block, a `superseded:`
marker, or a hard-won correction disappears without anyone editing it away. An
`Edit` that does not mention a section cannot damage it.

Order of work per repo, cheapest exit first:

| Gate | Outcome |
|---|---|
| 0.2 HEAD unchanged | write nothing, touch no date |
| 0.4 inert diff | stamp `head:` + `verified:` only |
| 0.5 docs-first | **write nothing at all**; never grep the source tree. `.db.agent.md` + `cross/` only |
| 0.6 incremental | `Edit` the affected sections |
| else | full read + `Write` |

**Report the gate you took, per repo, in one machine-checkable line** so the phase can
be audited rather than trusted — the orchestrator gates on this, and an unexplained
`full` on a repo whose diff was two lockfiles is the signal that this step was skipped:

```
<repo>	<gate: unchanged|inert|docs-first|incremental|full>	<commits>	<files changed>	<sections written>
```

## Process

### 1. Read the repo thoroughly

*(Full read — for first generation and non-docs-first repos. On an incremental
pass, Step 0.3 has already narrowed this to the changed files.)*

Read these files in this order (skip any that don't exist):

**Identity & config:**
- `README.md`, `CLAUDE.md`, `AGENTS.md`, `DEVELOPER.md`
- `package.json` (or `Cargo.toml`, `composer.json`, `go.mod`, `pyproject.toml`)
- `pnpm-workspace.yaml`, `turbo.json`, `nx.json` (monorepo detection)
- `.env.example`, `.env.local.template`, `deploy/*.env` (env vars)
- `Dockerfile`, `docker-compose.yml`
- `deploy/helm/values.yaml` (K8s resources, probes, replicas)

**Database & ORM:**
- For Prisma: `prisma/schema.prisma` — read EVERY model, enum, relation
- For MikroORM: `mikro-orm.config.ts` + glob `**/entities/**/*.ts` or `**/entities/*.entity.ts`
- For Kysely: `**/migrations/**` + `**/db/**`
- For TypeORM: `ormconfig.*` + `**/entities/**`
- For Laravel: `database/migrations/*.php` (all of them) + `app/Models/*.php`
- For Knex/raw SQL: `**/migrations/**`
- Read ALL migration files to understand schema evolution and current state

**Messaging & events:**
- Grep for `RabbitMQ`, `amqp`, `rmq`, `@<org>/nestjs-rmq`, `<org>-rmq`
- Find all consumers: grep for `@RabbitSubscribe`, `@MessagePattern`, `Consumer`, `consumer`
- Find all emitters/producers: grep for `publish`, `emit`, `RabbitPublisher`, `Emitter`
- Map exchange names, routing keys, payload shapes

**API surface:**
- For REST: grep `@Controller`, `@Get`, `@Post`, `@Put`, `@Delete`, `@Patch` — map all endpoints
- For GraphQL: grep `@Resolver`, `@Query`, `@Mutation`, `@Subscription` — map all operations
- For OpenAPI: read `openapi.ts`, `swagger.*`, any generated spec
- Read controller/resolver files to understand request/response shapes

**Inter-service dependencies:**
- Grep for HTTP clients: `axios`, `fetch`, `got`, `HttpService`, `@nestjs/axios`
- Find service URLs in env: `*_URL`, `*_HOST`, `*_API_URL`
- Find internal imports: `@<org>/*` packages
- Map which services this repo calls and which call it

**Auth & security:**
- Grep for `@Public`, `@CheckPermission`, `@Auth`, `Guard`, `FusionAuth`, JWT patterns
- Map auth strategy per endpoint group (public, M2M, user JWT, admin)

**Background jobs:**
- Grep for `@Cron`, `@Interval`, `cron`, `schedule`, `worker`
- Map schedule, purpose, health checks

**Testing:**
- Read test config: `vitest.config.*`, `jest.config.*`, `phpunit.xml`
- Identify test types available: unit, e2e, integration, eval

**Source structure:**
- `ls` the top-level dirs and `src/` (or equivalent) to map the module structure
- For NestJS: read `app.module.ts` to understand module wiring
- For monorepos: map each workspace and its role

### 2. Check existing service doc

Read the existing service doc if it exists (at the path defined in **Output Format** below —
jungle-managed repos live under `outputs/services/weroad/jungle/`). Compare against what you found.
Preserve any manually-added context (marked with comments or clearly editorial) unless
it's now wrong.

### 3. Check team ownership

Look up the repo in `memory/L1/entities.md` or the team L2 files to identify the owner team.
Also check CODEOWNERS if present.

## Output Format

**A doc goes under `outputs/services/weroad/jungle/` when the service is part of the jungle
local dev stack; everything else goes under `outputs/services/{owner}/`.** A service is
"jungle" if EITHER:

- it's listed in `github/weroad/jungle/bin/repos.sh` (cloned into `github/weroad/jungle/{repo}/`), OR
- `github/weroad/jungle/compose.*.yaml` defines a `{svc}.weroad.wr` service for it — this
  catches **workspace services** whose code is a subdir of another jungle repo rather than a
  standalone clone (e.g. `api-rooming` builds from `context: ./buynana` → jungle, even though
  it has no `repos.sh` entry of its own).

Everything else is non-jungle: `outputs/services/weroad/wemeet.agent.md` (mobile app, not a
compose service), `outputs/services/smnbss/super.agent.md`, etc. The **jungle repo itself**
(the dev-env container) lives at `outputs/services/weroad/jungle/jungle.agent.md` — the
package's own doc, alongside the services it runs. Create the target subdir if it doesn't
exist. Cross-cutting docs live in `outputs/services/weroad/jungle/cross/`.

**Extension MUST be lowercase `.agent.md` / `.db.agent.md`.** Never `.AGENT.MD`. gbrain's
sync classifier (`isMarkdownFilePath` in `src/core/sync.ts`) tests `path.endsWith('.md')`
**case-sensitively** — unlike its `isCodeFilePath` / `isImageFilePath` siblings, which
lowercase first. An uppercase `.MD` file is rejected with reason `strategy` and never
imported, so the doc becomes invisible to `gbrain query`/`search` and every
`[[{repo}.agent.md]]` wikilink pointing at it dangles. (Worse, uppercase can't be rescued
by a wikilink rewrite either: link extraction strips only a lowercase `.md` suffix, and
`normalizeBasename` deletes dots, so `[[cms.AGENT.MD]]` normalizes to `cmsagentmd` while
the page's index key is `cmsagent` — they can never meet.) This bit us on 2026-07-27, when
all 108 service docs turned out to be absent from the index. Verify after any rebuild:
`psql "$(gbrain config show | sed -n 's/^ *database_url: *//p')" -tAc "SELECT count(*) FROM pages WHERE slug LIKE 'outputs/services%';"`

**Filename & uniqueness rule:** the filename is the de-prefixed repo name
(`{repo}.agent.md`), NOT `{owner}-{repo}.agent.md` — the owner is the directory. gbrain
resolves wikilinks by **basename** (`global_basename: true`), so the basename MUST be
globally unique across ALL owners. This holds today (no repo-name collisions across
weroad/smnbss/NikolaiGoMedicus). If you ever add a repo whose name already exists under
another owner, keep the `{owner}-` prefix on BOTH colliding files (e.g.
`acme/{owner}-foo.agent.md`) and update the wikilinks that reference them.

Every section that has data MUST be included. Skip sections only if the repo genuinely
doesn't have that concept (e.g., no DB for a stateless service).

```markdown
# {owner}/{repo}

> {One-line description — what the service does in the ecosystem}
**Source:** `github/{owner}/{repo}/`

<!-- verified: {today YYYY-MM-DD} | source: github/{owner}/{repo}/ | head: {short sha of the commit this doc was generated from} -->

## Stack
{Bullet list: framework, language, runtime, DB, ORM, cache, messaging, auth, key libs, version}

## Source Structure
{ASCII tree of top-level dirs + key files with 1-line annotations}

## Architecture
{Paragraph explaining the architectural pattern (layered, DDD, MVC, etc.)}
{For monorepos: explain each workspace and how they relate}

## Database Schema
{Table of ALL models/entities with: name, table, key columns, relations}
{Entity relationship summary — which models reference which}
{Enum types with all values}
{Migration count and latest migration description}

## API Surface
{Table of all endpoints/operations: method, path/operation, auth, description}
{Group by domain/controller/resolver}
{Note request/response shapes for non-obvious endpoints}

## Request Flows
{For each major flow (2-5 flows): numbered steps showing the path through the code}
{Include: entry point → validation → business logic → DB → events → response}

## Messaging (RabbitMQ / Events)
### Produced Events
{Table: event name, routing key pattern, trigger, payload shape}

### Consumed Events
{Table: event name, routing key pattern, handler, what it does}

{Exchange and queue configuration}

## Inter-Service Dependencies
### This service calls:
{Table: service, protocol, purpose, env var for URL}

### Called by:
{List services that call this one, if discoverable from env/docs}

## Auth Patterns
{Map of auth strategies per endpoint group}
{Roles, permissions, scopes relevant to this service}

## Background Jobs
{Table: job name, schedule (cron expression), purpose, health check}

## Configuration
{Key env vars grouped by concern: server, DB, messaging, external services, feature flags}
{Per-market/country configuration if applicable}

## Testing
{Available test types, commands to run them, any special setup (Docker, etc.)}

## Key Files
{Table of the 10-15 most important files with purpose — the ones a developer needs first}

## Commands
{Code block with the most common dev commands: start, test, build, migrate, lint}

## Owner
{Team name}

Topics: [[services]] · [[{owner-team}]] · [[technologies]] · [[github]]{ · [[{repo}.db.agent.md]] if a DB doc exists}
```

**Footer rules:** the `Topics:` footer links back UP into the graph using **bare unique
basenames** (`global_basename` resolution) — never invent MOC names. Valid targets:
`[[services]]` (the service catalog — NOT `[[repos]]`, which does not exist), the owning
team L2 (`[[team-buktu]]`, …), `[[technologies]]`, `[[github]]`, `[[data-model]]` for
data services, and this service's own `[[{repo}.db.agent.md]]` when present. Do not emit
path-qualified links (`[[L1/…]]`, `[[../../…]]`) — the bare basename always resolves.

## 4. Update cross-cutting RabbitMQ Topology Files (if service has messaging)

If the service produces or consumes RabbitMQ events, you MUST also update the central
RabbitMQ documentation files in `outputs/services/weroad/jungle/cross/`:

### Files to update:
- `outputs/services/weroad/jungle/cross/<org>-rabbitmq-producers-consumers.md` — Add/update events in the reference table
- `outputs/services/weroad/jungle/cross/<org>-rabbitmq-schema.md` — Add/update payload schemas for new events
- `outputs/services/weroad/jungle/cross/<org>-rabbitmq-topology.md` — Update the mermaid diagram and matrices

### Process:

1. **Read all three cross-cutting files** to understand the current structure and formatting
2. **For producers-consumers.md**: 
   - Add new events to the Event Reference Table with proper routing keys, producers, consumers, and descriptions
   - Update the Exchange Summary table with accurate producer/consumer counts
3. **For schema.md**:
   - Add new event schemas under the appropriate exchange section
   - Follow the existing JSON format with field types and descriptions
4. **For topology.md**:
   - Update the mermaid diagram to include new producer/consumer connections
   - Update the Producer and Consumer matrices
   - Update the Exchange Summary counts

### Rules for cross-cutting updates:
- Preserve existing formatting and conventions
- Group events by exchange in the same order as existing sections
- Use `{cc}` placeholder for country code in routing keys (e.g., `{cc}.booking.created`)
- Mark unknown consumers/producers as `TBD` or `_source TBD_` — do not guess
- Update the `<!-- verified: -->` comment with today's date

## 5. Optional: Generate Deep Database Schema Doc (.db.agent.md)

If the service uses PostgreSQL, also generate a dedicated deep-dive database schema file at
`{repo}.db.agent.md` in the **same directory as the service's `.agent.md`** (so
`outputs/services/weroad/jungle/{repo}.db.agent.md` for jungle repos).

### 5.1 Detect PostgreSQL usage

Check these indicators **in order** (stop at first match):

| ORM | Detection file | Confirm with |
|-----|---------------|-------------|
| **Prisma** | `prisma/schema.prisma` or `*/prisma/schema.prisma` containing `provider = "postgresql"` | — (schema file is the source of truth) |
| **MikroORM** | `mikro-orm.config.ts` or `*/mikro-orm.config.ts` | Presence of `entities` glob pointing to `*.entity.ts` files |
| **Eloquent** (Laravel) | `.env.example` with `DB_CONNECTION=pgsql` **or** `config/database.php` with `'default' => ...pgsql` | `database/migrations/` directory exists |
| **Knex** | `knexfile.js` or `knex` in `package.json` dependencies | `migrations/` directory exists |
| **Kysely** | `kysely` in `package.json` dependencies | `.env.example` with `DATABASE_URL` containing `postgres` |

**Edge cases:**
- Check both root and `api/` subdirectory for monorepos.
- Document ALL database connections if multiple exist.
- Skip if the repo is a frontend-only app, CLI tool, infrastructure repo, or uses MySQL.

### 5.2 Extract schema using the appropriate strategy

**Strategy A — Prisma:**
- Read `prisma/schema.prisma` (or `api/prisma/schema.prisma`)
- Extract every `model`, `enum`, `@relation`, `@@map`, `@@index`, `@@unique`, and `///` doc comments

**Strategy B — MikroORM:**
- Find all `*.entity.ts` files
- Extract `@Entity`, `@Property`, `@Enum`, relationship decorators, `@Index`, `@Unique`, `@Filter`
- Check for shared base entities (e.g., `base.entity.ts`)
- Count migrations

**Strategy C — Eloquent (Laravel):**
- Read all files in `app/Models/` + subdirectories
- Extract `$table`, `$fillable`, `$casts`, `$dates`, `$hidden`, `$with`, relationship methods, scopes, `SoftDeletes`
- Read `database/migrations/` for column types, nullable, defaults, indexes, FKs
  - For 100+ migrations: read first 20 `create_*` + last 10 migrations
- Count migrations

**Strategy D — Knex / Kysely:**
- Read all migration files in `migrations/` or `src/migrations/`
- Extract `createTable` calls with column definitions
- Check for generated TypeScript interfaces
- Read seed files if `seeds/` exists

### 5.3 Write `{repo}.db.agent.md` (same directory as the `.agent.md`)

```markdown
# {owner}/{repo} — Database Schema

> <one-line description of what this database stores>
**Source:** `github/{owner}/{repo}/`

<!-- verified: {today YYYY-MM-DD} | source: github/{owner}/{repo}/ | head: {short sha} -->

## Overview

- **ORM**: <Prisma | MikroORM | Eloquent (Laravel) | Knex | Kysely>
- **Tables**: <count>
- **Enums**: <count>
- **Migrations**: <count> (latest: YYYY-MM-DD)
- **Connections**: <list if multi-db, otherwise "single (pgsql)">

## Tables

### <table_name>

<one-line purpose>

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| id | uuid | no | gen_random_uuid() | PK |
| ... | ... | ... | ... | ... |

**Indexes**: `idx_<name>` on (col1, col2), ...
**Unique constraints**: (col1, col2), ...

### <next_table>
...

## Relationships

| From | To | Type | FK Column | Notes |
|------|----|------|-----------|-------|
| ... | ... | ... | ... | ... |

## Enums

### <EnumName>
`VALUE_1` | `VALUE_2` | `VALUE_3` | ...

## Key Patterns

- **Soft deletes**: <list if any>
- **Timestamps**: <pattern>
- **UUID primary keys**: <yes/no, which tables>
- **Multi-tenancy**: <pattern if any>
- **Audit trail**: <pattern if any>

## Status Lifecycles

### <EntityName> Status
```
STATE_A → STATE_B → STATE_C
        → STATE_D
```

## Owner

<Team name>

Topics: [[{repo}.agent.md]] · [[data-model]] · [[services]] · [[{owner-team}]]
```

**Formatting rules:**
- Use actual PostgreSQL types (`varchar`, `text`, `integer`, `numeric`, `timestamp`, `boolean`, `bytea`, `bigint`)
- For Prisma `@db.*` → map to explicit PG type
- For MikroORM `@Property({ type: 'text' })` → use explicit type
- For Eloquent migrations → exact Laravel-to-PG mapping
- Sort tables alphabetically
- Omit "Status Lifecycles" if no status enums
- Omit "Multi-tenancy" if not applicable

### 5.4 Quality gate for .db.agent.md

After writing the file, run these checks:

1. **Table count match:** count models/entities in source vs `### ` headings in `.db.agent.md`
2. **No placeholders:** grep for `TODO`, `TBD`, `PLACEHOLDER`, `...`, or empty table cells
3. **Relationship completeness:** every FK column in a table must appear in the Relationships table
4. **Enum completeness:** every enum in source must appear in the Enums section
5. **Cross-reference with `.agent.md`:** if the `.agent.md` mentions tables/entities not in `.db.agent.md`, investigate and add them

If any check fails, re-read the source, fix the file, and re-run the check (max 3 iterations).

## Changelog & size discipline

These docs accrete. Each incremental pass wants to add a dated `<!-- YYYY-MM-DD:
HEAD … -->` note and a fresh "Recent / Earlier — shipped in vX" block, and nothing
ever removed one: by 2026-08-05 the 111 docs carried **172 dated comments totalling
140 KB** (`erp-buddy.agent.md` alone had 11), all of it re-read and re-emitted on
every regeneration of that file. `memory/` hit the same wall on 2026-07-14 and
solved it with a size cap plus verbatim archive rotation. Same rule here.

- **Keep at most 2 dated `<!-- YYYY-MM-DD: HEAD … -->` comments**: the current pass
  and the one before it. Rotate the rest **verbatim** (never summarized, never
  deleted) into `outputs/services/archive/<repo>-<YYYY-MM>.md`, appending in date
  order, and link it once from the doc: `<!-- earlier passes: [[<repo>-<YYYY-MM>]] -->`.
- **Keep at most 2 release blocks** in the body: the current unreleased set and the
  most recent released version. Older per-release narrative is already in
  `src/linear/` (441 release-note exports) and in the repo's own CHANGELOG —
  rotate it to the same archive page rather than carrying it forward.
- **40 KB hard cap** per doc, matching the `memory/` cap and for the same reason:
  oversized pages chunk badly in gbrain and dilute retrieval. If a doc is over
  after rotation, compress tables before dropping facts.
- The archive pages are ordinary curated pages — give each a `Topics:` footer
  (`[[<repo>.agent.md]] · [[services]]`) so the graph still reaches them.

## Rules

- Read the actual source code. Do not guess or infer from file names alone.
- For database schemas: list EVERY model and its columns. This is the most valuable
  part of the documentation — developers need to know what's in the DB without reading
  migration files. Include column types, nullable flags, defaults, and indexes for
  important tables.
- For messaging: capture the exact routing key patterns and payload interfaces.
  Messaging bugs are the hardest to debug — complete docs here save hours.
- **Always update cross-cutting RabbitMQ files when the service has messaging** — keep the topology
  documentation in sync with the service-level documentation.
- **Generate `.db.agent.md` for every PostgreSQL service** — the deep schema doc complements
  the architecture overview in `.agent.md`.
- For dependencies: be specific. Not "calls catalog API" but "calls api-catalog via
  GraphQL at `API_CATALOG_INTERNAL_URL` for travel data".
- Keep the file under 1000 lines **and under 40 KB**. Compress tables, use
  abbreviations in table cells, rotate old changelog entries (see
  [Changelog & size discipline](#changelog--size-discipline)).
- Set today's date **and the source commit** in the `<!-- verified: … | head: <sha> -->`
  comment. The `head:` field is not decoration — [Step 0](#step-0--change-gate-mandatory-before-you-read-a-single-source-file)
  reads it to decide whether this repo can be skipped entirely tomorrow. A doc
  written without it forces a full re-read on every future run.
- **Never bump `verified:` on a doc you did not actually re-derive.** Skipping is
  reported, not recorded — the whole freshness system downstream assumes a
  `verified:` date means someone looked.
- If updating an existing file, show a summary of what changed before writing.
