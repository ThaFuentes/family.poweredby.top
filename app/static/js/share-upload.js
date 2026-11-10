/* Resumable share uploads: 4 MB pieces, retry, and resume after a reload. */
(function () {
  "use strict";
  var form = document.querySelector("form[data-resumable-upload]");
  if (!form || !window.fetch || !window.File || !File.prototype.slice) return;
  var fileInput = form.querySelector('input[type="file"][name="file"]');
  if (!fileInput) return;

  var live = form.querySelector("[data-upload-live]");
  var bar = form.querySelector("[data-upload-bar]");
  var note = form.querySelector("[data-upload-note]");
  var cancelBtn = form.querySelector("[data-upload-cancel]");
  var submitBtn = form.querySelector('button[type="submit"]');
  var storageKey = "family.shareUpload.v1";
  var uploading = false;
  var stopped = false;
  var active = null;

  function csrf() {
    var m = document.querySelector('meta[name="csrf-token"]');
    return m ? m.content : "";
  }
  function human(n) {
    n = Number(n) || 0;
    if (n < 1024) return n + " B";
    if (n < 1048576) return (n / 1024).toFixed(0) + " KB";
    if (n < 1073741824) return (n / 1048576).toFixed(1) + " MB";
    return (n / 1073741824).toFixed(1) + " GB";
  }
  function say(text) {
    if (live) live.hidden = false;
    if (note) note.textContent = text || "";
  }
  function showLive(on) {
    if (live) live.hidden = !on;
  }
  function setProgress(done, total, startedAt) {
    var pct = total ? Math.max(0, Math.min(100, Math.floor((done * 100) / total))) : 0;
    if (bar) bar.value = pct;
    var rate = "";
    if (startedAt && done > 0) {
      var secs = Math.max(0.05, (Date.now() - startedAt) / 1000);
      var per = done / secs;
      if (per > 0) rate = " · " + human(per) + "/s";
    }
    if (note) note.textContent = pct + "% · " + human(done) + " of " + human(total) + rate;
  }
  function remember(state) {
    try { localStorage.setItem(storageKey, JSON.stringify(state)); } catch (e) {}
  }
  function saved() {
    try {
      var raw = localStorage.getItem(storageKey);
      return raw ? JSON.parse(raw) : null;
    } catch (e) { return null; }
  }
  function forget() {
    try { localStorage.removeItem(storageKey); } catch (e) {}
  }
  function fingerprint(file) {
    return file.name + "|" + file.size + "|" + (file.lastModified || 0);
  }
  function sessionUrl(id) {
    return String(form.dataset.sessionUrl || "").replace("UPLOAD_ID", encodeURIComponent(id));
  }
  function field(name) {
    var el = form.querySelector('[name="' + name + '"]');
    return el ? el.value : "";
  }
  function checkedPeople() {
    var out = [];
    var boxes = form.querySelectorAll('input[name="people"]:checked');
    for (var i = 0; i < boxes.length; i++) out.push(boxes[i].value);
    return out;
  }
  function settingsSig(p) {
    return [p.share_mode, p.title, p.expires_days, (p.people || []).join(",")].join("|");
  }
  function payloadFor(file) {
    return {
      name: file.name,
      size: file.size,
      title: field("title"),
      share_mode: field("share_mode") || "family",
      password: field("password"),
      expires_days: field("expires_days") || "0",
      people: checkedPeople()
    };
  }
  function applySaved(state) {
    if (!state) return;
    var mode = form.querySelector('[name="share_mode"]');
    if (mode && state.share_mode) mode.value = state.share_mode;
    var title = form.querySelector('[name="title"]');
    if (title && typeof state.title === "string") title.value = state.title;
    var expiry = form.querySelector('[name="expires_days"]');
    if (expiry && state.expires_days !== undefined) expiry.value = String(state.expires_days);
    var boxes = form.querySelectorAll('input[name="people"]');
    for (var i = 0; i < boxes.length; i++) {
      boxes[i].checked = (state.people || []).indexOf(boxes[i].value) >= 0;
    }
  }
  function sleep(ms) {
    return new Promise(function (resolve) { setTimeout(resolve, ms); });
  }
  async function readJson(res) {
    var data = null;
    try { data = await res.json(); } catch (e) {}
    if (!res.ok || !data || data.ok === false) {
      var err = new Error((data && data.error) || ("Upload failed (" + res.status + ")."));
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data;
  }
  async function getStatus(id) {
    var res = await fetch(sessionUrl(id), { headers: { Accept: "application/json" } });
    return readJson(res);
  }
  async function cancelId(id) {
    if (!id) return;
    try {
      await fetch(sessionUrl(id), {
        method: "DELETE",
        headers: { "X-CSRF-Token": csrf(), Accept: "application/json" }
      });
    } catch (e) {}
  }
  async function initUpload(payload) {
    var res = await fetch(form.dataset.initUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrf(),
        Accept: "application/json"
      },
      body: JSON.stringify(payload)
    });
    return readJson(res);
  }
  async function sendChunk(id, blob, offset, total, startedAt) {
    var attempt = 0;
    while (true) {
      attempt++;
      if (stopped) {
        var stopErr = new Error("Upload stopped.");
        stopErr.name = "AbortError";
        throw stopErr;
      }
      try {
        var res = await fetch(sessionUrl(id) + "/chunk?offset=" + encodeURIComponent(offset), {
          method: "PUT",
          headers: {
            "Content-Type": "application/octet-stream",
            "X-CSRF-Token": csrf(),
            Accept: "application/json"
          },
          body: blob
        });
        var data = null;
        try { data = await res.json(); } catch (e) {}
        if (res.status === 409 && data && typeof data.offset === "number") {
          if (data.offset > offset) return data.offset;
          throw new Error("The server lost track of this upload. Start it again.");
        }
        if (!res.ok || !data || data.ok === false) {
          var err = new Error((data && data.error) || ("Upload failed (" + res.status + ")."));
          err.status = res.status;
          throw err;
        }
        return data.offset;
      } catch (err) {
        var retryable = !err.status || err.status >= 500;
        if (!retryable || attempt >= 6) throw err;
        var wait = Math.pow(2, attempt - 1);
        say("Connection hiccup — retrying in " + wait + "s. (" + err.message + ")");
        await sleep(wait * 1000);
        setProgress(offset, total, startedAt);
      }
    }
  }
  async function finishUpload(id) {
    var res = await fetch(sessionUrl(id) + "/finish", {
      method: "POST",
      headers: { "X-CSRF-Token": csrf(), Accept: "application/json" }
    });
    return readJson(res);
  }
  function fail(err) {
    showLive(true);
    if (note) note.textContent = (err && err.message) || "Upload failed.";
    if (submitBtn) submitBtn.disabled = false;
  }

  fileInput.addEventListener("change", async function () {
    var file = fileInput.files && fileInput.files[0];
    showLive(false);
    if (!file) return;
    if (!file.size) {
      showLive(true);
      if (note) note.textContent = "That file is empty.";
      return;
    }
    var prior = saved();
    if (!prior || prior.fingerprint !== fingerprint(file)) return;
    applySaved(prior);
    try {
      var st = await getStatus(prior.id);
      if (st.size !== file.size) { forget(); return; }
      showLive(true);
      setProgress(st.offset, st.size, 0);
      say("Saved upload found — submitting resumes at " + (st.size ? Math.floor((st.offset * 100) / st.size) : 0) + "%.");
    } catch (e) {
      forget();
    }
  });

  form.addEventListener("submit", async function (ev) {
    var file = fileInput.files && fileInput.files[0];
    if (!file) return;
    ev.preventDefault();
    if (uploading) return;
    if (!file.size) { fail(new Error("That file was empty.")); return; }

    uploading = true;
    stopped = false;
    if (submitBtn) submitBtn.disabled = true;
    showLive(true);
    setProgress(0, file.size, 0);
    say("Starting…");

    var payload = payloadFor(file);
    var prior = saved();
    var state = null;

    if (prior && prior.fingerprint === fingerprint(file)) {
      if (prior.settings === settingsSig(payload)) {
        try {
          var st = await getStatus(prior.id);
          if (st.size === file.size && st.offset > 0 && st.offset < file.size) {
            state = {
              id: st.upload_id,
              offset: st.offset,
              size: st.size,
              chunk: st.chunk_size,
              started: Date.now()
            };
            say("Resuming at " + Math.floor((st.offset * 100) / st.size) + "%…");
          }
        } catch (e) { state = null; }
      }
      if (!state) { await cancelId(prior.id); forget(); }
    }

    if (!state) {
      try {
        var init = await initUpload(payload);
        state = {
          id: init.upload_id,
          offset: 0,
          size: init.size,
          chunk: init.chunk_size,
          started: Date.now()
        };
        remember({
          id: state.id,
          fingerprint: fingerprint(file),
          settings: settingsSig(payload),
          share_mode: payload.share_mode,
          title: payload.title,
          expires_days: payload.expires_days,
          people: payload.people
        });
      } catch (err) {
        uploading = false;
        fail(err);
        return;
      }
    }

    active = state;
    setProgress(state.offset, state.size, state.started);
    try {
      var offset = state.offset;
      while (offset < file.size) {
        var end = Math.min(offset + state.chunk, file.size);
        offset = await sendChunk(state.id, file.slice(offset, end), offset, file.size, state.started);
        state.offset = offset;
        setProgress(offset, file.size, state.started);
      }
      var done = await finishUpload(state.id);
      forget();
      active = null;
      uploading = false;
      if (done.redirect) window.location.assign(done.redirect);
      else window.location.reload();
    } catch (err) {
      uploading = false;
      active = null;
      if (submitBtn) submitBtn.disabled = false;
      if (err && err.name === "AbortError") {
        say("Upload stopped. Pick the same file again to resume.");
      } else {
        fail(err);
      }
    }
  });

  if (cancelBtn) {
    cancelBtn.addEventListener("click", async function () {
      stopped = true;
      uploading = false;
      if (active) await cancelId(active.id);
      var prior = saved();
      if (prior && prior.id && (!active || prior.id !== active.id)) await cancelId(prior.id);
      forget();
      active = null;
      if (submitBtn) submitBtn.disabled = false;
      if (bar) bar.value = 0;
      say("Upload cancelled. The partial file was removed.");
    });
  }

  window.addEventListener("beforeunload", function (ev) {
    if (!uploading) return;
    ev.preventDefault();
    ev.returnValue = "";
    return "";
  });
})();
