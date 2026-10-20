/* Signature pad - draws to a canvas and submits a PNG data URL.
   Pads can appear after load (opened in the reader dialog), so binding is
   per-element and re-runs whenever a dialog or a fragment is injected. */

(() => {
  "use strict";

  const bound = new WeakSet();
  const resizers = new WeakMap();

  function initPad(pad) {
    if (bound.has(pad)) return;

    const form = pad.closest("form");
    const canvas = pad.querySelector("[data-signature-canvas]");
    const context = canvas && canvas.getContext("2d");
    if (!form || !canvas || !context) return;

    bound.add(pad);

    const input = form.querySelector("[data-signature-input]");
    const clearButton = form.querySelector("[data-signature-clear]");
    const hint = pad.querySelector(".signature-hint");

    let drawing = false;
    let dirty = false;
    let lastWidth = 0;

    const resize = () => {
      const bounds = pad.getBoundingClientRect();
      if (bounds.width < 40) return; // Hidden (dialog closed) - wait for layout.
      if (Math.abs(bounds.width - lastWidth) < 1) return; // Already sized for this width.

      lastWidth = bounds.width;
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      const snapshot = dirty ? canvas.toDataURL() : null;

      canvas.width = Math.round(bounds.width * ratio);
      canvas.height = Math.round(bounds.height * ratio);

      context.setTransform(1, 0, 0, 1, 0, 0);
      context.scale(ratio, ratio);
      context.lineWidth = 2.1;
      context.lineCap = "round";
      context.lineJoin = "round";
      context.strokeStyle = "#10261e";

      if (snapshot) {
        const image = new Image();
        image.onload = () => context.drawImage(image, 0, 0, bounds.width, bounds.height);
        image.src = snapshot;
      }
    };

    const point = (event) => {
      const bounds = canvas.getBoundingClientRect();
      return { x: event.clientX - bounds.left, y: event.clientY - bounds.top };
    };

    const start = (event) => {
      event.preventDefault();
      drawing = true;
      const { x, y } = point(event);
      context.beginPath();
      context.moveTo(x, y);
      canvas.setPointerCapture?.(event.pointerId);
    };

    const move = (event) => {
      if (!drawing) return;
      event.preventDefault();
      const { x, y } = point(event);
      context.lineTo(x, y);
      context.stroke();
      dirty = true;
      hint?.classList.add("is-hidden");
    };

    const end = () => {
      if (!drawing) return;
      drawing = false;
      context.closePath();
    };

    canvas.addEventListener("pointerdown", start);
    canvas.addEventListener("pointermove", move);
    canvas.addEventListener("pointerup", end);
    canvas.addEventListener("pointerleave", end);
    canvas.addEventListener("pointercancel", end);

    clearButton?.addEventListener("click", () => {
      context.clearRect(0, 0, canvas.width, canvas.height);
      dirty = false;
      if (input) input.value = "";
      hint?.classList.remove("is-hidden");
    });

    form.addEventListener("submit", () => {
      if (dirty && input) input.value = canvas.toDataURL("image/png");
    });

    if (typeof ResizeObserver === "function") {
      new ResizeObserver(() => resize()).observe(pad);
    }

    // Re-measure once the pad is actually laid out.
    pad.addEventListener("pointerdown", () => {
      if (Math.abs(pad.getBoundingClientRect().width - lastWidth) > 1) resize();
    });
    window.addEventListener("resize", resize);

    resizers.set(pad, resize);
    resize();
  }

  function initAll(root) {
    const scope = root || document;
    if (scope.matches && scope.matches("[data-signature-pad]")) initPad(scope);
    scope.querySelectorAll("[data-signature-pad]").forEach(initPad);
  }

  document.addEventListener("vaka:modalopen", (event) => {
    const dialog = event.target.closest ? event.target.closest("dialog") : null;
    if (!dialog) return;
    initAll(dialog);
    // Dialogs are laid out only once opened.
    window.requestAnimationFrame(() => {
      dialog.querySelectorAll("[data-signature-pad]").forEach((pad) => {
        const resize = resizers.get(pad);
        if (resize) resize();
      });
    });
  });

  document.addEventListener("vaka:fragment", (event) => {
    initAll((event.detail && event.detail.root) || document);
  });

  initAll(document);
})();