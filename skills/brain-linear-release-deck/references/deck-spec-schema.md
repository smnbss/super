# `deck_spec.json` schema

The full JSON the model produces and `build_plenaria_deck.py` consumes.
Every field is optional; sensible defaults render an empty section
gracefully rather than crashing. Coordinates, fonts, colors, and the
WeRoad logo are fixed by the script — the spec is content only.

The renderer accepts both the new `tracks` key and the legacy `bets`
key (with matching legacy `four_bets_title` / `four_bets_footer`) for
transitional specs, but new specs should prefer the `tracks` vocabulary.

## Top level

| Field | Type | Notes |
|-------|------|-------|
| `window_label` | string | Human label ("May 2026", "Q1 2026"). Used for the cover source line and filenames. |
| `window_machine` | string | Machine slug ("2026-05") — same convention as the release-summary slug. |
| `source_url` | string | Defaults to the Linear MOL release-notes URL. Shown as small italic on the cover. |
| `cover_eyebrow` | string | Default `"PRODUCT REVIEW"`. Uppercased on render. Often extended with the window — e.g. `"PRODUCT REVIEW · MAY 2026"`. |
| `cover_title` | string | The editorial headline for *this window's* story. 2 lines max at 60pt. **Pick a fresh one each window** — see SKILL.md's "Picking the cover title". When omitted, the script falls back to `"<window_label> Review"` so you notice it's unset. |
| `cover_subtitle` | string | The track names separated by middots, e.g. `"AI · Conversion · Operations · Community"`. |
| `cover_source` | string | Default `"Source: Linear release notes"`. |
| `headline_count` | string | The H1 above the by-numbers cards. Window-specific punchline summarising the quantitative story. |
| `by_numbers` | array of `Number` | 1–4 stat cards. More than 4 are truncated. |
| `four_tracks_title` | string | Slide 3's H1. Default `"Four tracks, one direction"`. Rewrite per window. |
| `four_tracks_footer` | string | Small grey italic at slide-3 bottom. |
| `tracks` | array of `Track` | Up to 4 entries — fewer renders fewer columns and chapters. |
| `impact_spotlights` | array of `ImpactSpotlight` | Optional top-level spotlights rendered between slide 3 and the first chapter. Use this for window-wide hero stats that don't belong to a single track. Per-track spotlights go inside that track's `slides` array (with `"type": "impact_spotlight"`). |
| `looking_ahead_title` | string | Default `"Where each track sharpens next"`. |
| `looking_ahead` | array of `LookAheadCell` | Exactly 4 for the 2×2 grid. |
| `thank_you_title` | string | Default `"Thank you."`. |
| `thank_you_subtitle` | string | Default `"Questions, pushback, requests for deep dives — welcome."` |

## `Number`

```json
{"number": "69", "label": "releases shipped", "caption": "Jan–Apr 2026"}
```

Short numbers (≤3 chars) render at 64pt; longer strings auto-shrink to
keep them inside the card.

## `Track`

```json
{
  "key": "ai",
  "name": "AI",
  "claim": "Two AI surfaces went live across four markets.",
  "chapter_title": "AI takes the front line",
  "subtitle": "WhatsApp Assistant in 4 markets + Discord Salesbot.",
  "overview_bullets": ["WhatsApp Assistant in 4 markets", "Discord Salesbot"],
  "slides": [ /* ContentSlide or ImpactSpotlight entries */ ]
}
```

| Field | Notes |
|-------|-------|
| `key` | Short id, used internally only. |
| `name` | Header of the four-tracks column ("AI", "CONVERSION", ...). |
| `claim` | The one-sentence statement of *what this track did in this window* — shown on slide 3. Auto-shrinks for long sentences (10pt at >70 chars, 12pt at >50, 14pt otherwise). |
| `chapter_title` | Big white title on the red chapter divider. Defaults to `name` if missing. |
| `subtitle` | Subtitle line on the chapter divider. |
| `overview_bullets` | 2–5 short release names in the four-tracks column. |
| `slides` | Slides for this track. Each entry is either a `ContentSlide` (default) or an `ImpactSpotlight` (when `"type": "impact_spotlight"`). |

## `ContentSlide`

```json
{
  "eyebrow": "BUYNANA + PARTNER PORTAL",
  "title": "New Cost-Based Structure goes live",
  "mol_id": "MOL-432",
  "bullets": [
    {"lead": "Granular cost mapping", "body": "Tours model specific costs natively, not just sellable docs"}
  ],
  "visual": {"label": "Buynana costs UI"}
}
```

| Field | Notes |
|-------|-------|
| `type` | `"content"` (default — can be omitted). |
| `eyebrow` | Small red uppercase tag at top-left. |
| `title` | Bold black claim, max 2 lines at 32pt. |
| `mol_id` | Linear issue id (e.g. `"MOL-432"`). When set, `fetch_linear_images.py` downloads the issue's best attachment and `build_plenaria_deck.py` auto-uses it as the slide visual. **Animated GIFs win** when both are present. |
| `bullets` | 3–5 entries. Each is `{lead, body}` (red bold + black) or a plain string. |
| `visual.path` | Optional explicit override — wins over `mol_id`. |
| `visual.label` | Placeholder caption when no image is found. |

## `ImpactSpotlight`

A hero slide for a single significant measured win. Use when an impact
comment carries numbers strong enough to deserve the whole slide. Layout:
giant red KPI on the left, headline + context narrative on the right.

```json
{
  "type": "impact_spotlight",
  "kpi_number": "−91%",
  "kpi_label": "rejected documents",
  "kpi_period": "Feb–Apr vs Oct–Jan baseline",
  "headline": "Cost-Based Structure removes nearly all rejected documents.",
  "context": "Rework proxy fell 80%; finance reconciliation effort cut materially. Estimated €20–35k/yr saving.",
  "caveat": "Rejected costs are replaced, not reworked — delta measures noise reduction, not direct spend recovery.",
  "release_id": "MOL-432",
  "release_title": "New Cost-Based Structure",
  "author": "Mautino"
}
```

| Field | Notes |
|-------|-------|
| `type` | Must be `"impact_spotlight"` (when used inside a track's `slides`). |
| `kpi_number` | The giant red number. Use the format the impact comment uses (`-91%`, `+5.7pp`, `~€201K/yr`, `+€450K`). Auto-shrinks: 4 chars at 150pt → 8+ chars at 96pt. |
| `kpi_label` | Bold dark-grey line under the number. Keep ≤30 chars. |
| `kpi_period` | Italic grey line under the label, for the comparison window or sample size. Optional. |
| `headline` | Bold black takeaway sentence on the right. Auto-shrinks: ≤50 chars at 26pt, ≤90 chars at 22pt, longer at 18pt. |
| `context` | Black 12pt paragraph under the headline. The narrative — sample sizes, what improved, downstream effects. Keep to ~3 lines. |
| `caveat` | Italic grey line at the bottom-right. Important for measured impact: state the limit of the claim. Optional but encouraged. |
| `release_id`, `release_title`, `author` | Attribution along the bottom-right — e.g. `"New Cost-Based Structure  ·  MOL-432  ·  Mautino"`. All optional. |

When to use a spotlight:
- The impact comment has a hard KPI delta with sample size and pre/post
- The release answers a "what did this do?" question with a number
- Skipping the spotlight would force the win into a bullet on a content
  slide where the number's weight gets diluted

When *not* to use one:
- The impact comment is qualitative ("users seem happier") with no
  measured delta — render as a content slide with a quote instead.
- The win is a process metric with no numeric estimate — same treatment.

## `LookAheadCell`

```json
{"theme": "AI", "body": "More markets on WhatsApp; web widget for low-WA markets (US/UK)."}
```

Exactly 4 cells render correctly (2×2 grid). Themes are usually the four
track names; keep the body to one or two sentences.
