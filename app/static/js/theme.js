(function () {
  const grid = document.getElementById("theme-grid");
  if (!grid) return;

  function csrfToken() {
    const m = document.querySelector('meta[name="csrf-token"]');
    return m ? m.getAttribute("content") : "";
  }

  function paint(id) {
    document.documentElement.setAttribute("data-theme", id);
    const colors = { default: "#1f6a45", clean: "#111111", dark: "#0c0d0e", when99: "#008080" };
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", colors[id] || colors.default);
    grid.querySelectorAll(".theme-card").forEach(function (card) {
      card.classList.toggle("on", card.getAttribute("data-theme-id") === id);
    });
  }

  grid.addEventListener("click", function (e) {
    const card = e.target.closest("[data-theme-id]");
    if (!card) return;
    const id = card.getAttribute("data-theme-id");
    paint(id);
    fetch("/appearance/theme", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken(),
        "X-Requested-With": "fetch",
      },
      body: JSON.stringify({ theme: id }),
    }).catch(function () {});
  });
})();
