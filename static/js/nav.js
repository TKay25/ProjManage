/* ============================================================
   YaVaKa — smooth navigation
   Shows a branded overlay while the next server-rendered page loads.
   The overlay is delayed slightly so instant navigations never flash.
   ============================================================ */

(() => {
  "use strict";

  const SHOW_DELAY = 140; // ms before the overlay appears
  const MARKUP = `
    <div class="page-progress" aria-hidden="true"></div>
    <div class="page-loader" role="status" aria-live="polite" aria-label="Loading page">
      <div class="loader-mark">
        <span class="loader-ring" aria-hidden="true"></span>
        <svg class="logo-mark" width="56" height="56" viewBox="0 0 64 64" role="img" aria-label="YaVaKa">
          <rect width="64" height="64" rx="15" fill="#0F5D46"/>
          <path d="M12 32 32 15l20 17" fill="none" stroke="#F7F4EF" stroke-width="4.2"
                stroke-linecap="round" stroke-linejoin="round"/>
          <rect x="17" y="34" width="5.5" height="15" rx="2.4" fill="#C8963E"/>
          <rect x="26.5" y="29" width="5.5" height="20" rx="2.4" fill="#E3B968"/>
          <rect x="36" y="24" width="5.5" height="25" rx="2.4" fill="#C8963E"/>
        </svg>
      </div>
      <p class="loader-text">Loading</p>
      <p class="loader-sub">YaVaKa · build from anywhere</p>
    </div>`;

  const mount = () => {
    if (document.querySelector(".page-loader")) return;
    document.body.insertAdjacentHTML("beforeend", MARKUP);
  };

  let timer = null;
  let leaving = false;

  const show = () => {
    const loader = document.querySelector(".page-loader");
    const bar = document.querySelector(".page-progress");
    if (loader) loader.classList.add("is-visible");
    if (bar) bar.classList.add("is-active");
    document.body.classList.add("is-leaving");
    leaving = true;
  };

  const hide = () => {
    clearTimeout(timer);
    const loader = document.querySelector(".page-loader");
    const bar = document.querySelector(".page-progress");
    if (loader) loader.classList.remove("is-visible");
    if (bar) bar.classList.remove("is-active");
    document.body.classList.remove("is-leaving");
    leaving = false;
  };

  const begin = () => {
    if (leaving) return;
    clearTimeout(timer);
    timer = setTimeout(show, SHOW_DELAY);
  };

  const sameOrigin = (url) => {
    try {
      return new URL(url, window.location.href).origin === window.location.origin;
    } catch {
      return false;
    }
  };

  const isPlainNavigation = (event, anchor) => {
    if (!anchor || !anchor.href) return false;
    if (event.defaultPrevented) return false;
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return false;
    if (anchor.target && anchor.target !== "_self") return false;
    if (anchor.hasAttribute("download")) return false;
    // Modals and other in-page actions handle their own clicks.
    if (anchor.hasAttribute("data-modal-open") || anchor.hasAttribute("data-modal-close")) return false;
    if (anchor.dataset.noLoader === "1") return false;

    const url = new URL(anchor.href, window.location.href);
    if (!sameOrigin(anchor.href)) return false;
    if (url.protocol !== "http:" && url.protocol !== "https:") return false;

    // Pure in-page anchors should not trigger the loader.
    const current = new URL(window.location.href);
    if (url.pathname === current.pathname && url.search === current.search && url.hash) return false;

    return true;
  };

  // Start the transition as early as possible, before the browser commits the load.
  document.addEventListener("click", (event) => {
    const anchor = event.target.closest("a");
    if (isPlainNavigation(event, anchor)) begin();
  });

  document.addEventListener("submit", (event) => {
    // AJAX forms keep the page; only classic form posts navigate.
    if (event.target.matches("form[data-ajax]")) return;
    if (event.defaultPrevented) return;
    begin();
  });

  // Back/forward and bfcache restores must never leave the overlay up.
  window.addEventListener("pageshow", hide);
  window.addEventListener("pagehide", () => clearTimeout(timer));
  window.addEventListener("beforeunload", () => clearTimeout(timer));

  // If something blocks the navigation (new tab, blocked request), recover.
  setTimeout(() => {
    if (leaving && document.readyState === "complete") hide();
  }, 8000);

  document.addEventListener("DOMContentLoaded", () => {
    mount();
    hide();
  });

  if (document.readyState !== "loading") {
    mount();
  }
})();
