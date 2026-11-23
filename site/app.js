"use strict";

const input = document.querySelector("[data-search]");
const items = Array.from(document.querySelectorAll("[data-image]"));
const empty = document.querySelector("[data-empty]");

if (input) {
  input.addEventListener("input", () => {
    const term = input.value.trim().toLowerCase();
    let shown = 0;
    for (const item of items) {
      const text = (item.dataset.searchText || item.textContent || "").toLowerCase();
      const match = term === "" || text.includes(term);
      item.hidden = !match;
      if (match) {
        shown += 1;
      }
    }
    if (empty) {
      empty.hidden = shown !== 0;
    }
  });
}
