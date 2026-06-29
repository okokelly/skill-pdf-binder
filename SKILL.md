---
name: pdf-binder
description: Build a formatted PDF binder from multiple web articles and/or PDFs — readability extraction, TOC with page numbers, footers, bookmarks, and clickable TOC links. Includes pre-send quality checklist.
version: 1.1.0
category: productivity
---

# PDF Binder Builder

Build a polished PDF binder from a list of source URLs (HTML articles or PDFs). Uses Mozilla's Readability to strip nav/banners/ads, Playwright for proper rendering, reportlab for page number stamping, and pypdf (PyPDF2 fallback) for merging + annotations.

## Quick path

`scripts/rebuild.py` implements this entire pipeline. Drive it with a JSON manifest:

```bash
python3 scripts/rebuild.py ARTICLES_DIR output.pdf < manifest.json
```

The step-by-step below documents what the script does (and how to do it by hand).

## When to use

- "Build a PDF binder of these articles"
- "Combine these readings into one PDF"
- Any time you need to compile a curated reading pack from web sources

## Pipeline

```
Source URLs → download → readability extract (HTML) / keep original (PDF)
    → render each via Playwright → merge in order → stamp page numbers
    → build cover + TOC with real page numbers → re-merge
    → add PDF bookmarks + clickable TOC links → output
```

## Step-by-step

### 1. Download all sources

- HTML pages: `curl -sL -o <file>.html "<url>"`
- PDFs: `curl -sL -o <file>.pdf "<url>"`

### 2. Extract clean article content

For **HTML** sources — use readability-lxml (Mozilla's Readability):

```python
from readability import Document
from urllib.parse import urljoin

doc = Document(raw_html)
clean_html = doc.summary()

# CRITICAL: Fix relative image URLs using the ARTICLE URL as base (not domain root!)
# e.g. urljoin("https://site.com/posts/article/", "image.png") → correct
# NOT urljoin("https://site.com", "image.png") → 404
# fix_image_urls must also rewrite srcset, single-quoted src, and protocol-
# relative (//) URLs — not just double-quoted src="" attributes.
clean_html = fix_image_urls(clean_html, article_url)
```

For **PDF** sources — keep the original file, do NOT extract text.

### 3. Render each article via Playwright

Use the individual article HTML template (see `templates/article.html`). Key CSS:
- Font: Georgia 11pt, line-height 1.7
- Max-width 720px, centered
- Images: `max-width: 100%` to prevent overflow
- Pre/code blocks for technical content

```python
page.goto(f"file://{html_path}", wait_until="networkidle", timeout=30000)
page.wait_for_timeout(2000)  # let images load
page.pdf(path=pdf_path, format="A4", margin={...}, print_background=True)
```

### 4. First merge + calculate page offsets

Merge in correct order: Cover+TOC → articles in sequence (insert PDFs at their correct positions).

Count pages to determine where each article starts.

### 5. Stamp page numbers

Use reportlab to create overlay PDFs with:
- Centered page number at bottom (Helvetica 8pt, gray)
- Left-aligned "Title — Subtitle" header on non-cover pages (Helvetica 7pt, lighter gray)

```python
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
# Create overlay, merge with each page
```

### 6. Rebuild TOC with real page numbers

After knowing each article's start page, rebuild the cover+TOC HTML and re-render via Playwright.

TOC format:
```html
<ol>
  <li><strong>Article Title</strong> — <em>page N</em><br>
      <span class="author">Author Name</span></li>
</ol>
```

### 7. Add PDF bookmarks and clickable TOC links

**Bookmarks:** `writer.add_outline_item(title, page_index, parent=None)` — one per article, plus a "Contents" entry pointing at the TOC page. These are robust and the primary navigation.

**Clickable TOC links — measure rects, don't estimate them.** Rendering each article individually (so PDFs splice in at exact positions) means native `<a href="#…">` anchors can't span documents, so the TOC links are PDF `/Link` annotations. The reliable way to place them is to **measure the rendered TOC**: have Playwright return each entry's bounding box, then convert CSS px → PDF points.

```python
# After rendering the TOC, measure each row in the SAME pass:
rects = page.eval_on_selector_all(
    ".toc-link",
    "els => els.map(e => { const r = e.getBoundingClientRect();"
    " return {top:r.top, left:r.left, width:r.width, height:r.height}; })",
)
# Render with print media + an A4-width viewport so layout == the PDF.
# Convert: pt = px * 72/96; PDF y is from the page bottom.
```

This survives title wrapping and layout shifts — the older "estimate y from font sizes (~34pt/entry)" heuristic breaks the moment any title wraps to a second line. Avoid it.

Build the annotation with a `/Dest` pointing at the target page (no `/A` action needed):

```python
link = DictionaryObject()
link[NameObject("/Subtype")] = NameObject("/Link")
link[NameObject("/Rect")]    = RectangleObject([x0, y0, x1, y1])
link[NameObject("/Border")]  = ArrayObject([NumberObject(0)] * 3)  # no visible box
link[NameObject("/Dest")]    = ArrayObject([
    writer.pages[target_idx].indirect_reference,
    NameObject("/XYZ"), NumberObject(0), NumberObject(int(A4_H)), NumberObject(0),
])
toc_page[NameObject("/Annots")] = ArrayObject([link])  # or append if it exists
```

**Note:** if the TOC rows are `<a href="#">` elements, Playwright emits its own dead link annotations for them — use plain `<div>` rows so the only links are the measured ones you add.

## Pre-Send Quality Checklist

Before uploading and sending, run this loop:

```
□ 1. IMAGES: For each HTML article, verify ≥80% of <img> tags resolve to 200.
       curl -s -o /dev/null -w "%{http_code}" <each image URL>
       Common fix: urljoin base must be ARTICLE URL, not domain root.

□ 2. TOC: Cover page present? TOC on page 2? Page numbers match actual starts?
       Open PDF, verify: cover (p1) → TOC (p2) → articles at listed pages.

□ 3. PAGE NUMBERS: Every page has a footer page number?
       Check pages 1-2 (no numbers), pages 3+ (should have numbers).

□ 4. BOOKMARKS: PDF outline has one entry per article?
       Open in any PDF viewer sidebar → check outline panel.

□ 5. TOC LINKS: Click each TOC entry → jumps to correct article start page?
       Links are /Link annotations placed from measured TOC rects.
       Verify count == #articles (no stray dead links from <a href="#"> rows).

□ 6. CLEAN CONTENT: No nav bars, sharing icons, "Related Articles" banners?
       Readability should handle this. Spot-check first and last page of each article.

□ 7. ORDERING: Articles in correct sequence? PDF sources inserted at right position?
       Verify against the user's requested order.

□ 8. FORMATTING: Bold, headings, links preserved (not stripped to plain text)?
       Core sign: headings render in Helvetica Bold, body in Georgia.

□ 9. SIZE: File size reasonable? If >20MB, consider compressing images.
```

**If any check fails → fix before sending. Do not ship a binder that fails any check.**

## Dependencies

```bash
pip3 install readability-lxml lxml_html_clean playwright reportlab pypdf
python3 -m playwright install chromium
```

(`pypdf` is the maintained successor to `PyPDF2`; the script accepts either.)

## Pitfalls

- **Image 404s:** `urljoin(base_url, img_src)` — use article URL as base, NOT domain root. A relative `src="image.png"` on `site.com/posts/article/` resolves differently than on `site.com/`. Rewrite `srcset` and single-quoted `src` too, or responsive images silently 404.
- **Readability stripping too much:** Some sites (paywalled, Substack) may return minimal content. Fall back to browser-based extraction if readability output < 500 chars.
- **Playwright timeout on heavy pages:** Some pages have endless JS. Cap at 30s, use `wait_until="networkidle"`.
- **Page number drift:** If merging order changes, TOC page numbers must be recalculated. Always rebuild TOC after final merge.
- **PDF source positioning:** When inserting a PDF between HTML-rendered articles, render articles individually (not as one combined HTML) so insertion point is exact.
- **Reportlab Unicode:** Core PDF fonts (Helvetica) only support Latin-1, so a non-Latin header (CJK, Greek, math) becomes `???`. Proper fix: register a TrueType Unicode font — `pdfmetrics.registerFont(TTFont("Uni", "<path>/DejaVuSans.ttf"))` — and stamp with it. Keep `safe_text()` only as the fallback for when no such font is found.
