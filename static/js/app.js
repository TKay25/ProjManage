/* Vaka — progressive enhancement. No framework, no build step.
   Components are mounted from data attributes, React-style. */

(() => {
  "use strict";

  const csrf = () => document.querySelector('meta[name="csrf-token"]')?.content || "";
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  /* ---------- Shell: drawer + tab bar ---------- */

  const body = document.body;
  const sidebar = $("#sidebar");

  const openDrawer = () => {
    if (!sidebar) return;
    sidebar.classList.add("is-open");
    body.classList.add("drawer-open");
  };

  const closeDrawer = () => {
    if (!sidebar) return;
    sidebar.classList.remove("is-open");
    body.classList.remove("drawer-open");
  };

  $$("[data-drawer-open]").forEach((el) => el.addEventListener("click", openDrawer));
  $$("[data-drawer-close]").forEach((el) => el.addEventListener("click", closeDrawer));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeDrawer();
  });

  /* ---------- Notices ---------- */

  const dismiss = (notice) => {
    notice.style.transition = "opacity .2s ease, transform .2s ease";
    notice.style.opacity = "0";
    notice.style.transform = "translateY(-6px)";
    setTimeout(() => notice.remove(), 220);
  };

  $$("[data-dismiss]").forEach((button) => {
    button.addEventListener("click", () => {
      const notice = button.closest(".notice");
      if (notice) dismiss(notice);
    });
  });

  $$(".toast-stack .notice").forEach((notice) => {
    setTimeout(() => {
      if (notice.isConnected) dismiss(notice);
    }, 6500);
  });

  /* ---------- Auto-submit selects ---------- */

  $$("[data-autosubmit]").forEach((select) => {
    select.addEventListener("change", () => select.form?.submit());
  });

  /* ---------- Confirmation dialogs ---------- */

  $$("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });

  /* ---------- Back buttons ---------- */

  $$("[data-back]").forEach((button) => {
    button.addEventListener("click", () => window.history.back());
  });

  /* ---------- Copy buttons ---------- */

  $$("[data-copy]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(button.dataset.copy);
        const original = button.innerHTML;
        button.innerHTML = '<svg class="icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>';
        setTimeout(() => (button.innerHTML = original), 1400);
      } catch {
        window.prompt("Copy this value:", button.dataset.copy);
      }
    });
  });

  /* ---------- Print ---------- */

  $$("[data-print]").forEach((button) => {
    button.addEventListener("click", () => window.print());
  });

  /* ---------- Money formatting & live balance ---------- */

  const parseMoney = (value) => {
    const cleaned = String(value || "").replace(/[^0-9.-]/g, "");
    const number = Number.parseFloat(cleaned);
    return Number.isFinite(number) ? number : 0;
  };

  const formatMoney = (value) =>
    value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  $$("[data-money]").forEach((input) => {
    input.addEventListener("blur", () => {
      if (String(input.value).trim() === "") return;
      input.value = formatMoney(parseMoney(input.value));
    });
    input.addEventListener("focus", () => {
      input.value = String(input.value).replace(/,/g, "");
    });
  });

  const moneyForm = $("[data-money-form]");
  if (moneyForm) {
    const amountInput = $("[data-amount]", moneyForm);
    const hint = $("[data-balance-hint]", moneyForm);
    const startingBalance = Number(moneyForm.dataset.balance || 0);
    const typeRadios = $$('input[name="type"]', moneyForm);
    const expenseOnly = $$(".expense-only", moneyForm);

    const refresh = () => {
      const type = typeRadios.find((radio) => radio.checked)?.value || "EXPENSE";
      const amount = Math.round(parseMoney(amountInput?.value) * 100);
      const nextBalance = type === "FUNDING" ? startingBalance + amount : startingBalance - amount;

      if (hint) {
        const sign = nextBalance < 0 ? "−" : "";
        hint.textContent = `Balance after this entry: ${sign}$${formatMoney(Math.abs(nextBalance) / 100)}`;
        hint.style.color = nextBalance < 0 ? "var(--brick)" : "";
      }

      expenseOnly.forEach((field) => {
        field.style.opacity = type === "FUNDING" ? "0.45" : "1";
        field.querySelectorAll("select").forEach((select) => {
          select.disabled = type === "FUNDING";
        });
      });
    };

    amountInput?.addEventListener("input", refresh);
    typeRadios.forEach((radio) => radio.addEventListener("change", refresh));
    refresh();
  }

  /* ---------- Receipt preview ---------- */

  const receiptInput = $("[data-receipt-input]");
  const preview = $("[data-upload-preview]");

  const humanSize = (bytes) => {
    if (bytes >= 1048576) return `${(bytes / 1048576).toFixed(1)}MB`;
    return `${Math.max(1, Math.round(bytes / 1024))}KB`;
  };

  if (receiptInput && preview) {
    receiptInput.addEventListener("change", () => {
      const file = receiptInput.files?.[0];
      if (!file) {
        preview.hidden = true;
        return;
      }
      $("[data-upload-name]", preview).textContent = file.name;
      $("[data-upload-size]", preview).textContent = humanSize(file.size);
      preview.hidden = false;
    });

    $("[data-upload-clear]", preview)?.addEventListener("click", () => {
      receiptInput.value = "";
      preview.hidden = true;
    });
  }

  /* ---------- Dropzone ---------- */

  $$("[data-dropzone]").forEach((zone) => {
    const input = $("[data-drop-input]", zone);
    const title = $("[data-drop-title]", zone);

    input?.addEventListener("change", () => {
      const file = input.files?.[0];
      if (file && title) title.textContent = `${file.name} · ${humanSize(file.size)}`;
    });

    ["dragenter", "dragover"].forEach((eventName) => {
      zone.addEventListener(eventName, (event) => {
        event.preventDefault();
        zone.classList.add("is-dragging");
      });
    });

    ["dragleave", "drop"].forEach((eventName) => {
      zone.addEventListener(eventName, (event) => {
        event.preventDefault();
        zone.classList.remove("is-dragging");
      });
    });

    zone.addEventListener("drop", (event) => {
      if (!input) return;
      const file = event.dataTransfer?.files?.[0];
      if (!file) return;
      input.files = event.dataTransfer.files;
      if (title) title.textContent = `${file.name} · ${humanSize(file.size)}`;
    });
  });

  /* ---------- Milestones ---------- */

  const milestones = $("[data-milestones]");
  if (milestones) {
    const totalLabel = $("[data-milestone-total]");

    const refreshTotal = () => {
      const total = $$('input[name="milestone_amount"]', milestones).reduce(
        (sum, input) => sum + parseMoney(input.value),
        0,
      );
      if (totalLabel) totalLabel.textContent = `Milestone total: $${formatMoney(total)}`;
    };

    milestones.addEventListener("input", refreshTotal);
    refreshTotal();

    $("[data-add-milestone]")?.addEventListener("click", () => {
      const row = document.createElement("div");
      row.className = "milestone-row";
      row.innerHTML =
        '<input class="input" type="text" name="milestone_label" placeholder="Another milestone" />' +
        '<input class="input" type="text" name="milestone_amount" inputmode="decimal" placeholder="0.00" data-money />';
      milestones.appendChild(row);
    });
  }

  /* ---------- PWA install ---------- */

  let installPrompt = null;
  const installButtons = $$(".install-btn, #install-btn");

  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    installPrompt = event;
    installButtons.forEach((button) => {
      button.hidden = false;
    });
  });

  installButtons.forEach((button) => {
    button.addEventListener("click", async () => {
      if (!installPrompt) {
        button.insertAdjacentHTML(
          "afterend",
          '<span class="micro-note">Open your browser menu and choose “Add to home screen”.</span>',
        );
        return;
      }
      installPrompt.prompt();
      await installPrompt.userChoice;
      installPrompt = null;
      installButtons.forEach((item) => {
        item.hidden = true;
      });
    });
  });

  window.addEventListener("appinstalled", () => {
    installButtons.forEach((button) => {
      button.hidden = true;
    });
  });

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/sw.js").catch(() => {
        /* Offline support is optional; ignore failures. */
      });
    });
  }
})();
