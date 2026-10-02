#!/usr/bin/env python3
"""Check the mirror for references that will 404 once it is the only origin.

Every root-relative href/src/srcset/CSS url() in the output is resolved
against site/ and reported if the file is not there. Run this before every
push: a missing Elementor bundle or stylesheet is invisible in a casual
look at the homepage but breaks nav, popups and forms at runtime.

Known-404-on-the-live-site references are listed in EXPECTED_404 so they do
not drown out real regressions — a faithful mirror reproduces those.
"""
import os
import re
import sys
from collections import defaultdict
from urllib.parse import unquote, urlparse

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site")

# These 404 on the live WordPress site too (plugin CSS pointing at images that
# were never shipped, plus one internal link to a removed page). Mirroring the
# 404 is the faithful outcome, not a defect to fix.
EXPECTED_404 = {
    "/roofing-services-tampa",
    "/wp-content/plugins/bdthemes-prime-slider-lite/images/backgrounds/form-checkbox.svg",
    "/wp-content/plugins/bdthemes-prime-slider-lite/images/backgrounds/form-checkbox-indeterminate.svg",
    "/wp-content/plugins/bdthemes-prime-slider-lite/images/backgrounds/form-radio.svg",
    "/wp-content/plugins/bdthemes-prime-slider-lite/images/backgrounds/form-select.svg",
    "/wp-content/plugins/bdthemes-prime-slider-lite/images/backgrounds/form-datalist.svg",
    "/wp-content/plugins/bdthemes-prime-slider-lite/images/backgrounds/divider-icon.svg",
    "/wp-content/plugins/bdthemes-prime-slider-lite/images/backgrounds/list-bullet.svg",
}

# WordPress plumbing that does not survive the migration by design: the REST
# API, RSS feeds, oembed and xmlrpc all needed PHP. They appear only in <link
# rel="alternate"> head tags and are invisible to users, so they are reported
# as a count, not as regressions to chase.
WP_PLUMBING = re.compile(r'^/(wp-json/|xmlrpc\.php)|/feed/$')

RE_ATTR = re.compile(
    r'(?:href|src|data-lazy-src|data-src|poster)\s*=\s*["\'](/[^"\'#?]*)',
    re.I)
RE_SRCSET = re.compile(
    r'(?:srcset|data-srcset|data-lazy-srcset)\s*=\s*["\']([^"\']+)["\']', re.I)
RE_CSS_URL = re.compile(r'url\(\s*["\']?(/[^"\')?#]+)', re.I)
# Root-relative paths inside escaped JSON, e.g. "\/wp-content\/plugins\/...".
RE_ESCAPED = re.compile(r'"(\\/(?:wp-content|wp-includes)\\/[^"]+?\.[a-z0-9]{2,5})"',
                        re.I)


def resolve(ref):
    path = unquote(urlparse(ref).path)
    if path.endswith("/"):
        path += "index.html"
    local = os.path.join(OUT, path.lstrip("/"))
    if os.path.exists(local):
        return True
    # Extensionless internal links are pages: /foo -> /foo/index.html
    if "." not in os.path.basename(path):
        return os.path.exists(os.path.join(local, "index.html"))
    return False


def main():
    broken = defaultdict(set)
    plumbing = set()
    checked = 0
    for root, _, files in os.walk(OUT):
        for fn in files:
            if not fn.lower().endswith((".html", ".htm", ".css")):
                continue
            path = os.path.join(root, fn)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    text = f.read()
            except (UnicodeDecodeError, IsADirectoryError):
                continue
            page = "/" + os.path.relpath(path, OUT)
            refs = set(RE_ATTR.findall(text))
            refs |= set(RE_CSS_URL.findall(text))
            refs |= {m.replace("\\/", "/") for m in RE_ESCAPED.findall(text)}
            for m in RE_SRCSET.findall(text):
                for part in m.split(","):
                    u = part.strip().split(" ")[0]
                    if u.startswith("/"):
                        refs.add(u)
            for ref in refs:
                checked += 1
                if ref in EXPECTED_404:
                    continue
                if not resolve(ref):
                    if WP_PLUMBING.search(ref):
                        plumbing.add(ref)
                    else:
                        broken[ref].add(page)

    pages = len([1 for r, _, fs in os.walk(OUT) for f in fs if f == "index.html"])
    print(f"Pages: {pages}   references checked: {checked}")
    print(f"WordPress-only endpoints gone by design (wp-json/feed/xmlrpc): "
          f"{len(plumbing)}")
    if not broken:
        print("No broken references.")
        return
    print(f"\nBROKEN ({len(broken)} distinct):")
    for ref, where in sorted(broken.items()):
        sample = sorted(where)[:3]
        more = f" (+{len(where) - 3} more)" if len(where) > 3 else ""
        print(f"  {ref}\n      on {', '.join(sample)}{more}")
    sys.exit(1)


if __name__ == "__main__":
    main()
