/**
 * Admin Common JavaScript
 * Shared utility functions for admin pages
 */

// ── Auth ────────────────────────────────────────────────────────────
let _adminAuthCredentials = null;

/**
 * Fetch wrapper that handles Basic-auth 401 challenges.
 * Caches credentials after the first successful prompt.
 * @param {string} url - URL to fetch
 * @param {object} options - fetch options
 * @returns {Promise<Response>}
 */
async function authFetch(url, options = {}) {
  let response = await fetch(url, { ...options, credentials: "include" });

  if (response.status === 401 && _adminAuthCredentials) {
    response = await fetch(url, {
      ...options,
      headers: { ...options.headers, Authorization: "Basic " + _adminAuthCredentials },
    });
  }

  if (response.status === 401) {
    const username = prompt("Admin username:");
    if (!username) throw new Error("Authentication cancelled");
    const password = prompt("Admin password:");
    if (!password) throw new Error("Authentication cancelled");

    _adminAuthCredentials = btoa(username + ":" + password);

    response = await fetch(url, {
      ...options,
      headers: { ...options.headers, Authorization: "Basic " + _adminAuthCredentials },
    });

    if (response.status === 401) {
      _adminAuthCredentials = null;
      throw new Error("Invalid credentials");
    }
  }
  return response;
}

// ── Toast ───────────────────────────────────────────────────────────

/**
 * Show a toast notification.
 * @param {string} message - Message text
 * @param {"info"|"success"|"error"} type - Toast type
 * @param {number} duration - Auto-dismiss in ms (default 3000)
 */
function showToast(message, type = "info", duration = 3000) {
  const container = document.getElementById("toastContainer");
  if (!container) return;
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  const iconName = type === "success" ? "check-circle" : type === "error" ? "x-circle" : "info";
  toast.innerHTML = `<span class="icon"><i data-lucide="${iconName}"></i></span><span>${message}</span>`;
  container.appendChild(toast);
  if (typeof lucide !== "undefined") lucide.createIcons({ nodes: [toast] });
  setTimeout(() => {
    toast.style.animation = "slideOut 0.3s ease forwards";
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

// ── Save-button state ───────────────────────────────────────────────

/**
 * Transition a save button between saving / saved / error states.
 * @param {HTMLButtonElement|null} button
 * @param {"saving"|"saved"|"error"} state
 * @param {string} originalText - Label to restore after saved/error
 */
function setSaveButtonState(button, state, originalText = "Save") {
  if (!button) return;
  switch (state) {
    case "saving":
      button.disabled = true;
      button.classList.add("saving");
      button.classList.remove("saved");
      button.textContent = "Saving...";
      break;
    case "saved":
      button.disabled = false;
      button.classList.remove("saving");
      button.classList.add("saved");
      button.textContent = "Saved!";
      setTimeout(() => {
        button.classList.remove("saved");
        button.textContent = originalText;
      }, 2000);
      break;
    case "error":
    default:
      button.disabled = false;
      button.classList.remove("saving", "saved");
      button.textContent = originalText;
  }
}

// ── Page init ───────────────────────────────────────────────────────

/**
 * One-call initialiser for every admin page:
 *   - Theme toggle (dark / light)
 *   - Active nav-link highlighting
 *   - Lucide icon rendering
 *
 * Call at the end of each page's inline <script>.
 */
function initAdminPage() {
  // Theme toggle
  const themeToggle = document.getElementById("theme-toggle");
  const themeIcon = document.getElementById("theme-icon");
  const themeText = document.getElementById("theme-text");
  const htmlEl = document.documentElement;

  function updateThemeButton(theme) {
    if (themeIcon) {
      themeIcon.innerHTML = theme === "dark"
        ? '<i data-lucide="moon"></i>'
        : '<i data-lucide="sun"></i>';
      if (typeof lucide !== "undefined") lucide.createIcons({ nodes: [themeIcon] });
    }
    if (themeText) themeText.textContent = theme === "dark" ? "Dark" : "Light";
  }

  const savedTheme = localStorage.getItem("admin_theme") || "light";
  htmlEl.setAttribute("data-theme", savedTheme);
  updateThemeButton(savedTheme);

  if (themeToggle) {
    themeToggle.addEventListener("click", () => {
      const newTheme = htmlEl.getAttribute("data-theme") === "dark" ? "light" : "dark";
      htmlEl.setAttribute("data-theme", newTheme);
      localStorage.setItem("admin_theme", newTheme);
      updateThemeButton(newTheme);
    });
  }

  // Active nav-link highlighting
  const currentPath = window.location.pathname;
  document.querySelectorAll(".app-header .nav-links a, .app-header .nav-dropdown a").forEach(link => {
    const hrefMatch = link.getAttribute("href").match(/admin_(\w+)\.html/);
    const linkPage = hrefMatch ? hrefMatch[1] : null;
    const currentMatch = currentPath.match(/\/admin-ui\/(\w+)/);
    const currentPage = currentMatch ? currentMatch[1] : null;
    if (linkPage && currentPage && linkPage === currentPage) {
      link.classList.add("active");
      const navGroup = link.closest(".nav-group");
      if (navGroup) {
        const label = navGroup.querySelector(".nav-group-label");
        if (label) label.classList.add("active");
      }
    }
  });

  // Render all Lucide icons
  if (typeof lucide !== "undefined") lucide.createIcons();
}

// ── Escape HTML ─────────────────────────────────────────────────────

/**
 * Escape HTML entities to prevent XSS
 * @param {string} text - Text to escape
 * @returns {string} Escaped HTML
 */
function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

/**
 * Create a tag element in a tag input container
 * @param {string} text - Tag text
 * @param {HTMLElement} container - Tag container element
 * @param {HTMLInputElement} inputEl - The input element
 */
function createTagElement(text, container, inputEl) {
  // Check for duplicates (case-insensitive)
  const existing = getTagValues(container);
  if (existing.some(v => v.toLowerCase() === text.toLowerCase())) {
    return false;
  }
  const tag = document.createElement("span");
  tag.className = "tag-item";
  tag.innerHTML = `<span class="tag-text">${escapeHtml(text)}</span><span class="tag-remove">&times;</span>`;
  tag.querySelector(".tag-remove").addEventListener("click", (e) => {
    e.stopPropagation();
    tag.remove();
  });
  container.insertBefore(tag, inputEl);
}

/**
 * Get all tag values from a container
 * @param {HTMLElement} container - Tag container element
 * @returns {string[]} Array of tag values
 */
function getTagValues(container) {
  return Array.from(container.querySelectorAll(".tag-text")).map(el => el.textContent);
}

/**
 * Clear all tags from a container
 * @param {HTMLElement} container - Tag container element
 * @param {HTMLInputElement} inputEl - The input element
 */
function clearTags(container, inputEl) {
  container.querySelectorAll(".tag-item").forEach(tag => tag.remove());
  inputEl.value = "";
}

/**
 * Set tags in a container from an array or comma-separated string
 * @param {HTMLElement} container - Tag container element
 * @param {HTMLInputElement} inputEl - The input element
 * @param {string[]|string} values - Array of values or comma-separated string
 */
function setTags(container, inputEl, values) {
  clearTags(container, inputEl);
  if (Array.isArray(values)) {
    values.forEach(v => createTagElement(v, container, inputEl));
  } else if (typeof values === "string" && values.trim()) {
    values.split(",").map(s => s.trim()).filter(Boolean).forEach(v => createTagElement(v, container, inputEl));
  }
}

/**
 * Setup event handlers for a tag input field
 * @param {HTMLInputElement} inputEl - The input element
 * @param {HTMLElement} container - Tag container element
 */
function setupTagInput(inputEl, container) {
  inputEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      const value = inputEl.value.trim();
      if (value) {
        const added = createTagElement(value, container, inputEl);
        if (added === false && typeof showToast === "function") {
          showToast(`"${value}" already added`, "info");
        }
        inputEl.value = "";
      }
    } else if (e.key === "Backspace" && !inputEl.value) {
      const tags = container.querySelectorAll(".tag-item");
      if (tags.length > 0) {
        tags[tags.length - 1].remove();
      }
    }
  });
  inputEl.addEventListener("blur", () => {
    const value = inputEl.value.trim();
    if (value) {
      createTagElement(value, container, inputEl);
      inputEl.value = "";
    }
  });
}

/**
 * Setup refresh cache button/link handler
 * Call this after DOMContentLoaded or include element with id="refreshCacheBtn"
 * Requires: authFetch function and showToast function to be defined
 * @param {string} buttonId - ID of the refresh element (default: "refreshCacheBtn")
 */
function setupRefreshCacheButton(buttonId = "refreshCacheBtn") {
  const btn = document.getElementById(buttonId);
  if (!btn) return;

  btn.addEventListener("click", async (e) => {
    e.preventDefault();
    const originalText = btn.textContent;
    btn.style.pointerEvents = "none";
    btn.textContent = "Refreshing...";

    try {
      const response = await authFetch("/api/v1/admin/menu/cache/refresh", { method: "POST" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const result = await response.json();
      showToast("Cache refreshed successfully", "success");
      console.log("Cache refresh result:", result);
    } catch (err) {
      console.error("Error refreshing cache:", err);
      showToast("Failed to refresh cache", "error");
    } finally {
      btn.style.pointerEvents = "";
      btn.textContent = originalText;
    }
  });
}

// Auto-initialize refresh cache button if present
document.addEventListener("DOMContentLoaded", () => {
  setupRefreshCacheButton();
});
