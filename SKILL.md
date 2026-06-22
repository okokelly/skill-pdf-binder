---
name: pdf-binder
description: Build a formatted PDF binder from multiple web articles and/or PDFs — readability extraction, TOC with page numbers, footers, bookmarks, and clickable TOC links. Includes pre-send quality checklist.
version: 1.0.0
category: productivity
---

# PDF Binder Builder

Build a polished PDF binder from a list of source URLs (HTML articles or PDFs). Uses Mozilla's Readability to strip nav/banners/ads, Playwright for proper rendering, reportlab for page number stamping, and PyPDF2 for merging + annotations.

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

**Preferred approach: Native browser anchor links.** Render TOC + all HTML articles as ONE combined HTML. Use `<a href="#article-id">` in the TOC — Playwright's PDF output preserves these as native PDF internal links. This is truly "bound to text" — the browser engine calculates exact text bounding boxes, immune to zoom/reflow/layout shifts.

**For PDF sources inserted between HTML articles:** The insertion shifts page offsets, breaking native links for articles AFTER the insertion point. For these (typically only 2-3), use PyPDF2 Link annotations as fallback.

**Bookmarks:** `writer.add_outline_item(title, page_index, parent=None)`

**Fallback — PyPDF2 Link annotations for shifted entries:**

```python
annotation = DictionaryObject()
annotation[NameObject("/Subtype")] = NameObject("/Link")
annotation[NameObject("/Rect")] = rect
action = DictionaryObject()
action[NameObject("/S")] = NameObject("/GoTo")
action[NameObject("/D")] = ArrayObject([FloatObject(page_idx), NameObject("/XYZ"), ...])
annotation[NameObject("/A")] = action
toc_page["/Annots"].append(annotation)
```

Estimate TOC entry y-positions based on CSS margins + font sizes:
- TOC heading bottom: margin_top + 18 + 8 + 18 ≈ 101pt
- Each entry: ~34pt (11pt title + 9pt author + 14pt margin-bottom)

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
       Prefer native HTML anchors (render TOC+articles as one HTML).
       Only use annotation fallback for links broken by PDF insertions.

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
pip3 install readability-lxml playwright reportlab PyPDF2
python3 -m playwright install chromium
```

## Pitfalls

- **Image 404s:** `urljoin(base_url, img_src)` — use article URL as base, NOT domain root. A relative `src="image.png"` on `site.com/posts/article/` resolves differently than on `site.com/`.
- **Readability stripping too much:** Some sites (paywalled, Substack) may return minimal content. Fall back to browser-based extraction if readability output < 500 chars.
- **Playwright timeout on heavy pages:** Some pages have endless JS. Cap at 30s, use `wait_until="networkidle"`.
- **Page number drift:** If merging order changes, TOC page numbers must be recalculated. Always rebuild TOC after final merge.
- **PDF source positioning:** When inserting a PDF between HTML-rendered articles, render articles individually (not as one combined HTML) so insertion point is exact.
- **Reportlab Unicode:** Core PDF fonts only support Latin-1. Use `safe_text()` to replace Unicode chars before stamping — or the stamp itself will crash.
