// Calm Slate - minimal interactions for the UI kit demo (tabs only).
// The production console is read-only; this script performs no privileged action.
(function () {
  "use strict";
  document.addEventListener("click", function (event) {
    var tab = event.target.closest("[data-cs-tab]");
    if (!tab) return;
    var group = tab.closest("[data-cs-tabs]");
    if (!group) return;

    var targetId = tab.getAttribute("data-cs-tab");
    group.querySelectorAll("[data-cs-tab]").forEach(function (t) {
      t.classList.toggle("cs-active", t === tab);
    });

    // Panels are siblings after the tab group, scoped to the same parent card.
    var container = group.parentElement;
    container.querySelectorAll(".cs-tabpanel").forEach(function (panel) {
      panel.classList.toggle("cs-active", panel.id === targetId);
    });
  });
})();
