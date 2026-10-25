/* Public site header: scroll state, section highlighting and the phone menu.
   Everything here is an enhancement — with JS off the links still navigate. */

(() => {
  "use strict";

  const header = document.getElementById("site-header");
  if (!header) return;

  const toggle = header.querySelector(".site-menu-toggle");
  const menu = header.querySelector("#site-menu");
  const links = Array.from(header.querySelectorAll(".site-nav-link[data-spy]"));

  /* ---------- Scroll state ---------- */
  let ticking = false;

  const syncScrollState = () => {
    header.classList.toggle("is-scrolled", window.scrollY > 8);

    // Drive the header progress hairline. A CSS variable keeps this to one
    // style write per frame; the bar itself is scaled with transform, so the
    // browser never re-lays-out the header.
    const scrollable =
      document.documentElement.scrollHeight - window.innerHeight;
    const progress = scrollable > 0 ? Math.min(window.scrollY / scrollable, 1) : 0;
    header.style.setProperty("--scroll-progress", progress.toFixed(4));

    ticking = false;
  };

  window.addEventListener(
    "scroll",
    () => {
      if (ticking) return;
      ticking = true;
      window.requestAnimationFrame(syncScrollState);
    },
    { passive: true },
  );
  syncScrollState();

  /* ---------- Section highlighting ---------- */
  const sections = links
    .map((link) => {
      const id = link.dataset.spy;
      const section = id ? document.getElementById(id) : null;
      return section ? { link, section } : null;
    })
    .filter(Boolean);

  const setActive = (activeId) => {
    sections.forEach(({ link, section }) => {
      const on = section.id === activeId;
      link.classList.toggle("is-active", on);
      if (on) {
        link.setAttribute("aria-current", "true");
      } else {
        link.removeAttribute("aria-current");
      }
    });
  };

  if (sections.length && "IntersectionObserver" in window) {
    // The viewport band sits below the header, so a section is "current" once
    // its top crosses the upper third of the screen.
    const visible = new Map();

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          visible.set(entry.target.id, entry.isIntersecting ? entry.intersectionRatio : 0);
        });

        let bestId = null;
        let bestRatio = 0;
        visible.forEach((ratio, id) => {
          if (ratio > bestRatio) {
            bestRatio = ratio;
            bestId = id;
          }
        });
        setActive(bestId);
      },
      { rootMargin: "-88px 0px -55% 0px", threshold: [0, 0.15, 0.4, 0.75] },
    );

    sections.forEach(({ section }) => observer.observe(section));
  }

  /* ---------- Phone menu ---------- */
  const closeMenu = () => {
    if (!menu || menu.hidden) return;
    menu.hidden = true;
    toggle?.setAttribute("aria-expanded", "false");
    toggle?.setAttribute("aria-label", "Open menu");
  };

  const openMenu = () => {
    if (!menu) return;
    menu.hidden = false;
    toggle?.setAttribute("aria-expanded", "true");
    toggle?.setAttribute("aria-label", "Close menu");
  };

  toggle?.addEventListener("click", () => {
    if (menu?.hidden) {
      openMenu();
    } else {
      closeMenu();
    }
  });

  // A link tap should close the drawer; the browser handles the navigation.
  menu?.addEventListener("click", (event) => {
    if (event.target.closest("a")) closeMenu();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeMenu();
  });

  // Returning to a wide window must not leave a hidden-but-open drawer behind.
  window.addEventListener("resize", () => {
    if (window.innerWidth > 900) closeMenu();
  });

  document.addEventListener("click", (event) => {
    if (!menu || menu.hidden) return;
    if (header.contains(event.target)) return;
    closeMenu();
  });
})();
