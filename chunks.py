#!/usr/bin/env python3
"""Fetch Elementor's lazy-loaded webpack JS bundles. These are referenced only
inside the minified webpack runtime chunk-map (name.<hash>.bundle.min.js), so
crawl.py's static href/src pass never sees them and they 404 at runtime,
breaking interactive widgets (nav menu, popups, forms, carousels)."""
import os
import re
import time
from urllib.request import Request, urlopen

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site")
BASE = "https://www.jacbuildersfl.com"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

RUNTIMES = {
    "wp-content/plugins/elementor/assets/js": "wp-content/plugins/elementor/assets/js/webpack.runtime.min.js",
    "wp-content/plugins/elementor-pro/assets/js": "wp-content/plugins/elementor-pro/assets/js/webpack-pro.runtime.min.js",
}
BUNDLE_RE = re.compile(r'[a-z0-9-]+\.[0-9a-f]{16,}\.bundle\.min\.js')

# Named only inside other scripts, never in page markup, so the crawl misses
# them too. dialog.min.js is what Elementor popups are built on — without it
# the booking popup never opens.
EXTRAS = [
    "wp-content/plugins/elementor/assets/lib/dialog/dialog.min.js",
    "wp-includes/js/wp-emoji-release.min.js",
    "wp-content/plugins/elementor-pro/modules/lottie/assets/animations/default.json",
]


def fetch(url, retries=3):
    last = None
    for attempt in range(retries):
        try:
            req = Request(url, headers={"User-Agent": UA})
            with urlopen(req, timeout=45) as r:
                return r.read()
        except Exception as e:  # noqa
            last = e
            time.sleep(1.0 * (attempt + 1))
    raise last


def main():
    fetched = failed = skipped = 0
    for js_dir, runtime in RUNTIMES.items():
        rt_path = os.path.join(OUT, runtime)
        if not os.path.exists(rt_path):
            print(f"  ! runtime missing: {runtime}")
            continue
        with open(rt_path, "r", encoding="utf-8", errors="replace") as f:
            names = sorted(set(BUNDLE_RE.findall(f.read())))
        for name in names:
            rel = f"{js_dir}/{name}"
            local = os.path.join(OUT, rel)
            if os.path.exists(local):
                skipped += 1
                continue
            try:
                data = fetch(f"{BASE}/{rel}")
            except Exception as e:
                print(f"  ! fail {rel}: {e}")
                failed += 1
                continue
            os.makedirs(os.path.dirname(local), exist_ok=True)
            with open(local, "wb") as f:
                f.write(data)
            fetched += 1
            time.sleep(0.05)
    # Elementor also lazy-loads "conditional" stylesheets by building the URL
    # in JS (assetsLoader -> assets/css/conditionals/<name>.min.css), so these
    # are invisible to an href/src crawl exactly like the webpack bundles.
    # Without conditionals/dialog.min.css every popup — the booking form
    # included — opens unstyled.
    conditional_re = re.compile(r'conditionals/([a-z0-9-]+)')
    extras = list(EXTRAS)
    for js_dir in RUNTIMES:
        plugin_root = js_dir.rsplit("/assets/js", 1)[0]
        js_root = os.path.join(OUT, js_dir)
        if not os.path.isdir(js_root):
            continue
        names = set()
        for fn in os.listdir(js_root):
            if not fn.endswith(".js"):
                continue
            with open(os.path.join(js_root, fn), "r", encoding="utf-8",
                      errors="replace") as f:
                names |= set(conditional_re.findall(f.read()))
        for name in sorted(names):
            extras.append(f"{plugin_root}/assets/css/conditionals/{name}.min.css")

    for rel in extras:
        local = os.path.join(OUT, rel)
        if os.path.exists(local):
            skipped += 1
            continue
        try:
            data = fetch(f"{BASE}/{rel}")
        except Exception as e:
            print(f"  ! fail {rel}: {e}")
            failed += 1
            continue
        os.makedirs(os.path.dirname(local), exist_ok=True)
        with open(local, "wb") as f:
            f.write(data)
        fetched += 1

    print(f"\nBundles fetched: {fetched}, skipped(existing): {skipped}, failed: {failed}")


if __name__ == "__main__":
    main()
