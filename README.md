# PDF Binder

Turn a list of web articles (and PDFs) into one polished, navigable PDF binder — clean readability extraction, a real table of contents, page numbers, bookmarks, and clickable TOC links that actually land on the right page.

Born from a real workflow: compiling a 5-article reading pack and iterating through five versions to get formatting, images, and TOC links right. Every lesson from those iterations is baked into the pipeline and the 9-point pre-send checklist.

## Pipeline

```
sources (URLs / files)
  → readability extract (HTML)  ·  keep original (PDF)
  → render each via Playwright (headless Chromium)
  → merge in order, splicing PDFs at their exact positions
  → stamp page numbers + running headers
  → build cover + TOC with real page numbers
  → add bookmarks + clickable TOC links
  → binder.pdf
```

| Tool | Role |
|------|------|
| **Mozilla Readability** | Strips nav, banners, sharing icons, related-article promos |
| **Playwright** (headless Chromium) | Renders with full CSS — bold, headings, images, code blocks preserved |
| **ReportLab** | Stamps footer page numbers and running headers |
| **pypdf** | Merges, splices PDFs between articles, adds bookmarks + clickable TOC links |

## What you get

- **Cover page** with title, subtitle, and article count
- **Table of contents** with real page numbers and clickable rows
- **Running footers** — page numbers on every content page (cover/TOC excluded)
- **PDF bookmarks** — one outline entry per article, plus Contents
- **Clickable TOC links** placed from the rendered layout (measured, not estimated — they survive title wrapping)
- **Faithful Unicode** in headers when a Unicode font is available (accents, em-dashes, CJK)

## Quick start

```bash
pip install readability-lxml lxml_html_clean playwright reportlab pypdf
python -m playwright install chromium
```

Drive the whole pipeline from a JSON manifest:

```bash
python scripts/rebuild.py ARTICLES_DIR output.pdf < manifest.json
# or, if ARTICLES_DIR/manifest.json exists:
python scripts/rebuild.py ARTICLES_DIR output.pdf
```

`ARTICLES_DIR` holds your local source files; anything missing is downloaded from its `url`.

### Manifest format

A list of articles, or an object with optional `title` / `subtitle`:

```json
{
  "title": "A Curated Reading Pack",
  "subtitle": "Five essays on distributed systems",
  "articles": [
    {"file": "essay.html",  "title": "The First Essay", "author": "Ada Lovelace",  "url": "https://example.com/posts/first/", "type": "html"},
    {"file": "report.pdf",  "title": "Q3 Report",       "author": "Analytics",     "type": "pdf"}
  ]
}
```

- `type: "html"` entries are extracted with Readability and rendered.
- `type: "pdf"` entries are spliced in as-is (no text extraction).
- `file` is optional for HTML when `url` is given — it will be fetched.

See the [`rebuild.py`](scripts/rebuild.py) docstring for the full spec, and [SKILL.md](SKILL.md) for the step-by-step pipeline and the 9-point pre-send checklist.

## Latest update

**2026-06-30 — `rebuild.py` is now a complete, working pipeline.** It previously
shipped as a stub that stopped at the helper functions; it now runs end-to-end
from a JSON manifest and has been tested on a mixed binder (cover + TOC + HTML
articles + a spliced multi-page PDF). Highlights:

- **Full pipeline implemented** — resolve/download sources → Readability extract →
  Playwright render → merge + splice → stamp page numbers/headers → cover + TOC
  with real page numbers → bookmarks + clickable links.
- **Clickable TOC links are measured, not estimated** — link rectangles come from
  the rendered TOC layout, so they stay correct even when titles wrap.
- **Robust image-URL rewriting** — handles `srcset`, single-quoted `src`, and
  protocol-relative `//` URLs, resolved against the article URL.
- **`pypdf` with `PyPDF2` fallback**, and **Unicode headers** via an auto-registered
  TrueType font (graceful Latin-1 fallback when none is found).

## Files

| File | Purpose |
|------|---------|
| `SKILL.md` | Full pipeline doc + pre-send checklist (Hermes-compatible skill format) |
| `scripts/rebuild.py` | Standalone CLI — runs the full pipeline from a JSON manifest |
| `templates/article.html` | HTML template for rendering a single article |

## Future roadmap

The deterministic pipeline (extract → render → merge → stamp → TOC → links) needs
no LLM — it's pure Python and is more reliable run as a plain tool. An agent only
earns its place at two fuzzy edges, and the roadmap is about sharpening that split:

- **`--verify` mode** — move the mechanical pre-send checks (image links resolve,
  page numbers match starts, footers present, bookmark/link counts, file size)
  out of the prose checklist and into hard assertions the script runs itself. These
  don't need a model; they should fail loudly in CI, not rely on a human eyeballing.
- **`build-manifest` helper** — turn an unstructured request ("bind these five
  links") into a clean `manifest.json`: infer title/author/type, dedupe, and order
  the sources. This *is* the natural-language → structured-input step where an LLM
  genuinely helps.
- **Semantic QA (multimodal, optional)** — keep the model only for the judgment
  checks that resist automation: "did Readability strip the body to plain text?"
  and "are there leftover nav bars / Related-Articles banners?" — i.e. *does the
  rendered page look like a clean article?*

Net effect: the LLM's role shrinks to manifest-building and the handful of QA items
that truly need a brain; everything else becomes deterministic and testable.

## License

MIT
