/* Signature pad — draws to a canvas and submits a PNG data URL.
   Works inside a closed dialog by resizing when the pad becomes visible. */

(() => {
  "use strict";

  const form = document.querySelector("[data-signature-form]");
  const pad = document.querySelector("[data-signature-pad]");
  const canvas = document.querySelector("[data-signature-canvas]");

  if (!form || !pad || !canvas) return;

  const input = form.querySelector("[data-signature-input]");
  const clearButton = form.querySelector("[data-signature-clear]");
  const context = canvas.getContext("2d");

  let drawing = false;
  let dirty = false;
  let lastWidth = 0;

  const resize = () => {
    const bounds = pad.getBoundingClientRect();
    if (bounds.width < 40) return; // Hidden (dialog closed) — wait for layout.

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
    pad.querySelector(".signature-hint")?.classList.add("is-hidden");
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
    pad.querySelector(".signature-hint")?.classList.remove("is-hidden");
  });

  form.addEventListener("submit", () => {
    if (dirty && input) input.value = canvas.toDataURL("image/png");
  });

  if (typeof ResizeObserver === "function") {
    new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width || 0;
      if (width > 0 && Math.abs(width - lastWidth) > 1) resize();
    }).observe(pad);
  } else {
    window.addEventListener("resize", resize);
  }

  resize();
})();
