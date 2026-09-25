(() => {
  const toggleButtons = document.querySelectorAll("[data-password-toggle]");

  toggleButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const input = document.getElementById(button.getAttribute("aria-controls"));
      if (!input) return;

      const reveal = input.type === "password";
      input.type = reveal ? "text" : "password";
      button.textContent = reveal ? "Hide" : "Show";
      button.setAttribute("aria-pressed", String(reveal));
    });
  });

  document.querySelectorAll("form").forEach((form) => {
    const passwordInput = form.querySelector("#id_password1, #id_new_password1");
    const strengthStatus = form.querySelector("[data-password-strength]");
    if (!passwordInput || !strengthStatus) return;

    passwordInput.addEventListener("input", () => {
      const password = passwordInput.value;
      if (!password) {
        strengthStatus.textContent = "";
        strengthStatus.removeAttribute("data-strength");
        return;
      }

      const meetsRules = password.length >= 12 && password.length <= 50
        && /[a-z]/.test(password)
        && /[A-Z]/.test(password)
        && /[0-9]/.test(password)
        && /[^A-Za-z0-9\s]/.test(password);

      strengthStatus.dataset.strength = meetsRules ? "meets-rules" : "weak";
      strengthStatus.textContent = meetsRules
        ? "Meets the portal's password rules. This demo does not check breach databases."
        : "Use 12–50 characters, including lowercase and uppercase letters, a number, and a special character. This demo does not check breach databases. Try the generated suggestion below.";
    });
  });

  document.querySelectorAll("[data-password-suggest]").forEach((button) => {
    button.addEventListener("click", () => {
      const form = button.closest("form");
      const firstInput = form?.querySelector("#id_password1, #id_new_password1");
      const confirmInput = form?.querySelector("#id_password2, #id_new_password2");
      const status = form?.querySelector("[data-password-suggestion-status]");
      if (!firstInput || !confirmInput || !status) return;

      if (!window.crypto?.getRandomValues) {
        status.textContent = "Password suggestions are unavailable in this browser. Enter your own strong password.";
        return;
      }

      const groups = [
        "abcdefghijkmnopqrstuvwxyz",
        "ABCDEFGHJKLMNPQRSTUVWXYZ",
        "23456789",
        "!@#$%&*+-=?_",
      ];
      const all = groups.join("");
      const chars = groups.map((group) => group[randomIndex(group.length)]);
      while (chars.length < 24) chars.push(all[randomIndex(all.length)]);
      for (let index = chars.length - 1; index > 0; index -= 1) {
        const other = randomIndex(index + 1);
        [chars[index], chars[other]] = [chars[other], chars[index]];
      }

      const password = chars.join("");
      const meetsPolicy = password.length >= 12 && password.length <= 50
        && /[a-z]/.test(password)
        && /[A-Z]/.test(password)
        && /[0-9]/.test(password)
        && /[^A-Za-z0-9\s]/.test(password);
      if (!meetsPolicy) {
        status.textContent = "Could not generate a password that meets every rule. Please try again.";
        return;
      }

      firstInput.value = password;
      confirmInput.value = password;
      firstInput.type = "text";
      firstInput.dispatchEvent(new Event("input", { bubbles: true }));
      confirmInput.dispatchEvent(new Event("input", { bubbles: true }));
      const firstToggle = Array.from(form.querySelectorAll("[data-password-toggle]")).find(
        (toggle) => toggle.getAttribute("aria-controls") === firstInput.id,
      );
      if (firstToggle) {
        firstToggle.textContent = "Hide";
        firstToggle.setAttribute("aria-pressed", "true");
      }
      status.textContent = "Generated a 24-character password with all four required character types. Save it somewhere private before leaving.";
      firstInput.focus();
    });
  });

  document.querySelectorAll("form[data-busy-label]").forEach((form) => {
    form.addEventListener("submit", () => {
      const submit = form.querySelector('button[type="submit"], input[type="submit"]');
      if (!submit || submit.disabled) return;
      if (submit instanceof HTMLInputElement) submit.value = form.dataset.busyLabel;
      else submit.textContent = form.dataset.busyLabel;
      submit.disabled = true;
    });
  });

  function randomIndex(max) {
    const limit = Math.floor(0x100000000 / max) * max;
    const sample = new Uint32Array(1);
    do {
      window.crypto.getRandomValues(sample);
    } while (sample[0] >= limit);
    return sample[0] % max;
  }
})();

