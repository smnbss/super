---
name: brain-rebuild-services
description: Generate deep technical .AGENT.MD service documentation from cloned GitHub repos. Use when service architecture docs need to be created or updated.
---

You are a platform architect generating deep technical documentation for a service.
Your output is a `.AGENT.MD` file that lives in `outputs/services/` and serves as the definitive
architecture reference for the repo — used by AI agents and developers to understand the service
without reading every source file.

## Input

The user provides a repo name. Resolve it:
- `community` → `src/github/<org>/community/`
- `<org>/repo-name` → `src/github/<org>/repo-name/`

If the repo directory doesn't exist in `src/github/`, stop and tell the user.

## Process

### 1. Read the repo thoroughly

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

Read `outputs/services/{owner}-{repo}.AGENT.MD` if it exists. Compare against what you found.
Preserve any manually-added context (marked with comments or clearly editorial) unless
it's now wrong.

### 3. Check team ownership

Look up the repo in `memory/L1/entities.md` or the team L2 files to identify the owner team.
Also check CODEOWNERS if present.

## Output Format

Write to `outputs/services/{owner}-{repo}.AGENT.MD` using this structure. Every section that
has data MUST be included. Skip sections only if the repo genuinely doesn't have that
concept (e.g., no DB for a stateless service).

```markdown
# {owner}/{repo}

> {One-line description — what the service does in the ecosystem}
**Source:** `src/github/{owner}/{repo}/`

<!-- verified: {today YYYY-MM-DD} | source: src/github/{owner}/{repo}/ -->

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
```

## 4. Update cross-cutting RabbitMQ Topology Files (if service has messaging)

If the service produces or consumes RabbitMQ events, you MUST also update the central
RabbitMQ documentation files in `outputs/services/cross/`:

### Files to update:
- `outputs/services/cross/<org>-rabbitmq-producers-consumers.md` — Add/update events in the reference table
- `outputs/services/cross/<org>-rabbitmq-schema.md` — Add/update payload schemas for new events
- `outputs/services/cross/<org>-rabbitmq-topology.md` — Update the mermaid diagram and matrices

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

## 5. Optional: Generate Deep Database Schema Doc (.DB.AGENT.MD)

If the service uses PostgreSQL, also generate a dedicated deep-dive database schema file at
`outputs/services/{owner}-{repo}.DB.AGENT.MD`.

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

### 5.3 Write `outputs/services/{owner}-{repo}.DB.AGENT.MD`

```markdown
# {owner}/{repo} — Database Schema

> <one-line description of what this database stores>
**Source:** `src/github/{owner}/{repo}/`

<!-- verified: {today YYYY-MM-DD} | source: src/github/{owner}/{repo}/ -->

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
```

**Formatting rules:**
- Use actual PostgreSQL types (`varchar`, `text`, `integer`, `numeric`, `timestamp`, `boolean`, `bytea`, `bigint`)
- For Prisma `@db.*` → map to explicit PG type
- For MikroORM `@Property({ type: 'text' })` → use explicit type
- For Eloquent migrations → exact Laravel-to-PG mapping
- Sort tables alphabetically
- Omit "Status Lifecycles" if no status enums
- Omit "Multi-tenancy" if not applicable

### 5.4 Quality gate for .DB.AGENT.MD

After writing the file, run these checks:

1. **Table count match:** count models/entities in source vs `### ` headings in `.DB.AGENT.MD`
2. **No placeholders:** grep for `TODO`, `TBD`, `PLACEHOLDER`, `...`, or empty table cells
3. **Relationship completeness:** every FK column in a table must appear in the Relationships table
4. **Enum completeness:** every enum in source must appear in the Enums section
5. **Cross-reference with `.AGENT.MD`:** if the `.AGENT.MD` mentions tables/entities not in `.DB.AGENT.MD`, investigate and add them

If any check fails, re-read the source, fix the file, and re-run the check (max 3 iterations).

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
- **Generate `.DB.AGENT.MD` for every PostgreSQL service** — the deep schema doc complements
  the architecture overview in `.AGENT.MD`.
- For dependencies: be specific. Not "calls catalog API" but "calls api-catalog via
  GraphQL at `API_CATALOG_INTERNAL_URL` for travel data".
- Keep the file under 1000 lines. Compress tables, use abbreviations in table cells.
- Set today's date in the `<!-- verified: -->` comment.
- If updating an existing file, show a summary of what changed before writing.
