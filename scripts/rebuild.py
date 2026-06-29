#!/usr/bin/env python3
"""Standalone binder rebuild script.

Usage:
    python3 rebuild.py ARTICLES_DIR OUTPUT_PATH < manifest.json
    python3 rebuild.py ARTICLES_DIR OUTPUT_PATH          # reads ARTICLES_DIR/manifest.json

Runs the full pipeline described in SKILL.md:
    resolve sources -> readability extract (HTML) / keep original (PDF)
    -> render each via Playwright -> merge in order -> stamp page numbers + headers
    -> build cover + TOC with real page numbers -> add bookmarks + clickable TOC links

Manifest format (JSON). Either a bare list of articles, or an object with metadata:

    {
      "title": "My Reading Pack",          # optional, shown on cover
      "subtitle": "Five essays on X",       # optional
      "articles": [
        {"file": "a1.html", "title": "...", "author": "...", "url": "https://...", "type": "html"},
        {"file": "report.pdf", "title": "...", "author": "...", "type": "pdf"}
      ]
    }

For HTML entries, `file` is optional if `url` is given (it will be downloaded).
For PDF entries, the file is used as-is (no text extraction).
"""
import os
import sys
import re
import json
import tempfile
from datetime import date
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from readability import Document
from playwright.sync_api import sync_playwright
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# pypdf is the maintained successor of PyPDF2; accept either.
try:
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import (
        RectangleObject, NameObject, ArrayObject, DictionaryObject, NumberObject,
    )
except ImportError:  # fall back to legacy PyPDF2
    from PyPDF2 import PdfReader, PdfWriter
    from PyPDF2.generic import (
        RectangleObject, NameObject, ArrayObject, DictionaryObject, NumberObject,
    )

A4_W, A4_H = A4                # 595.28 x 841.89 pts
PT_PER_PX = 72.0 / 96.0        # CSS px (96dpi) -> PDF point (72dpi)
A4_PX_W, A4_PX_H = 794, 1123   # A4 in CSS px, used as the print viewport
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
UA = "Mozilla/5.0 (compatible; pdf-binder/1.0)"


# ── helpers ──────────────────────────────────────────────────────────────────
def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def safe_text(text):
    """Transliterate to Latin-1 for the Helvetica core-font fallback only.

    When a Unicode TrueType font is registered (see register_unicode_font) the
    stamping path uses the raw text instead, so this lossy map is never hit.
    """
    replacements = {
        '—': '--', '–': '-', '‘': "'", '’': "'",
        '“': '"', '”': '"', '…': '...', ' ': ' ',
        '•': '*', '·': '-', '™': '(TM)', '®': '(R)',
        '≤': '<=', '≥': '>=', '×': 'x',
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return ''.join(ch if ord(ch) < 256 else '?' for ch in text)


def register_unicode_font():
    """Register a Unicode TTF for footer/header stamping if one is available.

    Returns the font name to use, plus whether it supports full Unicode.
    """
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont("BinderUni", path))
                return "BinderUni", True
            except Exception:
                continue
    return "Helvetica", False


def fix_image_urls(html, base_url):
    """Rewrite relative image URLs to absolute, using the ARTICLE url as base.

    Handles src="", src='', and srcset (responsive images).
    """
    def absolutise(u):
        u = u.strip()
        if u.startswith(("http://", "https://", "data:", "//")) or not u:
            return u
        return urljoin(base_url, u)

    def repl_src(m):
        q = m.group(1)
        return f'src={q}{absolutise(m.group(2))}{q}'

    def repl_srcset(m):
        q = m.group(1)
        out = []
        for cand in m.group(2).split(","):
            seg = cand.strip().split()
            if not seg:
                continue
            seg[0] = absolutise(seg[0])
            out.append(" ".join(seg))
        return f'srcset={q}{", ".join(out)}{q}'

    html = re.sub(r'src=(["\'])(.*?)\1', repl_src, html)
    html = re.sub(r'srcset=(["\'])(.*?)\1', repl_srcset, html)
    return html


def fetch(url, binary=False):
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=30) as r:
        data = r.read()
    return data if binary else data.decode("utf-8", "ignore")


# ── HTML generation ────────────────────────────────────────────────────────────
def load_article_template():
    path = os.path.join(SCRIPT_DIR, "..", "templates", "article.html")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read()
    # Minimal inline fallback mirroring templates/article.html.
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><style>'
        "body{font-family:Georgia,serif;font-size:11pt;line-height:1.7;color:#1a1a1a;"
        "max-width:720px;margin:0 auto;padding:1.5cm 1.5cm 2.5cm 1.5cm}"
        "h2{font-family:Helvetica,Arial,sans-serif;font-size:20pt;margin-bottom:6pt}"
        ".meta{font-family:Helvetica,Arial,sans-serif;font-size:9pt;color:#777}"
        "img{max-width:100%;height:auto}hr{border:none;border-top:1px solid #ddd;margin:14pt 0}"
        "</style></head><body><h2>ARTICLE_TITLE</h2>"
        '<p class="meta"><strong>AUTHOR</strong></p>'
        '<p class="meta"><a href="ARTICLE_URL">ARTICLE_URL</a></p><hr>'
        "<!-- CLEAN_HTML from readability goes here --></body></html>"
    )


def build_article_html(template, title, author, url, clean_html):
    html = template.replace("ARTICLE_TITLE", esc(title))
    html = html.replace("AUTHOR", esc(author or ""))
    html = html.replace("ARTICLE_URL", esc(url or ""))
    marker = "<!-- CLEAN_HTML from readability goes here -->"
    if marker in html:
        html = html.replace(marker, clean_html)
    else:
        html = html.replace("</body>", clean_html + "</body>")
    return html


def build_cover_html(title, subtitle, count):
    return (
        '<!DOCTYPE html><html><head><meta charset="UTF-8"><style>'
        "html,body{margin:0;padding:0}"
        "body{font-family:Georgia,serif;height:1123px;display:flex;flex-direction:column;"
        "justify-content:center;align-items:center;text-align:center;color:#1a1a1a}"
        "h1{font-family:Helvetica,Arial,sans-serif;font-size:34pt;margin:0 0 12pt;max-width:600px}"
        ".sub{font-size:15pt;color:#555;max-width:560px;margin-bottom:40pt}"
        ".meta{font-family:Helvetica,Arial,sans-serif;font-size:11pt;color:#999;"
        "letter-spacing:1px;text-transform:uppercase}"
        "</style></head><body>"
        f"<h1>{esc(title)}</h1>"
        + (f'<div class="sub">{esc(subtitle)}</div>' if subtitle else "")
        + f'<div class="meta">{count} articles &middot; {date.today().isoformat()}</div>'
        "</body></html>"
    )


def build_toc_html(entries):
    """entries: list of {title, author, page}. page may be a placeholder string."""
    rows = []
    for e in entries:
        author = e.get("author") or ""
        # A div (not <a href="#">) so Playwright does not emit dead link
        # annotations; clickable links are added later as precise PDF annotations.
        rows.append(
            '<div class="toc-link">'
            f'<span class="t">{esc(e["title"])}</span>'
            f'<span class="pg">{esc(e["page"])}</span>'
            + (f'<div class="au">{esc(author)}</div>' if author else "")
            + "</div>"
        )
    return (
        '<!DOCTYPE html><html><head><meta charset="UTF-8"><style>'
        "html,body{margin:0;padding:0}"
        "body{font-family:Georgia,serif;color:#1a1a1a}"
        ".wrap{padding:2.4cm 2cm}"
        "h1{font-family:Helvetica,Arial,sans-serif;font-size:24pt;margin:0 0 22pt}"
        ".toc-link{display:block;color:#1a1a1a;"
        "padding:7pt 0;border-bottom:1px solid #eee;position:relative}"
        ".toc-link .t{font-size:12pt;font-weight:bold;padding-right:40pt}"
        ".toc-link .pg{position:absolute;right:0;top:7pt;font-family:Helvetica,Arial,sans-serif;"
        "font-size:11pt;color:#777}"
        ".toc-link .au{font-family:Helvetica,Arial,sans-serif;font-size:9pt;color:#999;margin-top:2pt}"
        "</style></head><body><div class=\"wrap\">"
        "<h1>Contents</h1>"
        + "\n".join(rows)
        + "</div></body></html>"
    )


# ── Playwright rendering ────────────────────────────────────────────────────────
def render_pdf(browser, html, out_path, margins, measure=None, print_media=False, viewport=None):
    """Render HTML to a PDF file. Optionally return bounding rects for a selector.

    Rects are returned in CSS px relative to the document top (scroll 0), which
    maps to the printed page when print media + an A4-width viewport are used.
    """
    ctx = browser.new_context(viewport=viewport) if viewport else browser.new_context()
    page = ctx.new_page()
    if print_media:
        page.emulate_media(media="print")
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html)
        tmp = f.name
    try:
        page.goto(f"file://{tmp}", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1500)  # let lazy images settle
        rects = None
        if measure:
            rects = page.eval_on_selector_all(
                measure,
                "els => els.map(e => { const r = e.getBoundingClientRect();"
                " return {top: r.top, left: r.left, width: r.width, height: r.height}; })",
            )
        page.pdf(path=out_path, format="A4", margin=margins, print_background=True)
        return rects
    finally:
        ctx.close()
        os.unlink(tmp)


def page_count(pdf_path):
    return len(PdfReader(pdf_path).pages)


# ── stamping ───────────────────────────────────────────────────────────────────
def make_overlay(page_number, header_text, font_name, unicode_ok):
    """Return a single-page A4 overlay (pypdf page) with footer number + header."""
    buf = tempfile.SpooledTemporaryFile()
    c = canvas.Canvas(buf, pagesize=A4)

    def emit(text):
        return text if unicode_ok else safe_text(text)

    if header_text:
        c.setFont(font_name, 7)
        c.setFillGray(0.6)
        head = emit(header_text)
        if len(head) > 95:
            head = head[:92] + "..."
        c.drawString(42.5, A4_H - 22, head)  # 1.5cm left margin

    c.setFont(font_name, 8)
    c.setFillGray(0.5)
    c.drawCentredString(A4_W / 2, 24, str(page_number))
    c.save()
    buf.seek(0)
    return PdfReader(buf).pages[0]


# ── annotations ────────────────────────────────────────────────────────────────
def add_link(writer, toc_page_index, rect, target_index):
    """Add a clickable /Link annotation on a TOC page jumping to target_index."""
    x0, y0, x1, y1 = rect
    link = DictionaryObject()
    link[NameObject("/Type")] = NameObject("/Annot")
    link[NameObject("/Subtype")] = NameObject("/Link")
    link[NameObject("/Rect")] = RectangleObject([x0, y0, x1, y1])
    link[NameObject("/Border")] = ArrayObject(
        [NumberObject(0), NumberObject(0), NumberObject(0)]
    )
    target = writer.pages[target_index]
    link[NameObject("/Dest")] = ArrayObject(
        [target.indirect_reference, NameObject("/XYZ"),
         NumberObject(0), NumberObject(int(A4_H)), NumberObject(0)]
    )
    page = writer.pages[toc_page_index]
    if "/Annots" in page:
        page[NameObject("/Annots")].append(link)
    else:
        page[NameObject("/Annots")] = ArrayObject([link])


def rect_to_pdf(r):
    """CSS-px rect (from document top) -> (toc_page_k, [x0,y0,x1,y1]) in PDF pts."""
    top_pt = r["top"] * PT_PER_PX
    left_pt = r["left"] * PT_PER_PX
    w_pt = r["width"] * PT_PER_PX
    h_pt = r["height"] * PT_PER_PX
    k = int(top_pt // A4_H)                     # which TOC page this row lands on
    top_in_page = top_pt - k * A4_H
    y1 = A4_H - top_in_page
    y0 = y1 - h_pt
    return k, [left_pt, y0, left_pt + w_pt, y1]


# ── pipeline ─────────────────────────────────────────────────────────────────────
def resolve_pdf(entry, articles_dir, workdir):
    fname = entry.get("file")
    if fname:
        path = os.path.join(articles_dir, fname)
        if os.path.exists(path):
            return path
    url = entry.get("url")
    if not url:
        raise SystemExit(f"PDF entry has no usable file or url: {entry!r}")
    out = os.path.join(workdir, fname or "download.pdf")
    with open(out, "wb") as f:
        f.write(fetch(url, binary=True))
    return out


def get_clean_html(entry, articles_dir):
    fname = entry.get("file")
    raw = None
    if fname:
        path = os.path.join(articles_dir, fname)
        if os.path.exists(path):
            with open(path, "rb") as f:
                raw = f.read().decode("utf-8", "ignore")
    if raw is None:
        url = entry.get("url")
        if not url:
            raise SystemExit(f"HTML entry has no usable file or url: {entry!r}")
        raw = fetch(url)
    doc = Document(raw)
    clean = doc.summary()
    if len(re.sub(r"<[^>]+>", "", clean)) < 500:
        # Readability stripped too much; fall back to the raw body.
        print(f"  ! readability output thin for {entry.get('title')!r}; using raw HTML",
              file=sys.stderr)
        clean = raw
    return fix_image_urls(clean, entry.get("url") or "")


def main():
    articles_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/articles"
    output_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(articles_dir, "binder.pdf")

    if not sys.stdin.isatty():
        manifest = json.loads(sys.stdin.read())
    else:
        with open(os.path.join(articles_dir, "manifest.json")) as f:
            manifest = json.load(f)

    if isinstance(manifest, list):
        meta = {}
        articles = manifest
    else:
        meta = manifest
        articles = manifest["articles"]

    title = meta.get("title", "Reading Pack")
    subtitle = meta.get("subtitle", "")
    template = load_article_template()
    font_name, unicode_ok = register_unicode_font()

    art_margins = {"top": "0", "bottom": "0", "left": "0", "right": "0"}
    flat_margins = {"top": "0", "bottom": "0", "left": "0", "right": "0"}

    workdir = tempfile.mkdtemp(prefix="binder_")

    with sync_playwright() as pw:
        browser = pw.chromium.launch()

        # 1-3. Resolve + render each source to its own PDF.
        print(f"Rendering {len(articles)} sources...", file=sys.stderr)
        for i, a in enumerate(articles):
            kind = (a.get("type") or "html").lower()
            if kind == "pdf":
                a["_pdf"] = resolve_pdf(a, articles_dir, workdir)
            else:
                clean = get_clean_html(a, articles_dir)
                html = build_article_html(
                    template, a.get("title", ""), a.get("author", ""),
                    a.get("url", ""), clean,
                )
                out = os.path.join(workdir, f"article_{i:02d}.pdf")
                render_pdf(browser, html, out, art_margins)
                a["_pdf"] = out
            a["_pages"] = page_count(a["_pdf"])
            print(f"  [{i+1}/{len(articles)}] {a.get('title','')!r}: "
                  f"{a['_pages']} pages", file=sys.stderr)

        # 4. Cover.
        cover_pdf = os.path.join(workdir, "cover.pdf")
        render_pdf(browser, build_cover_html(title, subtitle, len(articles)),
                   cover_pdf, flat_margins, viewport={"width": A4_PX_W, "height": A4_PX_H},
                   print_media=True)
        cover_pages = page_count(cover_pdf)

        # 5. TOC first pass (placeholder numbers) to learn its length + layout.
        placeholder = [{"title": a.get("title", ""), "author": a.get("author", ""),
                        "page": "--"} for a in articles]
        toc_pdf = os.path.join(workdir, "toc.pdf")
        render_pdf(browser, build_toc_html(placeholder), toc_pdf, flat_margins,
                   viewport={"width": A4_PX_W, "height": A4_PX_H}, print_media=True)
        toc_pages = page_count(toc_pdf)
        front_pages = cover_pages + toc_pages

        # 6. Real start pages, then rebuild the TOC with true numbers.
        idx = front_pages
        for a in articles:
            a["_start"] = idx           # 0-based final page index
            idx += a["_pages"]
        real = [{"title": a.get("title", ""), "author": a.get("author", ""),
                 "page": str(a["_start"] + 1)} for a in articles]
        toc_rects = render_pdf(
            browser, build_toc_html(real), toc_pdf, flat_margins, measure=".toc-link",
            viewport={"width": A4_PX_W, "height": A4_PX_H}, print_media=True,
        )
        browser.close()

    # 7. Assemble: cover -> toc -> articles, stamping article pages as we go.
    writer = PdfWriter()
    sources = [(cover_pdf, None), (toc_pdf, None)] + [(a["_pdf"], a) for a in articles]
    gp = 0
    for path, art in sources:
        reader = PdfReader(path)
        for p in reader.pages:
            if gp >= front_pages and art is not None:
                p.merge_page(make_overlay(gp + 1, art.get("title", ""),
                                          font_name, unicode_ok))
            writer.add_page(p)
            gp += 1

    # 8. Bookmarks.
    writer.add_outline_item("Contents", cover_pages)
    for a in articles:
        writer.add_outline_item(a.get("title", ""), a["_start"])

    # 9. Clickable TOC links (annotations measured from the rendered TOC).
    if toc_rects:
        for a, r in zip(articles, toc_rects):
            k, rect = rect_to_pdf(r)
            add_link(writer, cover_pages + k, rect, a["_start"])

    with open(output_path, "wb") as f:
        writer.write(f)
    print(f"Wrote {output_path} ({gp} pages, {len(articles)} articles)", file=sys.stderr)


if __name__ == "__main__":
    main()
