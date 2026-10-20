/* ============================================================
   Vaka — modal dialogs and AJAX form submission
   Turns page-navigation action flows into in-place dialogs.
   ============================================================ */

(() => {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  /* ---------- Toasts ---------- */

  const toastStack = () => {
    let stack = $("#toast-stack");
    if (!stack) {
      stack = document.createElement("div");
      stack.className = "toast-stack";
      stack.id = "toast-stack";
      document.body.appendChild(stack);
    }
    return stack;
  };

  const iconPath = {
    success: '<path d="M20 6 9 17l-5-5"/>',
    error: '<path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9 2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/>',
  };

  function toast(message, category = "success") {
    if (!message) return;
    const notice = document.createElement("div");
    notice.className = `notice notice-${category === "error" ? "error" : "success"}`;
    notice.setAttribute("role", "status");
    notice.innerHTML =
      `<svg class="icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" ` +
      `stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">` +
      `${iconPath[category === "error" ? "error" : "success"]}</svg>` +
      "<p></p>" +
      '<button class="notice-close" type="button" aria-label="Dismiss">&times;</button>';

    notice.querySelector("p").textContent = message;
    notice.querySelector("button").addEventListener("click", () => notice.remove());

    toastStack().appendChild(notice);
    setTimeout(() => notice.isConnected && notice.remove(), 6000);
  }

  window.vakaToast = toast;

  /* ---------- Modal controller ---------- */

  const focusStack = [];

  const openModal = (id) => {
    const dialog = document.getElementById(id);
    if (!dialog || typeof dialog.showModal !== "function") return null;

    if (!dialog.open) {
      focusStack.push(document.activeElement);
      dialog.showModal();
    }
    document.body.classList.add("modal-open");
    dialog.dispatchEvent(new CustomEvent("vaka:modalopen", { bubbles: true }));

    // Skip fields that live inside a nested (closed) dialog: focusing those
    // would pull focus out of the dialog the user actually opened.
    const marked = dialog.querySelector("[data-modal-autofocus]");
    const field = $$("input, select, textarea", dialog).find((node) => node.closest("dialog") === dialog);
    const first =
      (marked && marked.closest("dialog") === dialog ? marked : null) ||
      field ||
      dialog.querySelector("[data-modal-close]") ||
      dialog;
    setTimeout(() => {
      if (dialog.open) first.focus();
    }, 60);

    return dialog;
  };

  const closeModal = (dialog) => {
    if (!dialog) return;
    dialog.close();
    const anyOpen = $$("dialog.modal[open]").length > 0;
    if (!anyOpen) document.body.classList.remove("modal-open");
    const restore = focusStack.pop();
    if (restore && restore.isConnected) restore.focus();
  };

  const closeAll = () => {
    $$("dialog.modal[open]").forEach((dialog) => dialog.close());
    document.body.classList.remove("modal-open");
  };

  /* ---------- Remote reader ---------- */

  // Lets a list open a record without leaving the page: the link keeps a real
  // href so it still works without JavaScript.
  let readerToken = 0;

  const loadingMarkup = (label) =>
    '<div class="modal-loading" role="status">' +
    '<span class="modal-spinner" aria-hidden="true"></span>' +
    `<p>${label}</p>` +
    "</div>";

  async function openRemote(opener) {
    const dialog = document.getElementById("modal-view");
    const url = opener.dataset.modalRemote;
    if (!dialog || !url || typeof window.fetch !== "function") return;

    const body = dialog.querySelector("[data-modal-body]");
    const titleNode = dialog.querySelector("[data-modal-view-title]");
    const eyebrowNode = dialog.querySelector("[data-modal-view-eyebrow]");

    if (titleNode) titleNode.textContent = opener.dataset.modalTitle || "Loading";
    if (eyebrowNode && opener.dataset.modalEyebrow) eyebrowNode.textContent = opener.dataset.modalEyebrow;
    dialog.dataset.state = "loading";
    if (body) {
      body.setAttribute("aria-busy", "true");
      body.innerHTML = loadingMarkup("Opening");
    }
    openModal("modal-view");

    const token = ++readerToken;
    try {
      const response = await fetch(url, {
        headers: { Accept: "application/json", "X-Requested-With": "fetch" },
        credentials: "same-origin",
      });
      if (token !== readerToken) return;

      const contentType = response.headers.get("content-type") || "";
      if (!response.ok || !contentType.includes("application/json")) {
        // Session expired or an error page: fall back to a real navigation.
        closeModal(dialog);
        window.location.assign(url);
        return;
      }

      const data = await response.json();
      if (token !== readerToken) return;

      if (data.ok === false || !data.fragment) {
        if (body) body.innerHTML = '<p class="modal-empty">That record could not be opened.</p>';
        return;
      }

      if (titleNode && data.title) titleNode.textContent = data.title;
      if (body) {
        body.innerHTML = data.fragment;
        body.setAttribute("aria-busy", "false");
      }
      dialog.dataset.src = url;
      dialog.dataset.state = "ready";
      document.dispatchEvent(new CustomEvent("vaka:fragment", { detail: { root: body, opener } }));
    } catch (error) {
      if (token !== readerToken) return;
      console.error("[vaka] remote modal failed", error);
      closeModal(dialog);
      window.location.assign(url);
    }
  }

  async function refreshReader(view) {
    // Silent reload: after signing or voiding, the whole document has to agree
    // with itself, not just the panel that was patched.
    const url = view.dataset.src;
    if (!url || !view.open) return;
    try {
      const response = await fetch(url, {
        headers: { Accept: "application/json", "X-Requested-With": "fetch" },
        credentials: "same-origin",
      });
      if (!response.ok) return;
      const data = await response.json();
      const body = view.querySelector("[data-modal-body]");
      if (!data || !data.fragment || !body || !view.open) return;
      body.innerHTML = data.fragment;
      document.dispatchEvent(new CustomEvent("vaka:fragment", { detail: { root: body } }));
    } catch (error) {
      // Keep whatever is on screen; the patched fields are already correct.
      console.warn("[vaka] reader refresh failed", error);
    }
  }

  document.addEventListener("click", (event) => {
    const remote = event.target.closest("[data-modal-remote]");    if (remote) {
      event.preventDefault();
      openRemote(remote);
      return;
    }

    const opener = event.target.closest("[data-modal-open]");
    if (opener) {
      const id = opener.dataset.modalOpen;
      const dialog = document.getElementById(id);
      if (dialog) {
        event.preventDefault();
        const context = opener.dataset.modalContext;
        if (context) {
          dialog.querySelectorAll("[data-modal-context-target]").forEach((node) => {
            node.textContent = context;
          });
        }
        // data-modal-value-<field>="…" pre-fills a matching form field.
        Object.entries(opener.dataset).forEach(([key, value]) => {
          if (!key.startsWith("modalValue")) return;
          const fieldName = key.slice("modalValue".length).toLowerCase();
          dialog.querySelectorAll(`[name="${fieldName}"]`).forEach((field) => {
            if (field.type === "radio") field.checked = field.value === value;
            else if (field.type === "checkbox") field.checked = value === "true" || field.value === value;
            else field.value = value;
          });
        });
        if (opener.dataset.modalAction) {
          const form = dialog.querySelector("form[data-ajax]");
          if (form) form.action = opener.dataset.modalAction;
        }
        openModal(id);
      }
      return;
    }

    const closer = event.target.closest("[data-modal-close]");
    if (closer) {
      event.preventDefault();
      closeModal(closer.closest("dialog.modal"));
      return;
    }

    // Clicking the backdrop area (the dialog element itself) closes it.
    if (event.target.matches("dialog.modal")) {
      closeModal(event.target);
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeAll();
  });

  $$("dialog.modal").forEach((dialog) => {
    dialog.addEventListener("close", () => {
      if ($$("dialog.modal[open]").length === 0) document.body.classList.remove("modal-open");
      const form = dialog.querySelector("form[data-ajax]");
      if (form) resetForm(form);
      if (dialog.id === "modal-view") {
        const body = dialog.querySelector("[data-modal-body]");
        if (body) body.innerHTML = "";
        dialog.dataset.state = "idle";
      }
    });
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) closeModal(dialog);
    });
  });

  function resetForm(form) {
    form.reset();
    clearError(form);
    $$("[data-upload-preview]", form).forEach((preview) => {
      preview.hidden = true;
    });
    $$("[data-submit-label]", form).forEach((label) => {
      if (label.dataset.defaultLabel) label.textContent = label.dataset.defaultLabel;
    });
    form.querySelectorAll("[data-ajax-submit]").forEach((button) => {
      button.disabled = false;
    });
  }

  function clearError(form) {
    form.querySelectorAll(".form-error[data-ajax-error]").forEach((node) => node.remove());
  }

  function showError(form, message) {
    clearError(form);
    const box = document.createElement("div");
    box.className = "form-error";
    box.dataset.ajaxError = "1";
    box.setAttribute("role", "alert");
    box.innerHTML =
      '<svg class="icon" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
      'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
      iconPath.error +
      "</svg><span></span>";
    box.querySelector("span").textContent = message;
    form.prepend(box);
    box.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  /* ---------- DOM patching ---------- */

  function patch(data) {
    if (data.fields) {
      Object.entries(data.fields).forEach(([selector, value]) => {
        $$(selector).forEach((node) => {
          node.textContent = value;
          if (value && String(value).trim().startsWith("-")) node.classList.add("is-negative");
          else node.classList.remove("is-negative");
        });
      });
    }

    if (data.html) {
      Object.entries(data.html).forEach(([selector, value]) => {
        $$(selector).forEach((node) => {
          node.innerHTML = value;
        });
      });
    }

    if (!data.target) return;

    const container = $(data.target);
    if (!container) return;

    if (data.mode === "remove") {
      container.remove();
      return;
    }

    if (!data.fragment) return;

    const template = document.createElement("template");
    template.innerHTML = data.fragment.trim();
    const node = template.content.firstElementChild;
    if (!node) return;

    if (data.mode === "prepend") container.prepend(node);
    else if (data.mode === "append") container.appendChild(node);
    else if (data.mode === "innerHTML") container.innerHTML = data.fragment;
    else container.replaceWith(node);
  }

  /* ---------- AJAX form submission ---------- */

  document.addEventListener("submit", async (event) => {
    const form = event.target.closest("form[data-ajax]");
    if (!form) return;

    // A data-confirm listener may already have cancelled this submit.
    if (event.defaultPrevented) return;

    // Let the browser handle it if fetch is unavailable.
    if (typeof window.fetch !== "function") return;

    event.preventDefault();
    clearError(form);

    const submitButtons = form.querySelectorAll("[data-ajax-submit]");
    const label = form.querySelector("[data-submit-label]");
    if (label) {
      label.dataset.defaultLabel = label.dataset.defaultLabel || label.textContent;
      label.textContent = "Saving…";
    }
    submitButtons.forEach((button) => {
      button.disabled = true;
    });

    try {
      // form.method/form.action can be shadowed by controls named "method" or
      // "action", so read the attributes instead of the properties.
      const response = await fetch(form.getAttribute("action") || window.location.href, {
        method: (form.getAttribute("method") || "POST").toUpperCase(),
        body: new FormData(form),
        headers: {
          Accept: "application/json",
          "X-Requested-With": "fetch",
        },
        credentials: "same-origin",
      });

      const contentType = response.headers.get("content-type") || "";
      if (!contentType.includes("application/json")) {
        // Server answered with HTML (for example a session timeout page).
        window.location.href = response.url || "/app";
        return;
      }

      const data = await response.json();

      if (!response.ok || data.ok === false) {
        showError(form, data.message || "That did not work. Check the form and try again.");
        return;
      }

      patch(data);
      closeModal(form.closest("dialog.modal"));

      const view = document.getElementById("modal-view");
      if (view && view.open && view.contains(form)) refreshReader(view);

      toast(data.message || "Saved.", "success");

      if (data.redirect) {
        window.location.assign(data.redirect);
        return;
      }

      if (data.reload) {
        setTimeout(() => window.location.reload(), 220);
        return;
      }

      document.dispatchEvent(new CustomEvent("vaka:saved", { detail: data }));
    } catch (error) {
      console.error("[vaka] form submit failed", error);
      showError(form, "We could not save that. Check your connection and try again.");
    } finally {
      submitButtons.forEach((button) => {
        button.disabled = false;
      });
      if (label && label.dataset.defaultLabel) {
        label.textContent = label.dataset.defaultLabel;
      }
    }
  });

  /* ---------- Auto-open from query string ---------- */

  const params = new URLSearchParams(window.location.search);
  if (params.get("modal")) {
    const dialog = document.getElementById(`modal-${params.get("modal")}`);
    if (dialog) {
      openModal(dialog.id);
      params.delete("modal");
      const search = params.toString();
      window.history.replaceState({}, "", window.location.pathname + (search ? `?${search}` : "") + window.location.hash);
    }
  }

  window.vakaModal = { open: openModal, close: closeAll };
})();
