/* The conversation. Sends one turn, swaps in the rendered reply.
 *
 * The server owns every word and every button — this file only carries the
 * message there and puts the answer at the bottom of the transcript. With
 * JavaScript off the same form posts and the page reloads.
 *
 * The workspace navigates in place (nav.js replaces the body and announces
 * `vaka:pagechange`), so this binds itself again on every arrival at Home.
 */
(() => {
  function init() {
    const root = document.querySelector('[data-chat]');
    if (!root || root.dataset.chatReady === 'true') return;
    root.dataset.chatReady = 'true';

    const form = root.querySelector('[data-chat-form]');
    const log = root.querySelector('[data-chat-log]');
    const input = root.querySelector('[data-chat-input]');
    const submit = root.querySelector('[data-chat-submit]');
    const starters = root.querySelector('[data-chat-starters]');
    const switcher = document.querySelector('[data-chat-switcher]');

    const csrf =
      (document.querySelector('meta[name="csrf-token"]') || {}).content ||
      (form && form.querySelector('input[name="csrf_token"]')?.value) ||
      '';

    let pending = false;

    function scrollToEnd(smooth) {
      const target = log.lastElementChild;
      if (!target) return;
      target.scrollIntoView({ block: 'end', behavior: smooth ? 'smooth' : 'auto' });
    }

    function resize() {
      if (!input) return;
      input.style.height = 'auto';
      input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
    }

    function setPending(value) {
      pending = value;
      root.classList.toggle('is-pending', value);
      if (submit) submit.disabled = value;
      if (input) input.setAttribute('aria-busy', value ? 'true' : 'false');
    }

    function append(html) {
      if (!html) return;
      const holder = document.createElement('div');
      holder.innerHTML = html;
      while (holder.firstElementChild) {
        log.appendChild(holder.firstElementChild);
      }
      scrollToEnd(true);
    }

    function showError(message) {
      const notice = document.createElement('article');
      notice.className = 'chat-msg chat-msg--assistant chat-msg--error';
      const bubble = document.createElement('div');
      bubble.className = 'chat-bubble';
      const text = document.createElement('p');
      text.className = 'chat-text';
      text.textContent = message;
      bubble.appendChild(text);
      notice.appendChild(bubble);
      log.appendChild(notice);
      scrollToEnd(true);
    }

    async function send(text, label) {
      if (pending || !text) return;
      setPending(true);
      if (starters) starters.hidden = true;
      try {
        const body = { text, csrf_token: csrf };
        if (label) body.label = label;
        const response = await fetch(form.action, {
          method: 'POST',
          headers: {
            'X-Requested-With': 'fetch',
            Accept: 'application/json',
            'X-CSRF-Token': csrf,
          },
          body: new URLSearchParams(body),
          credentials: 'same-origin',
        });
        if (!response.ok) {
          let detail = 'I could not send that. Check your connection and try again.';
          try {
            const failure = await response.json();
            if (failure && failure.message) detail = failure.message;
          } catch (error) {
            /* keep the plain message */
          }
          showError(detail);
          return;
        }
        const result = await response.json();
        append(result.html);
      } catch (error) {
        showError('I could not reach the server. Your message was not sent.');
      } finally {
        setPending(false);
        if (input) input.focus();
      }
    }

    if (form) {
      form.addEventListener('submit', (event) => {
        event.preventDefault();
        const text = (input?.value || '').trim();
        if (!text) return;
        input.value = '';
        resize();
        send(text);
      });
    }

    if (input) {
      input.addEventListener('input', resize);
      input.addEventListener('keydown', (event) => {
        // Enter sends; Shift+Enter is a new line, which is what a keyboard expects.
        if (event.key === 'Enter' && !event.shiftKey) {
          event.preventDefault();
          if (form.requestSubmit) form.requestSubmit();
          else form.dispatchEvent(new Event('submit', { cancelable: true }));
        }
      });
      resize();
    }

    root.addEventListener('click', (event) => {
      const button = event.target.closest('[data-chat-send]');
      if (!button) return;
      event.preventDefault();
      const value = button.getAttribute('data-chat-send') || button.textContent.trim();
      send(value, button.textContent.trim());
    });

    if (switcher) {
      const select = switcher.querySelector('[data-chat-project]');
      select?.addEventListener('change', async () => {
        setPending(true);
        try {
          const response = await fetch(switcher.action, {
            method: 'POST',
            headers: {
              'X-Requested-With': 'fetch',
              Accept: 'application/json',
              'X-CSRF-Token': csrf,
            },
            body: new URLSearchParams({ project: select.value, csrf_token: csrf }),
            credentials: 'same-origin',
          });
          const payload = await response.json();
          if (payload.ok) append(payload.html);
        } catch (error) {
          showError('I could not switch build. Try again.');
        } finally {
          setPending(false);
        }
      });
    }

    scrollToEnd(false);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }

  document.addEventListener('vaka:pagechange', init);
})();
