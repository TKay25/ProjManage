/* YaVaKa — progressive enhancement. No framework, no build step.
   Components are mounted from data attributes, React-style. */

(() => {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  let installPrompt = null;

  function enhancePasswordField(input) {
    if (input.dataset.pwReady === "1") return;
    const parent = input.parentElement;
    if (!parent || parent.querySelector(".pw-toggle")) return;
    input.dataset.pwReady = "1";

    const wrap = document.createElement("span");
    wrap.className = "pw-field";
    parent.insertBefore(wrap, input);
    wrap.appendChild(input);

    const holder = document.createElement("span");
    holder.innerHTML = revealMarkup;
    const button = holder.firstElementChild;
    wrap.appendChild(button);

    button.addEventListener("click", () => {
      const showing = input.getAttribute("type") === "text";
      input.setAttribute("type", showing ? "password" : "text");
      button.classList.toggle("is-on", !showing);
      button.setAttribute("aria-label", showing ? "Show password" : "Hide password");
      button.setAttribute("aria-pressed", String(!showing));
      const end = input.value.length;
      input.focus();
      try {
        input.setSelectionRange(end, end);
      } catch (error) {
        /* type change can reset selection in some browsers */
      }
    });
  }

  const revealMarkup =
    '<button class="pw-toggle" type="button" aria-label="Show password" ' +
    'aria-pressed="false" tabindex="-1">' +
    '<svg class="icon pw-eye" width="17" height="17" viewBox="0 0 24 24" fill="none" ' +
    'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" ' +
    'aria-hidden="true"><path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6-10-6-10-6Z"/>' +
    '<circle cx="12" cy="12" r="3"/></svg>' +
    '<svg class="icon pw-eye-off" width="17" height="17" viewBox="0 0 24 24" fill="none" ' +
    'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" ' +
    'aria-hidden="true"><path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6-10-6-10-6Z"/>' +
    '<circle cx="12" cy="12" r="3"/><path d="m3 3 18 18"/></svg>' +
    "</button>";

  function enhancePasswords(root = document) {
    root.querySelectorAll('input[type="password"]').forEach(enhancePasswordField);
  }

  /* ---------- Theme ---------- */

  // Three modes: system, light, dark. The topbar button cycles through them in
  // the order that makes one click always do something visible.
  const themeMode = () => (window.vakaTheme ? window.vakaTheme.get() : "system");
  const themeEffective = () =>
    window.vakaTheme
      ? window.vakaTheme.effective()
      : document.documentElement.getAttribute("data-theme") === "dark"
        ? "dark"
        : "light";

  const nextTheme = () => {
    const mode = themeMode();
    if (mode === "system") return themeEffective() === "dark" ? "light" : "dark";
    return mode === "light" ? "dark" : "system";
  };

  function paintTheme() {
    const mode = themeMode();
    const next = nextTheme();
    const labels = {
      system: `Theme: follows your device. Switch to ${next}`,
      light: "Theme: light. Switch to dark",
      dark: "Theme: dark. Switch to follow your device",
    };
    $$("[data-theme-toggle]").forEach((button) => {
      button.setAttribute("aria-label", labels[mode]);
      button.title = labels[mode];
    });
    $$("[data-theme-set]").forEach((button) => {
      const on = button.dataset.themeSet === mode;
      button.classList.toggle("is-active", on);
      button.setAttribute("aria-checked", on ? "true" : "false");
    });
  }

  /* ---------- Shell: drawer + tab bar ---------- */

  function initPage() {
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
    /* ---------- Notices ---------- */

    const dismiss = (notice) => {
      if (!notice || notice.classList.contains("is-leaving")) return;
      notice.classList.add("is-leaving");
      setTimeout(() => notice.remove(), 240);
    };

    $$("[data-dismiss]").forEach((button) => {
      button.addEventListener("click", () => {
        const notice = button.closest(".notice");
        if (notice) dismiss(notice);
      });
    });

    $$(".toast-stack .notice").forEach((notice) => {
      const life = notice.dataset.tone === "error" ? 9000 : 6500;
      setTimeout(() => {
        if (notice.isConnected) dismiss(notice);
      }, life);
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

    enhancePasswords();

    /* ---------- Theme controls ---------- */

    $$("[data-theme-toggle]").forEach((button) => {
      button.addEventListener("click", () => {
        if (window.vakaTheme) window.vakaTheme.set(nextTheme());
        paintTheme();
      });
    });

    $$("[data-theme-set]").forEach((button) => {
      button.addEventListener("click", () => {
        if (window.vakaTheme) window.vakaTheme.set(button.dataset.themeSet);
        paintTheme();
      });
    });

    paintTheme();

    /* ---------- Stage picker ---------- */

    const picker = $("[data-stage-picker]");
    if (picker) {
      const boxes = $$("[data-stage-key]", picker);
      const count = $("[data-stage-count]");
      const none = $("[data-stage-none]", picker);
      const all = $("[data-stage-all]", picker);

      const refresh = () => {
        const checked = boxes.filter((box) => box.checked).length;
        if (count) count.textContent = checked;
        if (none) none.hidden = checked === 0;
      };

      boxes.forEach((box) => box.addEventListener("change", refresh));

      all?.addEventListener("click", () => {
        boxes.forEach((box) => (box.checked = true));
        refresh();
      });

      none?.addEventListener("click", () => {
        // Clearing everything would leave a project with no stages, so the
        // last one stays ticked.
        boxes.forEach((box, index) => (box.checked = index === 0));
        refresh();
      });

      // The structural work only: substructure and superstructure.
      document.querySelectorAll("[data-stage-preset='core']").forEach((button) => {
        button.addEventListener("click", () => {
          const keep = new Set([
            "land_due_diligence",
            "architectural_design",
            "plan_approval",
            "foundation",
            "superstructure",
            "ring_beam_roof",
          ]);
          boxes.forEach((box) => (box.checked = keep.has(box.value)));
          refresh();
        });
      });

      refresh();
    }

    /* ---------- PWA install ---------- */

    const installButtons = $$(".install-btn, #install-btn");

    if (installPrompt) {
      installButtons.forEach((button) => {
        button.hidden = false;
      });
    }

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

    /* ---------- Deep links that open a dialog ---------- */

    // /app/money#modal-money and friends: the palette and any shared link can
    // land on a page with the dialog already open.
    const hashId = decodeURIComponent(window.location.hash.slice(1));
    if (hashId) {
      document.querySelector(`[data-modal-open="${hashId}"]`)?.click();
    }

  }

  // Gentle scroll reveal on the public site. The class is only added when
  // IntersectionObserver exists, so content is never hidden without JS.
  const initReveal = () => {
    const targets = $$("[data-reveal]");
    if (!targets.length || !("IntersectionObserver" in window)) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    document.documentElement.classList.add("reveal-ready");
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          entry.target.classList.add("is-revealed");
          observer.unobserve(entry.target);
        });
      },
      { rootMargin: "0px 0px -12% 0px", threshold: 0.08 },
    );
    targets.forEach((target) => observer.observe(target));
  };

  // Sticky page head gets a hairline + shadow once it actually sticks.
  const syncStuckHeader = () => {
    const head = document.querySelector(".page-head");
    if (!head) return;
    head.classList.toggle("is-stuck", window.scrollY > 6);
  };
  window.addEventListener("scroll", syncStuckHeader, { passive: true });
  document.addEventListener("vaka:pagechange", syncStuckHeader);

  initPage();
  initReveal();
  syncStuckHeader();
  document.addEventListener("vaka:pagechange", initPage);
  document.addEventListener("vaka:themechange", paintTheme);
  document.addEventListener("vaka:fragment", (event) =>
    enhancePasswords((event.detail && event.detail.root) || document),
  );
  document.addEventListener("vaka:modalopen", (event) => enhancePasswords(event.target));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      const sidebar = $("#sidebar");
      sidebar?.classList.remove("is-open");
      document.body.classList.remove("drawer-open");
    }
  });
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    installPrompt = event;
    $$(".install-btn, #install-btn").forEach((button) => {
      button.hidden = false;
    });
  });
  window.addEventListener("appinstalled", () => {
    $$(".install-btn, #install-btn").forEach((button) => {
      button.hidden = true;
    });
  });
  /* First-run checklist. Dismissing is remembered on the account, so it does
     not come back on another device or after a cache clear. */
  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-onboarding-dismiss]");
    if (!button) return;
    event.preventDefault();

    const card = document.getElementById("onboarding");
    const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
    card?.classList.add("is-hiding");

    try {
      await fetch("/app/onboarding/dismiss", {
        method: "POST",
        headers: { "X-CSRF-Token": csrf, Accept: "text/html" },
        credentials: "same-origin",
      });
    } finally {
      card?.remove();
    }
  });

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/sw.js").catch(() => {
        /* Offline support is optional; ignore failures. */
      });
    });
  }
})();
