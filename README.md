# PDF Binder

Build polished PDF binders from web articles — readability extraction, table of contents, page numbers, bookmarks, and clickable TOC links.

Born from a real workflow: compiling a 5-article reading pack, iterating through 5 versions to get formatting, images, and TOC links right. All the lessons from those iterations are baked into the pipeline and the 9-point pre-send checklist.

## What it does

```
Source URLs → readability extract (HTML) / keep original (PDF)
   → render via Playwright → splice → stamp page numbers
   → build cover + TOC → add bookmarks + clickable links → PDF
```

- **Mozilla Readability** strips nav, banners, sharing icons, related-article promos
- **Playwright** (headless Chromium) renders with full CSS — bold, headings, code blocks preserved
- **ReportLab** stamps page numbers on every footer
- **PyPDF2** merges, splices PDFs between articles, and adds PDF bookmarks + TOC clickable links

## Quick start

```bash
pip install readability-lxml playwright reportlab PyPDF2
python -m playwright install chromium
```

See [SKILL.md](SKILL.md) for the full pipeline, step-by-step instructions, and the 9-point pre-send checklist.

## Files

| File | Purpose |
|------|---------|
| `SKILL.md` | Full pipeline doc + checklist (Hermes-compatible skill format) |
| `templates/article.html` | HTML template for rendering a single article |
| `scripts/rebuild.py` | Standalone CLI script (WIP — see SKILL.md for full pipeline) |

## License

MIT
