(function () {
  var root = document.getElementById("ask-root");
  if (!root) return;
  var panel = document.getElementById("ask-panel");
  var log = document.getElementById("ask-log");
  var form = document.getElementById("ask-form");
  var input = document.getElementById("ask-input");
  var send = document.getElementById("ask-send");
  var openBtn = document.getElementById("ask-open");
  var closeBtn = document.getElementById("ask-close");
  var clearBtn = document.getElementById("ask-clear");
  var busy = false;

  function csrfToken() {
    var m = document.querySelector('meta[name="csrf-token"]');
    return m ? m.getAttribute("content") : "";
  }

  function esc(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function linkify(raw) {
    var text = esc(raw);
    text = text.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+|\/[^\s)]+)\)/g, function (_, label, href) {
      return '<a href="' + href + '">' + label + "</a>";
    });
    text = text.replace(/(^|[\s(])(https?:\/\/[^\s<]+)/g, function (_, pre, href) {
      var clean = href.replace(/[.,;:!?)]+$/, "");
      var tail = href.slice(clean.length);
      return pre + '<a href="' + clean + '" rel="noopener noreferrer" target="_blank">' + clean + "</a>" + tail;
    });
    text = text.replace(/(^|[\s(])(\/(?:vault|find|notes|groceries|reminders|items|legal|members|house|tools|vehicles)[^\s<]*)/g, function (_, pre, href) {
      var clean = href.replace(/[.,;:!?)]+$/, "");
      var tail = href.slice(clean.length);
      return pre + '<a href="' + clean + '">' + clean + "</a>" + tail;
    });
    return text.replace(/\n/g, "<br>");
  }

  function addBubble(role, text) {
    if (!log) return;
    var el = document.createElement("div");
    el.className = "ask-bubble " + role;
    el.innerHTML = linkify(text);
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
  }

  function setOpen(on) {
    if (!panel || !openBtn) return;
    panel.hidden = !on;
    panel.classList.toggle("is-open", !!on);
    openBtn.hidden = on;
    openBtn.setAttribute("aria-expanded", on ? "true" : "false");
    root.classList.toggle("ask-on", on);
    if (on && input) {
      try { input.focus(); } catch (e) {}
    }
  }
  setOpen(false);

  if (openBtn) openBtn.addEventListener("click", function () { setOpen(true); });
  if (closeBtn) closeBtn.addEventListener("click", function () { setOpen(false); });
  if (clearBtn) {
    clearBtn.addEventListener("click", function () {
      fetch("/ask/clear", {
        method: "POST",
        headers: { "X-CSRF-Token": csrfToken(), "X-Requested-With": "fetch" },
      }).catch(function () {});
      if (log) log.innerHTML = "";
    });
  }

  if (input) {
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        if (form) form.requestSubmit();
      }
    });
  }

  if (form) {
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      if (busy) return;
      var text = (input && input.value || "").trim();
      if (!text) return;
      addBubble("me", text);
      input.value = "";
      busy = true;
      if (send) send.disabled = true;
      addBubble("them pending", "Looking…");
      var pending = log ? log.lastElementChild : null;
      fetch("/ask/message", {
        method: "POST",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken(),
          "X-Requested-With": "fetch",
        },
        body: JSON.stringify({ message: text }),
      })
        .then(function (res) {
          return res.json().then(function (data) {
            return { ok: res.ok, data: data };
          });
        })
        .then(function (out) {
          var data = out.data || {};
          var say = data.say || data.error || "Ask had nothing.";
          if (pending) pending.remove();
          addBubble(data.ok ? "them" : "them err", say);
          if (data.vault_locked) addBubble("them", "Open /vault/ with this login, then ask again.");
        })
        .catch(function () {
          if (pending) pending.remove();
          addBubble("them err", "Could not reach Ask.");
        })
        .then(function () {
          busy = false;
          if (send) send.disabled = false;
          if (input) input.focus();
        });
    });
  }
})();
