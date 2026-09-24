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

  document.querySelectorAll("[data-password-suggest]").forEach((button) => {
    button.addEventListener("click", () => {
      const form = button.closest("form");
      const firstInput = form?.querySelector("#id_password1");
      const confirmInput = form?.querySelector("#id_password2");
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
      const meetsPolicy = password.length >= 22
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

  function randomIndex(max) {
    const limit = Math.floor(0x100000000 / max) * max;
    const sample = new Uint32Array(1);
    do {
      window.crypto.getRandomValues(sample);
    } while (sample[0] >= limit);
    return sample[0] % max;
  }
})();
