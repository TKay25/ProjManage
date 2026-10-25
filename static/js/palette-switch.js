/* Instant palette switching.

   The choice is applied straight to <html data-palette> so the whole page
   recolours without a reload, then saved through the existing display
   preferences endpoint. The server stores it as well, because printed
   documents cannot read localStorage. */

(() => {
  "use strict";

  const STORAGE_KEY = "vaka-palette";
  const PALETTES = ["forest", "laterite", "granite", "msasa"];

  const apply = (palette) => {
    if (!PALETTES.includes(palette)) return;
    document.documentElement.dataset.palette = palette;
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", swatchColour(palette));
  };

  // Keep the mobile browser chrome in step with the chosen palette.
  const swatchColour = (palette) => {
    const probe = document.createElement("span");
    probe.dataset.palette = palette;
    probe.style.cssText = "position:absolute;visibility:hidden";
    document.body.appendChild(probe);
    const colour = getComputedStyle(probe).getPropertyValue("--forest-700").trim();
    probe.remove();
    return colour || "#0F5D46";
  };

  // A stored choice beats the server render, so a device keeps its preference
  // even before the setting is saved.
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored && PALETTES.includes(stored)) apply(stored);
  } catch (error) {
    /* Private mode: fall back to whatever the server rendered. */
  }

  const save = async (palette) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, palette);
    } catch (error) {
      /* ignore */
    }

    const form = document.querySelector('form[action$="/app/settings/preferences"]');
    if (!form) return; // public site: local only

    const body = new FormData(form);
    body.set("palette", palette);
    try {
      await fetch(form.action, {
        method: "POST",
        body,
        headers: { "X-Requested-With": "fetch" },
        credentials: "same-origin",
      });
    } catch (error) {
      /* Offline: the local choice still applies on this device. */
    }
  };

  document.addEventListener("change", (event) => {
    const input = event.target.closest("[data-palette-choice]");
    if (!input) return;
    apply(input.value);
    save(input.value);
  });
})();
