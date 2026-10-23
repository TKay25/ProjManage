/* Applies the saved theme before first paint.

   Loaded synchronously in <head> (not deferred) so the workspace never flashes
   light and then switches to dark. Kept out of an inline <script> because the
   Content-Security-Policy allows script-src 'self' only.

   Three modes: "system" (the default, follows the device), "light" and "dark". */

(function () {
  "use strict";

  var KEY = "yavaka-theme";
  var media = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

  function read() {
    try {
      var saved = localStorage.getItem(KEY);
      return saved === "light" || saved === "dark" || saved === "system" ? saved : "system";
    } catch (error) {
      return "system";
    }
  }

  function resolve(mode) {
    if (mode === "light" || mode === "dark") return mode;
    return media && media.matches ? "dark" : "light";
  }

  function apply(mode) {
    var root = document.documentElement;
    var effective = resolve(mode);
    if (effective === "dark") root.setAttribute("data-theme", "dark");
    else root.removeAttribute("data-theme");
    root.setAttribute("data-theme-mode", mode);
    root.style.colorScheme = effective;
  }

  function set(mode) {
    if (mode !== "light" && mode !== "dark" && mode !== "system") mode = "system";
    try {
      localStorage.setItem(KEY, mode);
    } catch (error) {
      /* private mode: the change lasts for this page only */
    }
    apply(mode);
    document.dispatchEvent(
      new CustomEvent("vaka:themechange", { detail: { mode: mode, effective: resolve(mode) } }),
    );
    return mode;
  }

  apply(read());

  if (media) {
    var onChange = function () {
      // Only follow the device while the user has not picked a side.
      if (read() === "system") apply("system");
    };
    if (media.addEventListener) media.addEventListener("change", onChange);
    else if (media.addListener) media.addListener(onChange);
  }

  window.vakaTheme = { get: read, set: set, effective: function () { return resolve(read()); } };
})();
