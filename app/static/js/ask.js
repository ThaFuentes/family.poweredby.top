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

  function canRetry(say) {
    return /model is busy|timed out|could not reach|request failed/i.test(say || "");
  }

  function addBubble(role, text, imageUrl, retry) {
    if (!log) return null;
    var el = document.createElement("div");
    el.className = "ask-bubble " + role;
    el.innerHTML = linkify(text);
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
    var body = { message: text };
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
        addBubble(data.ok ? "them" : "them err", say, "", !data.ok && canRetry(say) ? retry : null);
        if (data.vault_locked) addBubble("them", "Open /vault/ with this login, then ask again.");
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
