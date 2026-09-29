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
  var micBtn = document.getElementById("ask-mic");
  var micRec = null;
  var micListening = false;
  var busy = false;
  var pendingImage = "";
  var room = root.getAttribute("data-room") || "house";
  var mode = root.getAttribute("data-mode") || "fab";
  var cacheKey = "family-ask-log:" + room;
  var historyLoaded = false;
  var historyEpoch = 0;

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

  function isSensitiveAsk(text) {
    text = String(text || "").trim();
    var roomOnly = room === "vault";
    var vaultMention = /\b(?:vault|vault card)\b/i.test(text);
    var pastedSecret = /\b(?:my|our|their)\b.{0,30}\b(?:password|passcode|pass\s*phrase|login|username|pin)\b.{0,50}\b(?:is|=|:)\b|\b(?:password|passcode|pass\s*phrase|pin)\s*(?:is|=|:)\s*\S+/i.test(text);
    var passwordHelp = /\b(?:how\s+(?:do|can|to)|help\s+me|steps?\s+to)\b.{0,70}\b(?:reset|change|update|recover|forgot|forget|create|choose|make)\b.{0,50}\b(?:password|passcode|login|account)\b|\b(?:reset|change|update|recover|forgot|forget|create|choose|make)\b.{0,50}\b(?:password|passcode|login|account)\b|\b(?:good|strong|secure|safe)\s+(?:password|passcode)\b|\bwhat\s+makes?\b/i.test(text);
    var credentialLookup = !passwordHelp && (
      /\b(?:what(?:'s|\s+is)?|show|tell\s+me|give\s+me|get|find|retrieve|look\s+up|open|check|copy|read)\b.{0,70}\b(?:password|passcode|pass\s*phrase|secret|credential|login|username|account\s+number|2fa|two[- ]factor|verification\s+code|pin)\b/i.test(text) &&
      /\b(?:my|our|their)\b.{0,35}\b(?:password|passcode|pass\s*phrase|secret|credential|login|username|account\s+number|2fa|two[- ]factor|verification\s+code|pin)\b|\b(?:password|passcode|pass\s*phrase|secret|credential|login|username|account\s+number|2fa|two[- ]factor|verification\s+code|pin)\b.{0,35}\b(?:for|on|to|of)\s+[A-Za-z0-9][A-Za-z0-9 ._'-]{1,40}|\b[A-Za-z][A-Za-z0-9 ._'-]{1,40}\s+(?:password|passcode|login|username|PIN)\b/i.test(text)
    );
    var tokenOnly = /^[A-Za-z0-9!@#$%^&*()_+\-=\[\]{};':\",./?]{10,128}$/.test(text) && /[A-Za-z]/.test(text) && /\d/.test(text);
    return roomOnly || vaultMention || pastedSecret || credentialLookup || tokenOnly;
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

  function addBubble(role, text, imageUrl, retry, confirm, options) {
    if (!log) return null;
    var el = document.createElement("div");
    el.className = "ask-bubble " + role + (options && options.volatile ? " volatile" : "");
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
    historyEpoch += 1;
    try { window.localStorage.removeItem(cacheKey); } catch (e) {}
  }

  function turnsFromLog() {
    if (!log) return [];
    var out = [];
    Array.prototype.forEach.call(log.children, function (el) {
      var cls = el.className || "";
      if (cls.indexOf("pending") >= 0 || cls.indexOf("err") >= 0 || cls.indexOf("volatile") >= 0) return;
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
    if (room === "vault") cacheClear();
    if (room !== "vault" && (!log || !log.childElementCount)) {
      var cached = cacheRead();
      if (cached && cached.length) paintTurns(cached);
    }
    if (room === "vault") return;
    var requestEpoch = historyEpoch;
    fetch("/ask/history?room=" + encodeURIComponent(room), {
      headers: { Accept: "application/json", "X-Requested-With": "fetch" },
    })
      .then(function (res) { return res.json(); })
      .then(function (data) {
        if (requestEpoch !== historyEpoch) return;
        var turns = (data && data.turns) || [];
        if (historyLoaded && log && log.childElementCount && turns.length < turnsFromLog().length) {
          return;
        }
        paintTurns(turns);
        cacheWrite(turns);
        historyLoaded = true;
      })
      .catch(function () {
        if (requestEpoch === historyEpoch) historyLoaded = true;
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
    root.classList.toggle("ask-on", !!on);
    if (on) {
      if (!log || !log.childElementCount) loadHistory(true);
      if (input) {
        try { input.focus(); } catch (e) {}
      }
    } else if (room !== "vault") {
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
      var AGENT = (root && root.dataset.agent) || "Ask";
      shrinkFile(file, function (url) {
        if (!url) {
          setPreview("");
          addBubble("them err", "That file is not a photo " + AGENT + " can read.");
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
    var sensitive = isSensitiveAsk(text);
    if (!again) {
      if (sensitive) {
        if (log) log.innerHTML = "";
        cacheClear();
      } else {
        addBubble("me", text || "Photo", imageUrl);
      }
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
    var retry = sensitive ? null : { text: text, image: imageUrl };
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
        if (data.clear_history || data.volatile) {
          if (log) log.innerHTML = "";
          cacheClear();
          if (data.redirect_url) {
            window.location.assign(data.redirect_url);
            return;
          }
          addBubble(data.ok ? "them" : "them err", say, "", null, false, { volatile: true });
          return;
        }
        addBubble(data.ok ? "them" : "them err", say, "", !data.ok && canRetry(say) ? retry : null, data.ok && data.confirm);
        if (data.vault_locked) addBubble("them", "Open /vault/ with this login, then ask again.");
        if (data.ok) cacheWrite(turnsFromLog());
      })
      .catch(function () {
        if (pending) pending.remove();
        addBubble("them err", "Could not reach " + ((root && root.dataset.agent) || "Ask") + ".", "", retry);
      })
      .then(function () {
        busy = false;
        if (send) send.disabled = false;
        if (input) input.focus();
      });
  }

  function micStop() {
    micListening = false;
    if (micBtn) {
      micBtn.classList.remove("is-listening");
      micBtn.setAttribute("aria-pressed", "false");
      micBtn.textContent = "Mic";
    }
  }

  function micToggle() {
    if (!micRec) return;
    if (micListening) {
      try { micRec.stop(); } catch (err) { /* already stopping */ }
      micStop();
      return;
    }
    try {
      micRec.start();
      micListening = true;
      if (micBtn) {
        micBtn.classList.add("is-listening");
        micBtn.setAttribute("aria-pressed", "true");
        micBtn.textContent = "Listening…";
      }
      if (input) input.focus();
    } catch (err) {
      micStop();
    }
  }

  function micSetup() {
    var Rec = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!micBtn || !Rec || !input) return;
    micRec = new Rec();
    micRec.interimResults = false;
    micRec.continuous = false;
    micRec.onresult = function (event) {
      var said = "";
      for (var i = event.resultIndex || 0; i < event.results.length; i += 1) {
        var piece = event.results[i];
        if (piece.isFinal || i === event.results.length - 1) said += piece[0].transcript;
      }
      said = said.replace(/\s+/g, " ").trim();
      if (!said) return;
      var current = input.value || "";
      input.value = current && !/\s$/.test(current) ? current + " " + said : current + said;
      try { input.setSelectionRange(input.value.length, input.value.length); } catch (err) { /* not supported */ }
      input.dispatchEvent(new Event("input"));
    };
    micRec.onerror = micStop;
    micRec.onend = micStop;
    micBtn.hidden = false;
    micBtn.addEventListener("click", micToggle);
  }
  micSetup();

  if (form) {
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      sendAsk(input && input.value, pendingImage, false);
    });
  }
})();
