#!/usr/bin/env python3
"""Strip Elementor's reCAPTCHA v3 widget from the mirror.

The site key is registered in Google's reCAPTCHA admin against
jacbuildersfl.com. Served from any other host — the workers.dev preview —
Google refuses to render the badge and prints "ERROR for site owner: Invalid
domain for site" on the page instead.

Removing it is safe here because reCAPTCHA v3 exists only to score
submissions to /wp-admin/admin-ajax.php, and that endpoint does not survive
the migration. It is guarding a door that is no longer in the building. When
the forms are rewired to a real backend, bot protection has to be rebuilt on
that backend anyway (the secret-key half of reCAPTCHA lived in WordPress).

This is the one deliberate deviation from the as-is mirror. To put the widget
back, delete this step from the pipeline and re-run crawl.py.
"""
import os
import re

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site")

FIELD_OPEN = re.compile(r'<div class="elementor-field-type-recaptcha[^"]*"')
SCRIPT = re.compile(
    r'<script[^>]*\bsrc="[^"]*recaptcha/api\.js[^"]*"[^>]*>\s*</script>\s*', re.I)
DIV_TAG = re.compile(r'<div\b|</div>', re.I)


def strip_field(html, start):
    """Remove one field-group div by walking to its matching close tag.

    A fixed-length regex would be wrong: the widget nests three divs deep and
    Elementor's markup is not consistently formatted across templates.
    """
    depth = 0
    for m in DIV_TAG.finditer(html, start):
        depth += 1 if m.group(0).lower() == "<div" else -1
        if depth == 0:
            return html[:start] + html[m.end():]
    return None  # unbalanced; leave it alone rather than corrupt the page


def main():
    changed = fields = scripts = skipped = 0
    for root, _, files in os.walk(OUT):
        for fn in files:
            if not fn.lower().endswith((".html", ".htm")):
                continue
            path = os.path.join(root, fn)
            with open(path, "r", encoding="utf-8") as f:
                html = f.read()
            orig = html

            while True:
                m = FIELD_OPEN.search(html)
                if not m:
                    break
                stripped = strip_field(html, m.start())
                if stripped is None:
                    print(f"  ! unbalanced markup, left in place: "
                          f"{os.path.relpath(path, OUT)}")
                    skipped += 1
                    break
                html = stripped
                fields += 1

            html, n = SCRIPT.subn("", html)
            scripts += n

            if html != orig:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(html)
                changed += 1

    print(f"Pages changed: {changed}  widgets removed: {fields}  "
          f"api.js tags removed: {scripts}  skipped: {skipped}")


if __name__ == "__main__":
    main()
