(() => {
  const timers = document.querySelectorAll("[data-admin-lockout-countdown]");
  if (!timers.length) return;

  const format = seconds => {
    const minutes = Math.floor(seconds / 60);
    const remainder = seconds % 60;
    return `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
  };

  const update = () => {
    const now = Date.now() / 1000;
    timers.forEach(timer => {
      const remaining = Math.max(0, Math.ceil(Number(timer.dataset.until || 0) - now));
      if (remaining) {
        timer.textContent = format(remaining);
        return;
      }

      timer.hidden = true;
      const lockout = timer.closest("[data-account-lockout]");
      const state = lockout?.querySelector("[data-lockout-state]");
      if (state) {
        state.textContent = "Lockout ended; sign-in is available";
        state.classList.add("account-lockout-ended");
      }
      lockout?.querySelector("form")?.remove();
    });
  };

  update();
  window.setInterval(update, 1000);
})();
