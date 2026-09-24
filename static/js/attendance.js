document.querySelectorAll("[data-fill-present]").forEach((button) => {
  button.addEventListener("click", () => {
    const form = button.closest("form");
    form.querySelectorAll('select[name^="status_"]').forEach((select) => {
      if (!select.value) select.value = "present";
    });
  });
});
