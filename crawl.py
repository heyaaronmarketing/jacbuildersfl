#!/usr/bin/env python3
"""Static mirror of jacbuildersfl.com (WordPress) for Cloudflare hosting."""
import os
import re
import time
import gzip
from collections import deque
from urllib.parse import urljoin, urlparse, unquote, quote
from urllib.request import Request, urlopen

BASE = "https://www.jacbuildersfl.com"
HOSTS = ("www.jacbuildersfl.com", "jacbuildersfl.com")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

SEEDS = ["/"]

visited = set()
saved_assets = set()
queue = deque()

JUNK = re.compile(r'(/wp-json/|/xmlrpc\.php|/feed/?$|/feed/|oembed|/comments/feed|wp-login|/wp-admin)', re.I)


def is_junk(url):
    return bool(JUNK.search(url))


def encode_url(url):
    """Percent-encode non-ASCII path characters before the request.

    One upload here has a U+202F narrow no-break space in its filename;
    urlopen tries to send the path as ASCII and raises instead of fetching.
    "%" is in the safe set so an already-encoded path is not double-encoded.
    """
    p = urlparse(url)
    return p._replace(path=quote(p.path, safe="/%:@&=+$,;~!*'()")).geturl()


def fetch(url, retries=3):
    url = encode_url(url)
    last = None
    for attempt in range(retries):
        try:
            req = Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
            with urlopen(req, timeout=45) as r:
                data = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                ctype = r.headers.get("Content-Type", "")
                return data, ctype
        except Exception as e:  # noqa
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise last


def url_to_path(url):
    p = urlparse(url)
    path = unquote(p.path)
    if path.endswith("/") or path == "":
        path = path + "index.html"
    elif "." not in os.path.basename(path):
        path = path + "/index.html"
    return os.path.join(OUT, path.lstrip("/"))


def same_host(url):
    return urlparse(url).netloc in ("",) + HOSTS


def save(local, data):
    os.makedirs(os.path.dirname(local), exist_ok=True)
    with open(local, "wb") as f:
        f.write(data)


RE_HREF = re.compile(r'(href|src|data-lazy-src|data-src|data-bg|data-background|poster)\s*=\s*["\']([^"\']+)["\']', re.I)
RE_SRCSET = re.compile(r'(?:data-lazy-srcset|data-srcset|srcset)\s*=\s*["\']([^"\']+)["\']', re.I)
RE_CSS_URL = re.compile(r'url\(\s*["\']?([^"\')]+)["\']?\s*\)', re.I)


def looks_like_page(url):
    base = os.path.basename(urlparse(url).path)
    if "." in base:
        return base.rsplit(".", 1)[1].lower() in ("html", "htm", "php")
    return True


def discover_from_html(html, base_url):
    pages, assets = set(), set()
    for m in RE_HREF.finditer(html):
        attr, val = m.group(1), m.group(2).strip()
        if val.startswith(("mailto:", "tel:", "javascript:", "#", "data:")):
            continue
        absu = urljoin(base_url, val).split("#")[0]
        if not same_host(absu) or is_junk(absu):
            continue
        if attr.lower() == "href" and looks_like_page(absu):
            if urlparse(absu).query:
                continue
            pages.add(absu)
        else:
            assets.add(absu)
    for m in RE_SRCSET.finditer(html):
        for part in m.group(1).split(","):
            u = part.strip().split(" ")[0]
            if u and not u.startswith("data:"):
                absu = urljoin(base_url, u).split("#")[0]
                if same_host(absu):
                    assets.add(absu)
    for m in re.finditer(r'content\s*=\s*["\'](https?://[^"\']+\.(?:png|jpe?g|webp|gif|svg|ico))["\']', html, re.I):
        absu = m.group(1).split("#")[0]
        if same_host(absu):
            assets.add(absu)
    return pages, assets


def discover_from_css(css, base_url):
    assets = set()
    for m in RE_CSS_URL.finditer(css):
        u = m.group(1).strip()
        if u.startswith("data:"):
            continue
        absu = urljoin(base_url, u).split("#")[0].split("?")[0]
        if same_host(absu):
            assets.add(absu)
    return assets


def process():
    # Seed from the Yoast sitemap index, walking whatever children it lists
    # (pages, posts, locations, categories, author, Elementor CPTs) so every
    # URL Google already has registered exists in the mirror. Hardcoding a
    # subset silently drops the category archives.
    try:
        idx, _ = fetch(f"{BASE}/sitemap_index.xml")
        children = re.findall(r"<loc>([^<]+)</loc>", idx.decode("utf-8", "replace"))
    except Exception as e:
        print(f"  ! sitemap index fail: {e}")
        children = []
    for child in children:
        try:
            data, _ = fetch(child.strip())
            for m in re.finditer(r"<loc>([^<]+)</loc>", data.decode("utf-8", "replace")):
                queue.append(m.group(1).strip())
        except Exception as e:
            print(f"  ! sitemap fail {child}: {e}")
    for s in SEEDS:
        queue.append(urljoin(BASE, s))

    assets = set()
    while queue:
        url = queue.popleft().split("#")[0]
        if url in visited or is_junk(url):
            continue
        visited.add(url)
        try:
            data, ctype = fetch(url)
        except Exception as e:
            print(f"  ! page fail {url}: {e}")
            continue
        if "text/html" not in ctype:
            assets.add(url)
            continue
        html = data.decode("utf-8", "replace")
        save(url_to_path(url), html.encode("utf-8"))
        print(f"  page {url}")
        pages, a = discover_from_html(html, url)
        assets |= a
        for pg in pages:
            if pg not in visited:
                queue.append(pg)
        time.sleep(0.2)

    asset_queue = deque(assets)
    while asset_queue:
        url = asset_queue.popleft().split("#")[0]
        if url in saved_assets or is_junk(url):
            continue
        saved_assets.add(url)
        try:
            data, ctype = fetch(url)
        except Exception as e:
            print(f"  ! asset fail {url}: {e}")
            continue
        save(url_to_path(url), data)
        if "css" in ctype or url.endswith(".css"):
            try:
                for m in discover_from_css(data.decode("utf-8", "replace"), url):
                    if m not in saved_assets:
                        asset_queue.append(m)
            except Exception:
                pass
        time.sleep(0.1)

    print(f"\nPages: {len(visited)}, Assets: {len(saved_assets)}")


if __name__ == "__main__":
    process()
