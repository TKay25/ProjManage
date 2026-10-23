/* YaVaKa — command palette (⌘K / Ctrl+K) and global keyboard shortcuts.

   The workspace swaps the whole body on in-app navigation, so every element is
   looked up on demand rather than cached. Only document-level listeners are
   attached once. */

(() => {
  "use strict";

  const DEBOUNCE = 160;
  const MIN_CHARS = 2;

  let defaultHtml = "";
  let timer = null;
  let controller = null;
  let activeIndex = -1;

  const $dialog = () => document.getElementById("modal-palette");
  const $input = () => document.getElementById("palette-input");
  const $results = () => document.getElementById("palette-results");
  const $note = () => document.getElementById("palette-note");

  const escapeHtml = (value) =>
    String(value ?? "").replace(/[&<>"']/g, (character) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    })[character]);

  const items = () => Array.from($results()?.querySelectorAll(".palette-item") || []);
  const isOpen = () => Boolean($dialog()?.open);

  const setActive = (index) => {
    const list = items();
    if (!list.length) {
      activeIndex = -1;
      return;
    }
    activeIndex = (index + list.length) % list.length;
    list.forEach((item, position) => {
      const on = position === activeIndex;
      item.classList.toggle("is-active", on);
      item.setAttribute("aria-selected", on ? "true" : "false");
      if (on) item.scrollIntoView({ block: "nearest" });
    });
  };

  const setNote = (text) => {
    const note = $note();
    if (note) note.textContent = text;
  };

  const renderPages = () => {
    const root = $results();
    if (!root) return;
    // The first render carries both the Actions and Go to groups; keep the
    // whole thing so clearing the search restores the same list.
    if (!defaultHtml) defaultHtml = root.innerHTML;
    root.innerHTML = defaultHtml;
    setActive(0);
  };

  const renderGroups = (groups) => {
    const root = $results();
    if (!root) return;

    if (!groups.length) {
      root.innerHTML =
        '<p class="palette-empty">Nothing matched that. Try a project name, a payment or a stage.</p>';
      setActive(-1);
      return;
    }

    root.innerHTML = groups
      .map(
        (group) =>
          `<p class="palette-group-label">${escapeHtml(group.label)}</p>` +
          group.items
            .map(
              (item) =>
                `<a class="palette-item" role="option" aria-selected="false" href="${escapeHtml(item.href)}">` +
                '<span class="palette-icon">→</span>' +
                '<span class="palette-text">' +
                `<span class="palette-title">${escapeHtml(item.title)}</span>` +
                `<span class="palette-meta">${escapeHtml(item.meta || "")}</span>` +
                "</span>" +
                '<span class="palette-enter">↵</span></a>',
            )
            .join(""),
      )
      .join("");
    setActive(0);
  };

  const csrfToken = () =>
    document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || "";

  const openDialog = (id) => {
    const trigger = document.querySelector(`[data-modal-open="${id}"]`);
    if (trigger) {
      trigger.click();
      return true;
    }
    const dialog = document.getElementById(id);
    if (!dialog) return false;
    if (!dialog.open) dialog.showModal();
    document.body.classList.add("modal-open");
    return true;
  };

  const toggleDensity = async () => {
    const root = document.documentElement;
    const next = root.dataset.density === "compact" ? "comfortable" : "compact";
    root.dataset.density = next;
    close();
    try {
      await fetch("/app/settings/preferences", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
          "X-CSRF-Token": csrfToken(),
          "X-Requested-With": "fetch",
        },
        body: new URLSearchParams({ density: next }).toString(),
      });
    } catch (error) {
      /* Offline: the attribute still applies until the next page load. */
    }
  };

  const loadProjects = async () => {
    setNote("Loading projects…");
    try {
      const response = await fetch("/app/api/quick-find?group=projects", {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      renderGroups(payload.groups || []);
      setNote("Pick a build");
    } catch (error) {
      setNote("Projects unavailable — open the Projects page instead.");
    }
  };

  const runAction = (name) => {
    if (name === "new-money") {
      close();
      if (!openDialog("modal-money")) window.location.assign("/app/money#modal-money");
      return;
    }
    if (name === "new-document") {
      close();
      if (!openDialog("modal-document")) window.location.assign("/app/documents#modal-document");
      return;
    }
    if (name === "switch-project") {
      loadProjects();
      return;
    }
    if (name === "toggle-density") {
      toggleDensity();
      return;
    }
    if (name === "shortcuts") {
      close();
      openDialog("modal-shortcuts");
    }
  };

  const search = async (term) => {
    if (term.length < MIN_CHARS) {
      renderPages();
      setNote("");
      return;
    }

    controller?.abort();
    controller = new AbortController();
    setNote("Searching…");

    try {
      const response = await fetch(`/app/api/quick-find?q=${encodeURIComponent(term)}`, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      const payload = await response.json();
      const groups = payload.groups || [];
      renderGroups(groups);
      const total = groups.reduce((sum, group) => sum + group.items.length, 0);
      setNote(total ? `${total} result${total === 1 ? "" : "s"}` : "");
    } catch (error) {
      if (error.name === "AbortError") return;
      setNote("Search unavailable — open the search page instead.");
      renderPages();
    }
  };

  const open = () => {
    const dialog = $dialog();
    const input = $input();
    if (!dialog || dialog.open) return;

    if (input) input.value = "";
    renderPages();
    setNote("");
    dialog.showModal();
    document.body.classList.add("modal-open");
    input?.focus({ preventScroll: true });
  };

  const close = () => {
    const dialog = $dialog();
    if (dialog?.open) dialog.close();
    if (!document.querySelector("dialog.modal[open]")) {
      document.body.classList.remove("modal-open");
    }
  };

  const go = (href) => {
    close();
    window.location.assign(href);
  };

  document.addEventListener("click", (event) => {
    if (event.target.closest("[data-palette-open]")) {
      event.preventDefault();
      open();
      return;
    }

    const dialog = $dialog();
    if (dialog?.open && event.target === dialog) {
      close();
      return;
    }

    const action = event.target.closest("[data-palette-action]");
    if (action) {
      event.preventDefault();
      runAction(action.dataset.paletteAction);
      return;
    }

    const item = event.target.closest(".palette-item");
    if (!item?.getAttribute("href")) return;

    // Workspace routes stay with nav.js so the page swaps without a reload.
    if (!item.getAttribute("href").startsWith("/app")) {
      event.preventDefault();
      go(item.getAttribute("href"));
    }
  });

  document.addEventListener("mousemove", (event) => {
    if (!isOpen()) return;
    const item = event.target.closest(".palette-item");
    if (!item) return;
    const index = items().indexOf(item);
    if (index !== activeIndex) setActive(index);
  });

  document.addEventListener("input", (event) => {
    if (event.target.id !== "palette-input") return;
    clearTimeout(timer);
    const term = event.target.value.trim();
    timer = setTimeout(() => search(term), DEBOUNCE);
  });

  document.addEventListener("keydown", (event) => {
    if (!isOpen()) {
      const modifier = event.metaKey || event.ctrlKey;
      const element = event.target instanceof Element ? event.target : null;
      const typing = element?.closest("input, textarea, select, [contenteditable]");
      if ((modifier && event.key.toLowerCase() === "k") || (event.key === "/" && !typing)) {
        event.preventDefault();
        open();
      } else if (event.key === "?" && !typing && !modifier) {
        event.preventDefault();
        openDialog("modal-shortcuts");
      }
      return;
    }

    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive(activeIndex + 1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive(activeIndex - 1);
    } else if (event.key === "Home") {
      event.preventDefault();
      setActive(0);
    } else if (event.key === "End") {
      event.preventDefault();
      setActive(items().length - 1);
    } else if (event.key === "Enter") {
      const target = items()[activeIndex];
      if (target?.dataset.paletteAction) {
        event.preventDefault();
        runAction(target.dataset.paletteAction);
      } else if (target?.getAttribute("href")) {
        event.preventDefault();
        go(target.getAttribute("href"));
      }
    } else if (event.key === "Escape") {
      event.preventDefault();
      close();
    }
  });

  // A fresh document means fresh markup; drop the cached page list.
  document.addEventListener("vaka:pagechange", () => {
    defaultHtml = "";
    activeIndex = -1;
    close();
  });
})();
