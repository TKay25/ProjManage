/* Transfer progress for documents.

   fetch() cannot report upload progress, so an uploading form goes through
   XMLHttpRequest instead. Everything else about the response is handed back to
   modal.js, so the fragment swap, toast and close behave identically to a
   normal save.

   Downloads stream through a reader so a 20MB site video shows a percentage
   rather than a stalled spinner. */

(() => {
  "use strict";

  const csrf = () => {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute("content") : "";
  };

  const human = (bytes) => {
    if (!bytes) return "0 KB";
    if (bytes < 1024 * 1024) return Math.max(1, Math.round(bytes / 1024)) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  };

  const setBar = (root, percent, label) => {
    const bar = root.querySelector("[data-transfer-bar]");
    const text = root.querySelector("[data-transfer-label]");
    const track = root.querySelector("[data-transfer-track]");
    if (bar) bar.style.transform = "scaleX(" + Math.max(0, Math.min(100, percent)) / 100 + ")";
    if (text && label) text.textContent = label;
    if (track) track.dataset.state = percent >= 100 ? "done" : "active";
    if (track) track.setAttribute("aria-valuenow", String(Math.round(percent)));
  };

  const showProgress = (root) => {
    const form = root.querySelector("[data-transfer-form]");
    const progress = root.querySelector("[data-transfer-progress]");
    if (form) form.hidden = true;
    if (progress) progress.hidden = false;
  };

  const hideProgress = (root) => {
    const form = root.querySelector("[data-transfer-form]");
    const progress = root.querySelector("[data-transfer-progress]");
    if (form) form.hidden = false;
    if (progress) progress.hidden = true;
    setBar(root, 0, "Preparing?");
  };

  /* ---------------- Upload ---------------- */

  document.addEventListener(
    "submit",
    (event) => {
      const form = event.target.closest("form[data-upload-progress]");
      if (!form) return;
      if (typeof XMLHttpRequest !== "function") return;

      event.preventDefault();
      event.stopImmediatePropagation();

      const dialog = form.closest("dialog.modal");
      const scope = dialog || form;
      const buttons = Array.from(form.querySelectorAll("button[type='submit'], [data-ajax-submit]"));
      buttons.forEach((button) => button.setAttribute("disabled", "disabled"));
      showProgress(scope);
      setBar(scope, 0, "Starting?");

      const body = new FormData(form);
      const request = new XMLHttpRequest();
      let settled = false;

      const finish = () => {
        if (settled) return;
        settled = true;
        buttons.forEach((button) => button.removeAttribute("disabled"));
        hideProgress(scope);
      };

      request.upload.addEventListener("progress", (progressEvent) => {
        if (!progressEvent.lengthComputable) {
          setBar(scope, 35, "Uploading?");
          return;
        }
        const percent = (progressEvent.loaded / progressEvent.total) * 100;
        setBar(
          scope,
          percent,
          percent >= 100
            ? "Uploaded ? filing it?"
            : "Uploading " + human(progressEvent.loaded) + " of " + human(progressEvent.total),
        );
      });

      request.addEventListener("load", () => {
        let payload = null;
        try {
          payload = JSON.parse(request.responseText);
        } catch (error) {
          payload = null;
        }

        if (request.status >= 200 && request.status < 300 && payload && payload.ok !== false) {
          setBar(scope, 100, "Filed");
          if (window.vakaModal) {
            window.vakaModal.patch(payload);
            if (dialog) window.vakaModal.closeModal(dialog);
          }
          if (window.vakaToast && payload.message) window.vakaToast(payload.message, "success");
          document.dispatchEvent(new CustomEvent("vaka:saved", { detail: payload }));
          finish();
          return;
        }

        finish();
        const message =
          (payload && (payload.message || payload.error)) ||
          (request.status === 400
            ? "That upload was refused. Check the file type and size."
            : "The upload did not finish. Try again.");
        if (window.vakaModal && window.vakaModal.showError) {
          window.vakaModal.showError(form, message);
        } else if (window.vakaToast) {
          window.vakaToast(message, "error");
        }
      });

      request.addEventListener("error", () => {
        finish();
        const message = "The connection dropped mid-upload. Try again.";
        if (window.vakaModal && window.vakaModal.showError) window.vakaModal.showError(form, message);
        else if (window.vakaToast) window.vakaToast(message, "error");
      });

      request.open("POST", form.getAttribute("action") || window.location.href, true);
      request.setRequestHeader("Accept", "application/json");
      request.setRequestHeader("X-Requested-With", "XMLHttpRequest");
      if (csrf()) request.setRequestHeader("X-CSRF-Token", csrf());
      request.send(body);
    },
    true,
  );

  /* ---------------- Download ---------------- */

  const saveBlob = (blob, name) => {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = name || "download";
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 20000);
  };

  const nameFrom = (response, fallback) => {
    const disposition = response.headers.get("content-disposition") || "";
    const extended = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
    if (extended) {
      try {
        return decodeURIComponent(extended[1]);
      } catch (error) {
        return fallback;
      }
    }
    const plain = /filename="?([^";]+)"?/i.exec(disposition);
    return plain ? plain[1] : fallback;
  };

  document.addEventListener("click", async (event) => {
    const link = event.target.closest("[data-download]");
    if (!link) return;
    if (typeof fetch !== "function" || !window.vakaModal) return;

    const dialog = document.getElementById("modal-transfer");
    if (!dialog) return;

    event.preventDefault();

    const scope = dialog;
    const progress = scope.querySelector("[data-transfer-progress]");
    const form = scope.querySelector("[data-transfer-form]");
    if (form) form.hidden = true;
    if (progress) progress.hidden = false;
    setBar(scope, 0, "Starting?");
    window.vakaModal.open("modal-transfer");

    try {
      const response = await fetch(link.href, { credentials: "same-origin" });
      if (!response.ok) throw new Error("HTTP " + response.status);

      const total = Number(response.headers.get("content-length") || 0);
      const name = nameFrom(response, link.dataset.download || "download");

      if (!response.body || !response.body.getReader) {
        const blob = await response.blob();
        setBar(scope, 100, "Downloaded " + human(blob.size));
        saveBlob(blob, name);
        setTimeout(() => window.vakaModal.closeModal(dialog), 700);
        return;
      }

      const reader = response.body.getReader();
      const chunks = [];
      let received = 0;

      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        chunks.push(value);
        received += value.length;
        const percent = total ? (received / total) * 100 : 0;
        setBar(
          scope,
          percent,
          "Downloading " + human(received) + (total ? " of " + human(total) : ""),
        );
      }

      const blob = new Blob(chunks, {
        type: response.headers.get("content-type") || "application/octet-stream",
      });
      setBar(scope, 100, "Downloaded " + human(blob.size));
      saveBlob(blob, name);
      setTimeout(() => window.vakaModal.closeModal(dialog), 700);
    } catch (error) {
      setBar(scope, 100, "Could not download that file");
      const track = scope.querySelector("[data-transfer-track]");
      if (track) track.dataset.state = "error";
      setTimeout(() => window.vakaModal.closeModal(dialog), 1600);
    }
  });
})();
