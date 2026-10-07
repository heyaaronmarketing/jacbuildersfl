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
python3 scaffold.py   # robots.txt, sitemaps, _headers, 404.html, ignores
python3 recaptcha.py  # strip the domain-locked reCAPTCHA widget (AFTER scaffold)
python3 tighten.py    # UX overlay + Before/After review toggle (LAST)
python3 verify.py     # gate: every root-relative reference must resolve
```

`recaptcha.py` runs after `scaffold.py` on purpose — scaffold fetches a fresh
404 page from the live site, which arrives with the widget still in it.

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

## The one deliberate deviation from as-is

Elementor's reCAPTCHA v3 widget is stripped (`recaptcha.py`). Its site key is
registered against jacbuildersfl.com, so on any other host — the workers.dev
preview included — Google renders "ERROR for site owner: Invalid domain for
site" in place of the badge. It is safe to drop because reCAPTCHA v3 only
scored submissions to /wp-admin/admin-ajax.php, which does not survive the
migration. Rebuilding bot protection is part of rewiring the forms.

## UX overlay + Before/After toggle

`tighten.py` injects a review layer (`site/assets/tighten.{css,js}`, written by
the script, not committed by hand) that calms Elementor's animations, hides the
broken Owens Corning roof-designer, strips floating CTA clutter, and trims
repeat CTAs. It rewrites no source markup — delete the injected tags to revert.

Everything is gated behind `html.tighten-on`, so the toggle in the bottom-left
corner flips the whole layer instantly. The JS only *marks* nodes with
`.jac-ux-hide`; CSS does the hiding. The original overlay called `.remove()`,
which cannot be undone without a reload.

- **Before** = the mirror exactly as the live WordPress site renders it.
- **After** = the overlay applied. This is the default.
- Choice persists in `localStorage` under `jacUxMode` and follows you across pages.
- The toggle renders only on non-production hosts (`PROD_HOSTS` in `tighten.py`),
  so it cannot follow the site to jacbuildersfl.com. The overlay itself still
  applies there — by then it is the approved design.

Two details worth keeping in mind when editing it:

- **Elementor detaches both popup templates on load** and re-inserts them when
  triggered. The marking pass catches them while still inline (classes survive
  the detach/re-attach), and a MutationObserver covers anything injected later.
- **Popup `6576` is removed, popup `3011` is kept.** 3011 is the booking form
  that every Book Now / Get My Free Roof Report CTA opens. An earlier attempt
  removed all form-less popups and broke booking, because 3011's form hydrates
  late. Never reintroduce a rule that matches popups by absence of a `<form>`.

## Deliberately left as-is

Third-party phone-home is untouched (GA4, Google Ads, Facebook Pixel, Owens
Corning roof-designer widget, Google review avatars). Only same-origin assets
were localized. WordPress form backends are gone with WordPress — any live
contact/quote form needs rewiring before this becomes the production origin.
