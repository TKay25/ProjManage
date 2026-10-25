/* The floating assistant. It posts one question at a time and renders the
   reply with the links it came back with, so nothing has to be hardcoded here
   about where a given answer should point. */
(() => {
  const root = document.querySelector("[data-aide]");
  if (!root) return;

  const form = root.querySelector("[data-aide-form]");
  const input = root.querySelector(".aide-input");
  const log = root.querySelector("[data-aide-log]");
  const closeButton = root.querySelector("[data-aide-close]");
  const meta = document.querySelector('meta[name="csrf-token"]');
  const token = meta ? meta.getAttribute("content") : "";

  if (!form || !input || !log) return;

  const scrollToEnd = () => {
    log.scrollTop = log.scrollHeight;
  };

  const append = (text, modifier) => {
    const line = document.createElement("p");
    line.className = "aide-said aide-said--" + modifier;
    line.textContent = text;
    log.appendChild(line);
    scrollToEnd();
    return line;
  };

  const addLinks = (host, links) => {
    if (!links || !links.length) return;
    const row = document.createElement("div");
    row.className = "aide-links";
    links.forEach(([label, href]) => {
      const link = document.createElement("a");
      link.className = "aide-link";
      link.href = href;
      link.textContent = label;
      row.appendChild(link);
    });
    host.appendChild(row);
    scrollToEnd();
  };

  let busy = false;

  const ask = async (question) => {
    if (busy || !question) return;
    busy = true;
    append(question, "me");
    const pending = append("Looking that up?", "bot aide-said--pending");

    try {
      const response = await fetch("/api/assistant/ask", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": token,
        },
        body: JSON.stringify({ question }),
      });
      const payload = await response.json().catch(() => ({}));
      pending.remove();

      if (!response.ok || !payload.ok) {
        append(payload.error || "That did not go through. Try again in a moment.", "bot");
      } else {
        const host = append(payload.reply, "bot");
        addLinks(host, payload.links);
      }
    } catch (error) {
      pending.remove();
      append("I could not reach the server. Check the connection and ask again.", "bot");
    } finally {
      busy = false;
    }
  };

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const question = input.value.trim();
    if (!question) return;
    input.value = "";
    ask(question);
  });

  root.querySelectorAll("[data-aide-ask]").forEach((chip) => {
    chip.addEventListener("click", () => ask(chip.dataset.aideAsk));
  });

  if (closeButton) {
    closeButton.addEventListener("click", () => {
      root.open = false;
      root.querySelector("summary")?.focus();
    });
  }

  root.addEventListener("toggle", () => {
    if (root.open && input && !input.disabled) {
      // Deferred so the opening animation has started and focus does not
      // scroll a window that is still growing.
      requestAnimationFrame(() => input.focus({ preventScroll: true }));
      scrollToEnd();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && root.open) {
      root.open = false;
      root.querySelector("summary")?.focus();
    }
  });
})();
