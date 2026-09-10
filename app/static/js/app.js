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

  function copyText(text, btn) {
    function done() {
      if (!btn) return;
      var old = btn.textContent;
      btn.textContent = "Copied";
      setTimeout(function () {
        btn.textContent = old;
      }, 1600);
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(function () {
        fallback();
      });
      return;
    }
    fallback();
    function fallback() {
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
        done();
      } catch (e) {}
      document.body.removeChild(ta);
    }
  }

  document.addEventListener("click", function (e) {
    var close = e.target.closest("[data-close-issued]");
    if (close) {
      var wrap = document.getElementById("issued-key");
      if (wrap) wrap.remove();
      return;
    }
    var btn = e.target.closest("[data-copy]");
    if (!btn) return;
    e.preventDefault();
    copyText(btn.getAttribute("data-copy") || "", btn);
  });
})();
