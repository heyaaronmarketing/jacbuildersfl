#!/usr/bin/env python3
"""Inject the UX-cleanup overlay plus a Before/After review toggle.

The overlay from the May 2026 pass (kill animations, drop the broken Owens
Corning roof-designer and its auto-popup, strip floating CTA clutter, trim
repeat CTAs) is applied as a pure override layer — no source markup is
rewritten, so deleting the injected tags fully reverts the site.

Everything is gated behind `html.tighten-on`, which is what makes the toggle
instant. The original overlay called .remove() on the nodes it dropped; a
removal cannot be undone without a reload, so here the JS only *marks* nodes
with a class and CSS does the hiding. Flipping the toggle is then one class
change on <html> instead of a page load.

Assets are written by this script rather than committed by hand, so a wiped
site/ directory plus a re-crawl still produces a complete tree.

Pipeline position: last, after scaffold.py and recaptcha.py.
"""
import os
import re

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site")
ASSETS = os.path.join(OUT, "assets")
VER = "1"

# Hosts where the site is the real thing, not a review copy. The toggle widget
# hides itself here so it cannot follow the site into production, while the
# overlay itself still applies (by then it is the approved design).
PROD_HOSTS = ("www.jacbuildersfl.com", "jacbuildersfl.com")

BOOT = (
    '<script>(function(){var m;try{m=localStorage.getItem("jacUxMode")}'
    'catch(e){}if(m!=="before"){document.documentElement.className+='
    '" tighten-on"}})();</script>'
)
CSS_TAG = f'<link rel="stylesheet" href="/assets/tighten.css?v={VER}">'
JS_TAG = f'<script src="/assets/tighten.js?v={VER}" defer></script>'
MARKER = "/assets/tighten.css"
# Present on every mirrored WordPress page, on none of the hand-authored ones.
ELEMENTOR_PAGE = "elementor/assets/js/frontend.min.js"
VER_RE = re.compile(r'(/assets/tighten\.(?:css|js))\?v=\d+')

CSS = """/* ==========================================================================
   tighten.css — UX cleanup overlay + Before/After review toggle.

   Every cleanup rule is scoped to html.tighten-on so the toggle can flip the
   whole layer with one class change. Nothing here rewrites source markup.
   ========================================================================== */

/* --- 1. Kill motion ------------------------------------------------------ */
/* Snap transitions/animations to ~instant rather than 0 — transitionend still
   fires, so dropdowns and accordions that wait on it keep working. */
html.tighten-on *,
html.tighten-on *::before,
html.tighten-on *::after {
  animation-duration: 1ms !important;
  animation-delay: 0ms !important;
  transition-duration: 1ms !important;
  transition-delay: 0ms !important;
  scroll-behavior: auto !important;
}
/* Elementor hides elements with .elementor-invisible until its entrance-
   animation JS reveals them. With animations neutralized that reveal may
   never run, so force them visible or the page loads with holes in it. */
html.tighten-on .elementor-invisible {
  opacity: 1 !important;
  visibility: visible !important;
}
html.tighten-on .animated,
html.tighten-on .elementor-invisible {
  animation: none !important;
  transform: none !important;
}
/* Neutralize hover grow/scale micro-animations. */
html.tighten-on [class*="elementor-animation-"]:hover,
html.tighten-on [class*="elementor-animation-"]:focus {
  transform: none !important;
}

/* --- 2. Broken Owens Corning roof-designer widget ------------------------ */
/* The embedded TruDefinition iframe times out on every load and floods the
   console with "IFrame has not responded within 5 seconds". */
html.tighten-on .oc_shingle_view,
html.tighten-on .elementor-widget-html:has(.oc_shingle_view) {
  display: none !important;
}

/* --- 3. Floating CTA clutter --------------------------------------------- */
html.tighten-on .e-contact-buttons,   /* duplicate floating phone buttons    */
html.tighten-on .elementor-fixed {    /* floating calendar/scheduling button */
  display: none !important;
}

/* --- 4. Nodes the JS half marked ----------------------------------------- */
/* Marked once on load in both modes; only hidden in After. */
html.tighten-on .jac-ux-hide { display: none !important; }

/* ==========================================================================
   Review toggle — injected only on non-production hosts.
   ========================================================================== */
.jac-ux-toggle {
  position: fixed;
  left: 16px;
  bottom: 16px;
  z-index: 2147483000;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 999px;
  background: rgba(15, 28, 46, .94);
  box-shadow: 0 6px 24px rgba(0, 0, 0, .32);
  font: 600 12px/1 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  color: #fff;
  -webkit-font-smoothing: antialiased;
}
.jac-ux-toggle__label {
  padding-left: 6px;
  letter-spacing: .04em;
  text-transform: uppercase;
  font-size: 10px;
  color: #9fb0c4;
  white-space: nowrap;
}
.jac-ux-toggle__group {
  display: flex;
  background: rgba(255, 255, 255, .1);
  border-radius: 999px;
  padding: 2px;
}
.jac-ux-toggle__btn {
  appearance: none;
  border: 0;
  cursor: pointer;
  background: transparent;
  color: #cdd8e4;
  font: inherit;
  padding: 7px 15px;
  border-radius: 999px;
  line-height: 1;
}
.jac-ux-toggle__btn:hover { color: #fff; }
.jac-ux-toggle__btn[aria-pressed="true"] {
  background: #e8b339;
  color: #0f1c2e;
}
.jac-ux-toggle__btn:focus-visible {
  outline: 2px solid #e8b339;
  outline-offset: 2px;
}
@media (max-width: 480px) {
  .jac-ux-toggle { left: 8px; bottom: 8px; padding: 6px 8px; }
  .jac-ux-toggle__label { display: none; }
}
@media print { .jac-ux-toggle { display: none !important; } }
"""

JS = """/* tighten.js — runtime half of the UX cleanup overlay, plus the Before/After
   review toggle.

   The marking pass runs once per page load in BOTH modes and only adds
   classes; CSS decides what is actually hidden. That keeps the toggle
   instant and non-destructive — the original version called .remove(), which
   cannot be undone without a reload.

   The one genuinely stateful case is the Owens Corning auto-popup (Elementor
   popup id 6576): it opens itself and locks body scroll, so it has to be
   actively closed, not just hidden. The booking form popup (id 3011) that
   Book Now / Get My Free Roof Report open on click is never touched — an
   earlier attempt removed all form-less popups and broke booking, because
   3011's form content hydrates late. */
(function () {
  "use strict";

  var OC_POPUP = "6576";      // auto-opening Owens Corning quote popup: remove
  var BOOKING_POPUP = "3011"; // booking form popup: keep, it is the money path
  var PROD_HOSTS = __PROD_HOSTS__;
  var HIDE = "jac-ux-hide";

  function on() {
    return document.documentElement.classList.contains("tighten-on");
  }

  function mark(el) {
    if (!el) return;
    (el.closest(".elementor-widget") || el).classList.add(HIDE);
  }

  /* ---- one-time marking pass -------------------------------------------- */

  function markAll() {
    // Broken Owens Corning roof-designer widgets.
    document.querySelectorAll(".oc_shingle_view").forEach(mark);

    // The OC quote popup's whole modal.
    document
      .querySelectorAll('[data-elementor-id="' + OC_POPUP + '"]')
      .forEach(function (n) {
        var modal = n.closest(".elementor-popup-modal");
        (modal || n).classList.add(HIDE);
      });

    markSocialBar();
    markRedundantCtas();
  }

  // Mobile bottom social bar: a fixed/sticky element anchored near the bottom
  // of the viewport holding social links. Identified by position rather than a
  // class because Elementor generates no stable hook for it. The site header
  // is also sticky, hence the explicit exclusion.
  function markSocialBar() {
    var vh = window.innerHeight;
    document.querySelectorAll("body *").forEach(function (el) {
      if (el.closest(".fusion-header-wrapper")) return;
      if (el.classList.contains("jac-ux-toggle")) return;
      var cs = getComputedStyle(el);
      if (cs.position !== "fixed" && cs.position !== "sticky") return;
      if (cs.display === "none") return;
      var r = el.getBoundingClientRect();
      var nearBottom = r.bottom >= vh - 5 && r.height < vh * 0.4;
      var hasSocial = el.querySelector(
        'a[href*="facebook"],a[href*="instagram"],a[href*="youtube"],' +
        'a[href*="tiktok"],a[href*="linkedin"]'
      );
      if (nearBottom && hasSocial) el.classList.add(HIDE);
    });
  }

  // Trim repeat calls-to-action in the page body only — never nav or footer.
  // Keeps the nav Book Now, the hero CTA, the service-card "Learn More" links
  // (distinct destinations), and one consultation CTA.
  function markRedundantCtas() {
    var seen = {};
    document.querySelectorAll("a.elementor-button").forEach(function (a) {
      if (a.closest("header, .fusion-header-wrapper, nav, footer")) return;
      var t = a.textContent.trim().toLowerCase().replace(/\\s+/g, " ");
      // Redundant "call now" beside another CTA — the phone is in the header.
      if (t === "call now") { mark(a); return; }
      if (t === "get my free roof report" || t === "book now") {
        seen[t] = (seen[t] || 0) + 1;
        if (seen[t] > 1) mark(a);   // keep the first/hero instance
      }
    });
  }

  /* ---- the OC popup has to be actively closed --------------------------- */

  function closeOcPopup() {
    if (!on()) return;
    var closed = false;
    document
      .querySelectorAll(
        '[data-elementor-id="' + OC_POPUP + '"], .elementor-' + OC_POPUP
      )
      .forEach(function (n) {
        var modal = n.closest(".elementor-popup-modal");
        if (!modal) return;
        modal.classList.add(HIDE);
        modal.style.setProperty("display", "none", "important");
        closed = true;
      });
    if (closed) releaseScrollLock();
  }

  // Elementor locks body scroll while a popup is open. Only release it once no
  // genuinely visible popup is left — the booking popup must keep its lock.
  function releaseScrollLock() {
    var stillOpen = [].slice
      .call(document.querySelectorAll(".elementor-popup-modal"))
      .some(function (m) {
        return !m.classList.contains(HIDE) &&
               getComputedStyle(m).display !== "none";
      });
    if (stillOpen) return;
    document.body.classList.remove("elementor-popup-modal-open");
    document.documentElement.style.overflow = "";
    document.body.style.overflow = "";
  }

  /* ---- Before/After toggle ---------------------------------------------- */

  function readMode() {
    try {
      return localStorage.getItem("jacUxMode") === "before" ? "before" : "after";
    } catch (e) {
      return "after";
    }
  }

  function applyMode(mode) {
    document.documentElement.classList.toggle("tighten-on", mode !== "before");
    try { localStorage.setItem("jacUxMode", mode); } catch (e) {}
    if (mode !== "before") {
      closeOcPopup();
    } else {
      // Returning to Before: give the page its scroll back if we took it.
      document.documentElement.style.overflow = "";
      document.body.style.overflow = "";
    }
  }

  function buildToggle() {
    if (PROD_HOSTS.indexOf(location.hostname) !== -1) return;
    if (document.querySelector(".jac-ux-toggle")) return;

    var wrap = document.createElement("div");
    wrap.className = "jac-ux-toggle";
    wrap.setAttribute("role", "group");
    wrap.setAttribute("aria-label", "UX review: compare before and after");

    var label = document.createElement("span");
    label.className = "jac-ux-toggle__label";
    label.textContent = "UX review";

    var group = document.createElement("div");
    group.className = "jac-ux-toggle__group";

    var buttons = {};
    ["before", "after"].forEach(function (mode) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "jac-ux-toggle__btn";
      b.textContent = mode === "before" ? "Before" : "After";
      b.addEventListener("click", function () {
        applyMode(mode);
        sync(mode);
      });
      group.appendChild(b);
      buttons[mode] = b;
    });

    function sync(mode) {
      buttons.before.setAttribute("aria-pressed", String(mode === "before"));
      buttons.after.setAttribute("aria-pressed", String(mode !== "before"));
    }
    sync(readMode());

    wrap.appendChild(label);
    wrap.appendChild(group);
    document.body.appendChild(wrap);
  }

  /* ---- late hydration ---------------------------------------------------- */

  // Elementor detaches both popup templates from the DOM on load and re-inserts
  // them when triggered. The DOMContentLoaded pass catches them while they are
  // still inline (classes survive the detach/re-attach), but anything injected
  // later would arrive unmarked — which is the exact failure mode that broke
  // booking the first time this overlay was attempted. Watch for it.
  function watch() {
    if (!window.MutationObserver) return;
    var pending = false;
    new MutationObserver(function (records) {
      if (pending) return;
      var relevant = records.some(function (r) {
        return [].some.call(r.addedNodes, function (n) {
          return n.nodeType === 1 && (
            n.matches(".elementor-popup-modal, .oc_shingle_view, a.elementor-button") ||
            n.querySelector(".elementor-popup-modal, .oc_shingle_view, a.elementor-button")
          );
        });
      });
      if (!relevant) return;
      pending = true;
      requestAnimationFrame(function () {
        pending = false;
        document.querySelectorAll(".oc_shingle_view").forEach(mark);
        markRedundantCtas();
        closeOcPopup();
      });
    }).observe(document.body, { childList: true, subtree: true });
  }

  /* ---- boot -------------------------------------------------------------- */

  function init() {
    markAll();
    buildToggle();
    closeOcPopup();
    watch();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
  // Elementor opens its auto-popup after load; re-check and re-mark anything
  // that hydrated late.
  window.addEventListener("load", function () {
    setTimeout(function () { markAll(); closeOcPopup(); }, 400);
    setTimeout(closeOcPopup, 1500);
  });
})();
"""


def write_assets():
    os.makedirs(ASSETS, exist_ok=True)
    hosts = "[" + ", ".join('"%s"' % h for h in PROD_HOSTS) + "]"
    with open(os.path.join(ASSETS, "tighten.css"), "w", encoding="utf-8") as f:
        f.write(CSS)
    with open(os.path.join(ASSETS, "tighten.js"), "w", encoding="utf-8") as f:
        f.write(JS.replace("__PROD_HOSTS__", hosts))


def main():
    write_assets()
    n = 0
    for root, _, files in os.walk(OUT):
        for fn in files:
            if not fn.lower().endswith((".html", ".htm")):
                continue
            p = os.path.join(root, fn)
            with open(p, encoding="utf-8") as f:
                h = f.read()
            # Only mirrored Elementor pages. Hand-authored pages (the Roofle
            # lab, the instant-quote lander) have nothing for the overlay to
            # fix, so the review toggle would just be clutter on them.
            # Match Elementor's frontend bundle, not the bare word "elementor":
            # hand-authored pages reference /uploads/elementor/ for fonts and
            # would otherwise match too.
            if ELEMENTOR_PAGE not in h:
                continue
            if MARKER in h:
                # Already injected — only keep the asset version current so
                # Cloudflare's immutable cache picks up edited CSS/JS.
                h2 = VER_RE.sub(r"\1?v=" + VER, h)
                if h2 != h:
                    with open(p, "w", encoding="utf-8") as f:
                        f.write(h2)
                    n += 1
                continue
            orig = h
            head = BOOT + "\n" + CSS_TAG
            if "</head>" in h:
                h = h.replace("</head>", head + "\n</head>", 1)
            else:
                h = head + h
            if "</body>" in h:
                h = h.replace("</body>", JS_TAG + "\n</body>", 1)
            else:
                h = h + JS_TAG
            if h != orig:
                with open(p, "w", encoding="utf-8") as f:
                    f.write(h)
                n += 1
    print(f"Overlay assets written; injected into {n} Elementor pages (v{VER})")


if __name__ == "__main__":
    main()
