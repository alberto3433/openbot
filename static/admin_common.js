/**
 * Admin Common JavaScript
 * Shared utility functions for admin pages
 */

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
        createTagElement(value, container, inputEl);
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
      // Use authFetch if available, otherwise fall back to fetch
      const fetchFn = typeof authFetch === "function" ? authFetch : fetch;
      const response = await fetchFn("/api/v1/admin/menu/cache/refresh", { method: "POST" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const result = await response.json();

      // Use showToast if available
      if (typeof showToast === "function") {
        showToast("Cache refreshed successfully", "success");
      } else {
        alert("Cache refreshed successfully");
      }
      console.log("Cache refresh result:", result);
    } catch (err) {
      console.error("Error refreshing cache:", err);
      if (typeof showToast === "function") {
        showToast("Failed to refresh cache", "error");
      } else {
        alert("Failed to refresh cache: " + err.message);
      }
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
