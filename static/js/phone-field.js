/* Country-aware phone inputs.

   A selector plus a local number box, combined into +<dial><number> at submit
   time. That single string is what the server already normalises into
   263771234567, so no backend change is needed.

   Prefilled values are split back into (dial code, local number) on load, so a
   saved number from any country reopens correctly. */

(() => {
  "use strict";

  const fields = Array.from(document.querySelectorAll("[data-phone-field]"));
  if (!fields.length) return;

  const digitsOnly = (value) => String(value || "").replace(/\D/g, "");

  const dialCodes = () => {
    const codes = new Set();
    fields.forEach((field) => {
      field.querySelectorAll("[data-phone-code] option").forEach((option) => {
        codes.add(option.value);
      });
    });
    return Array.from(codes).sort((a, b) => b.length - a.length);
  };

  // Longest match wins, so 263 is preferred over 2 and 26.
  const split = (raw, codes) => {
    const digits = digitsOnly(raw);
    if (!digits) return null;
    for (const code of codes) {
      if (digits.startsWith(code) && digits.length > code.length) {
        return { code, national: digits.slice(code.length) };
      }
    }
    if (digits.startsWith("0")) return { code: null, national: digits.replace(/^0+/, "") };
    return { code: null, national: digits };
  };

  const codes = dialCodes();

  const applyPlaceholder = (field) => {
    const select = field.querySelector("[data-phone-code]");
    const number = field.querySelector("[data-phone-number]");
    if (!select || !number) return;
    const option = select.selectedOptions[0];
    if (option && option.dataset.placeholder) {
      number.placeholder = option.dataset.placeholder;
    }
  };

  fields.forEach((field) => {
    const select = field.querySelector("[data-phone-code]");
    const number = field.querySelector("[data-phone-number]");
    if (!select || !number) return;

    const parsed = split(number.value, codes);
    if (parsed && parsed.code) {
      select.value = parsed.code;
      number.value = parsed.national;
    } else if (parsed && parsed.national !== digitsOnly(number.value)) {
      number.value = parsed.national;
    }
    applyPlaceholder(field);

    select.addEventListener("change", () => applyPlaceholder(field));
  });

  // Runs in the capture phase so the combined value exists before any other
  // submit handler (native or fetch-based) reads the form.
  const combine = (event) => {
    const form = event.target;
    if (!form || !form.querySelectorAll) return;
    form.querySelectorAll("[data-phone-field]").forEach((field) => {
      const select = field.querySelector("[data-phone-code]");
      const number = field.querySelector("[data-phone-number]");
      if (!select || !number) return;

      const raw = number.value.trim();
      const alreadyCombined = raw.startsWith("+");
      let digits = digitsOnly(raw);

      // A second submit (validation error, retry) must not stack dial codes:
      // strip the one we added last time before adding it again.
      if (alreadyCombined && digits.startsWith(select.value) && digits.length > select.value.length) {
        digits = digits.slice(select.value.length);
      }
      digits = digits.replace(/^0+/, "");

      number.value = digits ? `+${select.value}${digits}` : "";
    });
  };

  document.addEventListener("submit", combine, true);
})();
