(() => {
  const input = document.querySelector("input[autocomplete='one-time-code']");
  if (!input) return;

  input.addEventListener("paste", (event) => {
    const pastedText = event.clipboardData?.getData("text") || "";
    const digits = pastedText.replace(/\D/g, "").slice(0, 6);
    if (!digits) return;

    event.preventDefault();
    input.value = digits;
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
})();
