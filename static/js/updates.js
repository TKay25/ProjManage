/* YaVaKa — live update notifications.

   The workspace is server-rendered, so there is no socket. Instead this polls a
   tiny JSON endpoint and raises a toast the moment a build manager posts
   something, then keeps the sidebar badge in step.

   Polling backs off when the tab is hidden and stops after repeated failures,
   so a phone on a bad connection is not hammered. */

(() => {
  "use strict";

  const POLL_MS = 45000;
  const MAX_FAILURES = 3;

  let known = null; // last count the user has been told about
  let failures = 0;
  let timer = null;
  let controller = null;

  const paintBadge = (count) => {
    const link = document.querySelector('.nav-link[href="/app/updates"]');
    if (!link) return;

    let live = link.querySelector(".nav-count");
    if (!count) {
      live?.remove();
      return;
    }

    if (!live) {
      // The page was rendered while the inbox was empty, so the badge has to be
      // created here rather than only updated.
      live = document.createElement("span");
      live.className = "nav-count nav-count--live";
      link.appendChild(live);
    }
    live.textContent = count > 99 ? "99+" : String(count);
  };

  const announce = (payload) => {
    const latest = payload.latest || {};
    const where = latest.project ? ` on ${latest.project}` : "";
    const label = payload.count === 1 ? "1 new update" : `${payload.count} new updates`;
    window.vakaToast?.(
      `${label}${where}${latest.title ? ` — ${latest.title}` : ""}`,
      "info",
      { href: latest.href || "/app/updates", label: "View" },
    );
  };

  const poll = async () => {
    controller?.abort();
    controller = new AbortController();

    try {
      const response = await fetch("/app/api/updates/unread", {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      const payload = await response.json();
      failures = 0;
      paintBadge(payload.count);

      // The first answer is the baseline: never toast for work that was already
      // waiting before this page opened.
      if (known !== null && payload.count > known) announce(payload);
      known = payload.count;
      return payload;
    } catch (error) {
      if (error.name === "AbortError") return null;
      failures += 1;
      // Silent by design: a failed poll must never interrupt the user.
      if (failures >= MAX_FAILURES) stop();
      return null;
    }
  };

  const schedule = () => {
    clearInterval(timer);
    timer = setInterval(() => {
      if (document.hidden) return;
      poll();
    }, POLL_MS);
  };

  const stop = () => {
    clearInterval(timer);
    timer = null;
  };

  const start = () => {
    known = null;
    failures = 0;
    poll();
    schedule();
  };

  // Coming back to a tab is the moment a stale badge is most obvious.
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) poll();
  });

  // An in-place page swap re-renders the sidebar, so the badge reference is new
  // and the count may have moved while the user was on the previous page.
  document.addEventListener("vaka:pagechange", () => poll());

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
})();
