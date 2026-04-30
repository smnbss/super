---
name: brain-linear-release-deck
description: >
  Build a WeRoad "Plenaria Tech" PPTX from Linear release notes for a given
  time window. Pulls release issues + comments from Linear directly, reads
  every release and impact update in scope, synthesizes the window's actual
  story into a branded deck ready for the monthly all-hands. Use whenever
  the user says "build the plenaria deck", "release deck for
  <month/quarter>", "tech all-hands deck", "monthly tech review slides", or
  asks for slides about what shipped — even if they don't say "use the
  skill". Self-contained: pulls from Linear via GraphQL, fetches Linear
  attachments (preferring animated GIFs), renders with python-pptx, uploads
  to Drive via gws. Does **not** depend on brain-linear-release-summary.
---

# WeRoad — Linear Release Deck

Standalone pipeline that turns the Linear MOL "Release Notes" project into
the monthly Plenaria Tech deck. Reference output: **2026 05 - Plenaria -
May 2026 - Tech** (Drive ID `1KIfGGs11BBS-Q8QHpSTh_bH9b3vuX8RWhUDvgahoteg`).

The deck has a stable visual structure (cover → by-numbers → four-tracks
overview → per-track chapter+slides → looking-ahead → thank-you) and a
fully window-specific editorial layer. **The script handles structure;
the model writes editorial.** Slides 1–3, every chapter divider, every
track's claim/subtitle, and the looking-ahead grid are rewritten each
window from a full read of the release notes and impact updates in
scope — not template-filled from the previous month.

The four "tracks" (AI · Conversion · Operations · Community) act as
recurring magazine sections, not strategic bets. The audience recognises
the format month-to-month; the content under each section is fresh.

## Inputs

The user provides a **time window**:

| Input | Window | Slug |
|-------|--------|------|
| `2026-05`, `May 2026` | a single month | `2026-05` |
| `Q1 2026`, `2026-Q1` | quarter | `2026-q1` |
| `last 30 days` | rolling | `<YYYY-MM-DD>-last-30-days` |
| `last 4 months` | rolling | `<YYYY-MM-DD>-last-4-months` |
| `2026-01..2026-04` | inclusive month range | `2026-01-2026-04` |
| `2026` | full year | `2026` |

Default if missing: **the most recent full month** (e.g. on 2026-05-04 →
`2026-04`). Confirm the chosen window in one line before starting.

No other inputs required. The pull script handles slug computation; the
rest of the pipeline reuses it.

## Output paths

Everything lives under `outputs/releases-decks/` keyed by `<slug>`:

| What | Where |
|------|-------|
| Raw Linear pull (cache) | `<slug>-raw.json` |
| Extended narrative | `<slug>-narrative.json` |
| Deck spec (JSON) | `<slug>-deck-spec.json` |
| Slide image assets | `<slug>-assets/<MOL-id>.{gif,png,…}` |
| Rendered deck (PPTX) | `<slug>-plenaria-deck.pptx` |
| PDF for verification | `<slug>-plenaria-deck.pdf` |

A neighbouring skill, `brain-linear-release-summary`, writes a different
file under `outputs/releases/<slug>-impact-summary.md`. That skill is
**not** a dependency of this one.

## Workflow

### 1. Pull the extended narrative from Linear

```bash
set -a; source .env.local; set +a   # gives us LINEAR_TOKEN
python skills/brain-linear-release-deck/scripts/pull_release_narrative.py \
  --window "<window>"
```

Produces:
- `<slug>-raw.json` — every issue + every comment for the project (cached;
  re-runs are free).
- `<slug>-narrative.json` — per-release records with full description,
  every comment (each flagged `is_impact`), inline image refs,
  word-boundary heuristic track classification, slide-worthiness flag.
  Plus aggregates: counts, impact list, tally by track and platform.

### 2. Read the whole narrative before writing the spec

This is the editorial step Simone keeps emphasising: **the deck must
reflect what shipped this window, not last month's template.**

Before opening a deck-spec editor, read `<slug>-narrative.json` end-to-end:

- Skim every release title to understand what shipped (don't just look at
  counts).
- Read every `is_impact: true` comment in full — these are the measured
  wins and they drive the by-numbers slide, the impact spotlights, and
  the chapter framings.
- Eyeball the `description` of slide-worthy releases to find quotable
  phrasing for content slides.
- Note which releases have `has_gif_in_description: true` — those are
  free visuals.
- Group releases mentally before formalising — do the heuristic track
  buckets in `narrative.by_bet`/`narrative.by_track` actually fit, or
  should you re-bucket some?

If you skip this read, slides 1–3 and the chapter dividers will copy
last month's framing and feel hollow. Do the read.

### 3. Synthesize the deck spec

Write `<slug>-deck-spec.json` (schema in `references/deck-spec-schema.md`).
The synthesis discipline is the heart of this skill — see the next major
section.

### 4. Pull images from Linear

```bash
python skills/brain-linear-release-deck/scripts/fetch_linear_images.py \
  --spec outputs/releases-decks/<slug>-deck-spec.json \
  --assets-dir outputs/releases-decks/<slug>-assets
```

Walks the spec, downloads the best attachment for each `mol_id`. **Prefers
the animated GIF when an issue has both** — Linear comments commonly include
both a static screenshot and an ezgif/Loom-export GIF; the GIF wins because
motion shows the change and Google Slides preserves the animation on upload.

### 5. Build the deck

```bash
python skills/brain-linear-release-deck/scripts/build_plenaria_deck.py \
  --spec outputs/releases-decks/<slug>-deck-spec.json \
  --assets-dir outputs/releases-decks/<slug>-assets \
  --output outputs/releases-decks/<slug>-plenaria-deck.pptx
```

The script hardcodes coordinates, fonts, the brand palette, and the
WeRoad logo. The model never writes python-pptx code.

Image resolution per content slide:
1. explicit `visual.path` — wins if set
2. `<assets-dir>/<mol_id>.gif` — preferred when a GIF exists
3. `<assets-dir>/<mol_id>.png` (or .jpg, .webp) — fallback
4. labeled placeholder rectangle — when nothing is found

### 6. (Optional) Upload to Google Drive

```bash
python skills/brain-linear-release-deck/scripts/upload_to_drive.py \
  --pptx outputs/releases-decks/<slug>-plenaria-deck.pptx \
  --name "<window human label> Tech Plenaria (auto-draft)"
```

Reads `RELEASES_DECKS_FOLDER` from `.env.local` (URL or bare folder id
both accepted), uploads to that folder converting to native Google Slides.
Idempotent: if a Slides file with the same `--name` already exists in the
folder, the script *updates it in place* (preserving file id and URL).

---

## Synthesis discipline — what to actually write

The spec is content; everything below is about content choices.

### What stays stable, what's rewritten every window

**Stable across windows — the masthead** (don't fight these):
- The four track *names* (`AI`, `Conversion`, `Operations`, `Community`)
  and their order. Magazine sections.
- The cover subtitle (`AI · Conversion · Operations · Community`).
- The slide *types* (cover → by-numbers → four-tracks → chapter+content
  per track → looking-ahead → thank-you) and their visual treatment.

**Rewritten every window — the editorial layer:**
- `cover_title` — the headline phrase for *this* window.
- `headline_count` (slide 2's H1) — the punchline for the by-numbers page.
- `four_tracks_title` (slide 3's H1) — re-frames the four-track overview.
- Per track: `claim`, `chapter_title`, `subtitle`.
- Content slides — per-release framing, with bullets pulled from the
  description and impact comments.
- `impact_spotlights` — heroes for measured wins big enough to deserve a
  whole slide.
- `looking_ahead` — what each track sharpens next.

If two consecutive windows share editorial copy, you copied instead of
synthesising. Re-read the narrative.

### Slide 1 — the cover title

The cover title is the editorial headline for *this window's* story. Not a
recurring brand line. Pick a phrase that captures the takeaway when you read
the impact comments + theme of what shipped.

| Window's reality | Cover title that fits |
|------------------|----------------------|
| Big tracks shipped, all live | "All four tracks live" |
| Foundation work, long-running re-platforms | "Laying the runway" |
| Mostly compounding small wins | "Compounding starts here" |
| Cost / ops re-platform dominated | "Re-platforming the engine" |
| AI rollout was the headline | "AI on the front line" |
| Cumulative review across multiple months | "The four months in flight" |
| Quiet month, polishing existing surfaces | "Sharpening what's live" |

When omitted from the spec, the script falls back to `<window_label>
Review` — a visual nudge that you forgot to write one.

### Slide 2 — the by-numbers headline + cards

`headline_count` (H1 above the four cards) is the *single sentence* that
summarises the window's quantitative story. The four cards are evidence
underneath.

| Window's reality | `headline_count` |
|------------------|-----------------|
| Big release count + measured wins | `"69 releases. €236K preserved."` |
| Velocity-dominated month | `"23 ships in 30 days."` |
| Re-platform window | `"One cost engine. Sixty downstream wins."` |
| Cumulative review | `"Four months. 69 ships. Every track compounds."` |
| Standard pattern | `"69 releases. Four tracks."` |

Pick four cards that *together* tell the window's story. Strong picks:
- A velocity number (releases shipped, lifetime or in window).
- A footprint number (markets, languages, channels live).
- A versions number (e.g. `WeMeet v2.8 → v5.10` reads as compounding).
- An outcome number from impact comments (annual NBV, contribution
  margin lift, conversion lift, fill-rate change).

Pull outcome numbers from `narrative.releases[].impact_comments[]`. Avoid
unmeasured claims on this slide; it's the credibility anchor of the deck.

### Slide 3 — the four-tracks overview

`four_tracks_title` names *the relationship* between the four tracks in
this window — not a static label.

| Window's reality | `four_tracks_title` |
|------------------|--------------------|
| All four advanced together | `"Four tracks, one direction"` |
| One track was clearly the engine | `"Four tracks, AI in the lead"` |
| Cumulative cross-quarter view | `"Four tracks, four months of progress"` |
| Foundation laid for all four | `"Four tracks, all in flight"` |

Each track in the spec needs **its own window-specific** `claim`,
`chapter_title`, and `subtitle`. The same track has different copy in
different windows:

| Window | Track AI `claim` | `chapter_title` | `subtitle` |
|--------|------------------|-----------------|-----------|
| May 2026 (rollout complete) | "Put AI on the front line of sales and support." | "AI on the front line" | "Built in-house. Live in 4 markets. First-touch on every channel." |
| Jan–Apr 2026 (rollout in motion) | "Two AI surfaces went live across four markets." | "AI takes the front line" | "WhatsApp Assistant in 4 markets + Discord Salesbot — first-touch where customers and Sales already are." |

The `claim` shifts from a perpetual mission statement (when the track is
fully landed) to a what-actually-shipped sentence (when the window is
cumulative or mid-flight). Both are valid; pick what fits the window.

### Chapter dividers — one per track

Same per-window discipline applies. The `chapter_title` opens the track
in 2–4 words at 64pt; the `subtitle` is one sentence underneath. Both
should reflect the window's actual reality, not the track's perpetual
purpose. Use the strongest measured number when you have one — the
chapter divider is where the narrative arc starts.

### Content slides — mapping releases to slides

Allocate slides per track based on what shipped, not equally. The
reference May 2026 deck:
- AI: 2 slides (assistant rollout + Discord bot)
- Conversion: 5 slides (deposit, compare, search, notify-me, CWV)
- Operations: 4 slides
- Community: 3 slides

If you're tempted to give one track 7 slides and another 1, that's a
sign the synthesis collapsed and you're listing.

For each content slide:
- Set `mol_id` to the Linear issue id so the image fetcher pulls the
  right attachment.
- `eyebrow` = the platform/area tag (e.g. `"WEBSITE"`,
  `"BUYNANA + PARTNER PORTAL"`).
- `title` = a *claim*, not a label. Examples:
  - Bad: "Search updates" → Good: `"Search 2.0 — cities, regions, smarter \"where\""`
  - Bad: "Cost structure" → Good: `"New Cost-Based Structure goes live"`
- `bullets` = 3–5 entries with red-bold lead-ins. **Bodies should be one
  line at 12pt** — roughly 8–14 words, ~70 chars. If a bullet wraps to
  3+ lines the slide reads like prose; tighten or split. Lead-ins do
  the scanning work; bodies have the substance. Examples (good — one
  line each):
  - `{"lead": "Checkout", "body": "Live on .com and .de via card / PayPal / Revolut"}`
  - `{"lead": "Why it matters", "body": "Earlier bookings → tours confirm sooner → higher fill"}`
- **Surface measured numbers in the body when present.** A bullet that
  reads "+150% Notify-me, +17% Wishlist" is far more useful than
  "Improved discoverability metrics". Pull deltas from the impact
  comment for the release if there is one.
- Pull bullets from the release description and from any non-impact
  comments — the description has the official framing; comments often
  have the punchier line.

### Impact spotlights — measured wins that deserve a whole slide

When an impact comment carries a hard KPI delta with sample size, render
it as an `impact_spotlight` (a hero slide with a giant red KPI on the
left and the narrative on the right) rather than burying it in a content
bullet. See `references/deck-spec-schema.md#impactspotlight` for fields.

Insertion strategy:
- **Top-level spotlights** (`spec.impact_spotlights`) sit between the
  four-tracks overview and the first chapter. Use these for window-wide
  hero stats — typically 0–2 per deck. They set the tone before the
  track-by-track walk-through.
- **Per-track spotlights** sit inside `track.slides` with
  `"type": "impact_spotlight"`. Use these when the win belongs to a
  specific track and reads better right after that chapter divider.

Significance bar — a measured win warrants a spotlight when:
- The KPI delta is concrete (`-91%`, `+5.7pp`, `~€201K/yr`, not "users
  seem happier")
- A pre/post sample is named (or implied via period like
  `"Feb–Apr vs Oct–Jan"`)
- The number changes a decision (annual NBV impact, conversion lift,
  fill-rate change), not just an internal process metric

Significance is not about the size of the number alone — `−91%` in a
small-population metric and `+€201K/yr` in a large-population metric both
qualify. What disqualifies: vague "we saw improvement" comments without
deltas, or directional claims with no baseline.

**Bias toward more spotlights, not fewer.** If the window has 3 measured
wins that pass the significance bar, the deck should have 3 spotlights —
don't pick "the biggest one" and bury the others in bullets. Plenaria
audiences read measured wins as proof the team is shipping outcomes, not
just features; under-representing them undersells the work. A 20-slide
deck with 3 spotlights is not "spotlight-heavy" — it's correctly
weighted.

Watch for impact data that *isn't* in a formal "📊 Output misurati" or
"## Impact update" comment but appears inline in the release description
(e.g. "A/B brought +150% Notify-me, +17% Wishlist"). These count as
measured wins too — promote them to spotlights when the delta is
significant.

When extracting, **quote the comment, don't paraphrase**. The author
wrote the impact analysis with the full context; the spotlight should
keep their numbers, their caveat, and their author attribution. Specs
should set:
- `kpi_number` — the headline delta as written
- `kpi_label` — what the delta is *of*
- `kpi_period` — when, optionally with sample size
- `headline` — the takeaway in one sentence
- `context` — pull 2–3 lines from the impact comment verbatim
- `caveat` — every impact comment has a caveat; surface it (it's also
  what makes Simone trust the slide)
- `release_id` + `release_title` + `author` — attribution

A deck without an impact spotlight is fine when the window had no
measured wins, but a deck *with* measured wins that buries them in
bullets is undersells the team.

### No looking-ahead / asks slides

The Plenaria deck reports what *shipped* — that's the whole job. Don't
add a "Looking ahead" / "Where each track sharpens next" / "What we ask
of you next quarter" / "Next steps" slide at the end. Those formats
belong to roadmap proposals and exec asks — different decks for
different meetings. The renderer no longer emits one even if the spec
includes `looking_ahead` data; the deck ends on the "Thank you." slide
right after the last track's content.

---

## Visual template (short)

| Slide | Background | Used for |
|-------|------------|----------|
| **cover** | black | first slide — eyebrow + huge claim + subtitle + source line |
| **by_numbers** | white | 4 stat cards (rounded grey-bordered rectangles) |
| **four_tracks** | white | 4 column cards summarizing each track |
| **chapter** | red `#FF4758` | "TRACK N OF M · NAME" + chapter title + subtitle |
| **content** | white | eyebrow + claim title + 4–5 bullets left + visual right |
| **impact_spotlight** | white | giant red KPI left + headline + narrative + caveat right |
| **thank_you** | black | red line + "Thank you." + subtitle |

Logo bottom-left auto-placed (red+grey on white, white on red/black).
For coordinate-level details and brand palette, see the
`weroad-presentations` skill — the renderer uses those exact values.

## Why these design choices

- **Tracks are stable, releases are not** — collapsing 60+ releases into
  four narrative tracks is what makes the deck Plenaria-ready instead of
  an engineering changelog. The four-track frame matches how the Tech
  org tells its story; resist adding a fifth unless the strategy itself
  shifts. Resist also calling them "bets" — they're sections, and the
  word "bet" carries a speculative-strategy connotation that doesn't fit
  what the slides actually show (work that landed).

- **Editorial per window, structure forever** — the script knows how to
  draw a chapter divider; only the model knows what *this month's*
  chapter is about. Every slide that carries copy (cover, by-numbers,
  four-tracks, chapter dividers, content, looking-ahead) gets rewritten
  from the narrative each window. The first signal that synthesis is
  weak is editorial copy that could fit any month.

- **Impact spotlights over inline bullets** — a measured win buried in a
  bullet on a content slide reads as a footnote. A measured win that
  earns a hero slide is what Plenaria audiences remember and what
  validates the team's work. The renderer makes spotlights cheap; use
  them when the comment justifies it.

- **Bundled script over inline python-pptx** — the visual template has
  ~100 coordinate decisions. Re-deriving them every run wastes model
  time and produces visual drift between months. Hardcoding once gives a
  consistent monthly artifact.

- **Own the data layer end-to-end** — the deck synthesis benefits from
  more granular per-release context than `brain-linear-release-summary`
  exposes (full description, every comment, image refs). Pulling from
  Linear directly keeps the deck independent of the summary skill's
  output format and lets us mine richer angles. The raw pull is cached,
  so repeated runs are cheap.

- **GIFs win when present** — Linear comments commonly include both a
  screenshot and an ezgif-converted GIF showing the actual interaction.
  Motion communicates the change ten times better than a still, and
  Google Slides keeps the animation on upload.

- **Drive upload is opt-in but idempotent** — Plenaria is presented from
  Slides, but the draft cycle happens in PowerPoint locally. The upload
  helper updates an existing Slides file in place when the name matches,
  so links shared with colleagues still work after re-renders.
