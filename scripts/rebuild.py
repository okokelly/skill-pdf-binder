#!python3
"""Standalone binder rebuild script. Call with: python3 rebuild.py ARTICLES_DIR OUTPUT_PATH

Uses the full pipeline: readability → Playwright → merge → stamp → TOC → links.
"""
import os, sys, re, io, json
from urllib.parse import urljoin
from readability import Document
from playwright.sync_api import sync_playwright
from PyPDF2 import PdfMerger, PdfReader, PdfWriter
from PyPDF2.generic import (
    RectangleObject, FloatObject, NameObject,
    ArrayObject, DictionaryObject,
)
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm

A4_W, A4_H = A4  # 595.28 x 841.89 pts

def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

def safe_text(text):
    """Replace Unicode chars that don't work in PDF core fonts."""
    replacements = {
        '\u2014': '--', '\u2013': '-', '\u2018': "'", '\u2019': "'",
        '\u201c': '"', '\u201d': '"', '\u2026': '...', '\u00a0': ' ',
        '\u2022': '*', '\u00b7': '-', '\u2122': '(TM)', '\u00ae': '(R)',
        '\u00e9': 'e', '\u00e8': 'e', '\u00ea': 'e', '\u00eb': 'e',
        '\u00e0': 'a', '\u00e1': 'a', '\u00e2': 'a', '\u00e3': 'a',
        '\u00f1': 'n', '\u00f6': 'o', '\u00fc': 'u', '\u00f8': 'o',
        '\u00e7': 'c', '\u00ed': 'i', '\u00f3': 'o', '\u00fa': 'u',
        '\u00c9': 'E', '\u00c8': 'E', '\u00c0': 'A', '\u00c1': 'A',
        '\u00d1': 'N', '\u00d6': 'O', '\u00dc': 'U', '\u00c7': 'C',
        '\u00df': 'ss', '\u0153': 'oe', '\u0152': 'OE',
        '\u2264': '<=', '\u2265': '>=', '\u00d7': 'x',
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return ''.join(ch if ord(ch) < 256 else '?' for ch in text)

def fix_image_urls(html, base_url):
    """Rewrite relative image src to absolute, using article URL as base."""
    def replace_src(m):
        src = m.group(1)
        if src.startswith(("http://", "https://", "data:")):
            return m.group(0)
        return f'src="{urljoin(base_url, src)}"'
    return re.sub(r'src="([^"]*)"', replace_src, html)

# ── CLI ──────────────────────────────────────────
if __name__ == "__main__":
    articles_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/articles"
    output_path = sys.argv[2] if len(sys.argv) > 2 else f"{articles_dir}/binder.pdf"
    
    # Load article list from stdin or a manifest file
    manifest = json.loads(sys.stdin.read())
    # manifest: [{"file": "article.html", "title": "...", "author": "...", "url": "...", "type": "html"|"pdf"}, ...]
    
    # ... rest of pipeline
    # See the full pipeline in SKILL.md
