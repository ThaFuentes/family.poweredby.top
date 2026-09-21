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
  const moreBtn = document.getElementById("nav-more");
  const moreSheet = document.getElementById("more-sheet");
  if (moreBtn && moreSheet) {
    moreBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      const on = moreSheet.hidden;
      moreSheet.hidden = !on;
      moreBtn.setAttribute("aria-expanded", on ? "true" : "false");
    });
    document.addEventListener("click", function (e) {
      if (e.target.closest("#more-sheet, #nav-more")) return;
      moreSheet.hidden = true;
      moreBtn.setAttribute("aria-expanded", "false");
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

  var sheetDirty = false;
  function closeSheet() {
    var overlay = document.getElementById("sheet-overlay");
    var frame = document.getElementById("sheet-frame");
    var reload = sheetDirty;
    sheetDirty = false;
    if (!overlay || overlay.hidden) return;
    overlay.hidden = true;
    if (frame) {
      frame.src = "about:blank";
      frame.hidden = true;
    }
    document.body.classList.remove("sheet-open");
    if (
      reload &&
      (location.pathname.indexOf("/items/") === 0 ||
        location.pathname.indexOf("/vault") === 0 ||
        location.pathname.indexOf("/groceries") === 0 ||
        location.pathname === "/" ||
        location.pathname.indexOf("/home") === 0)
    ) {
      location.reload();
    }
  }
  window.addEventListener("message", function (e) {
    if (!e.data || e.data.family !== "sheet-saved") return;
    sheetDirty = true;
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeSheet();
  });
  (function () {
    var grab = document.getElementById("sheet-grab");
    var panel = document.querySelector(".sheet-panel");
    if (!grab || !panel) return;
    var startY = 0;
    function onStart(e) {
      var t = e.touches ? e.touches[0] : e;
      startY = t.clientY;
    }
    function onMove(e) {
      if (!startY) return;
      var t = e.touches ? e.touches[0] : e;
      var dy = t.clientY - startY;
      if (dy > 0) panel.style.transform = "translateY(" + Math.min(dy, 280) + "px)";
    }
    function onEnd(e) {
      var t = (e.changedTouches && e.changedTouches[0]) || e;
      var dy = t.clientY - startY;
      startY = 0;
      panel.style.transform = "";
      if (dy > 90) closeSheet();
    }
    grab.addEventListener("touchstart", onStart, { passive: true });
    grab.addEventListener("touchmove", onMove, { passive: true });
    grab.addEventListener("touchend", onEnd);
  })();
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
    if (btn) {
      e.preventDefault();
      copyText(btn.getAttribute("data-copy") || "", btn);
      return;
    }
    var reveal = e.target.closest("[data-reveal]");
    if (reveal) {
      e.preventDefault();
      var target = document.querySelector(reveal.getAttribute("data-reveal") || "");
      if (!target) return;
      var hide = target.getAttribute("type") === "password";
      target.setAttribute("type", hide ? "text" : "password");
      reveal.textContent = hide ? "Hide" : "Show";
      return;
    }
    var deltaBtn = e.target.closest("[data-qty-delta]");
    if (deltaBtn) {
      e.preventDefault();
      e.stopPropagation();
      bumpQty(deltaBtn);
      return;
    }
    var listBtn = e.target.closest("[data-list-item]");
    if (listBtn) {
      e.preventDefault();
      e.stopPropagation();
      putOnList(listBtn);
      return;
    }
    var foldBtn = e.target.closest("[data-open-fold]");
    if (foldBtn) {
      e.preventDefault();
      var id = foldBtn.getAttribute("data-open-fold");
      var fold = id ? document.getElementById(id) : null;
      if (fold) {
        fold.open = true;
        try {
          fold.scrollIntoView({ behavior: "smooth", block: "nearest" });
        } catch (err) {}
      }
    }
  });

  function csrfToken() {
    var m = document.querySelector('meta[name="csrf-token"]');
    return m ? m.getAttribute("content") : "";
  }

  function paintQty(root, data) {
    if (!root || !data) return;
    var label = root.querySelector("[data-qty-label]");
    if (label) label.textContent = data.quantity_label != null ? data.quantity_label : data.quantity;
    var badge = root.querySelector("[data-stock-badge]");
    if (!badge) return;
    var status = data.status || "";
    badge.className = "badge";
    if (status === "low") {
      badge.classList.add("low");
      badge.textContent = root.classList.contains("onhand-row") ? "Low" : "Need more";
    } else if (status === "out") {
      badge.classList.add("out");
      badge.textContent = "Had";
    } else if (status === "want") {
      badge.classList.add("want");
      badge.textContent = "Want";
    } else {
      badge.textContent = "Have";
    }
  }

  function putOnList(btn) {
    var itemId = btn.getAttribute("data-list-item");
    if (!itemId) return;
    btn.disabled = true;
    fetch("/items/" + itemId + "/qty", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        "X-CSRF-Token": csrfToken(),
        "X-Requested-With": "fetch",
      },
      body: JSON.stringify({ action: "need_more", amount: 1 }),
    })
      .then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok, data: data };
        });
      })
      .then(function (out) {
        if (!out.ok || !out.data || !out.data.ok) {
          btn.disabled = false;
          return;
        }
        btn.textContent = "On list";
      })
      .catch(function () {
        btn.disabled = false;
      });
  }

  function bumpQty(btn) {
    var stepper = btn.closest("[data-qty-item]") || btn.closest(".qty-stepper");
    var row = btn.closest("[data-item-id]");
    var itemId = (stepper && stepper.getAttribute("data-qty-item")) || (row && row.getAttribute("data-item-id"));
    if (!itemId) return;
    var delta = parseInt(btn.getAttribute("data-qty-delta") || "0", 10);
    if (!delta) return;
    var action = delta > 0 ? "plus" : "minus";
    if (stepper) stepper.classList.add("busy");
    fetch("/items/" + itemId + "/qty", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        "X-CSRF-Token": csrfToken(),
        "X-Requested-With": "fetch",
      },
      body: JSON.stringify({ action: action, amount: 1, place: stepper.getAttribute("data-qty-place") || "" }),
    })
      .then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok, data: data };
        });
      })
      .then(function (out) {
        if (!out.ok || !out.data || !out.data.ok) return;
        paintQty(row || stepper, out.data);
      })
      .catch(function () {})
      .then(function () {
        if (stepper) stepper.classList.remove("busy");
      });
  }

  (function vaultKeep() {
    if (!document.getElementById("vault-keep")) return;
    var last = 0;
    function ping() {
      if (document.hidden) return;
      var now = Date.now();
      if (now - last < 8000) return;
      last = now;
      fetch("/vault/stay", {
        method: "POST",
        headers: {
          Accept: "application/json",
          "X-CSRF-Token": csrfToken(),
          "X-Requested-With": "fetch",
        },
      }).catch(function () {});
    }
    setInterval(ping, 60000);
    ping();
  })();
})();
