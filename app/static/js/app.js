/* family.poweredby.top — UI helpers (SW lives in pwa-install.js) */
(function () {
  const menu = document.getElementById("who-menu");
  const toggle = document.getElementById("who-toggle");
  if (toggle && menu) {
    toggle.addEventListener("click", function (e) {
      e.stopPropagation();
      menu.classList.toggle("open");
    });
    document.addEventListener("click", function () {
      menu.classList.remove("open");
    });
  }
})();
