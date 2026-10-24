/* WhatsApp simulator — posts a message, renders the bot reply inline. */

(() => {
  "use strict";

  function init(root = document) {
    const form = root.querySelector("#wa-sim-form");
    const messages = root.querySelector("#wa-messages");
    const input = root.querySelector("#wa-input");

    if (!form || !messages || !input || form.dataset.waReady === "1") return;
    form.dataset.waReady = "1";

    const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";

    const scroll = () => {
      messages.scrollTop = messages.scrollHeight;
    };

    const quickButton = (option) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "wa-quick-btn";
      button.dataset.waQuick = option;
      button.textContent = option;
      return button;
    };

    const bubble = (text, direction, suggestions = []) => {
      messages.querySelector(".wa-empty")?.remove();

      const turn = document.createElement("div");
      turn.className = `wa-turn ${direction === "IN" ? "wa-turn-in" : "wa-turn-out"}`;

      const element = document.createElement("div");
      element.className = `wa-bubble ${direction === "IN" ? "wa-in" : "wa-out"}`;

      const paragraph = document.createElement("p");
      paragraph.textContent = text;

      const time = document.createElement("span");
      time.className = "wa-time";
      time.textContent = "just now";

      element.append(paragraph, time);
      turn.appendChild(element);

      if (direction === "OUT" && suggestions.length) {
        const actions = document.createElement("div");
        actions.className = "wa-actions";
        actions.setAttribute("aria-label", "Quick replies");
        suggestions.forEach((option) => actions.appendChild(quickButton(option)));
        turn.appendChild(actions);
      }

      messages.appendChild(turn);
      scroll();
      return element;
    };

    messages.addEventListener("click", (event) => {
      const button = event.target.closest("[data-wa-quick]");
      if (!button || input.disabled) return;
      input.value = button.dataset.waQuick || "";
      form.requestSubmit();
    });

    const typing = () => {
      const element = document.createElement("div");
      element.className = "wa-bubble wa-out";
      element.textContent = "…";
      messages.appendChild(element);
      scroll();
      return element;
    };

    const refreshConversationChrome = async () => {
      try {
        const response = await fetch(window.location.href, {
          headers: { Accept: "text/html" },
          credentials: "same-origin",
        });
        if (!response.ok) return;

        const page = new DOMParser().parseFromString(await response.text(), "text/html");
        for (const selector of [".wa-contacts", ".wa-chat-head"]) {
          const fresh = page.querySelector(selector);
          const current = document.querySelector(selector);
          if (fresh && current) current.replaceWith(fresh);
        }
      } catch {
        // The conversation still works; the chrome catches up on the next visit.
      }
    };

    form.addEventListener("submit", async (event) => {
      event.preventDefault();

      const text = input.value.trim();
      if (!text) return;

      bubble(text, "IN");
      input.value = "";
      input.disabled = true;
      const indicator = typing();

      try {
        const response = await fetch("/app/whatsapp/simulate", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": csrf,
            Accept: "application/json",
          },
          body: JSON.stringify({
            body: text,
            phone: form.dataset.phone || "",
            project_id: form.dataset.projectId || "",
          }),
        });

        const data = await response.json();
        indicator.remove();

        if (!response.ok) {
          bubble(data.error || "The assistant could not process that message.", "OUT");
          return;
        }

        if (data.handoff) {
          const note = document.createElement("p");
          note.className = "wa-note";
          note.textContent = "The assistant is paused for this conversation — no automatic reply.";
          messages.appendChild(note);
          scroll();
        } else {
          bubble(data.reply, "OUT", data.quick_replies || []);
        }

        if (!form.dataset.contactId && data.contact_id) {
          // Remember the conversation in place. Reloading the page here used to
          // wipe the bubbles that had just been rendered.
          form.dataset.contactId = data.contact_id;
          window.history.replaceState(
            {},
            "",
            `/app/whatsapp?contact=${encodeURIComponent(data.contact_id)}`,
          );
          refreshConversationChrome();
        }
      } catch {
        indicator.remove();
        bubble("Network error — the message was not sent.", "OUT");
      } finally {
        input.disabled = false;
        input.focus();
      }
    });
  }

  init();
  document.addEventListener("vaka:pagechange", (event) => init(event.detail?.root || document));
})();
