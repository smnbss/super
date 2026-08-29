---
name: brain-work-on-google-cloud
description: >-
  Create a GCP VM that runs one WeRoad jungle service stack, and start a detached
  Claude agent on it. Use when the user says "work on <service> in google cloud",
  "work on <service> in gcp", "spin up a cloud dev box", or wants a jungle stack on
  a real machine instead of the laptop. Runs several sessions at once, one VM each.
  The agent runs ON the VM under tmux, so work continues while the laptop is closed.
---

# Brain — Work On, in Google Cloud

This skill gives one WeRoad service a running stack on its own GCP machine, then
starts a Claude agent on that machine. The agent runs under tmux. Work continues
while the operator's laptop is closed.

## Operating rules

1. **The agent runs ON the VM.** A laptop-side agent stops when the lid closes.
   That is the requirement this skill exists to meet.
2. **Never run `gcloud auth application-default revoke`.** The VM ADC holds the
   same refresh token as the laptop ADC. A revoke destroys the operator's local
   credentials. Delete the credential files instead.
3. **Never run `./bin/hosts.init.sh` on the laptop.** It rewrites tracked compose
   files. The VM is the only correct place.
4. **Run `session refresh-ip` when everything times out.** The firewall allows one
   address. A change of network breaks SSH and HTTP together, with no other symptom.

## Verbs

```
jungle_up_gcp.sh golden build [--refresh]
jungle_up_gcp.sh session create <repo|preset> <session>
jungle_up_gcp.sh session up <session>
jungle_up_gcp.sh session refresh-db <session> [db...]
jungle_up_gcp.sh session agent start <session> "<prompt>"
jungle_up_gcp.sh session agent log <session>
jungle_up_gcp.sh session agent attach <session>
jungle_up_gcp.sh session list | stop <s> | rm <s>
jungle_up_gcp.sh session mount <s> | unmount <s>
jungle_up_gcp.sh session refresh-ip <s>
```

## Steps

1. Read the context on the laptop. Read `DEVELOPER.md`, the matching repo under
   `github/weroad/jungle/`, the service docs in `outputs/services/`, and any prior
   session in `outputs/projects-work-on/<repo|preset>/`.
2. Confirm a golden image exists. Run `golden build` when it does not.
3. Run `session create <repo|preset> <session>`.
4. Run `session agent start <session> "<prompt>"`.
5. Open the printed Chrome command. Confirm the page renders.
6. Close the laptop. Read progress later with `session agent log <session>`.

## Measured behaviour — verified 2026-08-27 on a real VM

Do not re-derive these. Each cost a failed run.

1. **`--allow=tcp:22,80,443` is wrong.** gcloud reads `80` and `443` as protocol
   names. Write `tcp:22,tcp:80,tcp:443`.
2. **jungle binds the reverse proxy to `127.0.0.1:80`** (`compose.jungle.yaml`).
   On a remote VM the stack is unreachable whatever the firewall allows.
   `files/reverseproxy-expose.yaml` republishes it on `0.0.0.0`.
3. **`repos.sh` lists all 72 repos as `git@github.com:` SSH URLs.** The VM has no
   GitHub SSH key. The skill injects `~/.git-credentials` and an `insteadOf`
   rewrite, using the `repo`-scoped token from `~/.npmrc`.
4. **The jungle root `package.json` declares no `packageManager` and no
   `engines`.** It installs with `npm`. pnpm matters inside the service repos, not
   at the root.
5. **Node 20 is too old.** corepack's default pnpm 11 crashes on it with
   `ERR_UNKNOWN_BUILTIN_MODULE`, which reads as a broken install. Use Node 22.
6. **`compose.merge.js` needs `dbt/` and `dlt-pipelines/` stubs** whenever the
   clone is partial. Both directories are gitignored.
7. **GCE Ubuntu 24.04 HAS IPv6.** php-fpm binds `[::]:9000` and serves. DVO-419
   does not apply here. The probe stays for hosts that lack IPv6.
8. **nginx caches the php-fpm upstream IP at startup.** A `laravel.*` container
   that starts after its `api-*` nginx gives a permanent 502. Restart the nginx.
9. **A partner stack is FOUR compose services**, not one:
   `laravel.api-partner.weroad.wr`, `api-partner.weroad.wr`,
   `nest-api-partner.weroad.wr`, `partner.weroad.wr`. Derive the set. Never guess.

## Measured behaviour — verified 2026-08-29 on a real VM

Found while starting a beye session. Tracked as SIM-63.

10. **The golden image does not need the repos.** `docker compose -f compose.yaml config`
    parses cleanly with 57 of 60 build contexts absent, because compose.yaml is generated
    up front and lists every service whatever is on disk. So a partial image is a slow
    first session, never a broken one. `files/ensure-repos.sh` clones what a session
    actually builds from, on the VM.
11. **A 3xx is a healthy answer.** beye redirects to `/auth/login` and on to
    `staging-auth.weroad.io`; partner behaves the same. Only a 4xx, a 5xx, no response,
    or a 200 with an empty body is a failure.
12. **beye authenticates against staging-auth.weroad.io, not the local FusionAuth.** Do
    not start `fusionauth.weroad.wr` for it. The callback is
    `http://beye.weroad.wr/auth/callback`, so the Chrome host-resolver mapping is what
    makes the login return.
13. **The operator ADC must keep being copied, and a registry audit does not prove
    otherwise.** Dropping it was tried on 2026-08-29 and reverted the same day. Nothing
    pulls from a private registry — true, and beside the point. **Jungle compose
    bind-mounts `~/.config/gcloud` into the containers and services authenticate to
    Google APIs with it at RUNTIME.** `api-beye` reads and writes the bucket
    `weroad-eu-api-beye-development` that way, and without the ADC it returns 403 on
    dashboard content while the rest of beye keeps working. The real fix is IAM on the VM
    service account, in a WeRoad project — not a change to this script. `SKIP_ADC=1` opts
    out for a stack that provably needs no Google API at runtime.
14. **`run` always returns 0, so `run cmd || die` can never fire.** Use `run_checked` for
    any command whose failure must stop the script. `session create` reported success for
    a branch it never created because of this.
15. **Databases are the one thing nothing refreshed.** `golden build` restores them once,
    at image-build time; `session create` never touched them. `session refresh-db`
    restores only the session's own databases — one, not 84.
16. **The service-to-database mapping is NOT in the resolved compose config.** Only 5 of
    ~88 services expose any DB variable through `docker compose config`, because the
    jungle declares env with the long-form `env_file: [{path: …}]`, which compose does
    not inline. Read the name from each repo's own deploy env file, and note that BOTH
    spellings are needed: `DB_NAME` (NestJS, `beye` → `api_beye`) and `DB_DATABASE`
    (Laravel, `api-partner` → `api_partner`).

⚠️ **Run the guard tests after ANY edit to the script.** No network, no VM:

```
node tests/test_jungle_up_gcp.mjs
```

Its dead-code check exists because five functions in this file were defined and called by
nothing, while SKILL.md documented all five as live.

## A VM agent has NO MCP servers — give it a Linear API key instead

⚠️ Measured 2026-08-29: `claude mcp list` on a fresh session VM prints *"No MCP servers
configured"*. claude.ai connectors are an **account** feature delivered by the Claude app;
the `claude` CLI reads MCP servers from `~/.claude.json` and `.mcp.json` only, and
`CLAUDE_CODE_OAUTH_TOKEN` carries no connector configuration. Being "logged in" changes
nothing.

The symptom is not an error: a careful agent stops and asks for the issue text, which
reads as obtuseness. It cannot see Linear at all.

`session create` now fetches `wr-linear-api-key` from Secret Manager and appends
`LINEAR_API_KEY` to `~/.claude-env`. The key goes in the header **bare** — no `Bearer`.

⚠️ **A Linear API key acts as the operator across the WHOLE workspace, read AND write.**

⚠️ `inject_linear_auth` MUST run AFTER `inject_agent_auth`, which deletes and rewrites
`~/.claude-env`. The order is load-bearing.

⚠️ The credential-free fallback still works: scp the issue body to the VM and say in the
prompt that the file is **authoritative and complete** — without that wording an agent
stops to ask whether it is missing context.

## The first argument is a repo OR a preset

`session create <repo|preset> <session>` takes one name and uses it three ways: the
git directory to branch on the VM, the pattern `derive_services` greps compose with,
and the VM name. A **preset** is a name that selects a whole stack rather than one
repo — `partner` derives four compose services, `my` likewise. The script holds no
preset list. The grep is the mechanism.

The session workspace is `outputs/projects-work-on/<repo|preset>/<session>/`, the
same shape `brain-work-on` uses, so a local session and a cloud session on the same
repo group together and one session's notes, plan, `.linear.json` and
`.jungle-vm.json` sit side by side.

⚠️ **This layout changed on 2026-08-29.** It used to be flat —
`outputs/projects-work-on/<session>/` — which put a session exactly where a repo
directory belongs. `state_path` still resolves the flat form so an existing session
keeps working, but nothing writes it any more.

⚠️ **Every verb but `create` takes only `<session>`**, so the directory is resolved
by searching for that name. Two scopes carrying the same session name is refused,
not guessed — a wrong guess would point `rm` at the wrong VM.

## Seeing two sessions at once

Two session VMs both serve `partner.weroad.wr` on different addresses. Use one
Chrome instance for each session.

    open -na "Google Chrome" --args \
      --user-data-dir=/tmp/chrome-<session> --no-first-run \
      --host-resolver-rules="MAP *.weroad.wr <VM_IP>" \
      "http://partner.weroad.wr/"

`--user-data-dir` is mandatory. Without it, `open` gives the URL to the running
Chrome and you reach the wrong stack. Verified against two live VMs on 2026-08-27:
the `Host` header arrives unmodified and nginx-proxy routes correctly.

## Why this duplicates setup_gcp.sh

`brain-clone-in-gcp/setup_gcp.sh` also creates a VM, detects the caller's public IP
and scopes a firewall rule to it. This skill reimplements all three, because
`setup_gcp.sh` additionally installs Ollama, Chromium, three AI CLIs and the
`super` bootstrap, and copies `.env.local` and both sources files.

⚠️ **Two copies of the IP and firewall logic now exist and will drift.** An
upstream fix does not reach this skill.

## The mount is optional

Each session can mount its VM with Fuse-T and `fuse-t-sshfs`. The agent runs on the
VM, so the mount is a convenience for browsing files while attached. It is not the
work surface.

Two sources state different licence terms.

1. `fuse-t.org` states: "Free for personal use. Commercial license available for
   embedding and shipping Fuse-T in a product."
2. `License.txt` states: "For commercial use or/and bundling with commercial
   software, the software vendor has to obtain a commercial license."

Simone chose the website reading on 2026-08-27. This skill never installs Fuse-T
silently. The preflight prints both readings and stops. mutagen (MIT) is the
alternative.

## Agent authentication

Claude on the VM talks to **Anthropic directly**. It does not go through WeRoad's
LiteLLM proxy.

**The token never passes through a laptop file, a shell history or an agent
context.** It is created once, straight into Secret Manager, and each VM fetches it
with its own service account.

### One-time setup

1. Create the secret. The pipe matters: the token is never printed.

   ```
   claude setup-token                      # interactive; prints the token
   read -rs TOK && printf '%s' "$TOK" | \
     gcloud secrets create claude-agent-token --data-file=- --project <project> && unset TOK
   ```

   ⚠️ **Do NOT pipe `claude setup-token` straight into the secret.** It is
   interactive, so the pipe stores its banner, its URL and ANSI colour codes —
   about 2000 bytes of terminal output. That fetches successfully and then fails
   three steps later as a bare "Not logged in". `read -rs` does not echo and does
   not enter shell history. The skill now validates the shape and says so.

2. Let the VM service account read it.

   ```
   gcloud secrets add-iam-policy-binding claude-agent-token --project <project> \
     --member "serviceAccount:<vm-service-account>" \
     --role roles/secretmanager.secretAccessor
   ```

3. Rotate later by adding a version. Every future VM picks it up with no code change.

   ```
   claude setup-token
   read -rs TOK && printf '%s' "$TOK" | \
     gcloud secrets versions add claude-agent-token --data-file=- --project <project> && unset TOK
   ```

### Resolution order

⚠️ **Any credential file this script writes must also be listed in `scrub_credentials`.**
`~/.claude-env` was not, so `jungle-golden-20260827` shipped a live LiteLLM API token and
so did every VM built from it. A machine image is a copyable artifact.

⚠️ **`session create` deletes `~/.claude-env` before writing one.** Every write uses `>`,
but a failed fetch writes nothing, so a stale credential would otherwise survive — which
is exactly how a VM ended up using the removed LiteLLM route.


1. `CLAUDE_CODE_OAUTH_TOKEN` in the environment, for a one-off run.
2. `ANTHROPIC_API_KEY` in the environment, for API-key users.
3. Secret Manager, fetched on the VM. This is the intended path.

⚠️ **Scopes are fixed when the instance is created.** The default compute scopes do
NOT reach Secret Manager, so `vm_create` passes `--scopes=cloud-platform`. A VM built
without it cannot fetch the token however the IAM is set, and the failure looks like
a missing secret. Changing the scope afterwards needs the instance stopped.

⚠️ The LiteLLM proxy route was removed on 2026-08-27. `litellm.weroad.io` sits behind
Cloudflare Access, so a GCP VM receives HTTP 302 to `weroad.cloudflareaccess.com` and
Claude Code reports "API returned an empty or malformed response (HTTP 200)". Whether
LiteLLM exposes an Anthropic-compatible `/v1/messages` was never verified either. Do
not reintroduce it without testing both.

## Linear tracking

⚠️ **These rules are one of THREE copies.** `brain-work-on` Step 9 holds the first,
`brain-work-on-new-issue` the third. A change to the Linear conventions must land in
all three.

**Opening the NEXT issue on a session is `brain-work-on-new-issue`'s job, not this
skill's.** It reads `.jungle-vm.json` for the repo, VM, zone, image and branch, so a
cloud session created without tracking can still get its first issue — and it knows
not to close an issue whose branch exists only on the VM.

Three tiers. One session issue. One sub-issue for each plan phase. One comment
thread as the request log.

1. Resolve the team from the IDP service owner (Internal Developer Platform,
   `src/idp/<service>/service.md`), through `brain.config.yml` `linear_key`. Never
   infer a Linear key from a team name.
2. Fall back to `linear.fallback_team`. Ask the user when it is unset.
3. Leave `estimate` and `cycle` unset.
4. Never create a label.
5. Sync one direction only: the plan file to Linear.
6. Read `.linear.json` first and reattach. Never create a second issue on a re-run.
7. Record the VM name, the zone, the golden image version and the branch.

## Cost

Each session VM carries its own 200 GB disk. A running VM costs about EUR 0.25 each
hour. A stopped VM costs about EUR 18 each month for the disk. Run `session rm` at
the end of a work stream. `session rm` refuses while the branch is unpushed,
because code exists only on the VM.
