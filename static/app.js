const TEXT_EXTENSIONS = new Set(["html", "htm", "css", "js", "mjs", "json", "svg", "txt"]);

function extensionOf(name) {
  const pieces = String(name || "").toLowerCase().split(".");
  return pieces.length > 1 ? pieces.pop() : "";
}

function isTextFile(file) {
  return TEXT_EXTENSIONS.has(extensionOf(file.name));
}

function showFileMessage(message) {
  const fileList = document.getElementById("file-list");
  if (!fileList) return;
  const item = document.createElement("div");
  item.className = "selected-file";
  item.style.color = "#924848";
  item.textContent = message;
  fileList.appendChild(item);
}

function readAsText(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const content = String(reader.result || "");
      if (content.includes("\u0000")) {
        reject(new Error("binary"));
      } else {
        resolve(content);
      }
    };
    reader.onerror = () => reject(new Error("read"));
    reader.readAsText(file);
  });
}

function setupAssetEditor() {
  const form = document.querySelector(".editor-form");
  const fileInput = document.querySelector('input[type="file"][name="files"]');
  const fileList = document.getElementById("file-list");
  const editor = document.querySelector('textarea[name="html_content"]');
  const manifestInput = document.getElementById("text-files-json");
  if (!form || !fileInput || !fileList || !editor || !manifestInput) return;

  const state = new Map();
  try {
    const existing = JSON.parse(form.dataset.existingFiles || "[]");
    existing.forEach((item) => {
      if (item && item.name && typeof item.content === "string") state.set(item.name, item.content);
    });
  } catch {
    // A malformed optional manifest should not prevent manual HTML editing.
  }

  let activeName = editor.dataset.fileName || "index.html";

  const messages = [];

  function renderList() {
    fileList.innerHTML = "";
    state.forEach((content, name) => {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "selected-file";
      row.style.border = "0";
      row.style.textAlign = "left";
      row.innerHTML = `<span>${name}</span><span>${Math.ceil(new Blob([content]).size / 1024)} KB</span>`;
      row.addEventListener("click", () => {
        activeName = name;
        editor.value = state.get(name) || "";
        editor.dataset.fileName = name;
      });
      fileList.appendChild(row);
    });
    messages.forEach((message) => showFileMessage(message));
  }

  editor.addEventListener("input", () => {
    state.set(activeName, editor.value);
  });

  fileInput.addEventListener("change", async () => {
    fileList.innerHTML = "";
    messages.length = 0;
    const files = Array.from(fileInput.files || []);
    for (const file of files) {
      if (extensionOf(file.name) === "zip") {
        messages.push(`${file.name}: ZIP ko memory mein text files ke liye process kiya jayega.`);
        continue;
      }
      if (!isTextFile(file)) {
        messages.push(`${file.name}: unsupported/non-text file. Sirf HTML, CSS, JS, JSON, SVG aur TXT supported hain.`);
        continue;
      }
      try {
        const content = await readAsText(file);
        state.set(file.name, content);
        activeName = file.name;
        editor.dataset.fileName = activeName;
        editor.value = content;
      } catch {
        messages.push(`${file.name}: binary ya unreadable file, save nahi ki gayi.`);
      }
    }
    renderList();
  });

  form.addEventListener("submit", () => {
    state.set(activeName, editor.value);
    manifestInput.value = JSON.stringify(
      Array.from(state, ([name, content]) => ({ name, content })),
    );
  });

  renderList();
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-toggle-password]").forEach((button) => {
    button.addEventListener("click", () => {
      const input = document.getElementById(button.dataset.togglePassword);
      if (!input) return;
      input.type = input.type === "password" ? "text" : "password";
      button.textContent = input.type === "password" ? "Show" : "Hide";
    });
  });

  setupAssetEditor();

  const profileImageInput = document.querySelector('input[type="file"][name="profile_image"]');
  if (profileImageInput) {
    profileImageInput.addEventListener("change", () => {
      if (profileImageInput.files?.length) {
        profileImageInput.value = "";
        showFileMessage("Profile image: binary upload unsupported hai. Sirf text/code files save hoti hain.");
      }
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