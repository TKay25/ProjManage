/* WhatsApp simulator — posts a message, renders the bot reply inline. */

(() => {
  "use strict";

  const form = document.getElementById("wa-sim-form");
  const messages = document.getElementById("wa-messages");
  const input = document.getElementById("wa-input");

  if (!form || !messages || !input) return;

  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";

  const scroll = () => {
    messages.scrollTop = messages.scrollHeight;
  };

  const bubble = (text, direction) => {
    const element = document.createElement("div");
    element.className = `wa-bubble ${direction === "IN" ? "wa-in" : "wa-out"}`;

    const paragraph = document.createElement("p");
    paragraph.textContent = text;

    const time = document.createElement("span");
    time.className = "wa-time";
    time.textContent = "just now";

    element.append(paragraph, time);
    messages.appendChild(element);
    scroll();
    return element;
  };

  const typing = () => {
    const element = document.createElement("div");
    element.className = "wa-bubble wa-out";
    element.textContent = "…";
    messages.appendChild(element);
    scroll();
    return element;
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

      bubble(data.reply, "OUT");

      if (!form.dataset.contactId && data.contact_id) {
        setTimeout(() => {
          window.location.href = `/app/whatsapp?contact=${encodeURIComponent(data.contact_id)}`;
        }, 900);
      }
    } catch {
      indicator.remove();
      bubble("Network error — the message was not sent.", "OUT");
    } finally {
      input.disabled = false;
      input.focus();
    }
  });
})();
