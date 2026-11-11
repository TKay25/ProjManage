/* Landing page sliders.

   Two roots share the same behaviour:
     [data-hero-gallery]  the photographic hero
     [data-hero-slider]   the product panel inside the "live look" band

   Everything is progressive enhancement. With JS off the CSS shows the first
   slide, so the page still reads correctly and the tabs are simply inert.

   Autoplay stops for good the moment somebody takes over — a tab, an arrow or
   a key press — so the page never fights the reader. It also never starts when
   the visitor has asked for reduced motion. */

(() => {
  "use strict";

  const DELAY = 7000;

  function create(root, slideSelector) {
    const slides = Array.from(root.querySelectorAll(slideSelector));
    const tabs = Array.from(root.querySelectorAll("[data-hero-go]"));
    const copies = Array.from(root.querySelectorAll("[data-hero-copy]"));
    if (slides.length < 2 || tabs.length !== slides.length) return;

    const prev = root.querySelector("[data-hero-prev]");
    const next = root.querySelector("[data-hero-next]");
    const counter = root.querySelector("[data-hero-count]");
    const status = root.querySelector("[data-hero-status]");
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");

    let index = 0;
    let timer = null;
    let hovering = false;

    const pad = (value) => String(value).padStart(2, "0");
    const label = (i) => (tabs[i]?.textContent || "").trim();

    function sync() {
      slides.forEach((slide, i) => {
        slide.classList.toggle("is-active", i === index);
      });

      /* The hero slides a matching headline with each photograph. */
      if (copies.length === slides.length) {
        copies.forEach((copy, i) => {
          copy.classList.toggle("is-active", i === index);
        });
      }

      tabs.forEach((tab, i) => {
        const active = i === index;
        tab.classList.toggle("is-active", active);
        tab.setAttribute("aria-selected", active ? "true" : "false");
        tab.tabIndex = active ? 0 : -1;
      });

      if (counter) {
        counter.textContent = `${pad(index + 1)} / ${pad(slides.length)}`;
      }
    }

    function show(target, { focusTab = false, announce = false } = {}) {
      index = (target + slides.length) % slides.length;
      sync();

      if (announce && status) status.textContent = `${label(index)} view`;
      if (focusTab) tabs[index]?.focus();
    }

    function stop() {
      if (timer) {
        window.clearInterval(timer);
        timer = null;
      }
    }

    function start() {
      stop();
      if (reduced.matches || hovering || document.hidden) return;
      timer = window.setInterval(() => show(index + 1), DELAY);
    }

    /* A manual move wins: the sweep stops for the rest of the visit. */
    function takeOver(target, options) {
      stop();
      show(target, options);
    }

    tabs.forEach((tab, i) => {
      tab.addEventListener("click", () => takeOver(i, { announce: true }));
    });

    prev?.addEventListener("click", () => takeOver(index - 1, { announce: true }));
    next?.addEventListener("click", () => takeOver(index + 1, { announce: true }));

    root.addEventListener("keydown", (event) => {
      if (event.target.closest("input, textarea, select")) return;

      if (event.key === "ArrowRight") {
        event.preventDefault();
        takeOver(index + 1, { focusTab: true, announce: true });
      } else if (event.key === "ArrowLeft") {
        event.preventDefault();
        takeOver(index - 1, { focusTab: true, announce: true });
      } else if (event.key === "Home") {
        event.preventDefault();
        takeOver(0, { focusTab: true, announce: true });
      } else if (event.key === "End") {
        event.preventDefault();
        takeOver(slides.length - 1, { focusTab: true, announce: true });
      }
    });

    /* A pointer resting on the gallery holds the current frame still. */
    root.addEventListener("pointerenter", () => {
      hovering = true;
      stop();
    });
    root.addEventListener("pointerleave", () => {
      hovering = false;
      start();
    });
    root.addEventListener("focusin", stop);
    root.addEventListener("focusout", () => {
      if (!root.contains(document.activeElement)) start();
    });

    document.addEventListener("visibilitychange", () => {
      if (document.hidden) stop();
      else start();
    });

    reduced.addEventListener?.("change", () => {
      if (reduced.matches) stop();
    });

    show(0);
    start();
  }

  document
    .querySelectorAll("[data-hero-gallery]")
    .forEach((root) => create(root, ".hero-media-slide"));

  document
    .querySelectorAll("[data-hero-slider]")
    .forEach((root) => create(root, "[data-hero-slide]"));
})();
