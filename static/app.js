document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-toggle-password]").forEach((button) => {
    button.addEventListener("click", () => {
      const input = document.getElementById(button.dataset.togglePassword);
      if (!input) return;
      input.type = input.type === "password" ? "text" : "password";
      button.textContent = input.type === "password" ? "Show" : "Hide";
    });
  });

  const fileInput = document.querySelector('input[type="file"][name="files"]');
  const fileList = document.getElementById("file-list");
  if (fileInput && fileList) {
    fileInput.addEventListener("change", () => {
      fileList.innerHTML = Array.from(fileInput.files).map((file) =>
        `<div class="selected-file"><span>${file.name}</span><span>${Math.ceil(file.size / 1024)} KB</span></div>`
      ).join("");
    });
  }

  document.querySelectorAll("[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });

  document.querySelectorAll(".copy-button").forEach((button) => {
    button.addEventListener("click", async () => {
      const input = document.getElementById(button.dataset.copyTarget);
      if (!input) return;
      try {
        await navigator.clipboard.writeText(input.value);
        const original = button.textContent;
        button.textContent = "Copied";
        setTimeout(() => { button.textContent = original; }, 1500);
      } catch {
        input.select();
        document.execCommand("copy");
      }
    });
  });

  setTimeout(() => {
    document.querySelectorAll(".flash").forEach((flash) => {
      flash.style.opacity = "0";
      flash.style.transition = "opacity .3s";
      setTimeout(() => flash.remove(), 350);
    });
  }, 4500);
});
