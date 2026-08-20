import re, html, sys, os

RAG = {'🔴':'red','🟠':'amber','🟢':'green','🔵':'blue','⚪':'grey','⏸':'pause','✅':'done'}

def esc(t): return html.escape(t, quote=False)

def inline(t):
    t = t.replace('\\|','&#124;').replace('\\[','&#91;').replace('\\]','&#93;')
    t = esc(t).replace('&amp;#124;','&#124;').replace('&amp;#91;','&#91;').replace('&amp;#93;','&#93;')
    t = re.sub(r'`([^`]+)`', lambda m: '<code>%s</code>' % m.group(1), t)
    t = re.sub(r'\[((?:[^\[\]]|\[[^\[\]]*\])+)\]\((https?://[^)\s]+)\)',
               lambda m: '<a href="%s" target="_blank" rel="noopener noreferrer">%s</a>' % (m.group(2), m.group(1)), t)
    t = re.sub(r'\[([^\]]+)\]\(([^)\s]+\.md)\)', lambda m: '<span class="xref">%s</span>' % m.group(1), t)
    t = re.sub(r'\*\*(.+?)\*\*', lambda m: '<strong>%s</strong>' % m.group(1), t)
    t = re.sub(r'(?<!\*)\*([^*\n]+)\*(?!\*)', lambda m: '<em>%s</em>' % m.group(1), t)
    t = re.sub(r'\[\[([^\]]+)\]\]', lambda m: '<span class="wl">%s</span>' % m.group(1), t)
    def bare(m):
        url = m.group(0)
        host = re.sub(r'^www\.', '', url.split('/')[2])
        return '<a class="u" href="%s" target="_blank" rel="noopener noreferrer">%s\u2197</a>' % (url, host)
    t = re.sub(r'(?<!["\'>=])https?://[^\s<>"\')]+', bare, t)
    return t

def cells(line):
    s = line.strip()
    if s.startswith('|'): s = s[1:]
    if s.endswith('|'): s = s[:-1]
    out, buf, i = [], '', 0
    while i < len(s):
        c = s[i]
        if c == '\\' and i+1 < len(s): buf += s[i:i+2]; i += 2; continue
        if c == '|': out.append(buf); buf = ''; i += 1; continue
        buf += c; i += 1
    out.append(buf)
    return [x.strip().replace('\\|','|').replace('\\[','[').replace('\\]',']') for x in out]

def bar(t):
    m = re.match(r'^`([█▓░]{2,})`\s*(.*)$', t.strip())
    if not m: return None
    fill = m.group(1); rest = m.group(2)
    filled = sum(1 for ch in fill if ch in '█▓')
    pct = int(round(100.0*filled/len(fill)))
    return '<span class="bar"><span class="bar-fill" style="width:%d%%"></span></span><span class="bar-lbl">%s</span>' % (pct, inline(rest) if rest else '%d%%' % pct)

def cell_html(t, first):
    if first and t in RAG: return '<span class="chip %s">%s</span>' % (RAG[t], t)
    b = bar(t)
    if b: return b
    if t.startswith('— ') or t == '—': return '<span class="none">%s</span>' % inline(t)
    return inline(t)

# Column widths are pinned per table SHAPE so every register table on the page lines up.
# Without this each <table> is auto-laid-out independently and the columns drift between buckets.
COLGROUPS = {
    # project register: ● | Project | Teams | Status | What's up | Owner | Target | Progress/Untouched
    'reg8':   ['34px', '15%', '10%', '9%', '30%', '8%', '8%', '20%'],
    # health:  ● | Bucket | # | Signal
    'health': ['34px', '22%', '6%', '72%'],
    # due:     Item | Owner | Due | Status
    'due4':   ['46%', '18%', '14%', '22%'],
}

def table_shape(head):
    h = [x.strip().lower() for x in head]
    n = len(h)
    if n == 8 and h[0] == '●':
        return 'reg8'
    if n == 4 and h[0] == '●':
        return 'health'
    if n == 4 and h[0] in ('item',):
        return 'due4'
    return None


def mk_table(head, rows):
    shape = table_shape(head)
    th = ''.join('<th>%s</th>' % inline(h) for h in head)
    trs = []
    for r in rows:
        cls = ''
        if r and r[0] in RAG: cls = ' class="r-%s"' % RAG[r[0]]
        tds = ''.join('<td>%s</td>' % cell_html(c, k == 0) for k, c in enumerate(r))
        trs.append('<tr%s>%s</tr>' % (cls, tds))
    cg, tcls = '', ''
    if shape:
        cg = '<colgroup>%s</colgroup>' % ''.join('<col style="width:%s">' % w for w in COLGROUPS[shape])
        tcls = ' class="t-%s"' % shape
    return '<div class="tw"><table%s>%s<thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>' % (
        tcls, cg, th, ''.join(trs))


def convert(path):
    src = open(path).read().split('\n')
    meta = {}
    m = re.search(r'<!--\s*deep-dive-agenda:\s*(.*?)\s*-->', '\n'.join(src[:4]))
    if m:
        for part in m.group(1).split('|'):
            if ':' in part:
                k, v = part.split(':', 1); meta[k.strip()] = v.strip()
    title = src[0].lstrip('# ').strip()
    body, i, n = [], 0, len(src)
    while i < n:
        ln = src[i]
        if ln.startswith('# ') or ln.strip().startswith('<!--'): i += 1; continue
        if ln.strip() == '---': i += 1; continue
        if ln.lstrip().startswith('```'):
            fence = ln.strip()[:3]; i += 1; buf = []
            while i < n and not src[i].strip().startswith(fence):
                buf.append(src[i]); i += 1
            i += 1
            body.append('<pre><code>%s</code></pre>' % esc('\n'.join(buf)))
            continue
        if ln.startswith('#### '): body.append('<h4>%s</h4>' % inline(ln[5:])); i += 1; continue
        if ln.startswith('### '):
            h = ln[4:].strip(); cls = ''
            for e, c in RAG.items():
                if h.startswith(e): cls = ' class="sec-%s"' % c; break
            body.append('<h3%s>%s</h3>' % (cls, inline(h))); i += 1; continue
        if ln.startswith('## '):
            body.append('<h2>%s</h2>' % inline(ln[3:])); i += 1; continue
        if ln.lstrip().startswith('|') and i+1 < n and re.match(r'^\s*\|[\s:\-|]+\|?\s*$', src[i+1]):
            head = cells(ln); i += 2
            rows = []
            while i < n and src[i].lstrip().startswith('|'):
                rows.append(cells(src[i])); i += 1
            body.append(mk_table(head, rows))
            continue
        if ln.startswith('>'):
            buf = []
            while i < n and (src[i].startswith('>') or (buf and src[i].startswith('  ') and src[i].strip())):
                buf.append(re.sub(r'^>\s?', '', src[i])); i += 1
            txt = '\n'.join(buf)
            cls = 'warn' if ('⚠️' in txt) else ('ok' if ('✅' in txt) else ('stale' if '⏳' in txt else 'note'))
            paras = [p for p in re.split(r'\n\s*\n', txt) if p.strip()]
            inner = []
            for p in paras:
                sub = [x for x in p.split('\n')]
                if all(x.strip().startswith('- ') or not x.strip() for x in sub if x.strip()):
                    inner.append('<ul>%s</ul>' % ''.join('<li>%s</li>' % inline(x.strip()[2:]) for x in sub if x.strip()))
                else:
                    inner.append('<p>%s</p>' % inline(' '.join(x.strip() for x in sub if x.strip())))
            body.append('<blockquote class="%s">%s</blockquote>' % (cls, ''.join(inner)))
            continue
        if re.match(r'^\s*[-*]\s+', ln) or re.match(r'^\s*\d+\.\s+', ln):
            items = []
            while i < n:
                if not src[i].strip():
                    j = i + 1
                    while j < n and not src[j].strip(): j += 1
                    if j < n and items and src[j].startswith('  ') and not re.match(r'^\s*[-*]\s+', src[j]) and not re.match(r'^\s*\d+\.\s+', src[j]):
                        i = j; continue
                    break
                if not (re.match(r'^\s*[-*]\s+', src[i]) or re.match(r'^\s*\d+\.\s+', src[i]) or (items and src[i].startswith('  '))):
                    break
                cur = src[i]
                if cur.lstrip().startswith('|') and i+1 < n and re.match(r'^\s*\|[\s:\-|]+\|?\s*$', src[i+1]) and items:
                    thead = cells(cur); i += 2
                    trows = []
                    while i < n and src[i].lstrip().startswith('|'):
                        trows.append(cells(src[i])); i += 1
                    items[-1].append(mk_table(thead, trows))
                    continue
                if re.match(r'^\s*[-*]\s+', cur) or re.match(r'^\s*\d+\.\s+', cur):
                    ind = len(cur) - len(cur.lstrip())
                    items.append([ind, re.sub(r'^\s*(?:[-*]|\d+\.)\s+', '', cur)])
                elif items:
                    items[-1][1] += ' ' + cur.strip()
                i += 1
            ordered = bool(re.match(r'^\s*\d+\.\s+', ln))
            out, depth = [], 0
            tag = 'ol' if ordered else 'ul'
            out.append('<%s>' % tag)
            base = items[0][0]
            for it in items:
                ind, txt = it[0], it[1]
                extra = ''.join(it[2:])
                if ind > base and depth == 0: out.append('<ul class="sub">'); depth = 1
                elif ind <= base and depth == 1: out.append('</ul>'); depth = 0
                out.append('<li>%s%s</li>' % (inline(txt), extra))
            if depth: out.append('</ul>')
            out.append('</%s>' % tag)
            body.append(''.join(out)); continue
        if ln.strip():
            buf = []
            while i < n and src[i].strip() and not src[i].lstrip().startswith(('#', '|', '>', '- ', '* ', '```')) and not re.match(r'^\s*\d+\.\s', src[i]):
                buf.append(src[i].strip()); i += 1
            if not buf:
                # GUARANTEED PROGRESS. This line reached the paragraph branch but the
                # condition above excludes it, so without this guard `i` never advances
                # and convert() spins forever -- no error, no exit, no log.
                # Live case: a table row whose separator line is missing falls past the
                # table branch and lands here. On 2026-08-20 `buktu.md:133` (a ✅ Shipped
                # row that lost its header) hung a publish run at 14:06 and left b-eye
                # stale for 18 of 20 dashboards. Auto-publish runs unattended inside
                # brain-morning-start, so a hang there has nobody to kill it.
                # Emit the line and warn: a malformed agenda must look wrong and say so,
                # never render clean or stall in silence.
                sys.stderr.write(
                    "WARN %s:%d — line claimed by no block rule (missing table separator?), "
                    "emitted as a paragraph: %s\n" % (os.path.basename(path), i + 1, ln.strip()[:80]))
                buf.append(src[i].strip()); i += 1
            t = ' '.join(buf)
            if t.strip() in ('_none_',) or re.match(r'^_.*_$', t.strip()):
                body.append('<p class="empty">%s</p>' % inline(t.strip().strip('_')))
            elif t.startswith('**Verdict:**'):
                body.append('<p class="verdict">%s</p>' % inline(t))
            else:
                body.append('<p>%s</p>' % inline(t))
            continue
        i += 1
    return title, meta, '\n'.join(body)

CSS = """
:root{--bg:#fbfbfc;--panel:#fff;--ink:#16181d;--dim:#5b6270;--faint:#8b93a3;--line:#e4e7ec;--line2:#eef0f4;
--red:#d93a45;--amber:#c9750b;--green:#1c8a5a;--blue:#2563c9;--grey:#98a0b0;--pause:#7b52c9;--done:#1c8a5a;
--redbg:#fdf1f2;--amberbg:#fdf6ec;--greenbg:#eff9f4;--bluebg:#f0f5fd;--greybg:#f6f7f9;--pausebg:#f5f1fd;
--accent:#16181d;--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
/* b-eye's viewer chrome is light-only (v1.23.x), so this page commits to light and does NOT
   follow prefers-color-scheme — a dark page inside a light shell reads as broken.
   The [data-theme=dark] hook below is here for whenever b-eye grows a dark mode. */
:root[data-theme=dark]{--bg:#0e1014;--panel:#15181e;--ink:#e8eaee;--dim:#a2aab8;--faint:#7c8494;--line:#262b34;--line2:#1d2129;
--red:#f2717c;--amber:#e8a33d;--green:#4cc48c;--blue:#6ba3f5;--grey:#7c8494;--pause:#b393f0;--done:#4cc48c;
--redbg:#25161a;--amberbg:#241d13;--greenbg:#132420;--bluebg:#141d2c;--greybg:#191d24;--pausebg:#1d1830;--accent:#e8eaee}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;-webkit-font-smoothing:antialiased}
.wrap{max-width:1440px;margin:0 auto;padding:28px 24px 72px}
header.hd{border-bottom:2px solid var(--accent);padding-bottom:16px;margin-bottom:8px}
h1{margin:0 0 8px;font-size:clamp(22px,3.4vw,34px);line-height:1.15;letter-spacing:-.02em;font-weight:750}
.metarow{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.pill{font:600 11px/1 var(--mono);letter-spacing:.08em;text-transform:uppercase;padding:5px 9px;border-radius:5px;border:1px solid var(--line);color:var(--dim);background:var(--panel)}
.pill.live{color:var(--green);border-color:var(--green);background:var(--greenbg)}
.pill.archived{color:var(--amber);border-color:var(--amber);background:var(--amberbg)}
.pill.key{color:var(--ink);font-weight:700}
h2{margin:38px 0 12px;font-size:19px;letter-spacing:-.01em;font-weight:700;padding-bottom:7px;border-bottom:1px solid var(--line)}
h3{margin:26px 0 10px;font-size:15px;font-weight:700;letter-spacing:-.005em;display:flex;align-items:center;gap:8px}
h3::before{content:"";width:3px;height:16px;border-radius:2px;background:var(--grey);flex:none}
h3.sec-red::before{background:var(--red)}h3.sec-amber::before{background:var(--amber)}h3.sec-green::before{background:var(--green)}
h3.sec-blue::before{background:var(--blue)}h3.sec-grey::before{background:var(--grey)}h3.sec-pause::before{background:var(--pause)}h3.sec-done::before{background:var(--done)}
h4{margin:18px 0 6px;font-size:14px;font-weight:700}
p{margin:9px 0}
p.verdict{background:var(--panel);border:1px solid var(--line);border-left:3px solid var(--accent);border-radius:0 7px 7px 0;padding:12px 14px;margin:14px 0;font-size:15.5px}
p.empty{color:var(--faint);font-style:italic}
a{color:var(--blue);text-decoration:none;border-bottom:1px solid color-mix(in srgb,var(--blue) 32%,transparent)}
a:hover{border-bottom-color:var(--blue)}
code{font:12.5px/1.45 var(--mono);background:var(--greybg);border:1px solid var(--line2);border-radius:4px;padding:1px 5px}
.wl,.xref{font:12.5px/1.45 var(--mono);color:var(--dim);background:var(--greybg);border:1px dashed var(--line);border-radius:4px;padding:1px 5px}
strong{font-weight:680}
ul,ol{margin:9px 0;padding-left:22px}li{margin:5px 0}ul.sub{margin:5px 0}
blockquote{margin:14px 0;padding:12px 15px;border-radius:0 7px 7px 0;border:1px solid var(--line);border-left:3px solid var(--grey);background:var(--panel)}
blockquote>:first-child{margin-top:0}blockquote>:last-child{margin-bottom:0}
blockquote.warn{border-left-color:var(--red);background:var(--redbg)}
blockquote.ok{border-left-color:var(--green);background:var(--greenbg)}
blockquote.stale{border-left-color:var(--amber);background:var(--amberbg)}
.tw{overflow-x:auto;margin:12px 0;border:1px solid var(--line);border-radius:8px;background:var(--panel)}
table{border-collapse:collapse;width:100%;min-width:760px;font-size:13.5px}
/* pin the column grid so every table of the same shape lines up across buckets */
table.t-reg8{table-layout:fixed;min-width:1120px}
table.t-health{table-layout:fixed;min-width:640px}
table.t-due4{table-layout:fixed;min-width:680px}
table.t-reg8 td,table.t-reg8 th,table.t-health td,table.t-health th,table.t-due4 td,table.t-due4 th{
overflow-wrap:anywhere;word-break:normal}
table.t-reg8 code,table.t-due4 code{overflow-wrap:anywhere}
th{text-align:left;font:600 11px/1.3 -apple-system,BlinkMacSystemFont,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:var(--faint);
padding:10px 11px;border-bottom:1px solid var(--line);background:var(--greybg);position:sticky;top:0;white-space:nowrap}
td{padding:10px 11px;border-bottom:1px solid var(--line2);vertical-align:top;line-height:1.5}
tbody tr:last-child td{border-bottom:none}
tbody tr{border-left:3px solid transparent}
tr.r-red{border-left-color:var(--red)}tr.r-amber{border-left-color:var(--amber)}tr.r-green{border-left-color:var(--green)}
tr.r-blue{border-left-color:var(--blue)}tr.r-grey{border-left-color:var(--grey)}tr.r-pause{border-left-color:var(--pause)}tr.r-done{border-left-color:var(--done)}
table.t-reg8 td:first-child,table.t-health td:first-child{text-align:center;padding-left:9px}
.chip{font-size:14px;line-height:1}
.none{color:var(--faint);font-family:var(--mono);font-size:12.5px;white-space:nowrap}
.bar{display:inline-block;width:56px;height:7px;border-radius:4px;background:var(--line);overflow:hidden;vertical-align:middle;margin-right:7px}
.bar-fill{display:block;height:100%;background:var(--accent);border-radius:4px}
.bar-lbl{font:12px/1 var(--mono);color:var(--dim);white-space:nowrap}
a.u{font:12.5px/1.4 var(--mono);white-space:nowrap}
pre{background:var(--greybg);border:1px solid var(--line);border-radius:7px;padding:12px 14px;overflow-x:auto;margin:12px 0}
pre code{background:none;border:none;padding:0;font-size:12px;line-height:1.5;white-space:pre}
li>.tw{margin:10px 0}
@media (max-width:640px){.wrap{padding:18px 14px 56px}h1{font-size:21px}table{font-size:12.5px}}
"""

def render(path):
    title, meta, body = convert(path)
    fresh = meta.get('freshness', '')
    pills = []
    if fresh: pills.append('<span class="pill %s">%s</span>' % (fresh.lower(), esc(fresh)))
    if meta.get('team'): pills.append('<span class="pill key">%s</span>' % esc(meta['team']))
    if meta.get('linear') and meta['linear'] != '—': pills.append('<span class="pill">Linear: %s</span>' % esc(meta['linear']))
    if meta.get('generated'): pills.append('<span class="pill">built %s</span>' % esc(meta['generated']))
    if meta.get('type'): pills.append('<span class="pill">%s</span>' % esc(meta['type']))
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>%s</title><style>%s</style></head><body><div class="wrap">'
            '<header class="hd"><h1>%s</h1><div class="metarow">%s</div></header>%s'
            '</div></body></html>') % (esc(title), CSS, esc(title), ''.join(pills), body)

# ---------------------------------------------------------------------------
# Publish to b-eye.  Renders an agenda to a self-contained dashboard and pushes
# it into the "Deep Dives" folder (archive/ -> the Archive subfolder).
#
# This file lives WITH its skill, not with the agendas it publishes, so it never
# infers the agendas directory from its own location.  Resolution order:
#   --agendas <dir>  ->  $DEEP_DIVES_DIR  ->  outputs/agents/my-deep-dives (cwd)
# A missing directory is a hard error, never an empty glob reported as success.
#
#   python3 publish-to-beye.py tium              # one agenda, by SLUG
#   python3 publish-to-beye.py tium buktu        # several
#   python3 publish-to-beye.py --all             # every agenda + this skill's reference.md
#   python3 publish-to-beye.py --all --render    # build to .beye-build/ only, no upload
#
# Asset ids live in <agendas>/.beye-assets.json so re-runs append a VERSION to
# the existing dashboard instead of creating a duplicate.  That map is MERGED and
# replaced atomically: brain-morning-start publishes several agendas in PARALLEL,
# and a last-writer-wins overwrite silently drops a sibling's newly created id --
# which surfaces one run later as a duplicate dashboard.  Requires `wr-beye` on
# PATH and a live login (`wr-beye auth status`).
#
# b-eye render constraints the converter above already satisfies:
#   * CSP `default-src 'none'` + `style-src 'unsafe-inline'` -> everything inline,
#     no external CSS/JS/fonts/images.
#   * viewer iframe is `sandbox="allow-scripts allow-popups
#     allow-popups-to-escape-sandbox"`, so `target="_blank"` links DO open.
#     (Verified 2026-08-20 on b-eye v1.23.1 -- read the live attribute before
#     assuming; an older note in memory/L3 said links were impossible.)
#   * the viewer chrome is light-only, so the page pins light and does NOT
#     follow prefers-color-scheme.
# ---------------------------------------------------------------------------

FOLDER_LIVE = "a830ba29-0623-4019-aa2e-74eafa7faec7"   # Tech: Product / Deep Dives
FOLDER_ARCHIVE = "82f6bafa-6efb-4bf1-9e41-f0c99e0257ab"  # .../Archive (superseded)

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_AGENDAS = os.path.join("outputs", "agents", "my-deep-dives")
REFERENCE = os.path.join(SKILL_DIR, "reference.md")

NAMES = {
    "tium": "TIUM", "buktu": "BUKTU", "content-seo": "Content / SEO", "data": "DATA",
    "ged": "GED (Design)", "saian": "SAIAN", "rocket": "ROCKET (WeMeet)", "cyclops": "CYCLOPS",
    "saitama": "SAITAMA", "stomp": "STOMP", "tech": "TECH (cross-cutting)",
    "devops": "DevOps & IT", "ai": "AI (SAIAN + Guild)", "crm-sales-ai": "CRM & Sales AI",
    "template": "The standard (agenda template)",
    "archive/ai-sales": "AI Sales - Jul 6 (superseded)",
    "archive/deep-dive-tech": "TECH - Jun 18 (superseded)",
    "archive/devops-it": "DevOps & IT - Jul 30 (superseded)",
    "archive/monkeys-leads": "Monkeys Leads - Apr 14 (archived)",
    "archive/staff": "STAFF - Apr 16 (superseded)",
}

USAGE = """usage: publish-to-beye.py [SLUG ...] [--all] [--template] [--render] [--agendas DIR]

  SLUG            agenda slug, e.g. tium, devops, archive/staff (NOT a path)
  --all           every agenda in the agendas dir + archive/ + this skill's reference.md
  --template      also publish reference.md as the "The standard" dashboard
  --render        build HTML into <agendas>/.beye-build/ only, no upload
  --no-publish    alias for --render
  --agendas DIR   agendas directory (default: $DEEP_DIVES_DIR or outputs/agents/my-deep-dives)

Naming no target is an error, not a no-op: a bare run must not silently
republish all 20 dashboards, nor silently do nothing."""


def parse_args(argv):
    opts = {"render": False, "all": False, "template": False, "agendas": None}
    named, i = [], 0
    while i < len(argv):
        a = argv[i]
        if a in ("--render", "--no-publish"): opts["render"] = True
        elif a == "--all": opts["all"] = True
        elif a == "--template": opts["template"] = True
        elif a == "--agendas":
            i += 1
            if i >= len(argv): sys.exit("publish-to-beye: --agendas needs a directory\n\n" + USAGE)
            opts["agendas"] = argv[i]
        elif a.startswith("--agendas="): opts["agendas"] = a.split("=", 1)[1]
        elif a in ("-h", "--help"): print(USAGE); sys.exit(0)
        elif a.startswith("-"): sys.exit("publish-to-beye: unknown flag %s\n\n%s" % (a, USAGE))
        else: named.append(a)
        i += 1
    return opts, named


def resolve_agendas(opt):
    d = opt or os.environ.get("DEEP_DIVES_DIR") or DEFAULT_AGENDAS
    d = os.path.abspath(d)
    if not os.path.isdir(d):
        sys.exit("publish-to-beye: agendas dir not found: %s\n"
                 "  run from the brain root, or pass --agendas DIR / set DEEP_DIVES_DIR." % d)
    return d


def resolve_targets(opts, named, agendas):
    """-> [(slug, path)]. Slugs resolve under the agendas dir; 'template' is this skill's
    reference.md, which by design does NOT live there."""
    import glob
    out = []
    if opts["all"]:
        for p in sorted(glob.glob(os.path.join(agendas, "*.md"))) + \
                 sorted(glob.glob(os.path.join(agendas, "archive", "*.md"))):
            out.append((os.path.relpath(p, agendas)[:-3], p))
    for n in named:
        slug = n[:-3] if n.endswith(".md") else n
        if slug == "template":
            out.append(("template", REFERENCE)); continue
        p = os.path.join(agendas, slug + ".md")
        if not os.path.exists(p):
            sys.exit("publish-to-beye: no such agenda: %s\n  (slugs are relative to %s)"
                     % (p, agendas))
        out.append((slug, p))
    if opts["template"] or opts["all"]:
        out.append(("template", REFERENCE))
    seen, uniq = set(), []
    for slug, p in out:
        if slug in seen: continue
        if slug == "template" and not os.path.exists(p):
            print("%-34s SKIP (no reference.md beside the skill)" % slug); continue
        seen.add(slug); uniq.append((slug, p))
    return uniq


def save_assets(mapfile, touched):
    """Merge only this run's keys into the on-disk map, then replace it atomically.
    Never write the whole in-memory dict back: a parallel sibling may have added an
    id since we read it, and losing an id means the NEXT run creates a duplicate
    dashboard instead of appending a version."""
    import json, tempfile
    cur = json.load(open(mapfile)) if os.path.exists(mapfile) else {}
    cur.update(touched)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(mapfile),
                              prefix=".beye-assets.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(cur, f, indent=2, sort_keys=True)
        os.replace(tmp, mapfile)
    except BaseException:
        if os.path.exists(tmp): os.unlink(tmp)
        raise
    return cur


def main(argv):
    import json, subprocess
    opts, named = parse_args(argv)
    if not named and not opts["all"] and not opts["template"]:
        sys.exit(USAGE)

    agendas = resolve_agendas(opts["agendas"])
    build = os.path.join(agendas, ".beye-build")
    os.makedirs(build, exist_ok=True)
    mapfile = os.path.join(agendas, ".beye-assets.json")
    assets = json.load(open(mapfile)) if os.path.exists(mapfile) else {}

    targets = resolve_targets(opts, named, agendas)
    touched, failed = {}, []

    for slug, md in targets:
        out = os.path.join(build, slug.replace("/", "__") + ".html")
        open(out, "w").write(render(md))
        if opts["render"]:
            print("%-34s %6d B  %s" % (slug, os.path.getsize(out), out)); continue
        name = NAMES.get(slug)
        if not name:
            print("%-34s SKIP (no name mapped)" % slug); failed.append((slug, "no name mapped")); continue
        folder = FOLDER_ARCHIVE if slug.startswith("archive/") else FOLDER_LIVE
        if slug in assets:
            cmd = ["wr-beye", "upload-version", assets[slug], out]
        else:
            cmd = ["wr-beye", "upload", out, "--name", name, "--folder", folder]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            err = r.stderr.strip()[:140] or ("exit %d" % r.returncode)
            print("%-34s ERROR %s" % (slug, err)); failed.append((slug, err)); continue
        try:
            j = json.loads(r.stdout)
        except ValueError:
            err = "unparseable wr-beye output: %s" % r.stdout.strip()[:100]
            print("%-34s ERROR %s" % (slug, err)); failed.append((slug, err)); continue
        touched[slug] = j.get("assetId") or j.get("id")
        print("%-34s v%-3s %s" % (slug, j.get("version"), touched[slug]))

    if not opts["render"]:
        if touched:
            save_assets(mapfile, touched)
            print("\nasset map -> %s (%d merged)" % (mapfile, len(touched)))
        # Loud, per-slug, and non-fatal: the .md on disk is the primary output, so an
        # expired wr-beye login must not throw away a good agenda -- but a stale
        # dashboard has to announce itself rather than be assumed fresh.
        if failed:
            print("\n%d of %d FAILED TO PUBLISH -- b-eye is STALE for:" % (len(failed), len(targets)))
            for slug, why in failed:
                print("  %-30s %s" % (slug, why))
            print("  fix, then: python3 %s %s" % (os.path.relpath(__file__),
                                                  " ".join(s for s, _ in failed)))
            return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
