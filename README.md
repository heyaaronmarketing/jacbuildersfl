# jacbuildersfl.com — static mirror (Cloudflare Workers static assets)

Faithful as-is static mirror of the WordPress (Elementor + Elementor Pro + Yoast)
site at https://www.jacbuildersfl.com/, deployed to Cloudflare as a Workers
static-assets project.

- Deploy root: `site/` (declared in `wrangler.jsonc` as `assets.directory`)
- No build step. Cloudflare serves `site/` directly.
- `site/404.html` is wired via `not_found_handling: "404-page"`.

## Re-running the mirror (idempotent, in order)

```bash
python3 crawl.py      # BFS from Yoast page/post/locations sitemaps + home
python3 rewrite.py    # absolute jacbuildersfl.com URLs -> root-relative
python3 chunks.py     # Elementor lazy-loaded webpack bundles (not in HTML)
python3 video.py      # transcode any asset over Cloudflare's 25 MiB file cap
python3 scaffold.py   # robots.txt, sitemap.xml, _headers, 404.html, ignores
```

Local preview: `python3 -m http.server 8793 --directory site`
(also available as the `jac-static` launch config).

## Gotchas baked into these scripts

- **rewrite.py escaped-JSON rule maps `https:\/\/host` to an empty string**, not
  to `\/`. The following path already carries its own `\/`; emitting `\/` doubles
  it into `\/\/wp-content`, which the browser reads as the host `wp-content`
  (ERR_NAME_NOT_RESOLVED) and breaks every Elementor script.
- **chunks.py is required.** Elementor lazy-loads per-widget webpack bundles
  (`name.<hash>.bundle.min.js`) named only inside the minified webpack runtime
  chunk-map, so an href/src crawl never sees them. Without this step nav
  dropdowns, popups, forms and carousels 404 at runtime.
- **Cloudflare rejects any single asset over 25 MiB** and fails the whole
  deploy. The site-wide Elementor hero video is ~95 MB at 1080p/16 Mbps;
  `video.py` re-encodes oversized media in place (720p, ~3 Mbps) and keeps the
  untouched original out of git via `.gitignore` (`*.orig.mp4`).
- Because the assets directory is `site/` (not the repo root), Cloudflare's
  uploader never walks `.git/`, so there is no oversized-pack failure mode.

## Deliberately left as-is

Third-party phone-home is untouched (GA4, Google Ads, Facebook Pixel, Owens
Corning roof-designer widget, Google review avatars). Only same-origin assets
were localized. WordPress form backends are gone with WordPress — any live
contact/quote form needs rewiring before this becomes the production origin.
