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

  function closeSheet() {
    var overlay = document.getElementById("sheet-overlay");
    var frame = document.getElementById("sheet-frame");
    if (!overlay || overlay.hidden) return;
    overlay.hidden = true;
    if (frame) {
      frame.src = "about:blank";
      frame.hidden = true;
    }
    document.body.classList.remove("sheet-open");
  }
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeSheet();
  });
  document.addEventListener("click", function (e) {
    var overlay = document.getElementById("sheet-overlay");
    var frame = document.getElementById("sheet-frame");
    var openBtn = e.target.closest("[data-sheet]");
    if (openBtn && overlay && frame) {
      e.preventDefault();
      frame.hidden = false;
      frame.title = openBtn.getAttribute("data-sheet-title") || "Sheet";
      frame.src = openBtn.getAttribute("data-sheet") || "";
      overlay.hidden = false;
      document.body.classList.add("sheet-open");
      return;
    }
    if (overlay && !overlay.hidden && (e.target === overlay || e.target.closest("[data-sheet-close]"))) {
      closeSheet();
      return;
    }
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
