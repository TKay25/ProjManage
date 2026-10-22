/* YaVaKa — pin a ledger view as the default for this browser.

   The choice lives in localStorage rather than the database: it is a
   presentation preference, it needs no migration, and it is per device. */

(() => {
  "use strict";

  const read = (key) => {
    try {
      const raw = window.localStorage.getItem(key);
      return raw ? JSON.parse(raw) : null;
    } catch (error) {
      return null;
    }
  };

  const write = (key, value) => {
    try {
      if (value) window.localStorage.setItem(key, JSON.stringify(value));
      else window.localStorage.removeItem(key);
      return true;
    } catch (error) {
      return false;
    }
  };

  const currentView = () => {
    const params = new URLSearchParams(window.location.search);
    return {
      filter: params.get("filter") || "all",
      stage: params.get("stage") || "",
    };
  };

  const same = (a, b) => Boolean(a && b) && a.filter === b.filter && a.stage === b.stage;

  const applyPinned = (key) => {
    const saved = read(key);
    if (!saved) return;

    // A bare /app/money visit adopts the pinned view. Any explicit filter in
    // the URL wins, so a shared link is never silently rewritten.
    const params = new URLSearchParams(window.location.search);
    if (params.has("filter")) return;
    if (saved.filter === "all" && !saved.stage) return;

    params.set("filter", saved.filter);
    if (saved.stage) params.set("stage", saved.stage);
    window.location.replace(`${window.location.pathname}?${params.toString()}`);
  };

  const init = () => {
    const root = document.querySelector("[data-ledger-views]");
    if (!root) return;

    const key = root.dataset.viewKey;
    const pin = root.querySelector("[data-view-pin]");
    const label = root.querySelector("[data-view-pin-label]");
    if (!key || !pin || !label) return;

    // Only ever redirect once per rendered page, never in a loop.
    if (root.dataset.viewReady !== "1") {
      root.dataset.viewReady = "1";
      applyPinned(key);
    }

    const paint = () => {
      const pinned = same(read(key), currentView());
      pin.setAttribute("aria-pressed", pinned ? "true" : "false");
      pin.title = pinned
        ? "This view opens by default on this device"
        : "Open this view by default on this device";
      label.textContent = pinned ? "Default view" : "Pin as my default";
    };

    pin.addEventListener("click", () => {
      const now = currentView();
      write(key, same(read(key), now) ? null : now);
      paint();
    });

    paint();
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }

  // The workspace swaps page bodies, so the row is rebuilt on every visit.
  document.addEventListener("vaka:pagechange", init);
})();
