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
jungle_up_gcp.sh session create <repo> <session>
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
   session in `outputs/projects-work-on/<repo>/`.
2. Confirm a golden image exists. Run `golden build` when it does not.
3. Run `session create <repo> <session>`.
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

`super-clone-in-gcp/setup_gcp.sh` also creates a VM, detects the caller's public IP
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

## Agent authentication — the one open blocker

⚠️ **MEASURED 2026-08-27: `litellm.weroad.io` sits behind Cloudflare Access.** A GCP
VM receives HTTP 302 to `weroad.cloudflareaccess.com`. Claude Code follows it into
an HTML login page and reports "API returned an empty or malformed response
(HTTP 200)". The laptop works only because it already holds an Access session.

Three ways to authenticate the agent, best first.

1. **A Cloudflare Access service token for `litellm.weroad.io`.** Keeps the calls
   cost-monitored. Set `CF_ACCESS_CLIENT_ID` and `CF_ACCESS_CLIENT_SECRET`, and the
   skill writes `ANTHROPIC_CUSTOM_HEADERS` on the VM. Ask DevOps for the token.
2. **`ANTHROPIC_API_KEY`.** Works immediately. Bypasses cost monitoring.
3. **`claude setup-token`, run on the VM once.** Interactive, so it cannot be
   automated, and it must not be baked into the golden image.

## Linear tracking

⚠️ **These rules are a second copy. `brain-work-on` holds the first copy.** A change
to the Linear conventions must land in both skills.

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
