/* YaVaKa — opt-in offline snapshots.

   The service worker deliberately never caches authenticated HTML. This module
   adds the one exception the user explicitly asks for: a stripped, read-only
   copy of a single project, stored in its own cache so a version bump cannot
   quietly resurrect it.

   Wiped on sign-out and whenever a different user signs in on this device. */

(() => {
  "use strict";

  const CACHE = "vaka-snapshots";
  const OWNER_KEY = "yavaka-snapshot-owner";
  const INDEX_KEY = "yavaka-snapshot-index";

  const supported = () => "caches" in window;

  const readJson = (key) => {
    try {
      return JSON.parse(window.localStorage.getItem(key) || "{}");
    } catch (error) {
      return {};
    }
  };

  const writeJson = (key, value) => {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch (error) {
      /* Private mode: the copy lives for this session only. */
    }
  };

  const readOwner = () => {
    try {
      return window.localStorage.getItem(OWNER_KEY);
    } catch (error) {
      return null;
    }
  };

  const currentUser = () => document.documentElement.dataset.userId || "anonymous";

  const clearAll = async () => {
    if (supported()) {
      try {
        await caches.delete(CACHE);
      } catch (error) {
        /* nothing to delete */
      }
    }
    try {
      window.localStorage.removeItem(OWNER_KEY);
      window.localStorage.removeItem(INDEX_KEY);
    } catch (error) {
      /* private mode */
    }
  };

  const forget = async (path) => {
    if (supported()) {
      const cache = await caches.open(CACHE);
      await cache.delete(path);
    }
    const index = readJson(INDEX_KEY);
    delete index[path];
    writeJson(INDEX_KEY, index);
  };

  const savedPaths = async () => {
    if (!supported()) return [];
    try {
      const cache = await caches.open(CACHE);
      const keys = await cache.keys();
      return keys.map((request) => new URL(request.url).pathname);
    } catch (error) {
      return [];
    }
  };

  const paint = async () => {
    const button = document.querySelector("[data-snapshot-save]");
    if (!button) return;
    const path = window.location.pathname;
    const saved = (await savedPaths()).includes(path);
    button.setAttribute("aria-pressed", saved ? "true" : "false");
    const label = button.querySelector("[data-snapshot-label]");
    if (label) label.textContent = saved ? "Update offline copy" : "Save offline copy";
    button.title = saved
      ? "This build is stored on this device for offline reading"
      : "Store a read-only copy of this build on this device";
  };

  const save = async (button) => {
    const path = window.location.pathname;
    button.disabled = true;
    try {
      const response = await fetch(`${path}/snapshot`, {
        credentials: "same-origin",
        headers: { Accept: "text/html" },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      const cache = await caches.open(CACHE);
      await cache.put(new Request(path), response.clone());

      const index = readJson(INDEX_KEY);
      const heading = document.querySelector(".page-title");
      index[path] = {
        name: (heading?.textContent || path).trim(),
        savedAt: new Date().toISOString(),
      };
      writeJson(INDEX_KEY, index);
      try {
        window.localStorage.setItem(OWNER_KEY, currentUser());
      } catch (error) {
        /* private mode */
      }

      window.vakaToast?.("Offline copy saved. It opens when you have no signal.", "success");
    } catch (error) {
      window.vakaToast?.("That copy could not be saved. Check your connection and try again.", "error");
    } finally {
      button.disabled = false;
      paint();
      renderList();
    }
  };

  const escapeHtml = (value) =>
    String(value ?? "").replace(/[&<>"']/g, (character) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    })[character]);

  const renderList = async () => {
    const root = document.querySelector("[data-offline-list]");
    if (!root) return;

    if (!supported()) {
      root.innerHTML = '<p class="muted small">This browser cannot store offline copies.</p>';
      return;
    }

    const index = readJson(INDEX_KEY);
    const paths = await savedPaths();
    if (!paths.length) {
      root.innerHTML = '<p class="muted small">No offline copies on this device.</p>';
      return;
    }

    root.innerHTML = paths
      .map((path) => {
        const entry = index[path] || {};
        const name = entry.name || path;
        const savedAt = entry.savedAt ? new Date(entry.savedAt).toLocaleDateString() : "unknown date";
        return (
          "<li><div>" +
          `<p class="mini-title">${escapeHtml(name)}</p>` +
          `<p class="mini-meta">Saved ${escapeHtml(savedAt)}</p>` +
          "</div>" +
          `<button class="btn btn-ghost btn-xs" type="button" data-offline-remove="${escapeHtml(path)}">Delete</button>` +
          "</li>"
        );
      })
      .join("");
  };

  // A different account on the same device must not see the previous user's copy.
  const enforceOwner = async () => {
    const stored = readOwner();
    const current = currentUser();
    if (stored && stored !== current) await clearAll();
  };

  const init = () => {
    paint();
    renderList();
  };

  document.addEventListener("click", (event) => {
    const saveTrigger = event.target.closest("[data-snapshot-save]");
    if (saveTrigger) {
      event.preventDefault();
      save(saveTrigger);
      return;
    }

    const removeTrigger = event.target.closest("[data-offline-remove]");
    if (removeTrigger) {
      event.preventDefault();
      forget(removeTrigger.dataset.offlineRemove).then(() => {
        renderList();
        paint();
      });
      return;
    }

    const clearTrigger = event.target.closest("[data-offline-clear]");
    if (clearTrigger) {
      event.preventDefault();
      clearAll().then(() => {
        renderList();
        paint();
        window.vakaToast?.("Offline copies deleted from this device.", "success");
      });
    }
  });

  // Clearing before the sign-out request leaves the device, so a shared machine
  // does not keep a readable project behind the login screen.
  document.addEventListener(
    "submit",
    (event) => {
      const form = event.target;
      if (!(form instanceof HTMLFormElement) || !form.matches('form[action$="/logout"]')) return;
      if (!supported()) return;
      event.preventDefault();
      clearAll()
        .catch(() => {})
        .then(() => form.submit());
    },
    true,
  );

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      enforceOwner().then(init);
    }, { once: true });
  } else {
    enforceOwner().then(init);
  }

  document.addEventListener("vaka:pagechange", init);
})();
