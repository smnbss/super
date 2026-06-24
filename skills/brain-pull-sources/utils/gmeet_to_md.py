#!/usr/bin/env python3
from __future__ import annotations
"""
Google Meet / Calendar meeting-notes harvester (deterministic, no LLM).

Ports Steps 1-5 of the `brain-pull-my-meeting-notes` skill into a source CLI that
fits the sources.md / pull_sources pattern (like drive_to_md). It fetches the
calendar events <email> is invited to, discovers their artifacts (Gemini notes,
agendas, recordings, attachments, transcripts) on Drive, exports them to Markdown,
and writes per-meeting folders + a static per-day index.md. It does NOT produce
the daily/weekly/monthly/YTD digests — those stay in the skill (they need an LLM).

Usage:
    gmeet_to_md <email>                      # default: full span last_harvested .. today,
                                             #   re-harvested every run (idempotent — safe to
                                             #   loop every 15 min; the whole range is re-checked
                                             #   so notes added after a meeting ended are captured.
                                             #   First run for an email: yesterday + today)
    gmeet_to_md <email> --since 2026-06-01   # that date .. yesterday, inclusive
    gmeet_to_md <email> --day 2026-06-20     # a single specific day
    gmeet_to_md <email> --days 14            # trailing N days .. yesterday
    gmeet_to_md --list                       # print the registry and exit

Re-running always rebuilds each day in range non-destructively: CLI-owned files
(metadata.json, notes.md, agenda.md, recording.md, attachment-*.md, index.md)
are regenerated fresh, while day-level *-digest.md and per-meeting transcript.md
are preserved. `last_harvested` in the registry tracks the latest COMPLETE day
(never today).

Assumes  email == the authenticated gws user  (email is passed as calendarId).
A 403/404 from the calendar API is a hard error, never a silent fallback.

Output:
    src/gmeet/.registry.json                 # [{email, last_harvested, last_synced, stats}]
    src/gmeet/YYYY/WNN/MM-DD/
        <meeting-slug>/                      # only if >=1 content artifact
            metadata.json
            notes.md  agenda.md  transcript.md  recording.md  attachment-<slug>.md
        index.md                             # static table of the day's meetings
"""

import argparse
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo


# -- Paths / env --------------------------------------------------------------

PROJECT_ROOT = subprocess.run(
    ["git", "rev-parse", "--show-toplevel"],
    capture_output=True, text=True,
).stdout.strip()
OUTPUT_BASE = os.path.join(PROJECT_ROOT, "src", "gmeet")
REGISTRY_PATH = os.path.join(OUTPUT_BASE, ".registry.json")

TIMEZONE = ZoneInfo("Europe/Rome")
CONVERT_TIMEOUT_SECS = 120


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


def _rel(path: str) -> str:
    return os.path.relpath(path, PROJECT_ROOT)


# -- Filters (from the skill) -------------------------------------------------

EXCLUDE_PATTERNS = [
    re.compile(r"^Lunch$", re.I),
    re.compile(r"^Out of Office", re.I),
    re.compile(r"^Focus Time", re.I),
    re.compile(r"^Birthday", re.I),
]
EXCLUDE_EVENT_TYPES = {"workingLocation", "outOfOffice", "focusTime"}

GEMINI_NOTES_NEEDLES = ["Notes by Gemini", "Appunti di Gemini"]
TRANSCRIPT_NEEDLES = ["Transcript", "Trascrizione"]

GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
TITLE_MATCH_THRESHOLD = 0.55
MARKITDOWN_EXTS = {".pdf", ".docx", ".pptx", ".xlsx", ".xls", ".html"}
EXT_MAP = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/msword": ".doc",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.ms-excel": ".xls",
    "text/plain": ".txt",
    "text/html": ".html",
}


# -- gws helpers --------------------------------------------------------------

class CalendarAccessError(RuntimeError):
    pass


def gws_json(service: str, *args, **params) -> dict:
    clean = {k: v for k, v in params.items() if v is not None}
    cmd = ["gws", service, *args, "--params", json.dumps(clean)]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        if service == "calendar" and re.search(r"\b(403|404|forbidden|notFound|not found)\b", stderr, re.I):
            raise CalendarAccessError(stderr)
        raise RuntimeError(f"gws {service} {' '.join(args)} failed: {stderr}")
    out = result.stdout
    i = out.find("{")
    return json.loads(out[i:] if i >= 0 else out)


def gws_export(file_id: str, output_path: str, mime_type: str) -> bool:
    """Export a Google Workspace doc to a file (drive files export)."""
    cmd = ["gws", "drive", "files", "export",
           "--params", json.dumps({"fileId": file_id, "mimeType": mime_type}),
           "-o", _rel(output_path)]
    return subprocess.run(cmd, capture_output=True, cwd=PROJECT_ROOT).returncode == 0


def gws_download(file_id: str, output_path: str) -> bool:
    """Download a binary file via alt=media (drive files get)."""
    cmd = ["gws", "drive", "files", "get",
           "--params", json.dumps({"fileId": file_id, "alt": "media",
                                   "supportsAllDrives": True}),
           "-o", _rel(output_path)]
    return subprocess.run(cmd, capture_output=True, cwd=PROJECT_ROOT).returncode == 0


def drive_get(file_id: str, fields: str) -> dict:
    return gws_json("drive", "files", "get",
                    fileId=file_id, fields=fields, supportsAllDrives=True)


def drive_search(q: str, fields: str) -> list[dict]:
    items: list[dict] = []
    page_token = None
    while True:
        params = {
            "q": q,
            "fields": f"nextPageToken,{fields}",
            "pageSize": 100,
            "includeItemsFromAllDrives": True,
            "supportsAllDrives": True,
            "corpora": "allDrives",
        }
        if page_token:
            params["pageToken"] = page_token
        data = gws_json("drive", "files", "list", **params)
        items.extend(data.get("files", []))
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return items


# -- markitdown (subprocess with hard timeout) --------------------------------

_CONVERT_SCRIPT = """\
import sys, json
from markitdown import MarkItDown
try:
    r = MarkItDown().convert(sys.argv[1])
    with open(sys.argv[2], "w", encoding="utf-8") as f:
        f.write(r.text_content)
except Exception as e:
    print(json.dumps({"error": str(e)}), file=sys.stderr)
    sys.exit(1)
"""


def convert_with_markitdown(path: str, timeout: int = CONVERT_TIMEOUT_SECS) -> str:
    with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        result = subprocess.run(
            [sys.executable, "-c", _CONVERT_SCRIPT, path, tmp_path],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "markitdown conversion failed")
        with open(tmp_path, encoding="utf-8") as f:
            return f.read()
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"markitdown timed out after {timeout}s on {os.path.basename(path)}")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# -- date / range helpers -----------------------------------------------------

def day_bounds_utc(d: date) -> tuple[str, str]:
    """Midnight-to-midnight of `d` in Europe/Rome, as RFC3339 strings."""
    start = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=TIMEZONE)
    end = start + timedelta(days=1)
    return start.isoformat(), end.isoformat()


def iso_week_dir(d: date) -> str:
    return f"W{d.isocalendar()[1]:02d}"


def parse_ymd(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def daterange(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def resolve_range(args, last_harvested: str | None, today: date) -> list[date]:
    """Return the inclusive list of days to harvest."""
    yesterday = today - timedelta(days=1)
    given = [bool(args.day), bool(args.since), bool(args.days)]
    if sum(given) > 1:
        print("WARN: --day / --since / --days are mutually exclusive; using the last one given.",
              file=sys.stderr)
    if args.day:
        d = parse_ymd(args.day)
        return [d]
    if args.since:
        return list(daterange(parse_ymd(args.since), yesterday))
    if args.days:
        return list(daterange(yesterday - timedelta(days=args.days - 1), yesterday))
    # No flag → default: re-harvest the FULL span [last_harvested .. today],
    # inclusive, on every run. The start is last_harvested itself (not +1), and
    # every day in range is rebuilt non-destructively each pass — so notes and
    # recordings added after a meeting ended are always re-captured, and a gap is
    # self-healed. Safe to loop (e.g. every 15 min). First run (no registry)
    # seeds with yesterday + today.
    if last_harvested:
        start = min(parse_ymd(last_harvested), today)
        return list(daterange(start, today))
    return list(daterange(yesterday, today))


# -- slug / matching ----------------------------------------------------------

INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def slugify(name: str) -> str:
    s = name.lower().replace("1:1", "1on1")
    # Collapse every run of non-alphanumeric chars to a single hyphen.
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:80] or "meeting"


def normalize_title(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s.lower())).strip()


def strip_gemini_suffix(doc_name: str) -> str:
    """'Title – 2026/06/22 16:00 CEST – Notes by Gemini' → 'Title'."""
    parts = re.split(r"\s[–-]\s", doc_name)
    if len(parts) >= 2:
        return parts[0].strip()
    return doc_name.strip()


def best_match(meeting, candidates: list[dict]) -> dict | None:
    """Pick the Drive doc whose name best matches the meeting title; tie-break by
    creation-time proximity to the meeting start."""
    mt = normalize_title(meeting["title"])
    if not mt:
        return None
    scored = []
    for c in candidates:
        cand_title = normalize_title(strip_gemini_suffix(c.get("name", "")))
        ratio = difflib.SequenceMatcher(None, mt, cand_title).ratio()
        if ratio >= TITLE_MATCH_THRESHOLD:
            created = c.get("createdTime", "")
            delta = abs(_iso_to_epoch(created) - meeting["_start_epoch"]) if created else 1e18
            scored.append((ratio, -delta, c))
    if not scored:
        return None
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return scored[0][2]


def _iso_to_epoch(s: str) -> float:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


# -- content-date guard (Step 2a) --------------------------------------------

_DATE_RES = [
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),
    re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"),
]
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_MONTHS.update({m: i for i, m in enumerate(
    ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"], 1)})
_MONTH_RE = re.compile(r"\b([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})\b")


def find_content_date(text: str) -> date | None:
    head = "\n".join(text.splitlines()[:10]).lower()
    m = _DATE_RES[0].search(head)
    if m:
        try:
            return date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            pass
    m = _MONTH_RE.search(head)
    if m and m[1][:3] in _MONTHS:
        try:
            return date(int(m[3]), _MONTHS[m[1][:3]], int(m[2]))
        except ValueError:
            pass
    m = _DATE_RES[1].search(head)
    if m:
        for day_, mon_ in ((int(m[1]), int(m[2])), (int(m[2]), int(m[1]))):
            try:
                return date(int(m[3]), mon_, day_)
            except ValueError:
                continue
    return None


# -- calendar fetch + filter (Step 1) ----------------------------------------

def fetch_events(calendar_id: str, d: date) -> list[dict]:
    time_min, time_max = day_bounds_utc(d)
    items: list[dict] = []
    page_token = None
    while True:
        params = {
            "calendarId": calendar_id,
            "timeMin": time_min,
            "timeMax": time_max,
            "singleEvents": True,
            "orderBy": "startTime",
            "maxResults": 250,
        }
        if page_token:
            params["pageToken"] = page_token
        data = gws_json("calendar", "events", "list", **params)
        items.extend(data.get("items", []))
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return items


def keep_event(ev: dict) -> bool:
    if ev.get("status") == "cancelled":
        return False
    if ev.get("eventType") in EXCLUDE_EVENT_TYPES:
        return False
    summary = ev.get("summary", "") or ""
    if any(p.search(summary) for p in EXCLUDE_PATTERNS):
        return False
    return bool(ev.get("conferenceData") or ev.get("attachments"))


def event_to_meeting(ev: dict) -> dict:
    start = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date", "")
    end = ev.get("end", {}).get("dateTime") or ev.get("end", {}).get("date", "")
    start_dt = _iso_to_epoch(start)
    end_dt = _iso_to_epoch(end)
    duration = int((end_dt - start_dt) / 60) if start_dt and end_dt else 0
    org = ev.get("organizer", {})
    conf = ev.get("conferenceData", {})
    conf_id = conf.get("conferenceId", "")
    return {
        "eventId": ev.get("id", ""),
        "title": ev.get("summary", "(no title)"),
        "startTime": start,
        "endTime": end,
        "durationMinutes": duration,
        "organizer": {"name": org.get("displayName", ""), "email": org.get("email", "")},
        "attendees": [
            {"name": a.get("displayName", ""), "email": a.get("email", ""),
             "responseStatus": a.get("responseStatus", "")}
            for a in ev.get("attendees", [])
        ],
        "conferenceId": conf_id,
        "meetLink": ev.get("hangoutLink", ""),
        "attachments": ev.get("attachments", []),
        "_start_epoch": start_dt,
    }


# -- artifact export (Steps 2-3) ---------------------------------------------

def export_google_doc_md(file_id: str, title: str, out_path: str) -> bool:
    """Export a Google Doc as text/plain → '# Title' + de-wrapped markdown.

    The raw export is staged INSIDE the project tree (next to out_path), because
    `gws -o` refuses any path outside the current working directory."""
    raw_path = os.path.join(os.path.dirname(out_path), f".raw-{os.getpid()}.txt")
    try:
        if not gws_export(file_id, raw_path, "text/plain"):
            return False
        with open(raw_path, encoding="utf-8") as f:
            text = f.read()
        if not text.strip():
            return False
        body = text.replace("\r\n", "\n").strip("\n")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(f"# {title}\n\n{body}\n")
        return True
    finally:
        try:
            os.unlink(raw_path)
        except OSError:
            pass


def convert_attachment(att: dict, mime: str, out_dir: str) -> tuple[str, str] | None:
    """Download a non-Google-Doc attachment and convert via markitdown.
    Returns (local_md_filename, status) or None if it couldn't be saved."""
    file_id = att.get("fileId", "")
    name = att.get("title", file_id)
    stem = slugify(os.path.splitext(name)[0])
    ext = os.path.splitext(name)[1].lower() or EXT_MAP.get(mime, "")
    bin_path = os.path.join(out_dir, f"_dl-{stem}{ext}")
    if not gws_download(file_id, bin_path):
        return None
    md_name = f"attachment-{stem}.md"
    md_path = os.path.join(out_dir, md_name)
    drive_link = f"https://drive.google.com/open?id={file_id}"
    if ext in MARKITDOWN_EXTS:
        try:
            text = convert_with_markitdown(bin_path)
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(f"# Attachment: {name}\n\n<!-- source: {drive_link} -->\n\n{text}\n")
            os.remove(bin_path)
            return md_name, "converted"
        except Exception as e:
            print(f"    WARN: markitdown failed for {name}: {str(e).splitlines()[0][:140]}",
                  file=sys.stderr)
    # Unconvertible → keep a stub pointing at Drive, drop the binary.
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# Attachment: {name}\n\n> Not converted to markdown. "
                f"[Open in Drive]({drive_link})\n")
    try:
        os.remove(bin_path)
    except OSError:
        pass
    return md_name, "kept_link"


def write_recording_md(rec: dict, out_path: str) -> None:
    size = rec.get("size")
    size_str = f"{int(size) / (1024 * 1024):.1f} MB" if size else "unknown"
    link = rec.get("webViewLink", "")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"# Recording: {rec.get('name', '')}\n\n"
                f"- **Drive link:** {link}\n- **File size:** {size_str}\n")


# -- per-day harvest ----------------------------------------------------------

def harvest_day(calendar_id: str, d: date, stats: dict) -> int:
    """Harvest a single day. Returns the number of meeting folders written."""
    events = [e for e in fetch_events(calendar_id, d) if keep_event(e)]
    meetings = [event_to_meeting(e) for e in events]

    day_dir = os.path.join(OUTPUT_BASE, str(d.year), iso_week_dir(d), d.strftime("%m-%d"))
    os.makedirs(day_dir, exist_ok=True)
    # Rebuild idempotently, but never destroy artifacts the CLI doesn't own/reproduce:
    #   - day-level `*-digest.md` (LLM rollups from the meeting-notes skill)
    #   - per-meeting `transcript.md` (Meet-API transcripts — out of CLI scope)
    # Everything else (metadata.json, notes.md, agenda.md, recording.md,
    # attachment-*.md, index.md) is CLI-owned and rebuilt fresh.
    for entry in os.listdir(day_dir):
        p = os.path.join(day_dir, entry)
        if os.path.isfile(p):
            if not entry.endswith("-digest.md"):
                os.remove(p)
            continue
        kept_transcript = False
        for f in os.listdir(p):
            if f == "transcript.md":
                kept_transcript = True
                continue
            fp = os.path.join(p, f)
            shutil.rmtree(fp) if os.path.isdir(fp) else os.remove(fp)
        if not kept_transcript:
            shutil.rmtree(p)

    # Pre-fetch Drive candidates once per day (cheaper than per-meeting).
    time_min, time_max = day_bounds_utc(d)
    doc_window = (f"modifiedTime > '{time_min}' and modifiedTime < '{time_max}'")
    notes_q = (f'mimeType="{GOOGLE_DOC_MIME}" and ('
               + " or ".join(f'name contains "{n}"' for n in GEMINI_NOTES_NEEDLES)
               + f") and {doc_window}")
    transcript_q = (f'mimeType="{GOOGLE_DOC_MIME}" and ('
                    + " or ".join(f'name contains "{n}"' for n in TRANSCRIPT_NEEDLES)
                    + f") and {doc_window}")
    rec_q = f'mimeType contains "video" and {doc_window}'
    doc_fields = "files(id,name,createdTime,modifiedTime,webViewLink,owners)"
    rec_fields = "files(id,name,createdTime,modifiedTime,webViewLink,size)"

    note_candidates = drive_search(notes_q, doc_fields)
    transcript_candidates = drive_search(transcript_q, doc_fields)
    recording_candidates = drive_search(rec_q, rec_fields)

    rows = []
    folders_written = 0
    for m in meetings:
        slug = slugify(m["title"])
        # Collision: append start HHMM.
        existing = {r["slug"] for r in rows}
        if slug in existing and m["startTime"]:
            try:
                hhmm = datetime.fromisoformat(m["startTime"].replace("Z", "+00:00")
                                              ).astimezone(TIMEZONE).strftime("%H%M")
                slug = f"{slug}-{hhmm}"
            except Exception:
                pass
        m_dir = os.path.join(day_dir, slug)
        artifacts = {"notes": None, "transcript": None, "recording": None, "attachments": []}
        produced = []

        # 2a — event attachments (with stale + content-date guards)
        for att in m["attachments"]:
            mime = att.get("mimeType", "")
            fid = att.get("fileId", "")
            if not fid:
                continue
            title_l = (att.get("title", "") or "").lower()
            if mime == GOOGLE_DOC_MIME and any(
                    n.lower() in title_l for n in GEMINI_NOTES_NEEDLES + TRANSCRIPT_NEEDLES):
                # The Gemini notes/transcript doc is often attached to the event
                # itself. Skip it here — 2b/2d export it as notes.md/transcript.md.
                continue
            if mime == GOOGLE_DOC_MIME:
                meta = _safe_drive_get(fid, "id,name,modifiedTime")
                if meta and _attachment_too_stale(meta.get("modifiedTime", ""), d):
                    print(f"    Skipping stale attachment {att.get('title','')} "
                          f"(modified {meta.get('modifiedTime','')}, meeting {d})", file=sys.stderr)
                    continue
                os.makedirs(m_dir, exist_ok=True)
                agenda_path = os.path.join(m_dir, "agenda.md")
                if export_google_doc_md(fid, att.get("title", "Agenda"), agenda_path):
                    if _content_date_mismatch(agenda_path, d):
                        print(f"    Discarding attachment {att.get('title','')} — "
                              f"content date != meeting date {d}", file=sys.stderr)
                        os.remove(agenda_path)
                    else:
                        produced.append("agenda")
                        artifacts["attachments"].append(
                            {"name": att.get("title", ""), "fileId": fid,
                             "localFile": "agenda.md", "kind": "google-doc"})
            elif mime.startswith("video/"):
                # The Meet recording is attached to the event as a video. Never
                # download it — it's handled as a link by the recording step (2c).
                continue
            else:
                os.makedirs(m_dir, exist_ok=True)
                res = convert_attachment(att, mime, m_dir)
                if res:
                    md_name, status = res
                    produced.append("attachment")
                    artifacts["attachments"].append(
                        {"name": att.get("title", ""), "fileId": fid,
                         "localFile": md_name, "status": status})

        # 2b — Gemini notes
        note = best_match(m, note_candidates)
        if note:
            os.makedirs(m_dir, exist_ok=True)
            if export_google_doc_md(note["id"], m["title"], os.path.join(m_dir, "notes.md")):
                produced.append("notes")
                artifacts["notes"] = {"source": "drive-search", "docId": note["id"],
                                      "driveLink": note.get("webViewLink", "")}

        # 2d — transcript docs (best-effort)
        tr = best_match(m, transcript_candidates)
        if tr:
            os.makedirs(m_dir, exist_ok=True)
            if export_google_doc_md(tr["id"], f"Transcript: {m['title']}",
                                    os.path.join(m_dir, "transcript.md")):
                produced.append("transcript")
                artifacts["transcript"] = {"source": "drive-search", "docId": tr["id"],
                                           "driveLink": tr.get("webViewLink", "")}

        # 2c — recordings (link only)
        rec = best_match(m, recording_candidates)
        if rec:
            os.makedirs(m_dir, exist_ok=True)
            write_recording_md(rec, os.path.join(m_dir, "recording.md"))
            produced.append("recording")
            artifacts["recording"] = {"source": "drive-search", "driveFileId": rec["id"],
                                      "driveLink": rec.get("webViewLink", "")}

        rows.append({"slug": slug, "meeting": m, "produced": produced})

        if produced:
            _write_metadata(m_dir, m, slug, d, artifacts)
            folders_written += 1
            stats["meetings"] += 1
            stats["notes"] += 1 if artifacts["notes"] else 0
            stats["recordings"] += 1 if artifacts["recording"] else 0
            stats["attachments"] += len(artifacts["attachments"])
        elif os.path.isdir(m_dir):
            # No content artifact — never leave an empty folder behind.
            shutil.rmtree(m_dir)

    write_index(day_dir, d, rows)
    return folders_written


def _safe_drive_get(file_id: str, fields: str) -> dict | None:
    try:
        return drive_get(file_id, fields)
    except Exception:
        return None


def _attachment_too_stale(modified_iso: str, meeting_day: date) -> bool:
    if not modified_iso:
        return False
    mod = _iso_to_epoch(modified_iso)
    if not mod:
        return False
    meeting_epoch = datetime(meeting_day.year, meeting_day.month, meeting_day.day,
                             tzinfo=TIMEZONE).timestamp()
    return (meeting_epoch - mod) > 7 * 86400


def _content_date_mismatch(md_path: str, meeting_day: date) -> bool:
    try:
        with open(md_path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return False
    found = find_content_date(text)
    if not found:
        return False
    return abs((found - meeting_day).days) > 1


def _write_metadata(m_dir: str, m: dict, slug: str, d: date, artifacts: dict) -> None:
    meta = {
        "eventId": m["eventId"],
        "title": m["title"],
        "slug": slug,
        "date": d.strftime("%Y-%m-%d"),
        "startTime": m["startTime"],
        "endTime": m["endTime"],
        "durationMinutes": m["durationMinutes"],
        "organizer": m["organizer"],
        "attendees": m["attendees"],
        "conferenceId": m["conferenceId"],
        "meetLink": m["meetLink"],
        "artifacts": artifacts,
    }
    with open(os.path.join(m_dir, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


# -- index.md (Step 5) --------------------------------------------------------

def _hhmm(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(TIMEZONE).strftime("%H:%M")
    except Exception:
        return "--:--"


def _td(s: str) -> str:
    """Escape a value for a markdown table cell."""
    return str(s).replace("|", "\\|").replace("\n", " ")


def write_index(day_dir: str, d: date, rows: list[dict]) -> None:
    dow = d.strftime("%A")
    lines = [f"# {d.strftime('%Y-%m-%d')} ({dow}) — Meeting Index", ""]
    lines.append("| Time | Meeting | Attendees | Artifacts |")
    lines.append("|------|---------|-----------|-----------|")
    total_min = 0
    n_notes = n_rec = n_tr = 0
    for r in rows:
        m = r["meeting"]
        total_min += m["durationMinutes"]
        t = f"{_hhmm(m['startTime'])}–{_hhmm(m['endTime'])}"
        att_n = len(m["attendees"])
        att = f"{att_n} attendees" if att_n > 3 else ", ".join(
            a["name"] or a["email"].split("@")[0] for a in m["attendees"]) or "—"
        if r["produced"]:
            links = []
            for kind in ("notes", "agenda", "transcript", "recording"):
                if kind in r["produced"]:
                    links.append(f"[{kind}]({r['slug']}/{kind}.md)")
            if "attachment" in r["produced"]:
                links.append("attachment")
            arts = ", ".join(links)
            n_notes += 1 if "notes" in r["produced"] else 0
            n_rec += 1 if "recording" in r["produced"] else 0
            n_tr += 1 if "transcript" in r["produced"] else 0
        else:
            arts = "_no artifacts_"
        lines.append(f"| {t} | {_td(m['title'])} | {_td(att)} | {arts} |")
    h, mnt = divmod(total_min, 60)
    lines += ["", f"**Total:** {len(rows)} meetings, {h}h {mnt}m total meeting time",
              f"**Artifacts found:** {n_notes} notes, {n_rec} recordings, {n_tr} transcripts", ""]
    with open(os.path.join(day_dir, "index.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# -- registry -----------------------------------------------------------------

def load_registry() -> list[dict]:
    if os.path.isfile(REGISTRY_PATH):
        try:
            with open(REGISTRY_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_registry(reg: list[dict]) -> None:
    os.makedirs(OUTPUT_BASE, exist_ok=True)
    tmp = REGISTRY_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(reg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, REGISTRY_PATH)


def registry_entry(reg: list[dict], email: str) -> dict | None:
    return next((e for e in reg if e.get("email") == email), None)


# -- main ---------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Harvest Google Meet/Calendar notes to Markdown.")
    ap.add_argument("email", nargs="?", help="calendar/email to harvest (must be the authed gws user)")
    ap.add_argument("--since", help="harvest from this YYYY-MM-DD through yesterday")
    ap.add_argument("--day", help="harvest a single YYYY-MM-DD")
    ap.add_argument("--days", type=int, help="harvest the trailing N days through yesterday")
    ap.add_argument("--force", action="store_true",
                    help="(no-op; kept for compatibility) every run already re-exports each day")
    ap.add_argument("--list", action="store_true", help="print the registry and exit")
    args = ap.parse_args()

    reg = load_registry()

    if args.list:
        if not reg:
            print("No meetings harvested yet.")
        for e in reg:
            print(f"{e['email']}: last_harvested={e.get('last_harvested')} "
                  f"last_synced={e.get('last_synced')} stats={e.get('stats')}")
        return 0

    if not args.email:
        ap.error("email is required (or use --list)")

    today = datetime.now(TIMEZONE).date()
    entry = registry_entry(reg, args.email)
    last_harvested = entry.get("last_harvested") if entry else None
    days = resolve_range(args, last_harvested, today)

    if not days:
        print(f"Nothing to harvest for {args.email} (already current through {last_harvested}).")
        return 0

    print(f"Harvesting {args.email}: {days[0]} … {days[-1]} ({len(days)} day(s))")
    stats = {"days": 0, "meetings": 0, "notes": 0, "recordings": 0, "attachments": 0}
    try:
        for d in days:
            n = harvest_day(args.email, d, stats)
            stats["days"] += 1
            print(f"  {d}: {n} meeting folder(s)")
    except CalendarAccessError as e:
        lines = [l for l in str(e).splitlines() if l.strip()]
        detail = next((l for l in lines
                       if re.search(r"\b(403|404|forbidden|notFound|not found|message)\b", l, re.I)),
                      lines[-1] if lines else str(e))
        print(f"ERROR: cannot read calendar '{args.email}' — {detail.strip()[:200]}\n"
              f"This CLI only harvests the authenticated gws user's own calendar.",
              file=sys.stderr)
        return 1

    # Update registry. `last_harvested` tracks the latest COMPLETE day captured,
    # so today is excluded — the default run re-harvests today on every pass and
    # today is not "done" until it becomes yesterday. The value only ever moves
    # forward (a stale-then-default run keeps the older value if it's newer).
    now_iso = datetime.now(TIMEZONE).isoformat()
    prev_last = entry.get("last_harvested") if entry else None
    complete = [d for d in days if d < today]
    cand = max(complete).strftime("%Y-%m-%d") if complete else None
    recorded_last = max([x for x in (cand, prev_last) if x], default=None)
    if entry:
        if recorded_last:
            entry["last_harvested"] = recorded_last
        entry["last_synced"] = now_iso
        entry["stats"] = stats
    else:
        reg.append({"email": args.email, "last_harvested": recorded_last,
                    "last_synced": now_iso, "stats": stats})
    save_registry(reg)

    print(f"Done. {stats['meetings']} meetings, {stats['notes']} notes, "
          f"{stats['recordings']} recordings, {stats['attachments']} attachments "
          f"across {stats['days']} day(s). last_harvested={recorded_last}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
