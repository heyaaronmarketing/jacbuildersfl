#!/usr/bin/env python3
"""Rewrite absolute jacbuildersfl.com URLs to root-relative so the mirror is
portable: the same files work on the Cloudflare preview URL and on the
production domain.

Asset and link URLs become root-relative. Metadata that MUST stay absolute to
stay correct is protected first and restored afterwards:

  * <link rel="canonical"> and og:url — root-relative canonicals make the
    preview host self-canonicalize, which is exactly the duplicate-content
    signal the canonical exists to prevent.
  * og:image / twitter:image — social scrapers do not resolve relative paths.
  * JSON-LD blocks — schema.org @id/url values are only valid absolute, and
    they are identity, not plumbing.

This matches what WordPress emitted, so it is also the faithful choice.
"""
import os
import re

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site")
EXTS = (".html", ".htm", ".css", ".js", ".xml", ".json", ".svg")
PROD = "https://www.jacbuildersfl.com"

# Map the absolute origin to empty string (NOT "\/" for the escaped form): the
# path that follows already carries its own leading slash, so emitting "\/"
# would double it into "\/\/wp-content" — a protocol-relative URL the browser
# reads as the host "wp-content" (ERR_NAME_NOT_RESOLVED), which breaks every
# Elementor script on the page. Order matters: escaped-JSON forms first, www
# before bare so the longer host matches.
REPLACEMENTS = [
    (r"https:\/\/www.jacbuildersfl.com", ""),
    (r"http:\/\/www.jacbuildersfl.com", ""),
    (r"https:\/\/jacbuildersfl.com", ""),
    (r"http:\/\/jacbuildersfl.com", ""),
    ("https://www.jacbuildersfl.com", ""),
    ("http://www.jacbuildersfl.com", ""),
    ("https://jacbuildersfl.com", ""),
    ("http://jacbuildersfl.com", ""),
    ("//www.jacbuildersfl.com", ""),
    ("//jacbuildersfl.com", ""),
]

# Corrective for files already damaged by a prior run that emitted "\/":
# collapse an escaped protocol-relative prefix "\/\/seg" into "\/seg" UNLESS
# seg is a real external host (a token followed by a dot, e.g.
# \/\/www.facebook.com). Site paths have no dot before the next slash.
DAMAGE_RE = re.compile(r'\\/\\/(?![A-Za-z0-9-]+\.)')

PROTECT = [
    re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>.*?</script>',
               re.I | re.S),
    re.compile(r'<link[^>]+rel=["\']canonical["\'][^>]*>', re.I),
    re.compile(r'<meta[^>]+(?:property|name)=["\'](?:og:url|og:image(?::secure_url)?'
               r'|twitter:image)["\'][^>]*>', re.I),
]


def protect(text):
    """Swap must-stay-absolute blocks for placeholders the replacer can't touch."""
    stash = []
    for pattern in PROTECT:
        def keep(m):
            stash.append(m.group(0))
            return f"\x00PROTECTED{len(stash) - 1}\x00"
        text = pattern.sub(keep, text)
    return text, stash


def restore(text, stash):
    for i, block in enumerate(stash):
        text = text.replace(f"\x00PROTECTED{i}\x00", block)
    return text


def main():
    changed = 0
    for root, _, files in os.walk(OUT):
        for fn in files:
            if not fn.lower().endswith(EXTS):
                continue
            path = os.path.join(root, fn)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    text = f.read()
            except (UnicodeDecodeError, IsADirectoryError):
                continue
            orig = text
            is_html = fn.lower().endswith((".html", ".htm"))
            stash = []
            if is_html:
                text, stash = protect(text)
            for a, b in REPLACEMENTS:
                text = text.replace(a, b)
            text = DAMAGE_RE.sub(r'\\/', text)
            if is_html:
                text = restore(text, stash)
            if text != orig:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
                changed += 1
    print(f"Files rewritten: {changed}")


if __name__ == "__main__":
    main()
