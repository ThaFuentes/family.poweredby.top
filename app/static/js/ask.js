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
  var fileInput = document.getElementById("ask-file");
  var preview = document.getElementById("ask-preview");
  var previewImg = document.getElementById("ask-preview-img");
  var previewName = document.getElementById("ask-preview-name");
  var previewClear = document.getElementById("ask-preview-clear");
  var busy = false;
  var pendingImage = "";
  var room = root.getAttribute("data-room") || "house";
  var mode = root.getAttribute("data-mode") || "fab";
  var cacheKey = "family-ask-log:" + room;
  var historyLoaded = false;

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
    text = text.replace(/(^|[\s(])(\/(?:ask|vault|find|notes|groceries|reminders|items|legal|members|house|tools|vehicles)[^\s<]*)/g, function (_, pre, href) {
      var clean = href.replace(/[.,;:!?)]+$/, "");
      var tail = href.slice(clean.length);
      return pre + '<a href="' + clean + '">' + clean + "</a>" + tail;
    });
    return text.replace(/\n/g, "<br>");
  }

  function canRetry(say) {
    return /model is busy|timed out|could not reach|request failed/i.test(say || "");
  }

  function addConfirm(el, on) {
    if (!el || !on) return;
    var row = document.createElement("div");
    row.className = "ask-confirm";
    [
      ["yes", "Allow"],
      ["no", "Don’t"],
      ["always allow", "Always allow"],
    ].forEach(function (pair) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "ask-confirm-btn";
      btn.textContent = pair[1];
      btn.addEventListener("click", function () {
        sendAsk(pair[0], "", false);
      });
      row.appendChild(btn);
    });
    el.appendChild(row);
  }

  function addBubble(role, text, imageUrl, retry, confirm) {
    if (!log) return null;
    var el = document.createElement("div");
    el.className = "ask-bubble " + role;
    var body = document.createElement("div");
    body.className = "ask-text";
    body.innerHTML = linkify(text);
    el.appendChild(body);
    if (imageUrl && String(imageUrl).indexOf("data:image/") === 0) {
      var img = document.createElement("img");
      img.className = "ask-shot-img";
      img.alt = "Photo you sent";
      img.src = imageUrl;
      el.appendChild(img);
    }
    if (retry) {
      var again = document.createElement("button");
      again.type = "button";
      again.className = "ask-retry";
      again.textContent = "Try again";
      again.addEventListener("click", function () {
        if (el.parentNode) el.parentNode.removeChild(el);
        sendAsk(retry.text, retry.image, true);
      });
      el.appendChild(again);
    }
    if (confirm) addConfirm(el, true);
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
    return el;
  }

  function setPreview(url, name) {
    pendingImage = url || "";
    if (!preview) return;
    if (!pendingImage) {
      preview.hidden = true;
      preview.classList.remove("is-on");
      if (previewImg) previewImg.removeAttribute("src");
      if (previewName) previewName.textContent = "";
      return;
    }
    preview.hidden = false;
    preview.classList.add("is-on");
    if (previewImg) previewImg.src = pendingImage;
    if (previewName) previewName.textContent = name || "Photo";
  }

  function shrinkFile(file, cb) {
    if (!file || !/^image\//.test(file.type || "")) {
      cb("");
      return;
    }
    var url = URL.createObjectURL(file);
    var img = new Image();
    img.onload = function () {
      var max = 1600;
      var scale = Math.min(1, max / Math.max(img.width || 1, img.height || 1));
      var canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round((img.width || 1) * scale));
      canvas.height = Math.max(1, Math.round((img.height || 1) * scale));
      var ctx = canvas.getContext("2d");
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      URL.revokeObjectURL(url);
      cb(canvas.toDataURL("image/jpeg", 0.82));
    };
    img.onerror = function () {
      URL.revokeObjectURL(url);
      cb("");
    };
    img.src = url;
  }

  function cacheRead() {
    try {
      var raw = window.localStorage.getItem(cacheKey);
      var data = raw ? JSON.parse(raw) : null;
      if (!data || !Array.isArray(data.turns)) return null;
      return data.turns;
    } catch (e) {
      return null;
    }
  }

  function cacheWrite(turns) {
    try {
      window.localStorage.setItem(cacheKey, JSON.stringify({ turns: turns || [], at: Date.now() }));
    } catch (e) {}
  }

  function cacheClear() {
    try { window.localStorage.removeItem(cacheKey); } catch (e) {}
  }

  function turnsFromLog() {
    if (!log) return [];
    var out = [];
    Array.prototype.forEach.call(log.children, function (el) {
      var cls = el.className || "";
      if (cls.indexOf("pending") >= 0 || cls.indexOf("err") >= 0) return;
      var role = /\bme\b/.test(cls) ? "user" : "assistant";
      var textEl = el.querySelector(".ask-text");
      var text = ((textEl && (textEl.innerText || textEl.textContent)) || el.innerText || el.textContent || "")
        .replace(/\s*Try again\s*$/, "")
        .replace(/\s*Allow\s*Don’t\s*Always allow\s*$/, "")
        .trim();
      if (text) out.push({ role: role, text: text });
    });
    return out;
  }

  function paintTurns(turns) {
    if (!log) return;
    log.innerHTML = "";
    (turns || []).forEach(function (row) {
      var role = row.role === "user" ? "me" : "them";
      addBubble(role, row.text || "");
    });
  }

  function loadHistory(force) {
    if (!force && historyLoaded && log && log.childElementCount) return;
    if (!log || !log.childElementCount) {
      var cached = cacheRead();
      if (cached && cached.length) paintTurns(cached);
    }
    fetch("/ask/history?room=" + encodeURIComponent(room), {
      headers: { Accept: "application/json", "X-Requested-With": "fetch" },
    })
      .then(function (res) { return res.json(); })
      .then(function (data) {
        var turns = (data && data.turns) || [];
        if (historyLoaded && log && log.childElementCount && turns.length < turnsFromLog().length) {
          return;
        }
        paintTurns(turns);
        cacheWrite(turns);
        historyLoaded = true;
      })
      .catch(function () {
        historyLoaded = true;
      });
  }

  function setOpen(on) {
    if (mode === "desk") {
      if (panel) {
        panel.hidden = false;
        panel.classList.add("is-open");
      }
      if (on && input) {
        try { input.focus(); } catch (e) {}
      }
      return;
    }
    if (!panel || !openBtn) return;
    panel.hidden = !on;
    panel.classList.toggle("is-open", !!on);
    openBtn.hidden = on;
    openBtn.setAttribute("aria-expanded", on ? "true" : "false");
    root.classList.toggle("ask-on", on);
    if (on) {
      if (!log || !log.childElementCount) loadHistory(true);
      if (input) {
        try { input.focus(); } catch (e) {}
      }
    } else {
      cacheWrite(turnsFromLog());
    }
  }
  if (mode === "desk") {
    setOpen(true);
    loadHistory(true);
  } else {
    setOpen(false);
    loadHistory(false);
  }

  if (openBtn) openBtn.addEventListener("click", function () { setOpen(true); });
  if (closeBtn) closeBtn.addEventListener("click", function () { setOpen(false); });
  if (clearBtn) {
    clearBtn.addEventListener("click", function () {
      fetch("/ask/clear", {
        method: "POST",
        headers: {
          "X-CSRF-Token": csrfToken(),
          "X-Requested-With": "fetch",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ room: room }),
      }).catch(function () {});
      if (log) log.innerHTML = "";
      cacheClear();
      historyLoaded = true;
      setPreview("");
      if (fileInput) fileInput.value = "";
    });
  }
  if (previewClear) {
    previewClear.addEventListener("click", function () {
      setPreview("");
      if (fileInput) fileInput.value = "";
    });
  }
  if (fileInput) {
    fileInput.addEventListener("change", function () {
      var file = fileInput.files && fileInput.files[0];
      if (!file) {
        setPreview("");
        return;
      }
      shrinkFile(file, function (url) {
        if (!url) {
          setPreview("");
          addBubble("them err", "That file is not a photo Ask can read.");
          return;
        }
        setPreview(url, file.name || "Photo");
      });
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

  function sendAsk(text, imageUrl, again) {
    if (busy) return;
    text = (text || "").trim();
    imageUrl = imageUrl || "";
    if (!text && !imageUrl) return;
    if (!again) {
      addBubble("me", text || "Photo", imageUrl);
      if (input) input.value = "";
      setPreview("");
      if (fileInput) fileInput.value = "";
    }
    busy = true;
    if (send) send.disabled = true;
    addBubble("them pending", imageUrl ? "Reading the photo…" : "Looking…");
    var pending = log ? log.lastElementChild : null;
    var body = { message: text, room: room };
    if (imageUrl) {
      body.image = imageUrl;
      body.image_mime = "image/jpeg";
    }
    var retry = { text: text, image: imageUrl };
    fetch("/ask/message", {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken(),
        "X-Requested-With": "fetch",
      },
      body: JSON.stringify(body),
    })
      .then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok, data: data };
        });
      })
      .then(function (out) {
        var data = out.data || {};
        var say = (data.say || data.error || "").trim() || "Couldn’t get an answer. Try “what tools do I have.”";
        if (pending) pending.remove();
        addBubble(data.ok ? "them" : "them err", say, "", !data.ok && canRetry(say) ? retry : null, data.ok && data.confirm);
        if (data.vault_locked) addBubble("them", "Open /vault/ with this login, then ask again.");
        if (data.ok) cacheWrite(turnsFromLog());
      })
      .catch(function () {
        if (pending) pending.remove();
        addBubble("them err", "Could not reach Ask.", "", retry);
      })
      .then(function () {
        busy = false;
        if (send) send.disabled = false;
        if (input) input.focus();
      });
  }

  if (form) {
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      sendAsk(input && input.value, pendingImage, false);
    });
  }
})();
