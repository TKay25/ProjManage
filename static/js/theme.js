/* Applies the saved theme before first paint.

   Loaded synchronously in <head> (not deferred) so the workspace never flashes
   light and then switches to dark. Kept out of an inline <script> because the
   Content-Security-Policy allows script-src 'self' only. */

(function () {
  "use strict";

  try {
    var saved = localStorage.getItem("yavaka-theme");
    var prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    if (saved === "dark" || (!saved && prefersDark)) {
      document.documentElement.setAttribute("data-theme", "dark");
    }
  } catch (error) {
    /* Private mode or blocked storage: stay light. */
  }
})();
