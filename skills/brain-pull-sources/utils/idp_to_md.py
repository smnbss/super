#!/usr/bin/env python3
from __future__ import annotations
"""
WeRoad IDP -> Markdown service-catalog exporter.

Pulls the whole service catalog from the Internal Developer Platform
(https://idp.weroad.com, API https://api-idp.weroad.com) and writes one folder
per service under src/idp/, containing the full API documentation rendered as
markdown:

    src/idp/index.md              catalog-wide index (all services, one table)
    src/idp/<service>/index.md    catalog metadata, links, doc availability
    src/idp/<service>/openapi.md  every path + operation + component schema
    src/idp/<service>/asyncapi.md every channel + operation + message payload
    src/idp/<service>/graphql.md  every query/mutation + type definition
    src/idp/<service>/database.md full schema: tables, columns, comments

Usage:
    python idp_to_md.py https://idp.weroad.com/
    python idp_to_md.py https://idp.weroad.com/ --limit 10   # first N services
    python idp_to_md.py https://idp.weroad.com/ --service api-booking [--service ...]
    python idp_to_md.py --force        # re-render everything, ignore hashes
    python idp_to_md.py --list         # show registry, export nothing
    python idp_to_md.py --db-scope staging          # pin introspection scope
    python idp_to_md.py --no-db-introspect         # names only, no DB access

DATABASES ARE NOT AN IDP DOCUMENT. `/services/{name}/databases` returns database
NAMES ONLY, derived from the service name and its markets -- the IDP never
connects to a server and holds no table, column or comment information at all.
The schema in database.md is therefore read directly from PostgreSQL, which does
carry documentation: WeRoad services use `COMMENT ON TABLE/COLUMN`, so
pg_description yields real prose descriptions and not just column types. Access
is read-only catalog introspection (pg_class / pg_attribute / pg_description /
pg_constraint / pg_enum) -- no row data is ever selected. When no scope is
reachable the file says so explicitly and states that the blank table counts are
a connection failure, not an empty database.

Multi-market services derive one database per market that are expected to be
identical. Every reachable copy is introspected and fingerprinted; identical
shapes are documented once, and a divergence is reported as the migration-drift
signal it is rather than being averaged away.

Environment (loaded from <repo>/.env.local, then the process environment):
    IDP_ACCESS_TOKEN               -- a ready JWT; skips all token minting
    FUSIONAUTH_PRODUCTION_BASE_URL -- FusionAuth base, e.g. https://auth.weroad.io
    FUSIONAUTH_PRODUCTION_API_KEY  -- FusionAuth admin API key (vend fallback)
    IDP_API_BASE                   -- override the API base URL

AUTHENTICATION, in the order tried:
  1. IDP_ACCESS_TOKEN, used verbatim.
  2. ~/.config/wr-idp/get-token.sh -- the user-context refresh-token flow.
     Preferred when it works: it is the least-privileged credential.  NOTE the
     production FusionAuth tenant runs refreshTokenUsagePolicy=OneTimeUse, so
     every refresh ROTATES the token and that script does not persist the new
     one -- it therefore self-destructs after a single use and needs a fresh
     interactive login to recover.  A failure here is logged, not fatal.
  3. FusionAuth POST /api/jwt/vend with the admin API key, minting a 1-hour
     user-context JWT.  Non-interactive and durable, but it uses an admin
     credential -- revoke by rotating FUSIONAUTH_PRODUCTION_API_KEY.

The IDP only ever exposes documentation it has been handed: the per-service
`hasOpenapi` / `hasAsyncapi` / `hasGraphql` / `hasDatabase` booleans are catalog
metadata, NOT a guarantee the artifact exists.  Several services claim a spec
whose docs endpoint 404s.  Every per-type outcome is recorded in the registry
and surfaced in the run summary rather than being silently dropped.
"""

import argparse
import html as _html
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
from typing import Optional


# -- Project root (use git to find repo root) ---------------------------------

PROJECT_ROOT = subprocess.run(
    ["git", "rev-parse", "--show-toplevel"],
    capture_output=True, text=True,
).stdout.strip()


# -- Load .env from project root ----------------------------------------------

def load_dotenv():
    env_path = os.path.join(PROJECT_ROOT, ".env.local")
    if os.path.isfile(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    os.environ.setdefault(key.strip(), value.strip())


load_dotenv()


# -- Paths --------------------------------------------------------------------

OUTPUT_BASE = os.path.join(PROJECT_ROOT, "src", "idp")
REGISTRY_PATH = os.path.join(OUTPUT_BASE, ".registry.json")

DEFAULT_API_BASE = "https://api-idp.weroad.com"
DEFAULT_UI_BASE = "https://idp.weroad.com"

# The FusionAuth `idp` application. Its client id doubles as the audience the
# IDP API accepts, which is why a vended token must carry it verbatim.
IDP_APPLICATION_ID = "b9f1e5a2-e58b-40cd-ab69-765d9f972949"

DOC_TYPES = ("openapi", "asyncapi", "graphql")

# Both auth.weroad.io and api-idp.weroad.com sit behind Cloudflare, which blocks
# the default `Python-urllib/3.x` signature with "error code: 1010" — a 403 that
# looks exactly like a rejected credential. Always send a real User-Agent.
USER_AGENT = "weroad-brain-idp-exporter/1.0 (+https://github.com/smnbss/super)"

SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def slugify_service(name: str) -> str:
    """Service names are already [a-zA-Z0-9_-]+ (the API enforces it), but never
    trust an upstream string with a path separator in it."""
    return SAFE_NAME.sub("-", name.strip()).strip("-.") or "unnamed"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# -- Registry -----------------------------------------------------------------

def load_registry() -> dict:
    if os.path.isfile(REGISTRY_PATH):
        try:
            with open(REGISTRY_PATH, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_registry(data: dict):
    os.makedirs(os.path.dirname(REGISTRY_PATH), exist_ok=True)
    with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)


# -- Auth ---------------------------------------------------------------------

class AuthError(RuntimeError):
    pass


def _token_from_env() -> Optional[str]:
    tok = (os.environ.get("IDP_ACCESS_TOKEN") or "").strip()
    return tok or None


def _token_from_wr_idp() -> Optional[str]:
    script = os.path.expanduser("~/.config/wr-idp/get-token.sh")
    if not os.path.isfile(script):
        return None
    try:
        res = subprocess.run([script], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"  ! wr-idp get-token.sh did not run ({exc}); falling back", file=sys.stderr)
        return None
    tok = res.stdout.strip()
    if res.returncode != 0 or not tok:
        detail = (res.stderr or "").strip().splitlines()
        hint = detail[-1] if detail else f"exit {res.returncode}"
        print(f"  ! wr-idp refresh-token flow failed ({hint}); falling back", file=sys.stderr)
        return None
    return tok


def _token_from_fusionauth_vend() -> Optional[str]:
    base = (os.environ.get("FUSIONAUTH_PRODUCTION_BASE_URL") or "").strip().rstrip("/")
    key = (os.environ.get("FUSIONAUTH_PRODUCTION_API_KEY") or "").strip()
    if not base or not key:
        return None

    tenant_id = os.environ.get("FUSIONAUTH_PRODUCTION_TENANT_ID", "").strip()
    email = os.environ.get("IDP_USER_EMAIL", "").strip()
    user_id = os.environ.get("IDP_USER_ID", "").strip()
    first = os.environ.get("IDP_USER_FIRST_NAME", "").strip()
    last = os.environ.get("IDP_USER_LAST_NAME", "").strip()

    # ~/.config/wr-idp/.env is the canonical home for the caller's identity.
    wr_env = os.path.expanduser("~/.config/wr-idp/.env")
    if os.path.isfile(wr_env) and not (email and user_id):
        with open(wr_env) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k == "IDP_USER_ID" and not user_id:
                    user_id = v
                elif k == "IDP_USER_EMAIL" and not email:
                    email = v

    if not email:
        email = _git_user_email() or ""
    if not email:
        print("  ! cannot vend a token: no user email "
              "(set IDP_USER_EMAIL or git config user.email)", file=sys.stderr)
        return None
    if not first or not last:
        # IDP rejects a token missing firstName/lastName on /auth/sync-user, and
        # carries them through to audit rows, so derive something truthful.
        guessed = _git_user_name() or email.split("@")[0].replace(".", " ")
        parts = guessed.split()
        first = first or (parts[0] if parts else "Unknown")
        last = last or (parts[-1] if len(parts) > 1 else "User")

    claims = {
        "iss": base,
        "aud": IDP_APPLICATION_ID,
        "applicationId": IDP_APPLICATION_ID,
        "email": email,
        "email_verified": True,
        "firstName": first,
        "lastName": last,
        # idp-user is the lowest of the four IDP roles and is all the read-only
        # catalog + docs endpoints require.
        "roles": ["idp-user"],
    }
    if user_id:
        claims["sub"] = user_id
    if tenant_id:
        claims["tid"] = tenant_id

    payload = {"claims": claims, "timeToLiveInSeconds": 3600}
    key_id = os.environ.get("FUSIONAUTH_ACCESS_TOKEN_KEY_ID", "").strip()
    if key_id:
        payload["keyId"] = key_id

    req = urllib.request.Request(
        f"{base}/api/jwt/vend",
        data=json.dumps(payload).encode(),
        headers={"Authorization": key, "Content-Type": "application/json",
                 "User-Agent": USER_AGENT},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        print(f"  ! FusionAuth vend failed: HTTP {exc.code} {exc.read()[:200]!r}", file=sys.stderr)
        return None
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        print(f"  ! FusionAuth vend failed: {exc}", file=sys.stderr)
        return None

    tok = (body.get("token") or "").strip()
    return tok or None


def _git_cfg(field: str) -> Optional[str]:
    res = subprocess.run(["git", "config", "--get", field], capture_output=True, text=True)
    val = res.stdout.strip()
    return val or None


def _git_user_email() -> Optional[str]:
    return _git_cfg("user.email")


def _git_user_name() -> Optional[str]:
    return _git_cfg("user.name")


def get_token() -> tuple[str, str]:
    """Return (token, how-it-was-obtained). Raises AuthError if every path fails."""
    for label, fn in (
        ("IDP_ACCESS_TOKEN", _token_from_env),
        ("wr-idp refresh token", _token_from_wr_idp),
        ("FusionAuth jwt/vend", _token_from_fusionauth_vend),
    ):
        tok = fn()
        if tok:
            return tok, label
    raise AuthError(
        "No IDP credential available. Provide one of:\n"
        "  - IDP_ACCESS_TOKEN=<jwt>\n"
        "  - a working ~/.config/wr-idp/get-token.sh refresh token\n"
        "  - FUSIONAUTH_PRODUCTION_BASE_URL + FUSIONAUTH_PRODUCTION_API_KEY in .env.local"
    )


# -- HTTP ---------------------------------------------------------------------

class IDPClient:
    def __init__(self, api_base: str, token: str):
        self.api_base = api_base.rstrip("/")
        self.token = token

    def get(self, path: str) -> tuple[int, bytes, str]:
        """GET an IDP path. Returns (status, body, content_type). A 404 is data,
        not an error -- the catalog routinely flags docs it does not hold."""
        url = f"{self.api_base}{path}"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
            "User-Agent": USER_AGENT,
        })
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return resp.status, resp.read(), resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), exc.headers.get("Content-Type", "") if exc.headers else ""
        except (urllib.error.URLError, OSError) as exc:
            raise RuntimeError(f"GET {url} failed: {exc}") from exc

    def get_json(self, path: str):
        status, body, _ = self.get(path)
        if status != 200:
            return status, None
        try:
            return status, json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RuntimeError(f"GET {path} returned unparseable JSON: {exc}") from exc


# -- Markdown helpers ---------------------------------------------------------

def md_escape(text) -> str:
    """Escape for use inside a markdown table cell."""
    if text is None:
        return ""
    s = str(text).replace("\r\n", "\n").replace("\r", "\n")
    s = s.replace("|", "\\|").replace("\n", "<br>")
    return s.strip()


def one_line(text) -> str:
    if text is None:
        return ""
    return " ".join(str(text).split())


def anchor(name: str) -> str:
    """GitHub-flavoured heading anchor for a schema/type name."""
    slug = re.sub(r"[^\w\- ]", "", str(name)).strip().lower().replace(" ", "-")
    return slug or "unnamed"


def fence(payload, lang: str = "json") -> list[str]:
    if isinstance(payload, (dict, list)):
        text = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False)
    else:
        text = str(payload)
    return [f"```{lang}", text, "```", ""]


def ref_name(ref: str) -> str:
    return str(ref).rsplit("/", 1)[-1]


def type_of(schema, depth: int = 0) -> str:
    """Render a JSON-Schema fragment as a short human type string.

    $ref is rendered as a link to the schema's own section rather than being
    expanded: these specs are cyclic (api-catalog has 456 schemas) and inlining
    them would not terminate.
    """
    if schema is None:
        return ""
    if not isinstance(schema, dict):
        return f"`{schema}`"
    if "$ref" in schema:
        n = ref_name(schema["$ref"])
        return f"[`{n}`](#{anchor(n)})"
    if depth > 6:
        return "`…`"

    for key, joiner in (("oneOf", " \\| "), ("anyOf", " \\| "), ("allOf", " & ")):
        if key in schema and isinstance(schema[key], list):
            inner = [type_of(s, depth + 1) for s in schema[key]]
            return f"({joiner.join(x for x in inner if x)})" if inner else ""

    t = schema.get("type")
    if isinstance(t, list):
        t = " \\| ".join(str(x) for x in t)

    if t == "array" or (t is None and "items" in schema):
        inner = type_of(schema.get("items"), depth + 1) or "`any`"
        return f"array&lt;{inner}&gt;"

    if t == "object" or (t is None and ("properties" in schema or "additionalProperties" in schema)):
        ap = schema.get("additionalProperties")
        if isinstance(ap, dict):
            return f"map&lt;string, {type_of(ap, depth + 1)}&gt;"
        return "`object`"

    if "enum" in schema and isinstance(schema["enum"], list):
        vals = ", ".join(f"`{v}`" for v in schema["enum"][:12])
        more = "…" if len(schema["enum"]) > 12 else ""
        base = f"`{t}`" if t else "enum"
        return f"{base} — one of {vals}{more}"

    if t:
        fmt = schema.get("format")
        return f"`{t}({fmt})`" if fmt else f"`{t}`"
    return "`any`"


def constraints_of(schema) -> str:
    """Collect the JSON-Schema validation keywords worth carrying into docs."""
    if not isinstance(schema, dict):
        return ""
    bits = []
    for key, label in (
        ("minimum", "min"), ("maximum", "max"),
        ("exclusiveMinimum", "min>"), ("exclusiveMaximum", "max<"),
        ("minLength", "minLen"), ("maxLength", "maxLen"),
        ("minItems", "minItems"), ("maxItems", "maxItems"),
        ("pattern", "pattern"), ("default", "default"),
        ("multipleOf", "multipleOf"),
    ):
        if key in schema:
            bits.append(f"{label}=`{schema[key]}`")
    if schema.get("nullable"):
        bits.append("nullable")
    if schema.get("readOnly"):
        bits.append("readOnly")
    if schema.get("writeOnly"):
        bits.append("writeOnly")
    if schema.get("deprecated"):
        bits.append("**deprecated**")
    return ", ".join(bits)


def render_schema_block(name: str, schema: dict, heading_level: int = 3) -> list[str]:
    """Render a named schema: its type line, description, and a property table."""
    h = "#" * heading_level
    out = [f"{h} {name}", ""]
    if not isinstance(schema, dict):
        out += [f"`{schema}`", ""]
        return out

    desc = schema.get("description") or schema.get("title")
    if desc:
        out += [one_line(desc), ""]

    meta = []
    t = schema.get("type")
    if t:
        meta.append(f"**Type:** {type_of({k: v for k, v in schema.items() if k != 'description'})}")
    cons = constraints_of(schema)
    if cons:
        meta.append(f"**Constraints:** {cons}")
    if meta:
        out += [" · ".join(meta), ""]

    props = schema.get("properties")
    if isinstance(props, dict) and props:
        required = set(schema.get("required") or [])
        out += ["| Property | Type | Required | Description |",
                "| --- | --- | --- | --- |"]
        for pname, pschema in props.items():
            pdesc = ""
            if isinstance(pschema, dict):
                pdesc = one_line(pschema.get("description") or "")
                pcons = constraints_of(pschema)
                if pcons:
                    pdesc = f"{pdesc} ({pcons})" if pdesc else pcons
            out.append(
                f"| `{md_escape(pname)}` | {type_of(pschema)} | "
                f"{'yes' if pname in required else ''} | {md_escape(pdesc)} |"
            )
        out.append("")
        # Inline object properties would otherwise lose their own shape.
        for pname, pschema in props.items():
            if isinstance(pschema, dict) and "$ref" not in pschema:
                nested = pschema.get("properties")
                if isinstance(nested, dict) and nested:
                    out += render_schema_block(f"{name}.{pname}", pschema, heading_level + 1)
    elif "enum" in schema:
        out += ["**Values:** " + ", ".join(f"`{v}`" for v in schema["enum"]), ""]
    elif "items" in schema:
        out += [f"**Items:** {type_of(schema.get('items'))}", ""]

    if isinstance(schema.get("example"), (dict, list)):
        out += ["**Example**", ""] + fence(schema["example"])
    elif schema.get("example") is not None:
        out += [f"**Example:** `{schema['example']}`", ""]

    return out


# -- OpenAPI renderer ---------------------------------------------------------

HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")


def render_openapi(service: str, spec: dict, source_url: str) -> str:
    info = spec.get("info") or {}
    paths = spec.get("paths") or {}
    components = spec.get("components") or {}
    schemas = components.get("schemas") or {}

    op_count = sum(1 for p in paths.values() if isinstance(p, dict)
                   for m in p if m.lower() in HTTP_METHODS)

    out = [
        f"# {service} — OpenAPI",
        "",
        f"**Source:** [{source_url}]({source_url})",
        f"**Spec title:** {one_line(info.get('title')) or '(none)'}"
        f" · **Version:** {one_line(info.get('version')) or '(none)'}"
        f" · **OpenAPI:** {spec.get('openapi') or spec.get('swagger') or '(unknown)'}",
        f"**Paths:** {len(paths)} · **Operations:** {op_count} · **Component schemas:** {len(schemas)}",
        f"**Exported:** {utc_stamp()}",
        "",
    ]

    if info.get("description"):
        out += [one_line(info["description"]), ""]

    contact = info.get("contact") or {}
    if contact:
        parts = [v for v in (contact.get("name"), contact.get("email"), contact.get("url")) if v]
        if parts:
            out += [f"**Contact:** {' · '.join(str(p) for p in parts)}", ""]
    if info.get("license"):
        lic = info["license"]
        out += [f"**License:** {one_line(lic.get('name') if isinstance(lic, dict) else lic)}", ""]

    servers = spec.get("servers") or []
    if servers:
        out += ["## Servers", "", "| URL | Description |", "| --- | --- |"]
        for s in servers:
            if isinstance(s, dict):
                out.append(f"| `{md_escape(s.get('url'))}` | {md_escape(one_line(s.get('description')))} |")
        out.append("")

    tags = spec.get("tags") or []
    if tags:
        out += ["## Tags", "", "| Tag | Description |", "| --- | --- |"]
        for t in tags:
            if isinstance(t, dict):
                out.append(f"| `{md_escape(t.get('name'))}` | {md_escape(one_line(t.get('description')))} |")
        out.append("")

    sec_schemes = components.get("securitySchemes") or {}
    if sec_schemes:
        out += ["## Security schemes", "", "| Name | Type | Detail |", "| --- | --- | --- |"]
        for sname, s in sec_schemes.items():
            if not isinstance(s, dict):
                continue
            detail = []
            for k in ("scheme", "bearerFormat", "in", "name", "openIdConnectUrl"):
                if s.get(k):
                    detail.append(f"{k}=`{s[k]}`")
            if s.get("flows"):
                detail.append("flows=`" + ", ".join(s["flows"].keys()) + "`")
            out.append(f"| `{md_escape(sname)}` | `{md_escape(s.get('type'))}` | {md_escape(', '.join(detail))} |")
        out.append("")
        if spec.get("security"):
            out += ["**Default security:** " +
                    ", ".join(f"`{k}`" for req in spec["security"] if isinstance(req, dict) for k in req), ""]

    # -- Endpoint summary table (the thing you actually scan) --
    out += ["## Endpoints", "", "| Method | Path | Summary | Tags |", "| --- | --- | --- | --- |"]
    for path, item in paths.items():
        if not isinstance(item, dict):
            continue
        for method in HTTP_METHODS:
            op = item.get(method)
            if not isinstance(op, dict):
                continue
            summary = one_line(op.get("summary") or op.get("operationId") or "")
            tag_s = ", ".join(f"`{t}`" for t in (op.get("tags") or []))
            dep = " **(deprecated)**" if op.get("deprecated") else ""
            out.append(f"| `{method.upper()}` | `{md_escape(path)}` | {md_escape(summary)}{dep} | {tag_s} |")
    out.append("")

    # -- Full operation detail --
    out += ["## Operations", ""]
    for path, item in paths.items():
        if not isinstance(item, dict):
            continue
        shared_params = item.get("parameters") or []
        for method in HTTP_METHODS:
            op = item.get(method)
            if not isinstance(op, dict):
                continue
            out += render_operation(method, path, op, shared_params)

    if schemas:
        out += ["## Component schemas", ""]
        for sname, schema in schemas.items():
            out += render_schema_block(sname, schema, heading_level=3)

    for section, label in (("parameters", "Component parameters"),
                           ("requestBodies", "Component request bodies"),
                           ("responses", "Component responses"),
                           ("headers", "Component headers")):
        block = components.get(section) or {}
        if not block:
            continue
        out += [f"## {label}", ""]
        for bname, bval in block.items():
            out += [f"### {bname}", ""]
            if isinstance(bval, dict) and bval.get("description"):
                out += [one_line(bval["description"]), ""]
            out += fence(bval)

    return "\n".join(out).rstrip() + "\n"


def render_operation(method: str, path: str, op: dict, shared_params: list) -> list[str]:
    title = one_line(op.get("summary") or op.get("operationId") or "")
    head = f"### `{method.upper()} {path}`"
    if title:
        head += f" — {title}"
    out = [head, ""]

    meta = []
    if op.get("operationId"):
        meta.append(f"**operationId:** `{op['operationId']}`")
    if op.get("tags"):
        meta.append("**Tags:** " + ", ".join(f"`{t}`" for t in op["tags"]))
    if op.get("deprecated"):
        meta.append("**DEPRECATED**")
    if op.get("security") is not None:
        names = [k for req in op["security"] if isinstance(req, dict) for k in req]
        meta.append("**Security:** " + (", ".join(f"`{n}`" for n in names) if names else "none (public)"))
    if meta:
        out += [" · ".join(meta), ""]

    if op.get("description"):
        out += [one_line(op["description"]), ""]

    params = list(shared_params) + list(op.get("parameters") or [])
    if params:
        out += ["**Parameters**", "",
                "| Name | In | Type | Required | Description |",
                "| --- | --- | --- | --- | --- |"]
        for p in params:
            if not isinstance(p, dict):
                continue
            if "$ref" in p:
                n = ref_name(p["$ref"])
                out.append(f"| [`{md_escape(n)}`](#{anchor(n)}) | — | — | — | (component parameter) |")
                continue
            desc = one_line(p.get("description") or "")
            cons = constraints_of(p.get("schema") or {})
            if cons:
                desc = f"{desc} ({cons})" if desc else cons
            out.append(
                f"| `{md_escape(p.get('name'))}` | `{md_escape(p.get('in'))}` | "
                f"{type_of(p.get('schema'))} | {'yes' if p.get('required') else ''} | {md_escape(desc)} |"
            )
        out.append("")

    body = op.get("requestBody")
    if isinstance(body, dict):
        req = " (required)" if body.get("required") else ""
        out += [f"**Request body**{req}", ""]
        if body.get("description"):
            out += [one_line(body["description"]), ""]
        out += render_content(body.get("content") or {})
        if "$ref" in body:
            n = ref_name(body["$ref"])
            out += [f"See [`{n}`](#{anchor(n)}).", ""]

    responses = op.get("responses") or {}
    if responses:
        out += ["**Responses**", "", "| Status | Description | Content |", "| --- | --- | --- |"]
        for code, resp in responses.items():
            if not isinstance(resp, dict):
                out.append(f"| `{md_escape(code)}` | | |")
                continue
            if "$ref" in resp:
                n = ref_name(resp["$ref"])
                out.append(f"| `{md_escape(code)}` | (component response `{md_escape(n)}`) | |")
                continue
            content = resp.get("content") or {}
            ctypes = []
            for ct, cv in content.items():
                schema = (cv or {}).get("schema") if isinstance(cv, dict) else None
                ctypes.append(f"`{ct}` → {type_of(schema)}" if schema is not None else f"`{ct}`")
            out.append(
                f"| `{md_escape(code)}` | {md_escape(one_line(resp.get('description')))} | "
                f"{md_escape(' · '.join(ctypes))} |"
            )
        out.append("")

    return out


def render_content(content: dict) -> list[str]:
    out = []
    for ctype, cval in (content or {}).items():
        if not isinstance(cval, dict):
            continue
        schema = cval.get("schema")
        out.append(f"- `{ctype}` → {type_of(schema)}")
        inline = isinstance(schema, dict) and "$ref" not in schema and schema.get("properties")
        if inline:
            required = set(schema.get("required") or [])
            out += ["", "| Property | Type | Required | Description |", "| --- | --- | --- | --- |"]
            for pname, pschema in schema["properties"].items():
                pdesc = one_line(pschema.get("description") or "") if isinstance(pschema, dict) else ""
                out.append(f"| `{md_escape(pname)}` | {type_of(pschema)} | "
                           f"{'yes' if pname in required else ''} | {md_escape(pdesc)} |")
    if out:
        out.append("")
    return out


# -- AsyncAPI renderer --------------------------------------------------------

def render_asyncapi(service: str, spec: dict, source_url: str) -> str:
    info = spec.get("info") or {}
    channels = spec.get("channels") or {}
    operations = spec.get("operations") or {}
    components = spec.get("components") or {}
    messages = components.get("messages") or {}
    schemas = components.get("schemas") or {}

    out = [
        f"# {service} — AsyncAPI",
        "",
        f"**Source:** [{source_url}]({source_url})",
        f"**Spec title:** {one_line(info.get('title')) or '(none)'}"
        f" · **Version:** {one_line(info.get('version')) or '(none)'}"
        f" · **AsyncAPI:** {spec.get('asyncapi') or '(unknown)'}",
        f"**Channels:** {len(channels)} · **Operations:** {len(operations)}"
        f" · **Messages:** {len(messages)} · **Schemas:** {len(schemas)}",
        f"**Default content type:** `{spec.get('defaultContentType') or '(unset)'}`",
        f"**Exported:** {utc_stamp()}",
        "",
    ]
    if info.get("description"):
        out += [one_line(info["description"]), ""]

    contact = info.get("contact") or {}
    parts = [v for v in (contact.get("name"), contact.get("email"), contact.get("url")) if v]
    if parts:
        out += [f"**Contact:** {' · '.join(str(p) for p in parts)}", ""]

    if info.get("tags"):
        out += ["## Tags", "", "| Tag | Description |", "| --- | --- |"]
        for t in info["tags"]:
            if isinstance(t, dict):
                out.append(f"| `{md_escape(t.get('name'))}` | {md_escape(one_line(t.get('description')))} |")
        out.append("")

    servers = spec.get("servers") or {}
    if servers:
        out += ["## Servers", "", "| Name | Host / URL | Protocol | Description |", "| --- | --- | --- | --- |"]
        for sname, s in servers.items():
            if not isinstance(s, dict):
                continue
            host = s.get("host") or s.get("url") or ""
            if s.get("pathname"):
                host = f"{host}{s['pathname']}"
            out.append(f"| `{md_escape(sname)}` | `{md_escape(host)}` | "
                       f"`{md_escape(s.get('protocol'))}` | {md_escape(one_line(s.get('description')))} |")
        out.append("")

    # -- Channel summary: address is what a consumer actually binds to --
    if channels:
        out += ["## Channels", "", "| Channel | Address | Messages | Description |", "| --- | --- | --- | --- |"]
        for cname, ch in channels.items():
            if not isinstance(ch, dict):
                continue
            msgs = ", ".join(f"[`{ref_name(m.get('$ref', k))}`](#{anchor(ref_name(m.get('$ref', k)))})"
                             if isinstance(m, dict) else f"`{k}`"
                             for k, m in (ch.get("messages") or {}).items())
            out.append(f"| `{md_escape(cname)}` | `{md_escape(ch.get('address'))}` | {msgs} | "
                       f"{md_escape(one_line(ch.get('description')))} |")
        out.append("")

    if operations:
        out += ["## Operations", "", "| Operation | Action | Channel | Messages | Description |",
                "| --- | --- | --- | --- | --- |"]
        for oname, op in operations.items():
            if not isinstance(op, dict):
                continue
            ch = op.get("channel") or {}
            ch_s = ref_name(ch.get("$ref", "")) if isinstance(ch, dict) else str(ch)
            msgs = ", ".join(ref_name(m.get("$ref", "")) for m in (op.get("messages") or [])
                             if isinstance(m, dict))
            out.append(f"| `{md_escape(oname)}` | `{md_escape(op.get('action'))}` | `{md_escape(ch_s)}` | "
                       f"{md_escape(msgs)} | {md_escape(one_line(op.get('summary') or op.get('description')))} |")
        out.append("")

    if messages:
        out += ["## Messages", ""]
        for mname, msg in messages.items():
            out += [f"### {mname}", ""]
            if not isinstance(msg, dict):
                out += fence(msg)
                continue
            meta = []
            if msg.get("name"):
                meta.append(f"**Name:** `{msg['name']}`")
            if msg.get("title"):
                meta.append(f"**Title:** {one_line(msg['title'])}")
            if msg.get("contentType"):
                meta.append(f"**Content type:** `{msg['contentType']}`")
            if meta:
                out += [" · ".join(meta), ""]
            if msg.get("summary"):
                out += [one_line(msg["summary"]), ""]
            if msg.get("description"):
                out += [one_line(msg["description"]), ""]
            payload = msg.get("payload")
            if isinstance(payload, dict):
                if "$ref" in payload:
                    n = ref_name(payload["$ref"])
                    out += [f"**Payload:** [`{n}`](#{anchor(n)})", ""]
                else:
                    out += ["**Payload**", ""] + render_schema_block("payload", payload, 4)[2:]
            if msg.get("headers"):
                out += ["**Headers**", ""] + render_schema_block("headers", msg["headers"], 4)[2:]
            if msg.get("examples"):
                out += ["**Examples**", ""] + fence(msg["examples"])

    if schemas:
        out += ["## Schemas", ""]
        for sname, schema in schemas.items():
            out += render_schema_block(sname, schema, heading_level=3)

    sec = components.get("securitySchemes") or {}
    if sec:
        out += ["## Security schemes", ""] + fence(sec)

    return "\n".join(out).rstrip() + "\n"


# -- GraphQL renderer (SpectaQL HTML -> markdown) -----------------------------

class SpectaQLParser(HTMLParser):
    """Extract operations and type definitions from a SpectaQL static page.

    The IDP stores GraphQL documentation as a fully rendered SpectaQL HTML page
    -- there is no introspection JSON and no SDL anywhere in it -- so the schema
    has to be recovered from the DOM. SpectaQL marks every part with a stable
    class name, and the shape this parser is written against is:

        <h1 class="group-heading">Queries</h1>
        <section class="operation operation-query">
          <div class="operation-group-name">…</div>            (absent on the
          <h2 class="operation-heading"><code>publicTravel</code></h2>   first
          <div class="operation-description">                   block of a group)
            <h5>Description</h5><p>real text</p>              <- h5 is a LABEL
          </div>
          <div class="operation-response"><h5>Response</h5><p>Returns a …</p></div>
          <div class="operation-arguments">
            <h5>Arguments</h5>
            <table><tbody><tr>
              <td><span class="property-name">slug</span> -
                  <span class="property-type">String</span></td>
              <td>Find by Slug</td>                            <- description
            </tr></tbody></table>
          </div>
          <div class="example-section operation-query-example">
            <h5>Query</h5><pre><code>…SDL…</code></pre>
          </div>
        </section>

    Two traps this encodes: the `<h5>` inside every section is a LABEL, not
    content (capturing it yields a document where every description reads
    "Description"), and the group name is rendered inside the section for every
    block EXCEPT the first in each group, which needs the preceding
    `group-heading` to fill in.
    """

    OP_KINDS = {"query", "mutation", "subscription"}
    DEF_KINDS = {"scalar", "object", "enum", "input", "interface", "union", "directive"}
    LABEL_TAGS = {"h3", "h4", "h5", "h6"}
    # Void elements never emit an end tag, so counting them would desynchronise
    # the depth counter every block-termination check depends on.
    VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
                 "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.operations: list[dict] = []
        self.definitions: list[dict] = []
        self._depth = 0
        # Captures form a stack of [key, depth, buf]; text lands in the innermost.
        self._caps: list[list] = []
        self._ignore_depth: Optional[int] = None
        self._block: Optional[dict] = None
        self._block_depth: Optional[int] = None
        self._group: Optional[str] = None     # last group-heading seen
        self._row: Optional[dict] = None
        self._td_has_prop = False

    # -- helpers --
    @staticmethod
    def _classes(attrs) -> set:
        for k, v in attrs:
            if k == "class" and v:
                return set(v.split())
        return set()

    def _push(self, key: str):
        self._caps.append([key, self._depth, []])

    def _pop_at_depth(self):
        while self._caps and self._caps[-1][1] >= self._depth:
            key, _, buf = self._caps.pop()
            raw = "".join(buf)
            text = raw.strip() if key == "example" else " ".join(raw.split())
            self._dispatch(key, text)

    def _dispatch(self, key: str, text: str):
        if key == "group-heading":
            if text:
                self._group = text
            return
        b = self._block
        if key == "property-name":
            if self._row is not None and text:
                self._row["name"] = text
                self._td_has_prop = True
            return
        if key == "property-type":
            if self._row is not None and text:
                self._row["type"] = text
                self._td_has_prop = True
            return
        if key == "td":
            # A cell with no property span, in a row that already has a name,
            # is that field's description column.
            if self._row is not None and not self._td_has_prop \
                    and self._row.get("name") and "desc" not in self._row and text:
                self._row["desc"] = text
            return
        if b is None or not text:
            return
        # First non-empty wins: SpectaQL repeats headings into the sidebar nav.
        b.setdefault(key, text)

    # -- HTMLParser hooks --
    def handle_starttag(self, tag, attrs):
        if tag in self.VOID_TAGS:
            return
        self._depth += 1
        cls = self._classes(attrs)

        if self._ignore_depth is not None:
            return
        if tag in self.LABEL_TAGS and self._caps:
            # A label inside a section we are capturing: skip its text entirely.
            self._ignore_depth = self._depth
            return

        if "group-heading" in cls:
            self._push("group-heading")
            return

        if "operation" in cls or "definition" in cls:
            kind = "operation" if "operation" in cls else "definition"
            self._caps.clear()
            self._block = {}
            self._block_depth = self._depth
            (self.operations if kind == "operation" else self.definitions).append(self._block)
            if self._group:
                self._block["group"] = self._group
            for c in cls:
                if kind == "operation" and c.startswith("operation-") \
                        and c[len("operation-"):] in self.OP_KINDS:
                    self._block["op_kind"] = c[len("operation-"):]
                if kind == "definition" and c.startswith("definition-") \
                        and c[len("definition-"):] in self.DEF_KINDS:
                    self._block["def_kind"] = c[len("definition-"):]
            return

        if self._block is None:
            return

        if tag == "tr":
            self._row = {}
            self._td_has_prop = False
            return
        if tag in ("td", "th"):
            self._td_has_prop = False
            self._push("td")
            return

        for c, key in (
            ("operation-heading", "heading"),
            ("definition-heading", "heading"),
            ("operation-description", "description"),
            ("definition-description", "description"),
            ("operation-response", "returns"),
            # Fallback for a page that has no group-heading h1 at all; when the
            # heading was seen, setdefault makes this a no-op.
            ("operation-group-name", "group"),
            ("definition-group-name", "group"),
            ("property-name", "property-name"),
            ("property-type", "property-type"),
            ("operation-query-example", "example"),
        ):
            if c in cls:
                self._push(key)
                return

    def handle_endtag(self, tag):
        if tag in self.VOID_TAGS:
            return
        if self._ignore_depth is not None:
            if self._depth <= self._ignore_depth:
                self._ignore_depth = None
            self._depth = max(0, self._depth - 1)
            return

        self._pop_at_depth()

        if tag == "tr" and self._row is not None:
            if self._row.get("name"):
                self._block.setdefault("fields", []).append(self._row)
            self._row = None
            self._td_has_prop = False

        if self._block is not None and self._block_depth is not None \
                and self._depth <= self._block_depth:
            self._block = None
            self._block_depth = None
            self._row = None

        self._depth = max(0, self._depth - 1)

    def handle_data(self, data):
        if self._ignore_depth is not None:
            return
        if self._caps:
            self._caps[-1][2].append(data)


def render_graphql(service: str, raw: bytes, source_url: str) -> str:
    text = raw.decode("utf-8", errors="replace")
    parser = SpectaQLParser()
    try:
        parser.feed(text)
        parser.close()
    except Exception as exc:  # a malformed page must not kill the whole run
        parser.operations, parser.definitions = [], []
        parse_error = str(exc)
    else:
        parse_error = ""

    ops = [o for o in parser.operations if o.get("heading")]
    defs = [d for d in parser.definitions if d.get("heading")]

    title_m = re.search(r"<title>(.*?)</title>", text, re.S | re.I)
    page_title = _html.unescape(title_m.group(1)).strip() if title_m else "GraphQL API Reference"

    by_kind: dict[str, list] = {}
    for o in ops:
        by_kind.setdefault(o.get("op_kind") or "operation", []).append(o)

    out = [
        f"# {service} — GraphQL",
        "",
        f"**Source:** [{source_url}]({source_url})",
        f"**Page title:** {page_title}",
        f"**Operations:** {len(ops)}"
        + (" (" + ", ".join(f"{k}: {len(v)}" for k, v in sorted(by_kind.items())) + ")" if by_kind else "")
        + f" · **Type definitions:** {len(defs)}",
        f"**Exported:** {utc_stamp()}",
        "",
        "> The IDP serves GraphQL documentation as a rendered SpectaQL HTML page —"
        " it contains no introspection JSON and no SDL, so the schema below was"
        " recovered from that page's markup. Field-level descriptions SpectaQL"
        " did not render are absent upstream, not dropped here.",
        "",
    ]
    if parse_error:
        out += [f"> ⚠️ The SpectaQL page failed to parse: `{parse_error}`."
                " Operations and definitions below may be incomplete.", ""]
    if not ops and not defs:
        out += ["> ⚠️ No operations or type definitions were recovered from this page."
                " Either the service publishes an empty schema or SpectaQL changed its"
                " markup — re-check before treating this as an empty API.", ""]

    for kind in sorted(by_kind):
        items = by_kind[kind]
        out += [f"## {kind.capitalize()} operations ({len(items)})", "",
                "| Operation | Group | Description |", "| --- | --- | --- |"]
        for o in items:
            out.append(f"| [`{md_escape(o['heading'])}`](#{anchor(o['heading'])}) | "
                       f"{md_escape(o.get('group'))} | {md_escape(o.get('description'))} |")
        out.append("")

    if ops:
        out += ["## Operation detail", ""]
        for o in ops:
            out += [f"### {o['heading']}", ""]
            meta = []
            if o.get("op_kind"):
                meta.append(f"**Kind:** `{o['op_kind']}`")
            if o.get("group"):
                meta.append(f"**Group:** {o['group']}")
            if meta:
                out += [" · ".join(meta), ""]
            if o.get("description"):
                out += [o["description"], ""]
            if o.get("fields"):
                out += ["| Argument / field | Type |", "| --- | --- |"]
                for f in o["fields"]:
                    out.append(f"| `{md_escape(f['name'])}` | {md_escape(f['type'])} |")
                out.append("")
            for ex in (o.get("examples") or [])[:2]:
                out += ["```graphql", ex, "```", ""]

    if defs:
        out += ["## Type definitions", ""]
        for d in defs:
            out += [f"### {d['heading']}", ""]
            meta = []
            if d.get("def_kind"):
                meta.append(f"**Kind:** `{d['def_kind']}`")
            if d.get("group"):
                meta.append(f"**Group:** {d['group']}")
            if meta:
                out += [" · ".join(meta), ""]
            if d.get("description"):
                out += [d["description"], ""]
            if d.get("fields"):
                out += ["| Field | Type |", "| --- | --- |"]
                for f in d["fields"]:
                    out.append(f"| `{md_escape(f['name'])}` | {md_escape(f['type'])} |")
                out.append("")

    return "\n".join(out).rstrip() + "\n"


# -- Database introspection ---------------------------------------------------
#
# The IDP knows database NAMES ONLY -- /services/{name}/databases derives them
# from the service name and its markets and never touches a server, so there is
# no table, column or comment information anywhere in the IDP. Real schema
# documentation therefore has to come from the databases themselves, which do
# carry it: WeRoad services use `COMMENT ON TABLE/COLUMN`, so pg_description
# yields genuine prose descriptions rather than just types.
#
# Scopes are tried least-sensitive first (development, then staging, then
# production) and every attempt is read-only catalog introspection -- no row
# data is ever selected.

PG_SCOPES = ("DEVELOPMENT", "STAGING", "PRODUCTION")

# One script, four record shapes, each tagged by its first column so the output
# parses unambiguously. Tabs and newlines are scrubbed inside SQL because they
# are the field and record separators.
_CLEAN = r"regexp_replace(coalesce({0}, ''), '[\t\r\n]+', ' ', 'g')"

INTROSPECT_SQL = f"""
SET statement_timeout = '60s';
SELECT concat_ws(chr(9), 'T', n.nspname, c.relname, c.relkind::text,
       c.reltuples::bigint::text,
       pg_size_pretty(pg_total_relation_size(c.oid)),
       {_CLEAN.format("obj_description(c.oid, 'pg_class')")})
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE c.relkind IN ('r','p','v','m')
   AND n.nspname NOT IN ('pg_catalog','information_schema')
   AND n.nspname NOT LIKE 'pg\\_%'
 ORDER BY n.nspname, c.relname;

SELECT concat_ws(chr(9), 'C', n.nspname, c.relname, a.attnum::text, a.attname,
       format_type(a.atttypid, a.atttypmod),
       CASE WHEN a.attnotnull THEN 'NOT NULL' ELSE '' END,
       {_CLEAN.format('pg_get_expr(d.adbin, d.adrelid)')},
       {_CLEAN.format('col_description(c.oid, a.attnum)')})
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
  JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
  LEFT JOIN pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum
 WHERE c.relkind IN ('r','p','v','m')
   AND n.nspname NOT IN ('pg_catalog','information_schema')
   AND n.nspname NOT LIKE 'pg\\_%'
 ORDER BY n.nspname, c.relname, a.attnum;

SELECT concat_ws(chr(9), 'K', n.nspname, c.relname, con.contype::text, con.conname,
       {_CLEAN.format('pg_get_constraintdef(con.oid)')})
  FROM pg_constraint con
  JOIN pg_class c ON c.oid = con.conrelid
  JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname NOT IN ('pg_catalog','information_schema')
   AND n.nspname NOT LIKE 'pg\\_%'
 ORDER BY n.nspname, c.relname, con.contype, con.conname;

SELECT concat_ws(chr(9), 'E', n.nspname, t.typname,
       string_agg(e.enumlabel, ', ' ORDER BY e.enumsortorder))
  FROM pg_type t
  JOIN pg_namespace n ON n.oid = t.typnamespace
  JOIN pg_enum e ON e.enumtypid = t.oid
 WHERE n.nspname NOT IN ('pg_catalog','information_schema')
   AND n.nspname NOT LIKE 'pg\\_%'
 GROUP BY n.nspname, t.typname
 ORDER BY n.nspname, t.typname;
"""

RELKIND_LABEL = {"r": "table", "p": "partitioned table", "v": "view", "m": "materialized view"}
CONTYPE_LABEL = {"p": "PRIMARY KEY", "f": "FOREIGN KEY", "u": "UNIQUE",
                 "c": "CHECK", "x": "EXCLUDE", "t": "TRIGGER"}


def pg_scope_config(scope: str) -> Optional[dict]:
    host = (os.environ.get(f"POSTGRESQL_{scope}_HOST") or "").strip()
    if not host:
        return None
    return {
        "host": host,
        "port": (os.environ.get(f"POSTGRESQL_{scope}_PORT") or "5432").strip(),
        "user": (os.environ.get(f"POSTGRESQL_{scope}_USER") or "").strip(),
        "password": os.environ.get(f"POSTGRESQL_{scope}_PASSWORD") or "",
    }


def load_wr_postgres_env():
    """wr-postgres keeps its credentials in its own config dir; the brain's
    .env.local may not carry them. Read both, without overriding .env.local."""
    path = os.path.expanduser("~/.config/wr-postgres/.env")
    if not os.path.isfile(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def introspect_database(dbname: str, scopes: list[str]) -> dict:
    """Read one database's catalog. Returns a result dict that always records
    what happened -- an unreachable database is a documented outcome, never a
    silent empty schema."""
    if not shutil_which("psql"):
        return {"status": "psql not installed", "dbname": dbname}

    attempts = []
    for scope in scopes:
        cfg = pg_scope_config(scope)
        if not cfg:
            attempts.append(f"{scope.lower()}: not configured")
            continue
        env = dict(os.environ)
        if cfg["password"]:
            env["PGPASSWORD"] = cfg["password"]
        conn = (f"host={cfg['host']} port={cfg['port']} dbname={dbname} "
                f"connect_timeout=6")
        if cfg["user"]:
            conn += f" user={cfg['user']}"
        try:
            res = subprocess.run(
                ["psql", "-X", "-q", "-A", "-t", "-F", "\t",
                 "-v", "ON_ERROR_STOP=1", conn, "-f", "-"],
                input=INTROSPECT_SQL, capture_output=True, text=True,
                env=env, timeout=180,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            attempts.append(f"{scope.lower()}: {exc.__class__.__name__}")
            continue
        if res.returncode != 0:
            err = " ".join((res.stderr or "").split())[:160] or f"exit {res.returncode}"
            attempts.append(f"{scope.lower()}: {err}")
            continue
        parsed = parse_introspection(res.stdout)
        parsed["status"] = "introspected"
        parsed["scope"] = scope.lower()
        parsed["dbname"] = dbname
        parsed["attempts"] = attempts
        return parsed

    return {"status": "unreachable", "dbname": dbname, "attempts": attempts}


def shutil_which(prog: str) -> Optional[str]:
    import shutil
    return shutil.which(prog)


def parse_introspection(stdout: str) -> dict:
    """Turn the tagged TSV back into {schema: {table: {...}}} plus enums."""
    schemas: dict = {}
    enums: dict = {}

    def rel(sch, tbl):
        return schemas.setdefault(sch, {}).setdefault(
            tbl, {"kind": "table", "rows": None, "size": "", "comment": "",
                  "columns": [], "constraints": []})

    for line in stdout.splitlines():
        if not line:
            continue
        parts = line.split("\t")
        tag = parts[0]
        try:
            if tag == "T" and len(parts) >= 7:
                _, sch, tbl, kind, rows, size, comment = parts[:7]
                r = rel(sch, tbl)
                r["kind"] = RELKIND_LABEL.get(kind, kind)
                r["rows"] = int(rows) if rows.lstrip("-").isdigit() else None
                r["size"] = size
                r["comment"] = comment
            elif tag == "C" and len(parts) >= 9:
                _, sch, tbl, _num, col, ctype, notnull, default, comment = parts[:9]
                rel(sch, tbl)["columns"].append({
                    "name": col, "type": ctype, "notnull": bool(notnull),
                    "default": default, "comment": comment,
                })
            elif tag == "K" and len(parts) >= 6:
                _, sch, tbl, ctype, cname, cdef = parts[:6]
                rel(sch, tbl)["constraints"].append({
                    "type": CONTYPE_LABEL.get(ctype, ctype), "name": cname, "def": cdef,
                })
            elif tag == "E" and len(parts) >= 4:
                _, sch, tname, labels = parts[:4]
                enums[f"{sch}.{tname}" if sch != "public" else tname] = labels
        except (ValueError, IndexError):
            continue

    tables = sum(len(t) for t in schemas.values())
    columns = sum(len(tb["columns"]) for t in schemas.values() for tb in t.values())
    described_t = sum(1 for t in schemas.values() for tb in t.values() if tb["comment"])
    described_c = sum(1 for t in schemas.values() for tb in t.values()
                      for c in tb["columns"] if c["comment"])
    return {"schemas": schemas, "enums": enums,
            "counts": {"tables": tables, "columns": columns,
                       "table_comments": described_t, "column_comments": described_c}}


def schema_fingerprint(result: dict) -> str:
    """Identity of a schema's *shape*, so the five markets of a multi-market
    service can be proven identical instead of rendered five times."""
    parts = []
    for sch in sorted(result.get("schemas") or {}):
        for tbl in sorted(result["schemas"][sch]):
            t = result["schemas"][sch][tbl]
            cols = ",".join(f"{c['name']}:{c['type']}" for c in t["columns"])
            parts.append(f"{sch}.{tbl}({cols})")
    return sha256("|".join(parts).encode()).hexdigest()[:16]


# -- Database renderer --------------------------------------------------------

def render_database(service: str, databases: list, detail: dict, source_url: str,
                    introspections: list[dict]) -> str:
    got = [r for r in introspections if r.get("status") == "introspected"]
    total = {"tables": sum(r["counts"]["tables"] for r in got),
             "columns": sum(r["counts"]["columns"] for r in got)}

    out = [
        f"# {service} — Databases",
        "",
        f"**Names source:** [{source_url}]({source_url})",
        f"**Declared `hasDatabase`:** {'yes' if detail.get('hasDatabase') else 'no'}"
        f" · **Derived names:** {len(databases)}"
        f" · **Introspected:** {len(got)}/{len(databases)}",
        f"**Exported:** {utc_stamp()}",
        "",
    ]

    if databases:
        out += ["| # | Database | Schema read from | Tables | Columns |",
                "| --- | --- | --- | --- | --- |"]
        by_name = {r.get("dbname"): r for r in introspections}
        for i, db in enumerate(databases, 1):
            r = by_name.get(db) or {}
            if r.get("status") == "introspected":
                src = f"`{r.get('scope')}`"
                tb, cl = r["counts"]["tables"], r["counts"]["columns"]
            else:
                src = md_escape(r.get("status") or "not attempted")
                tb = cl = ""
            out.append(f"| {i} | `{md_escape(db)}` | {src} | {tb} | {cl} |")
        out.append("")
    else:
        out += ["_The IDP returned no database names for this service._", ""]
        return "\n".join(out).rstrip() + "\n"

    if not got:
        attempts = []
        for r in introspections:
            for a in r.get("attempts") or []:
                if a not in attempts:
                    attempts.append(a)
        out += [
            "> ⚠️ **No schema below — no database was reachable from this machine.**"
            " The IDP supplies database *names* only: they are derived from the"
            " service name and its markets and the IDP never connects to a"
            " server, so it holds no table, column or comment information at"
            " all. Tables and columns above are therefore blank because the"
            " connection failed, **not** because the databases are empty.",
            "",
            "To fill this in, configure a scope in `.env.local` or"
            " `~/.config/wr-postgres/.env`"
            " (`POSTGRESQL_<SCOPE>_HOST/PORT/USER/PASSWORD`) and re-run."
            " Introspection is read-only catalog access — it reads"
            " `pg_class`/`pg_attribute`/`pg_description`, never row data.",
            "",
        ]
        if attempts:
            out += ["Connection attempts:", ""] + [f"- {md_escape(a)}" for a in attempts] + [""]
        out += [f"In the meantime the closest available column-level"
                f" documentation is `outputs/services/` — the `.db.agent.md`"
                f" doc for this service's repository, generated from its"
                f" migrations rather than from a live server.", ""]
        return "\n".join(out).rstrip() + "\n"

    # Group identical schemas so a five-market service is documented once.
    groups: dict[str, list[dict]] = {}
    for r in got:
        groups.setdefault(schema_fingerprint(r), []).append(r)

    described = sum(r["counts"]["column_comments"] for r in got)
    out += [f"**Schema totals:** {total['tables']} tables · {total['columns']} columns"
            f" · {described} column(s) carry a `COMMENT ON` description", ""]

    if len(groups) > 1:
        out += ["> ⚠️ **These databases do not share one schema.** The derived"
                " names are per-market copies that are expected to be identical;"
                f" they resolved into **{len(groups)} different shapes**, which is"
                " a real drift signal — a migration has not been applied"
                " everywhere. Each shape is documented separately below.", ""]
    elif len(got) > 1:
        out += [f"> All {len(got)} databases share one identical schema"
                " (verified by comparing every table and column, not assumed);"
                " it is documented once below.", ""]

    if described == 0:
        out += ["> Note: this schema has no `COMMENT ON` metadata, so the"
                " Description column below is empty throughout. That is the state"
                " of the database — the descriptions were never written, they were"
                " not lost in export.", ""]

    for gi, (fp, members) in enumerate(sorted(groups.items(), key=lambda kv: -len(kv[1])), 1):
        rep = members[0]
        if len(groups) > 1:
            out += [f"## Schema shape {gi} — `{', '.join(m['dbname'] for m in members)}`",
                    "", f"Read from `{rep['scope']}` · fingerprint `{fp}`", ""]
        else:
            out += [f"## Schema", "",
                    f"Read from `{rep['scope']}` · database"
                    f" `{rep['dbname']}` · fingerprint `{fp}`", ""]

        for sch in sorted(rep["schemas"]):
            tables = rep["schemas"][sch]
            heading = "###" if len(groups) == 1 else "####"
            if sch != "public" or len(rep["schemas"]) > 1:
                out += [f"{heading} Schema `{sch}`", ""]
            for tname in sorted(tables):
                t = tables[tname]
                sub = heading if (sch == "public" and len(rep["schemas"]) == 1) else heading + "#"
                out += [f"{sub} `{tname}`", ""]
                meta = [f"**Kind:** {t['kind']}"]
                if t["rows"] is not None and t["rows"] >= 0:
                    meta.append(f"**Approx. rows:** {t['rows']:,} (planner estimate)")
                if t["size"]:
                    meta.append(f"**Size:** {t['size']}")
                out += [" · ".join(meta), ""]
                if t["comment"]:
                    out += [t["comment"], ""]
                if t["columns"]:
                    out += ["| Column | Type | Null | Default | Description |",
                            "| --- | --- | --- | --- | --- |"]
                    for c in t["columns"]:
                        out.append(
                            f"| `{md_escape(c['name'])}` | `{md_escape(c['type'])}` | "
                            f"{'NOT NULL' if c['notnull'] else ''} | "
                            f"{('`' + md_escape(c['default']) + '`') if c['default'] else ''} | "
                            f"{md_escape(c['comment'])} |")
                    out.append("")
                if t["constraints"]:
                    out += ["**Constraints**", ""]
                    for k in t["constraints"]:
                        out.append(f"- **{k['type']}** `{k['name']}` — `{k['def']}`")
                    out.append("")

        if rep.get("enums"):
            out += [("### " if len(groups) == 1 else "#### ") + "Enum types", "",
                    "| Type | Values |", "| --- | --- |"]
            for ename in sorted(rep["enums"]):
                out.append(f"| `{md_escape(ename)}` | {md_escape(rep['enums'][ename])} |")
            out.append("")

    return "\n".join(out).rstrip() + "\n"


# -- Service index ------------------------------------------------------------

def render_service_index(detail: dict, listing: dict, databases: list,
                         doc_status: dict, ui_base: str) -> str:
    name = detail.get("name") or listing.get("name")
    repo_owner = detail.get("repositoryOwner") or listing.get("repositoryOwner") or ""
    repo_name = detail.get("repositoryName") or listing.get("repositoryName") or ""
    repo = f"{repo_owner}/{repo_name}".strip("/")

    out = [
        f"# {name}",
        "",
        f"**Source:** [{ui_base}/catalog/{name}]({ui_base}/catalog/{name})",
        f"**Exported:** {utc_stamp()}",
        "",
    ]
    if detail.get("description"):
        out += [one_line(detail["description"]), ""]

    runtime = detail.get("runtime") or listing.get("runtime") or ""
    if detail.get("runtimeVersion"):
        runtime = f"{runtime} {detail['runtimeVersion']}".strip()

    out += ["## Catalog metadata", "", "| Field | Value |", "| --- | --- |"]
    for label, value in (
        ("Service id", detail.get("id") or listing.get("id")),
        ("Repository", f"[{repo}](https://github.com/{repo})" if repo else ""),
        ("Owning team", detail.get("teamName") or listing.get("teamName")),
        ("Tier", detail.get("tier") or listing.get("tier")),
        ("Type", detail.get("type") or listing.get("type")),
        ("Runtime", runtime),
    ):
        if value not in (None, ""):
            out.append(f"| {label} | {md_escape(value) if label != 'Repository' else value} |")
    out.append("")

    out += ["## Documentation", "", "| Type | Declared | Exported | File |", "| --- | --- | --- | --- |"]
    for dtype, flag, fname in (
        ("OpenAPI", "hasOpenapi", "openapi.md"),
        ("AsyncAPI", "hasAsyncapi", "asyncapi.md"),
        ("GraphQL", "hasGraphql", "graphql.md"),
    ):
        declared = "yes" if detail.get(flag) else "no"
        status = doc_status.get(dtype.lower(), "not declared")
        link = f"[{fname}]({fname})" if status == "exported" else "—"
        out.append(f"| {dtype} | {declared} | {md_escape(status)} | {link} |")
    db_status = "exported" if databases else ("declared, none returned" if detail.get("hasDatabase") else "not declared")
    out.append(f"| Databases | {'yes' if detail.get('hasDatabase') else 'no'} | {md_escape(db_status)} | "
               f"{'[database.md](database.md)' if databases else '—'} |")
    out.append("")

    mismatches = [d for d, s in doc_status.items() if s.startswith("declared but")]
    if mismatches:
        out += ["> ⚠️ This service declares documentation the IDP does not hold: "
                + ", ".join(f"**{m}**" for m in sorted(mismatches))
                + ". The `has*` booleans are catalog metadata, not proof an artifact exists.", ""]

    if databases:
        out += ["## Databases", ""] + [f"- `{db}`" for db in databases] + [""]

    links = detail.get("links") or []
    if links:
        by_type: dict[str, list] = {}
        for l in links:
            if isinstance(l, dict):
                by_type.setdefault(l.get("type") or "other", []).append(l)
        out += ["## Links", ""]
        for ltype in sorted(by_type):
            out += [f"**{ltype}**", ""]
            for l in by_type[ltype]:
                out.append(f"- [{md_escape(one_line(l.get('label')))}]({l.get('url')})")
            out.append("")

    return "\n".join(out).rstrip() + "\n"


def render_catalog_index(rows: list[dict], api_base: str, ui_base: str,
                         total_in_catalog: int) -> str:
    out = [
        "# IDP Service Catalog",
        "",
        f"**Source:** [{ui_base}]({ui_base}) · API `{api_base}`",
        f"**Services exported:** {len(rows)} of {total_in_catalog} in the catalog",
        f"**Last indexed:** {utc_stamp()}",
        "",
        "One folder per service. Each holds `index.md` (catalog metadata and links)"
        " plus a markdown rendering of every API document the IDP actually serves.",
        "",
        "> `Declared` columns come from the catalog's `has*` booleans; `✓` means the"
        " document was fetched and rendered. A declared document that failed to"
        " download shows `✗` — that gap is upstream, in the IDP, not in this export.",
        "",
        "| Service | Team | Tier | Type | Runtime | Repository | OpenAPI | AsyncAPI | GraphQL | DBs |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    def cell(declared: bool, status: str) -> str:
        if status == "exported":
            return "✓"
        if status.startswith("declared but"):
            return "✗"
        return ""

    for r in sorted(rows, key=lambda x: x["name"]):
        d = r["detail"]
        repo = f"{d.get('repositoryOwner','')}/{d.get('repositoryName','')}".strip("/")
        runtime = d.get("runtime") or ""
        if d.get("runtimeVersion"):
            runtime = f"{runtime} {d['runtimeVersion']}".strip()
        out.append(
            f"| [{md_escape(r['name'])}]({r['slug']}/index.md) "
            f"| {md_escape(d.get('teamName'))} "
            f"| {md_escape(d.get('tier'))} "
            f"| {md_escape(d.get('type'))} "
            f"| {md_escape(runtime)} "
            f"| `{md_escape(repo)}` "
            f"| {cell(d.get('hasOpenapi'), r['doc_status'].get('openapi',''))} "
            f"| {cell(d.get('hasAsyncapi'), r['doc_status'].get('asyncapi',''))} "
            f"| {cell(d.get('hasGraphql'), r['doc_status'].get('graphql',''))} "
            f"| {len(r['databases']) or ''} |"
        )
    out.append("")

    gaps = [(r["name"], t) for r in rows for t, s in r["doc_status"].items()
            if s.startswith("declared but")]
    if gaps:
        out += ["## Declared but missing", "",
                "The catalog flags these documents as present; the docs endpoint does not serve them.",
                "", "| Service | Document | Detail |", "| --- | --- | --- |"]
        for name, t in sorted(gaps):
            detail = next(r["doc_status"][t] for r in rows if r["name"] == name)
            out.append(f"| `{md_escape(name)}` | {md_escape(t)} | {md_escape(detail)} |")
        out.append("")

    return "\n".join(out).rstrip() + "\n"


# -- Writing ------------------------------------------------------------------

def write_if_changed(path: str, content: str) -> bool:
    """Write only on change so unchanged files keep their mtime and stay out of
    the git diff. Returns True when the file was written."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                if f.read() == content:
                    return False
        except OSError:
            pass
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return True


def strip_export_stamp(text: str) -> str:
    """Drop the `**Exported:** …` / `**Last indexed:** …` lines before hashing,
    so a re-run with genuinely unchanged upstream content does not churn the
    whole tree every day."""
    return "\n".join(l for l in text.splitlines()
                     if not l.startswith("**Exported:**") and not l.startswith("**Last indexed:**"))


def content_hash(text: str) -> str:
    return sha256(strip_export_stamp(text).encode("utf-8")).hexdigest()[:16]


# -- Main ---------------------------------------------------------------------

def export(args) -> int:
    api_base = (os.environ.get("IDP_API_BASE") or DEFAULT_API_BASE).rstrip("/")
    ui_base = (args.url or DEFAULT_UI_BASE).rstrip("/")

    try:
        token, how = get_token()
    except AuthError as exc:
        print(f"idp_to_md: {exc}", file=sys.stderr)
        return 1
    print(f"→ authenticated via {how}")

    client = IDPClient(api_base, token)

    status, listing = client.get_json("/api/v1/services")
    if status != 200 or listing is None:
        print(f"idp_to_md: GET /api/v1/services returned HTTP {status}", file=sys.stderr)
        return 1
    if not isinstance(listing, list):
        print("idp_to_md: /api/v1/services did not return a list", file=sys.stderr)
        return 1

    total_in_catalog = len(listing)
    print(f"→ catalog holds {total_in_catalog} services")

    selected = listing
    if args.service:
        wanted = {s.lower() for s in args.service}
        selected = [s for s in listing if (s.get("name") or "").lower() in wanted]
        missing = wanted - {(s.get("name") or "").lower() for s in selected}
        if missing:
            print(f"  ! not in the catalog, skipped: {', '.join(sorted(missing))}", file=sys.stderr)
    if args.limit:
        selected = sorted(selected, key=lambda s: s.get("name") or "")[:args.limit]

    print(f"→ exporting {len(selected)} service(s) to src/idp/")

    registry = load_registry()
    services_reg = registry.setdefault("services", {})

    # Resolve which Postgres scopes are usable once, up front: an unconfigured
    # scope must not be retried per database for 85 services.
    load_wr_postgres_env()
    if args.no_db_introspect:
        pg_scopes = []
        print("→ database introspection disabled (--no-db-introspect)")
    else:
        wanted = [args.db_scope.upper()] if args.db_scope else list(PG_SCOPES)
        pg_scopes = [s for s in wanted if pg_scope_config(s)]
        if pg_scopes:
            print(f"→ database introspection via: {', '.join(s.lower() for s in pg_scopes)}")
        else:
            print("→ no POSTGRESQL_<SCOPE>_HOST configured; database.md will carry"
                  " names only (the IDP has no schema information)")

    rows = []
    files_written = 0
    stats = {"openapi": 0, "asyncapi": 0, "graphql": 0, "databases": 0, "missing": 0,
             "introspected": 0, "tables": 0}

    for entry in sorted(selected, key=lambda s: s.get("name") or ""):
        name = entry.get("name")
        if not name:
            continue
        slug = slugify_service(name)
        out_dir = os.path.join(OUTPUT_BASE, slug)

        status, detail = client.get_json(f"/api/v1/services/{urllib.parse.quote(name)}")
        if status != 200 or not isinstance(detail, dict):
            print(f"  ! {name}: detail HTTP {status}, using list metadata only", file=sys.stderr)
            detail = dict(entry)

        databases: list = []
        if detail.get("hasDatabase"):
            dstatus, dbody = client.get_json(f"/api/v1/services/{urllib.parse.quote(name)}/databases")
            if dstatus == 200 and isinstance(dbody, dict):
                databases = list(dbody.get("databases") or [])
            else:
                print(f"  ! {name}: databases HTTP {dstatus}", file=sys.stderr)

        doc_status: dict[str, str] = {}
        entry_reg = services_reg.setdefault(name, {})

        for dtype in DOC_TYPES:
            flag = {"openapi": "hasOpenapi", "asyncapi": "hasAsyncapi", "graphql": "hasGraphql"}[dtype]
            fname = f"{dtype}.md"
            fpath = os.path.join(out_dir, fname)

            if not detail.get(flag):
                doc_status[dtype] = "not declared"
                # A flag flipped off upstream should not leave a stale doc behind.
                if os.path.isfile(fpath):
                    os.remove(fpath)
                    print(f"  - {name}/{fname} removed (no longer declared)")
                entry_reg.pop(dtype, None)
                continue

            doc_url = f"{api_base}/api/v1/docs/{urllib.parse.quote(name)}?type={dtype}"
            http_status, body, _ctype = client.get(f"/api/v1/docs/{urllib.parse.quote(name)}?type={dtype}")
            if http_status != 200 or not body:
                doc_status[dtype] = f"declared but HTTP {http_status}"
                stats["missing"] += 1
                print(f"  ! {name}: {dtype} declared but docs endpoint returned HTTP {http_status}")
                entry_reg[dtype] = {"status": f"http-{http_status}", "bytes": len(body or b"")}
                continue

            try:
                if dtype == "graphql":
                    rendered = render_graphql(name, body, doc_url)
                else:
                    spec = json.loads(body.decode("utf-8"))
                    rendered = (render_openapi(name, spec, doc_url) if dtype == "openapi"
                                else render_asyncapi(name, spec, doc_url))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                doc_status[dtype] = f"declared but unparseable ({exc.__class__.__name__})"
                stats["missing"] += 1
                print(f"  ! {name}: {dtype} downloaded but could not be parsed: {exc}")
                entry_reg[dtype] = {"status": "unparseable", "bytes": len(body)}
                continue

            new_hash = content_hash(rendered)
            prev = entry_reg.get(dtype) or {}
            if not args.force and prev.get("hash") == new_hash and os.path.isfile(fpath):
                doc_status[dtype] = "exported"
                stats[dtype] += 1
                continue

            if write_if_changed(fpath, rendered):
                files_written += 1
            doc_status[dtype] = "exported"
            stats[dtype] += 1
            entry_reg[dtype] = {
                "status": "exported",
                "hash": new_hash,
                "source_bytes": len(body),
                "source_sha256": sha256(body).hexdigest(),
                "rendered_bytes": len(rendered.encode("utf-8")),
            }

        # database.md
        db_path = os.path.join(out_dir, "database.md")
        if databases:
            introspections = []
            if pg_scopes:
                for db in databases:
                    introspections.append(introspect_database(db, pg_scopes))
            db_md = render_database(name, databases, detail,
                                    f"{api_base}/api/v1/services/{name}/databases",
                                    introspections)
            if args.force or content_hash(db_md) != (entry_reg.get("databases") or {}).get("hash"):
                if write_if_changed(db_path, db_md):
                    files_written += 1
            got = [r for r in introspections if r.get("status") == "introspected"]
            entry_reg["databases"] = {
                "status": "exported", "hash": content_hash(db_md),
                "count": len(databases), "introspected": len(got),
                "tables": sum(r["counts"]["tables"] for r in got),
                "columns": sum(r["counts"]["columns"] for r in got),
            }
            stats["databases"] += 1
            stats["introspected"] += len(got)
            if got:
                stats["tables"] += sum(r["counts"]["tables"] for r in got)
        else:
            if os.path.isfile(db_path):
                os.remove(db_path)
            entry_reg.pop("databases", None)

        idx_md = render_service_index(detail, entry, databases, doc_status, ui_base)
        if write_if_changed(os.path.join(out_dir, "index.md"), idx_md):
            files_written += 1

        entry_reg["name"] = name
        entry_reg["slug"] = slug
        entry_reg["exported_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

        rows.append({"name": name, "slug": slug, "detail": detail,
                     "databases": databases, "doc_status": doc_status})

        flags = "".join(c for c, t in (("O", "openapi"), ("A", "asyncapi"), ("G", "graphql"))
                        if doc_status.get(t) == "exported") or "-"
        print(f"  ✓ {name} [{flags}]" + (f" {len(databases)} db" if databases else ""))

    # Catalog index: only rewrite it for a full run, otherwise a --limit run
    # would truncate the index to the subset it happened to touch.
    partial = bool(args.limit or args.service)
    index_path = os.path.join(OUTPUT_BASE, "index.md")
    if partial and os.path.isfile(index_path):
        print("→ src/idp/index.md left untouched (partial run)")
    else:
        if write_if_changed(index_path, render_catalog_index(rows, api_base, ui_base, total_in_catalog)):
            files_written += 1

    registry["api_base"] = api_base
    registry["ui_base"] = ui_base
    registry["last_run"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    registry["catalog_total"] = total_in_catalog
    registry["last_run_partial"] = partial
    save_registry(registry)

    print(f"\n→ done: {len(rows)} services · {files_written} file(s) written")
    print(f"  openapi {stats['openapi']} · asyncapi {stats['asyncapi']} · "
          f"graphql {stats['graphql']} · databases {stats['databases']}"
          f" ({stats['introspected']} introspected, {stats['tables']} tables)")
    if stats["missing"]:
        print(f"  ⚠ {stats['missing']} declared document(s) the IDP did not serve — see index.md")
    return 0


def show_registry() -> int:
    reg = load_registry()
    if not reg:
        print("No registry at src/idp/.registry.json — nothing exported yet.")
        return 0
    print(f"api_base: {reg.get('api_base')}")
    print(f"last_run: {reg.get('last_run')} (partial={reg.get('last_run_partial')})")
    print(f"catalog_total: {reg.get('catalog_total')}")
    svcs = reg.get("services") or {}
    print(f"services: {len(svcs)}")
    for name in sorted(svcs):
        e = svcs[name]
        got = [t for t in DOC_TYPES if (e.get(t) or {}).get("status") == "exported"]
        bad = [f"{t}:{(e.get(t) or {}).get('status')}" for t in DOC_TYPES
               if e.get(t) and (e[t] or {}).get("status") != "exported"]
        line = f"  {name:<28} {','.join(got) or '-'}"
        if e.get("databases"):
            line += f" +{e['databases'].get('count')}db"
        if bad:
            line += f"   ! {' '.join(bad)}"
        print(line)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Export the WeRoad IDP service catalog and API documentation to markdown.")
    ap.add_argument("url", nargs="?", default=DEFAULT_UI_BASE,
                    help=f"IDP UI base URL (default {DEFAULT_UI_BASE})")
    ap.add_argument("--limit", type=int, default=0,
                    help="export only the first N services (alphabetical) — for testing")
    ap.add_argument("--service", action="append", default=[],
                    help="export only this service (repeatable)")
    ap.add_argument("--force", action="store_true",
                    help="re-render every document, ignoring registry hashes")
    ap.add_argument("--db-scope", default="",
                    help="pin database introspection to one scope "
                         "(development|staging|production); default tries each in that order")
    ap.add_argument("--no-db-introspect", action="store_true",
                    help="skip Postgres introspection; database.md carries names only")
    ap.add_argument("--list", action="store_true", help="show the registry and exit")
    args = ap.parse_args()

    if not PROJECT_ROOT:
        print("idp_to_md: not inside a git repository", file=sys.stderr)
        return 1
    if args.list:
        return show_registry()
    return export(args)


if __name__ == "__main__":
    sys.exit(main())
