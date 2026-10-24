/* YaVaKa — smooth workspace navigation and page transitions. */

(() => {
  "use strict";

  const SHOW_DELAY = 140;
  const SKELETON_DELAY = 220;
  let activeRequest = null;
  let navigationId = 0;
  let progressTimer = null;
  let loaderTimer = null;
  let skeletonTimer = null;
  let leaving = false;
  let pendingPath = window.location.pathname;

  const mount = () => {
    if (document.querySelector(".page-loader")) return;
    document.body.insertAdjacentHTML(
      "beforeend",
      '<div class="page-progress" aria-hidden="true"></div>' +
        '<div class="page-loader" role="status" aria-live="polite" aria-label="Loading page">' +
        '<div class="loader-mark"><span class="loader-frame" aria-hidden="true">' +
        '<span class="loader-corner loader-corner-1"></span><span class="loader-corner loader-corner-2"></span>' +
        '<span class="loader-corner loader-corner-3"></span><span class="loader-corner loader-corner-4"></span>' +
        "</span></div>" +
        '<p class="loader-text">Loading</p></div>',
    );
  };

  const showLoader = () => {
    document.querySelector(".page-loader")?.classList.add("is-visible");
    document.querySelector(".page-progress")?.classList.add("is-active");
    document.body.classList.add("is-leaving");
    leaving = true;
  };

  const hideLoader = () => {
    clearTimeout(loaderTimer);
    document.querySelector(".page-loader")?.classList.remove("is-visible");
    document.querySelector(".page-progress")?.classList.remove("is-active");
    document.body.classList.remove("is-leaving");
    leaving = false;
  };

  const beginLoader = () => {
    if (leaving) return;
    clearTimeout(loaderTimer);
    loaderTimer = setTimeout(showLoader, SHOW_DELAY);
  };

  try {
    window.history.scrollRestoration = "manual";
  } catch (error) {
    // Some embedded browsers do not expose scrollRestoration.
  }

  const isWorkspacePath = (pathname) =>
    pathname === "/app" ||
    pathname.startsWith("/app/") ||
    pathname === "/admin" ||
    pathname.startsWith("/admin/");

  const isPlainNavigation = (event, anchor) => {
    if (!anchor || !anchor.href || event.defaultPrevented) return false;
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return false;
    if (anchor.target && anchor.target !== "_self") return false;
    if (anchor.hasAttribute("download") || anchor.dataset.noSpa === "1" || anchor.dataset.noLoader === "1") return false;
    if (anchor.hasAttribute("data-modal-open") || anchor.hasAttribute("data-modal-close")) return false;
    if (anchor.hasAttribute("data-modal-switch") || anchor.hasAttribute("data-modal-remote")) return false;

    const url = new URL(anchor.href, window.location.href);
    if (url.origin !== window.location.origin) return false;
    if (url.protocol !== "http:" && url.protocol !== "https:") return false;

    const current = new URL(window.location.href);
    return url.pathname !== current.pathname || url.search !== current.search;
  };

  const setNavigating = (active) => {
    clearTimeout(progressTimer);
    clearTimeout(skeletonTimer);
    const main = document.getElementById("main");
    if (active) {
      document.body.classList.add("is-navigating");
      main?.setAttribute("aria-busy", "true");
      progressTimer = setTimeout(() => {
        document.querySelector(".page-progress")?.classList.add("is-active");
      }, 100);
      // A slow swap gets placeholders instead of a dimmed stale page. Fast
      // swaps never reach this, so nothing flashes.
      skeletonTimer = setTimeout(showSkeleton, SKELETON_DELAY);
      return;
    }
    hideSkeleton();
    document.body.classList.remove("is-navigating");
    document.getElementById("main")?.removeAttribute("aria-busy");
    document.querySelector(".page-progress")?.classList.remove("is-active");
  };

  /* ---------- Page-shaped skeletons ----------
     Shown only when a swap is slow enough to notice. Each destination gets a
     placeholder with the same bones as the real page, so the layout does not
     jump when the response lands. */

  const HEAD =
    '<div><div class="sk sk-title"></div><div class="sk sk-sub"></div></div>';

  const kpis = (count) =>
    `<div class="sk-kpis${count === 3 ? " sk-kpis--3" : ""}">` +
    '<div class="sk sk-kpi"></div>'.repeat(count) +
    "</div>";

  const ROW =
    '<div class="sk-row">' +
    '<div class="sk sk-avatar"></div>' +
    '<div class="sk-lines">' +
    '<div class="sk sk-line"></div>' +
    '<div class="sk sk-line sk-line--short"></div>' +
    "</div>" +
    '<div class="sk sk-amount"></div>' +
    "</div>";

  const rows = (count) =>
    '<div class="sk-frame"><div class="sk-rows">' + ROW.repeat(count) + "</div></div>";

  const cards = (count, kind) =>
    '<div class="sk-grid">' + `<div class="sk ${kind}"></div>`.repeat(count) + "</div>";

  const fields = (count) =>
    '<div class="sk-frame sk-form">' +
    (
      '<div class="sk sk-field-label"></div><div class="sk sk-field"></div>'
    ).repeat(count) +
    "</div>";

  const PANEL = '<div class="sk sk-panel"></div>';
  const SIDE = '<div class="sk sk-side"></div>';

  const SKELETONS = {
    dashboard:
      HEAD +
      kpis(4) +
      `<div class="sk-body">${PANEL}${SIDE}</div>` +
      `<div class="sk-body"><div class="sk sk-panel sk-panel--short"></div>${SIDE}</div>`,
    money:
      HEAD +
      kpis(4) +
      '<div class="sk-toolbar">' +
      '<div class="sk sk-chip"></div>'.repeat(5) +
      "</div>" +
      `<div class="sk-body">${rows(5)}${SIDE}</div>`,
    attention: HEAD + kpis(3) + rows(5),
    projects: HEAD + cards(6, "sk-card"),
    project: HEAD + '<div class="sk sk-hero"></div>' + rows(5),
    documents: HEAD + cards(6, "sk-doc"),
    agreements: HEAD + rows(4) + rows(4),
    suppliers: HEAD + cards(4, "sk-card"),
    settings:
      HEAD +
      '<div class="sk-split">' +
      `<div class="sk-stack">${fields(3)}${fields(2)}</div>` +
      `<div class="sk-stack">${rows(2)}${rows(1)}</div>` +
      "</div>",
    chat:
      HEAD +
      '<div class="sk-chat">' +
      '<div class="sk sk-chat-side"></div><div class="sk sk-chat-main"></div>' +
      "</div>",
    search: HEAD + '<div class="sk sk-searchbar"></div>' + rows(4),
    admin: HEAD + kpis(4) + rows(6),
    generic: HEAD + kpis(4) + `<div class="sk-body">${PANEL}${SIDE}</div>`,
  };

  function skeletonFor(pathname) {
    if (pathname === "/app") return SKELETONS.dashboard;
    if (pathname.startsWith("/app/money")) return SKELETONS.money;
    if (pathname.startsWith("/app/attention")) return SKELETONS.attention;
    if (pathname.startsWith("/app/projects/")) return SKELETONS.project;
    if (pathname.startsWith("/app/projects")) return SKELETONS.projects;
    if (pathname.startsWith("/app/documents")) return SKELETONS.documents;
    if (pathname.startsWith("/app/reports")) return SKELETONS.money;
    if (pathname.startsWith("/app/updates")) return SKELETONS.attention;
    if (pathname.startsWith("/app/agreements")) return SKELETONS.agreements;
    if (pathname.startsWith("/app/suppliers")) return SKELETONS.suppliers;
    if (pathname.startsWith("/app/whatsapp")) return SKELETONS.chat;
    if (pathname.startsWith("/app/settings")) return SKELETONS.settings;
    if (pathname.startsWith("/app/search")) return SKELETONS.search;
    if (pathname === "/admin" || pathname.startsWith("/admin/")) return SKELETONS.admin;
    return SKELETONS.generic;
  }

  function showSkeleton() {
    const main = document.getElementById("main");
    if (!main || !document.body.classList.contains("is-navigating")) return;
    main.innerHTML =
      '<div class="skel-page" aria-hidden="true">' + skeletonFor(pendingPath) + "</div>";
    document.body.classList.add("is-skeleton");
  }

  function hideSkeleton() {
    document.body.classList.remove("is-skeleton");
  }

  const syncMeta = (parsed, selector) => {
    const next = parsed.querySelector(selector);
    const current = document.querySelector(selector);
    if (next && current) current.setAttribute("content", next.content);
  };

  const updatePage = (parsed, url) => {
    const newShell = parsed.querySelector(".shell");
    if (!newShell || !parsed.body.classList.contains("app")) return false;

    document.body.className = parsed.body.className;
    const newNodes = Array.from(parsed.body.childNodes)
      .filter((node) => node.nodeName !== "SCRIPT")
      .map((node) => document.importNode(node, true));
    document.body.replaceChildren(...newNodes);

    document.title = parsed.title;
    syncMeta(parsed, 'meta[name="csrf-token"]');
    syncMeta(parsed, 'meta[name="description"]');
    syncMeta(parsed, 'meta[property="og:title"]');

    const main = document.getElementById("main");
    document.dispatchEvent(new CustomEvent("vaka:pagechange", { detail: { url, root: main } }));
    if (main) {
      document.dispatchEvent(new CustomEvent("vaka:fragment", { detail: { root: main } }));
      const heading = main.querySelector("h1");
      if (heading) {
        heading.setAttribute("tabindex", "-1");
        heading.focus({ preventScroll: true });
      }
    }
    return true;
  };

  async function navigate(url, { push = true, scrollY = 0 } = {}) {
    activeRequest?.abort();
    const controller = new AbortController();
    activeRequest = controller;
    const requestId = ++navigationId;
    const previousScrollY = window.scrollY;
    pendingPath = url.pathname;
    setNavigating(true);

    try {
      const response = await fetch(url.href, {
        credentials: "same-origin",
        signal: controller.signal,
        headers: { Accept: "text/html" },
      });
      if (!response.ok || response.redirected) {
        window.location.assign(response.url || url.href);
        return;
      }

      const parsed = new DOMParser().parseFromString(await response.text(), "text/html");
      if (!updatePage(parsed, url)) {
        window.location.assign(response.url || url.href);
        return;
      }

      if (push) {
        window.history.replaceState(
          Object.assign({}, window.history.state, { scrollY: previousScrollY }),
          "",
          window.location.href,
        );
        window.history.pushState({ scrollY: 0 }, "", url.href);
      }

      requestAnimationFrame(() => {
        if (url.hash) {
          document.getElementById(decodeURIComponent(url.hash.slice(1)))?.scrollIntoView();
        } else {
          window.scrollTo({ top: scrollY, behavior: "auto" });
        }
      });
    } catch (error) {
      if (error.name !== "AbortError") {
        console.error("[yavaka] workspace navigation failed", error);
        window.location.assign(url.href);
      }
    } finally {
      if (requestId === navigationId) {
        activeRequest = null;
        setNavigating(false);
      }
    }
  }

  document.addEventListener("click", (event) => {
    const anchor = event.target.closest("a");
    if (!isPlainNavigation(event, anchor)) return;

    const url = new URL(anchor.href, window.location.href);
    if (isWorkspacePath(url.pathname) && anchor.closest("#sidebar, .tabbar, .palette")) {
      event.preventDefault();
      navigate(url);
      return;
    }
    beginLoader();
  });

  document.addEventListener("submit", (event) => {
    if (event.target.matches("form[data-ajax]") || event.defaultPrevented) return;
    beginLoader();
  });

  window.addEventListener("pageshow", hideLoader);
  window.addEventListener("pagehide", () => clearTimeout(loaderTimer));
  window.addEventListener("beforeunload", () => clearTimeout(loaderTimer));

  setTimeout(() => {
    if (leaving && document.readyState === "complete") hideLoader();
  }, 8000);

  document.addEventListener("DOMContentLoaded", () => {
    mount();
    hideLoader();
  });

  if (document.readyState !== "loading") mount();

  window.addEventListener("popstate", (event) => {
    const url = new URL(window.location.href);
    if (!isWorkspacePath(url.pathname)) return;
    navigate(url, { push: false, scrollY: event.state?.scrollY || 0 });
  });
})();
