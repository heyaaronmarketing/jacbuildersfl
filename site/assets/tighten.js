/* tighten.js — runtime half of the UX cleanup overlay, plus the Before/After
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
  var PROD_HOSTS = ["www.jacbuildersfl.com", "jacbuildersfl.com"];
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
      var t = a.textContent.trim().toLowerCase().replace(/\s+/g, " ");
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
