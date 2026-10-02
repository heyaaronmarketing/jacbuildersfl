#!/usr/bin/env python3
"""Deploy scaffolding for the static mirror.

Everything here is mirrored from the live WordPress site rather than invented,
so the static origin keeps answering the URLs Google already has registered:

  * robots.txt, verbatim.
  * The Yoast sitemap index AND every child it lists, at their original paths.
    Search Console has /sitemap_index.xml submitted; a hand-rolled
    /sitemap.xml would leave that URL 404ing and every child with it.
  * The real WordPress 404 page (site chrome and nav intact) instead of a
    hand-made placeholder.

Only _headers and the ignore files are additions, and neither is user-visible.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from urllib.error import HTTPError  # noqa: E402
from urllib.request import Request, urlopen  # noqa: E402

import crawl    # noqa: E402  (fetch/save/url_to_path, incl. non-ASCII encoding)
import rewrite  # noqa: E402  (same URL rewriting the crawled pages got)

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site")
BASE = "https://www.jacbuildersfl.com"

# A path that cannot exist, so WordPress serves its genuine 404 template.
NOT_FOUND_PROBE = "/this-page-does-not-exist-static-mirror-probe/"

HEADERS = """/*
  X-Content-Type-Options: nosniff
  X-Frame-Options: SAMEORIGIN
  Referrer-Policy: strict-origin-when-cross-origin

# Fingerprinted/static assets cache hard. HTML is left on the default
# (revalidated) policy so content updates show up immediately.
/wp-content/*
  Cache-Control: public, max-age=31536000, immutable
/wp-includes/*
  Cache-Control: public, max-age=31536000, immutable
/*.css
  Cache-Control: public, max-age=31536000, immutable
/*.js
  Cache-Control: public, max-age=31536000, immutable
/*.webp
  Cache-Control: public, max-age=31536000, immutable
/*.avif
  Cache-Control: public, max-age=31536000, immutable
/*.jpg
  Cache-Control: public, max-age=31536000, immutable
/*.jpeg
  Cache-Control: public, max-age=31536000, immutable
/*.png
  Cache-Control: public, max-age=31536000, immutable
/*.svg
  Cache-Control: public, max-age=31536000, immutable
/*.gif
  Cache-Control: public, max-age=31536000, immutable
/*.mp4
  Cache-Control: public, max-age=31536000, immutable
/*.woff
  Cache-Control: public, max-age=31536000, immutable
/*.woff2
  Cache-Control: public, max-age=31536000, immutable
/*.ttf
  Cache-Control: public, max-age=31536000, immutable
"""


def apply_rewrite(html):
    """Run the same rewrite the crawled pages got: root-relative plumbing,
    absolute canonical/og/JSON-LD."""
    text, stash = rewrite.protect(html)
    for a, b in rewrite.REPLACEMENTS:
        text = text.replace(a, b)
    text = rewrite.DAMAGE_RE.sub(r'\\/', text)
    return rewrite.restore(text, stash)


def write_robots():
    data, _ = crawl.fetch(f"{BASE}/robots.txt")
    crawl.save(os.path.join(OUT, "robots.txt"), data)
    return data.decode("utf-8", "replace")


def mirror_sitemaps():
    """Mirror the sitemap index, its children, and the Yoast XSL.

    <loc> values stay absolute — the sitemap protocol requires it, and these
    are the production URLs being declared. Only the xml-stylesheet href is
    made root-relative so the sitemaps also render on the preview host.
    """
    idx_bytes, _ = crawl.fetch(f"{BASE}/sitemap_index.xml")
    idx = idx_bytes.decode("utf-8", "replace")
    children = [u.strip() for u in re.findall(r"<loc>([^<]+)</loc>", idx)]

    xsl = None
    written = []
    for url in [f"{BASE}/sitemap_index.xml"] + children:
        data, _ = crawl.fetch(url)
        text = data.decode("utf-8", "replace")
        m = re.search(r'href="(//[^"]+\.xsl)"', text)
        if m and xsl is None:
            xsl = "https:" + m.group(1)
        # Only the stylesheet reference is plumbing; <loc> stays absolute.
        text = re.sub(r'href="//www\.jacbuildersfl\.com(/[^"]+\.xsl)"',
                      r'href="\1"', text)
        local = os.path.join(OUT, url[len(BASE):].lstrip("/"))
        crawl.save(local, text.encode("utf-8"))
        written.append(os.path.relpath(local, OUT))

    if xsl:
        local = crawl.url_to_path(xsl)
        if not os.path.exists(local):
            data, _ = crawl.fetch(xsl)
            crawl.save(local, data)
    return written


def fetch_404_body(url):
    """crawl.fetch raises on a 404 — but here the 404 body IS the payload.
    HTTPError is itself a readable response, so read it off the exception."""
    req = Request(url, headers={"User-Agent": crawl.UA})
    try:
        with urlopen(req, timeout=45) as r:
            return r.read(), r.status
    except HTTPError as e:
        return e.read(), e.code


def write_404():
    """Mirror WordPress's own 404 template, with nav and branding intact."""
    data, status = fetch_404_body(f"{BASE}{NOT_FOUND_PROBE}")
    if status != 404:
        raise SystemExit(f"404 probe returned {status}, not 404 — pick a new probe path")
    html = apply_rewrite(data.decode("utf-8", "replace"))
    # The probe path leaks into the markup (body classes, search form action,
    # the Yoast canonical); drop it so the page is generic.
    html = html.replace(NOT_FOUND_PROBE.strip("/"), "")
    with open(os.path.join(OUT, "404.html"), "w", encoding="utf-8") as f:
        f.write(html)

    # The 404 template carries its own per-page Elementor CSS, which nothing
    # else on the site references — so the crawl never discovered it. Pull the
    # 404's assets from the pre-rewrite markup, where they are still absolute.
    _, assets = crawl.discover_from_html(data.decode("utf-8", "replace"),
                                         f"{BASE}{NOT_FOUND_PROBE}")
    fetched = 0
    for url in sorted(assets):
        local = crawl.url_to_path(url)
        if os.path.exists(local):
            continue
        try:
            blob, _ = crawl.fetch(url)
        except Exception as e:
            print(f"  ! 404 asset {url}: {e}")
            continue
        crawl.save(local, blob)
        fetched += 1
    return len(html), fetched


def write_headers():
    with open(os.path.join(OUT, "_headers"), "w") as f:
        f.write(HEADERS)


def write_ignores():
    proj = os.path.dirname(OUT)
    with open(os.path.join(proj, ".gitignore"), "w") as f:
        f.write(".DS_Store\n__pycache__/\n*.pyc\ncrawl.log\n"
                "# pre-transcode originals kept locally for re-encodes (see video.py)\n"
                "*.orig.mp4\n")
    # The assets directory is site/, so Cloudflare's uploader never walks .git.
    # The *.orig.* entries matter for a local `wrangler deploy`: those are the
    # pre-transcode originals, which are over Cloudflare's 25 MiB per-asset
    # limit and would fail the upload (git never sees them — see .gitignore).
    with open(os.path.join(OUT, ".assetsignore"), "w") as f:
        f.write(".assetsignore\n*.orig.mp4\n*.orig.mov\n*.orig.webm\n")


def main():
    robots = write_robots()
    maps = mirror_sitemaps()
    n404, n404_assets = write_404()
    write_headers()
    write_ignores()
    print(f"robots.txt: {len(robots.splitlines())} lines (mirrored verbatim)")
    print(f"sitemaps mirrored ({len(maps)}): {', '.join(maps)}")
    print(f"404.html: {n404} bytes (WordPress 404 template), "
          f"{n404_assets} new assets fetched for it")
    print("_headers, .gitignore, .assetsignore written")


if __name__ == "__main__":
    main()
