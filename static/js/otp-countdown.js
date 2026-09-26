(() => {
  const timer = document.querySelector("[data-otp-countdown]");
  if (!timer) return;

  const codeInput = document.querySelector("[name='code']");
  const verifyButton = document.querySelector("[data-otp-verify]");
  const resendButton = document.querySelector("[data-otp-resend]");
  const resendLabel = resendButton?.dataset.idleLabel || resendButton?.textContent.trim() || "Send a new code";
  let expiresAt = Number(timer.dataset.expiresAt || 0);
  let resendAt = Number(timer.dataset.resendAt || 0);

  function format(seconds) {
    const minutes = Math.floor(seconds / 60);
    const remainder = seconds % 60;
    return `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
  }

  function tick() {
    const now = Date.now() / 1000;
    const remaining = Math.max(0, Math.ceil(expiresAt - now));
    if (remaining) {
      timer.textContent = `Code expires in ${format(remaining)}`;
    } else {
      timer.textContent = "Code expired. Request a new code to continue.";
      timer.dataset.expired = "true";
      if (codeInput) codeInput.disabled = true;
      if (verifyButton) verifyButton.disabled = true;
    }

    if (resendButton) {
      const wait = Math.max(0, Math.ceil(resendAt - now));
      resendButton.disabled = wait > 0;
      resendButton.textContent = wait > 0 ? `${resendLabel} (${wait}s)` : resendLabel;
    }
  }

  window.authShieldOtpCountdown = {
    update(nextExpiresAt, nextResendAt) {
      expiresAt = Number(nextExpiresAt || 0);
      resendAt = Number(nextResendAt || 0);
      timer.hidden = false;
      timer.dataset.expiresAt = String(expiresAt);
      timer.dataset.resendAt = String(resendAt);
      timer.dataset.expired = "false";
      if (codeInput) codeInput.disabled = false;
      tick();
    },
  };

  tick();
  window.setInterval(tick, 1000);
})();
