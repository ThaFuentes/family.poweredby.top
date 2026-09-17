/* Scan identifies the item. Kids then tap Just used / Needs more / Got more. */
(function () {
  const pageStatus = document.getElementById("scan-status");
  const pageResult = document.getElementById("scan-result");
  const liveStatus = document.getElementById("scan-live-status");
  const liveResult = document.getElementById("scan-live-result");
  const manualForm = document.getElementById("manual-form");
  const canCreate = window.FAMILY_CAN_CREATE === true;
  const scanKind = window.FAMILY_SCAN_KIND || "any";
  let statusEl = pageStatus || liveStatus;
  let resultEl = pageResult || liveResult;
  if (!statusEl) statusEl = liveStatus;
  if (!resultEl) resultEl = liveResult;
  let busy = false;
  let pauseDecode = false;
  let lastCode = "";
  let lastAt = 0;
  let settleTimer = null;
  let pending = null;
  const JOB_KEY = "family_scan_job";
  let lastUndoId = null;

  function hostKindWord(host) {
    const t = (host && host.item_type) || "";
    if (t === "vehicle") return "VEHICLE";
    if (t === "house") return "HOUSE";
    return "EQUIPMENT";
  }
  function addFormOpen() {
    const d = document.getElementById("add-vehicle");
    return !!(d && d.open);
  }
  function paintHostBanner() {
    const banner = document.getElementById("scan-host-banner");
    const jobs = document.querySelector(".scan-jobs");
    const label = document.getElementById("scan-host-label");
    const undoBtn = document.getElementById("scan-host-undo");
    const host = window.FAMILY_SCAN_HOST;
    if (!banner) return;
    if (addFormOpen()) {
      banner.hidden = false;
      if (jobs) jobs.hidden = true;
      if (label) label.textContent = "SCAN TO CREATE A VEHICLE";
      if (undoBtn) undoBtn.hidden = !lastUndoId;
      return;
    }
    if (host && host.id) {
      banner.hidden = false;
      if (jobs) jobs.hidden = true;
      if (label) {
        label.textContent =
          "SCAN FOR " + String(host.name || "").toUpperCase() + " · " + hostKindWord(host);
      }
      if (undoBtn) undoBtn.hidden = !lastUndoId;
      return;
    }
    banner.hidden = true;
    if (jobs) jobs.hidden = false;
    if (undoBtn) undoBtn.hidden = true;
  }

  function getScanJob() {
    try {
      const j = localStorage.getItem(JOB_KEY);
      if (j === "out" || j === "buy" || j === "in" || j === "mix") return j;
    } catch (e) {}
    return "in";
  }
  function setScanJob(job) {
    if (job !== "out" && job !== "buy" && job !== "mix") job = "in";
    try {
      localStorage.setItem(JOB_KEY, job);
    } catch (e) {}
    document.querySelectorAll("[data-scan-job]").forEach(function (el) {
      el.classList.toggle("on", el.getAttribute("data-scan-job") === job);
    });
    const st = document.getElementById("scan-live-status");
    if (st) {
      const host = window.FAMILY_SCAN_HOST;
      if (addFormOpen()) {
        st.textContent = "VIN sticker creates a new vehicle.";
      } else if (host && host.id) {
        st.textContent = "Scan for " + (host.name || "this") + ".";
      } else {
        st.textContent =
          job === "out"
            ? "Used — every scan takes one off."
            : job === "buy"
              ? "Needed — every scan goes on the list."
              : job === "mix"
                ? "Mix — pick Incoming, Used, or Needed after each scan."
                : "Incoming — every scan adds one.";
      }
    }
    paintHostBanner();
  }
  function actionForJob() {
    const j = getScanJob();
    if (j === "out") return "consume";
    if (j === "buy") return "buy";
    if (j === "mix") return "mix";
    return "into";
  }
  const QUEUE_KEY = "family_scan_queue";

  function readQueue() {
    try {
      const raw = localStorage.getItem(QUEUE_KEY);
      const q = raw ? JSON.parse(raw) : [];
      return Array.isArray(q) ? q : [];
    } catch (e) {
      return [];
    }
  }
  function writeQueue(q) {
    localStorage.setItem(QUEUE_KEY, JSON.stringify(q.slice(-40)));
  }
  function enqueueScan(barcode, action) {
    const q = readQueue();
    q.push({ barcode: barcode, action: action || "check", at: Date.now() });
    writeQueue(q);
    statusEl.textContent = "Saved for when you're back online.";
  }
  async function flushQueue() {
    if (!navigator.onLine || busy) return;
    const q = readQueue();
    if (!q.length) return;
    writeQueue([]);
    for (let i = 0; i < q.length; i++) {
      await applyBarcode(q[i].barcode, q[i].action, true);
    }
  }
  window.addEventListener("online", flushQueue);

  function csrfToken() {
    const m = document.querySelector('meta[name="csrf-token"]');
    return m ? m.getAttribute("content") : "";
  }

  function encode(s) {
    const d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }

  function showResult(html, tone) {
    if (!resultEl) return;
    resultEl.hidden = false;
    resultEl.className = "scan-result" + (tone ? " " + tone : "");
    resultEl.innerHTML = html;
  }

  function readyNextScan(msg) {
    if (settleTimer) {
      clearTimeout(settleTimer);
      settleTimer = null;
    }
    pauseDecode = false;
    busy = false;
    pauseDecode = false;
    busy = false;
    if (statusEl) statusEl.textContent = msg || "Next.";
    unfreezeScan();
  }

  function qtyChips() {
    return (
      [1, 5, 10]
        .map(function (n) {
          return '<button type="button" class="chip" data-qty-now="' + n + '">' + n + "</button>";
        })
        .join("") +
      '<form class="scan-enter" data-qty-form>' +
      '<input type="number" min="1" step="1" inputmode="numeric" data-qty-enter placeholder="3" aria-label="Count">' +
      '<button type="submit" class="chip">Enter</button>' +
      "</form>"
    );
  }

  function productPic(data) {
    const src = (data && (data.image_url || data.thumb_url)) || "";
    const letter = encode(((data && data.name) || "?").charAt(0).toUpperCase());
    return (
      '<span class="row-pic">' +
      (src
        ? '<img src="' +
          encodeURI(src) +
          '" alt="" referrerpolicy="no-referrer" onerror="this.remove()">'
        : "") +
      "<span>" +
      letter +
      "</span></span>"
    );
  }

  function flashToast(data) {
    const live = document.getElementById("scan-live");
    if (!resultEl || !live || live.hidden) return false;
    const qty = data.quantity_label != null ? data.quantity_label : data.quantity;
    const job = getScanJob();
    let html =
      productPic(data) +
      "<strong>" +
      encode(data.name || "Item") +
      "</strong> " +
      encode(String(qty != null ? qty : "")) +
      " now · 1, 5, 10, or type it " +
      qtyChips();
    if (data.ask_list) {
      html +=
        ' <button type="button" class="btn sm" data-add-list data-barcode="' +
        encode(data.barcode || "") +
        '">Add to list</button>';
    }
    resultEl.hidden = false;
    resultEl.className = "scan-toast";
    resultEl.innerHTML = html;
    resultEl.dataset.barcode = data.barcode || "";
    resultEl.dataset.jobAction = job === "mix" ? "" : actionForJob();
    freezeScan();
    return true;
  }

  function snapFrame() {
    const video = document.querySelector("#scan-live-reader video");
    const canvas = document.getElementById("scan-freeze");
    if (!video || !canvas || !video.videoWidth) return;
    try {
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      canvas.getContext("2d").drawImage(video, 0, 0);
      canvas.hidden = false;
    } catch (e) {}
  }

  function freezeScan() {
    snapFrame();
    pauseDecode = true;
    try {
      if (liveSlot.qr && liveSlot.qr.pause) liveSlot.qr.pause(true);
    } catch (e) {}
  }

  function unfreezeScan() {
    const canvas = document.getElementById("scan-freeze");
    if (canvas) canvas.hidden = true;
    pauseDecode = false;
    try {
      if (liveSlot.qr && liveSlot.qr.resume) liveSlot.qr.resume();
    } catch (e) {}
  }

  function flushPending(amount) {
    if (settleTimer) {
      clearTimeout(settleTimer);
      settleTimer = null;
    }
    const p = pending;
    pending = null;
    pauseDecode = false;
    if (!p) {
      unfreezeScan();
      return Promise.resolve();
    }
    return applyBarcode(p.barcode, p.action, false, amount || 1).then(function () {
      if (resultEl) {
        resultEl.hidden = false;
        resultEl.className = "scan-toast";
        resultEl.innerHTML = "<strong>" + encode(String(amount || 1)) + " done.</strong> Next box.";
      }
      unfreezeScan();
      if (settleTimer) clearTimeout(settleTimer);
      settleTimer = setTimeout(function () {
        if (resultEl) {
          resultEl.hidden = true;
          resultEl.innerHTML = "";
        }
      }, 900);
    });
  }

  function flashMixPick(data) {
    const live = document.getElementById("scan-live");
    if (!resultEl || !live || live.hidden) return false;
    resultEl.hidden = false;
    resultEl.className = "scan-toast";
    resultEl.dataset.barcode = data.barcode || "";
    resultEl.innerHTML =
      "<strong>" +
      encode(data.name || "Item") +
      "</strong>" +
      '<button type="button" class="btn sm" data-mix="into">Incoming</button>' +
      '<button type="button" class="btn sm terracotta" data-mix="consume">Used</button>' +
      '<button type="button" class="btn sm" data-mix="buy">Needed</button>';
    return true;
  }

  function isUpcLike(raw) {
    return /^\d{8,14}$/.test(String(raw || "").replace(/\s/g, ""));
  }
  function extractVin(raw) {
    let t = String(raw || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
    if (t.length >= 18 && t.charAt(0) === "I" && /^[A-HJ-NPR-Z0-9]{17}$/.test(t.slice(1, 18))) {
      return t.slice(1, 18);
    }
    const m = t.match(/[A-HJ-NPR-Z0-9]{17}/g) || [];
    for (let i = 0; i < m.length; i++) {
      if (/^[A-HJ-NPR-Z0-9]{17}$/.test(m[i]) && !/[IOQ]/.test(m[i])) return m[i];
    }
    return null;
  }
  function isVinLike(raw) {
    return !!extractVin(raw);
  }
  function isFamilyQr(raw) {
    return /^FAM:/i.test(String(raw || ""));
  }
  function isWebQr(raw) {
    return /^https?:\/\//i.test(String(raw || "").trim());
  }
  function preferUpc(decoded) {
    const s = String(decoded || "").trim();
    const vin = extractVin(s);
    if (vin) return vin;
    if (isUpcLike(s) || isFamilyQr(s)) return s;
    if (window.FAMILY_SCAN_INTO && isWebQr(s)) return null;
    return s.replace(/^\*+|\*+$/g, "");
  }

  function statusClass(data) {
    if (data.status === "want") return "want";
    if (data.status === "out") return "out";
    if (data.status === "low" || data.needs_restock) return "low";
    if (data.is_in_stock === false && data.status !== "ok") return "out";
    return "ok";
  }

  function statusLabel(tone) {
    if (tone === "want") return "Want";
    if (tone === "out") return "Had — out";
    if (tone === "low") return "Need more";
    return "Have";
  }

  function groceryCard(data) {
    const tone = statusClass(data);
    const qty = data.quantity_label != null ? data.quantity_label : data.quantity;
    const unit = data.unit || "";
    const meta = [];
    if (data.brand) meta.push(data.brand);
    if (data.location) meta.push(data.location);
    if (data.allergens) meta.push("Allergens: " + data.allergens);
    const img = productPic(data);
    let factsHtml = "";
    if (data.facts && typeof data.facts === "object") {
      const bits = ["ingredients", "serving_size", "energy_kcal", "nutriscore"];
      const lines = bits
        .map(function (k) {
          return data.facts[k] ? "<div><dt>" + encode(k.replace(/_/g, " ")) + "</dt><dd>" + encode(data.facts[k]) + "</dd></div>" : "";
        })
        .join("");
      if (lines) factsHtml = '<dl class="facts">' + lines + "</dl>";
    }
    const listLine = data.on_list
      ? '<p class="muted">On the basket.</p>'
      : "";
    const buttons =
      '<button type="button" class="btn" data-rescan="set">That\'s how many we have</button>' +
      '<button type="button" class="btn" data-rescan="into">Add that many more</button>' +
      '<button type="button" class="btn terracotta" data-rescan="just_used">Used / out</button>' +
      '<button type="button" class="btn secondary" data-skip-place data-rescan="set">No room — just the count</button>';
    const places = Array.isArray(data.places) ? data.places : [];
    const here = data.location || (data.ai_report && data.ai_report.location) || "";
    const placeHtml =
      places.length
        ? '<p class="kicker" style="margin:.85rem 0 .35rem">Where?</p>' +
          '<div class="scan-qty" role="group" aria-label="Where">' +
          places
            .map(function (p) {
              const on = here && p.toLowerCase() === String(here).toLowerCase() ? " on" : "";
              return (
                '<button type="button" class="chip' +
                on +
                '" data-place="' +
                encode(p) +
                '">' +
                encode(p) +
                "</button>"
              );
            })
            .join("") +
          "</div>" +
          (data.needs_place && !data.ai_ready
            ? '<p class="muted">No AI key — tap a room, or skip.</p>'
            : data.needs_place
              ? '<p class="muted">AI did not pick a room. Tap one, or skip.</p>'
              : "")
        : "";
    return (
      '<div class="scan-status-card">' +
      '<span class="badge ' +
      (tone === "ok" ? "" : tone) +
      '">' +
      statusLabel(tone) +
      "</span>" +
      "<h2>" +
      encode(data.name) +
      "</h2>" +
      '<p class="qty">' +
      encode(qty) +
      ' <span class="muted">' +
      encode(unit) +
      (tone === "want" ? " in the house" : " on hand") +
      "</span></p>" +
      "<p><strong>" +
      encode(data.message || "") +
      "</strong></p>" +
      img +
      (meta.length ? '<p class="muted">' + encode(meta.join(" · ")) + "</p>" : "") +
      factsHtml +
      (function () {
        const r = data.ai_report;
        if (!r || typeof r !== "object") return "";
        const bits = [];
        if (r.used_ai) bits.push("AI");
        else bits.push("Guess");
        if (r.kind) bits.push(r.kind);
        if (r.location) bits.push("put in " + r.location);
        if (r.confidence != null && r.used_ai) bits.push(Math.round(Number(r.confidence) * 100) + "%");
        let html = '<div class="ai-report"><strong>' + encode(bits.join(" · ")) + "</strong>";
        if (r.why) html += "<p>" + encode(r.why) + "</p>";
        html += '<p class="muted">Change the place on the item if that is wrong.</p></div>';
        return html;
      })() +
      listLine +
      '<p class="kicker" style="margin:.85rem 0 .35rem">How many?</p>' +
      '<div class="scan-qty" role="group" aria-label="How many">' +
      '<button type="button" class="chip" data-qty-chip="1">1</button>' +
      '<button type="button" class="chip" data-qty-chip="5">5</button>' +
      '<button type="button" class="chip" data-qty-chip="10">10</button>' +
      '<input type="number" min="0" step="1" value="1" inputmode="numeric" data-scan-qty aria-label="Count">' +
      "</div>" +
      '<p class="muted">Tap 1, 2, 4… then next box. Camera stays on.</p>' +
      placeHtml +
      '<div class="scan-kid-actions">' +
      buttons +
      "</div>" +
      "</div>"
    );
  }

  function unknownCard(data) {
    const name = data.name || "This item";
    const extra = data.brand ? '<p class="muted">' + encode(data.brand) + "</p>" : "";
    const code = encodeURIComponent(data.barcode || "");
    const kind = data.kind || "";
    const kindLabel = data.kind_label || "New code";
    const suggested = data.suggested_type || (scanKind === "any" ? "grocery" : scanKind);
    const img = productPic(data);
    const kindBtns = [];
    const vehicles = data.vehicles || [];
    const tools = data.tools || [];
    if (vehicles.length) {
      vehicles.forEach(function (v) {
        kindBtns.push(
          '<button type="button" class="btn" data-quick="1" data-type="grocery" data-kind="' +
            encode(kind) +
            '" data-kind-label="' +
            encode(kindLabel) +
            '" data-linked="' +
            encode(v.id) +
            '" data-action="restock">Install on ' +
            encode(v.name) +
            "</button>"
        );
      });
    }
    if (tools.length) {
      tools.forEach(function (t) {
        kindBtns.push(
          '<button type="button" class="btn" data-quick="1" data-type="grocery" data-kind="' +
            encode(kind) +
            '" data-linked="' +
            encode(t.id) +
            '" data-action="restock">Save on ' +
            encode(t.name) +
            "</button>"
        );
      });
    }
    if (scanKind === "tool") {
      kindBtns.push(
        '<button type="button" class="btn" data-quick="1" data-type="tool" data-kind="tool">Save as tool</button>'
      );
    } else if (scanKind === "vehicle") {
      kindBtns.push(
        '<button type="button" class="btn" data-quick="1" data-type="vehicle">Save as vehicle</button>'
      );
    } else {
      if (suggested === "tool") {
        kindBtns.push(
          '<button type="button" class="btn" data-quick="1" data-type="tool" data-kind="' +
            encode(kind) +
            '">Save as tool</button>'
        );
      } else if (suggested === "vehicle") {
        kindBtns.push(
          '<button type="button" class="btn" data-quick="1" data-type="vehicle">Save as vehicle</button>'
        );
      } else if (!vehicles.length && !tools.length) {
        kindBtns.push(
          '<button type="button" class="btn warn" data-rescan="want">Want this</button>'
        );
        kindBtns.push(
          '<button type="button" class="btn" data-rescan="got_more">Got more</button>'
        );
      }
      if (!vehicles.length && kind && (data.attach_to === "vehicle" || data.attach_to === "tool")) {
        kindBtns.push(
          '<button type="button" class="btn" data-quick="1" data-type="grocery" data-kind="' +
            encode(kind) +
            '" data-kind-label="' +
            encode(kindLabel) +
            '" data-action="restock">Save in the garage</button>'
        );
      }
    }
    if (canCreate || data.can_create) {
      kindBtns.push(
        '<label class="btn secondary photo-btn">Photo if the UPC is wrong<input type="file" accept="image/*" capture="environment" hidden data-wrong-upc></label>'
      );
      kindBtns.push(
        '<a class="btn secondary" href="/items/new?type=' +
          encodeURIComponent(suggested || "grocery") +
          "&barcode=" +
          code +
          '">Type the rest</a>'
      );
    }
    return (
      '<div class="scan-status-card">' +
      '<span class="badge want">' +
      encode(kindLabel) +
      "</span>" +
      "<h2>" +
      encode(name) +
      "</h2>" +
      "<p><strong>" +
      encode(data.message || "New here. Is this food, a tool, or a vehicle? Tap one, or type the name.") +
      "</strong></p>" +
      extra +
      img +
      '<p class="muted">Code ' +
      encode(data.barcode) +
      "</p>" +
      '<div class="scan-kid-actions choice-grid">' +
      kindBtns.join("") +
      "</div>" +
      "</div>"
    );
  }

  function hostToast(data) {
    const host = data.host || window.FAMILY_SCAN_HOST || {};
    let html = productPic(data) + "<strong>" + encode(data.message || "Saved on this.") + "</strong>";
    if (data.undo_id) {
      html +=
        ' <button type="button" class="btn sm" data-scan-undo="' +
        encode(String(data.undo_id)) +
        '">Undo</button>';
    }
    if (data.ask_installed) {
      html += ' <button type="button" class="btn sm" data-rescan="install">Installed it</button>';
    }
    return html;
  }

  function installCard(data) {
    const host = data.host || window.FAMILY_SCAN_HOST || {};
    const hostLabel = host.name || "this";
    return (
      '<div class="scan-status-card">' +
      productPic(data) +
      "<h2>" +
      encode(data.name || "Item") +
      "</h2>" +
      "<p><strong>" +
      encode(data.message || "Did you install this on " + hostLabel + "?") +
      "</strong></p>" +
      (data.slot_label
        ? '<p class="muted">' + encode((data.system_label || "") + " · " + data.slot_label) + "</p>"
        : "") +
      '<div class="scan-kid-actions">' +
      '<button type="button" class="btn" data-rescan="install">Installed it</button>' +
      '<button type="button" class="btn secondary" data-rescan="stash">Just save on ' +
      encode(hostLabel) +
      "</button>" +
      '<button type="button" class="btn secondary" data-skip-host data-rescan="into">Not this one</button>' +
      "</div></div>"
    );
  }

  function vinDiffCard(data) {
    const diffs = data.diffs || [];
    const rows = diffs
      .map(function (d) {
        return (
          '<label class="vin-diff-row"><input type="checkbox" data-vin-field="' +
          encode(d.field) +
          '" checked><span><strong>' +
          encode(d.label) +
          '</strong><span class="muted">' +
          encode(d.ours || "—") +
          " → " +
          encode(d.theirs) +
          "</span></span></label>"
        );
      })
      .join("");
    return (
      '<div class="scan-status-card">' +
      "<h2>" +
      encode(data.name || "Vehicle") +
      "</h2>" +
      "<p><strong>" +
      encode(data.message || "NHTSA has different info. Update ours?") +
      "</strong></p>" +
      rows +
      '<div class="scan-kid-actions">' +
      '<button type="button" class="btn" data-apply-vin>Update these</button>' +
      '<button type="button" class="btn secondary" data-skip-vin>Keep ours</button>' +
      (data.item_id
        ? '<a class="btn secondary" href="/items/' + data.item_id + '">Open</a>'
        : "") +
      "</div></div>"
    );
  }

  async function quickSave(opts) {
    if (busy) return;
    busy = true;
    statusEl.textContent = "Saving…";
    try {
      const fd = new FormData();
      fd.append("name", opts.name || "");
      fd.append("item_type", opts.type || "grocery");
      fd.append("barcode", opts.barcode || "");
      fd.append("kind", opts.kind || "");
      fd.append("kind_label", opts.kindLabel || "");
      fd.append("linked_item_id", opts.linked || "");
      fd.append("action", opts.action || "check");
      fd.append("caption", opts.caption || "");
      if (opts.photo) fd.append("photo", opts.photo);
      const res = await fetch("/api/items/quick", {
        method: "POST",
        headers: { "X-CSRF-Token": csrfToken() },
        body: fd,
      });
      const data = await res.json().catch(function () {
        return {};
      });
      if (!res.ok || !data.item_id) {
        statusEl.textContent = data.error || "Could not save. Try again.";
        return;
      }
      statusEl.textContent = "Saved.";
      window.location.href = "/items/" + data.item_id;
    } catch (err) {
      statusEl.textContent = "Could not save. Try again.";
    } finally {
      busy = false;
    }
  }

  function mileageCard(data) {
    const isTool = data.item_type === "tool";
    const field = isTool ? "hours" : "mileage";
    const current = isTool
      ? data.hours_used != null
        ? data.hours_used
        : ""
      : data.current_mileage != null
        ? data.current_mileage
        : "";
    const label = isTool ? "Hours on this tool" : "Miles on the dash";
    const btn = isTool ? "Log hours" : "Log miles";
    const link = data.item_id
      ? '<p><a class="btn secondary" href="/items/' + data.item_id + '">Open ' + encode(data.name || "item") + "</a></p>"
      : "";
    return (
      '<div class="scan-status-card">' +
      "<h2>" +
      encode(data.name || "") +
      "</h2>" +
      "<p><strong>" +
      encode(data.message || "Opened.") +
      "</strong></p>" +
      '<form class="mileage-form" data-mileage-form data-item="' +
      encode(data.item_id || "") +
      '" data-field="' +
      field +
      '">' +
      "<label>" +
      encode(label) +
      "</label>" +
      '<div class="btn-row">' +
      '<input name="' +
      field +
      '" inputmode="numeric" value="' +
      encode(current) +
      '" placeholder="' +
      (isTool ? "Hours" : "87432") +
      '">' +
      '<button class="btn" type="submit">' +
      encode(btn) +
      "</button>" +
      "</div></form>" +
      link +
      "</div>"
    );
  }

  function qtyFromCard() {
    const el = resultEl && resultEl.querySelector("[data-scan-qty]");
    if (!el) return 1;
    const n = parseFloat(String(el.value || "1").replace(",", "."));
    return isFinite(n) && n >= 0 ? n : 1;
  }
  function placeFromCard() {
    const on = resultEl && resultEl.querySelector("[data-place].on");
    return on ? on.getAttribute("data-place") || "" : "";
  }

  async function applyBarcode(barcode, forcedAction, fromQueue, amount, extra) {
    barcode = preferUpc(barcode);
    if (!barcode) return;
    if (!forcedAction && pending && pending.barcode && pending.barcode !== barcode) {
      const hold = barcode;
      return flushPending(1).then(function () {
        return applyBarcode(hold, null, fromQueue, amount, extra);
      });
    }
    if (busy) return;
    if (!statusEl) statusEl = document.getElementById("scan-live-status") || document.getElementById("scan-status");
    if (!resultEl) resultEl = document.getElementById("scan-live-result") || document.getElementById("scan-result");
    if (!statusEl) return;
    const now = Date.now();
    if (!forcedAction && pauseDecode) return;
    if (!forcedAction && barcode === lastCode && now - lastAt < 1800) return;
    lastCode = barcode;
    lastAt = now;
    busy = true;
    if (!forcedAction) freezeScan();
    const verb =
      forcedAction === "just_used" || forcedAction === "consume"
        ? "Marking just used…"
        : forcedAction === "need_more"
          ? "Marking needs more…"
          : forcedAction === "want"
            ? "Adding to the want list…"
            : forcedAction === "got_more" || forcedAction === "restock"
            ? "Adding what you got…"
            : forcedAction === "set"
            ? "Setting the count…"
            : "Looking it up…";
    statusEl.textContent = verb;
    if (!navigator.onLine && !fromQueue) {
      enqueueScan(barcode, forcedAction || "check");
      busy = false;
      return;
    }
    try {
      const res = await fetch("/scan/apply", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken(),
        },
        body: JSON.stringify({
          barcode: barcode,
          action: forcedAction || (function () {
            const liveOn = document.getElementById("scan-live") && !document.getElementById("scan-live").hidden;
            if (!liveOn) return scanKind === "basket" ? "got_more" : "check";
            if (getScanJob() === "mix") return "check";
            return "check";
          })(),
          amount: amount != null ? amount : window.FAMILY_SCAN_INTO ? 1 : 1,
          location: extra && extra.location != null ? extra.location : placeFromCard(),
          skip_place: extra && extra.skip_place ? true : false,
          skip_host: extra && extra.skip_host ? true : false,
          create_new: addFormOpen() || (extra && extra.create_new) ? true : false,
          host_item_id: extra && extra.skip_host ? null : (window.FAMILY_SCAN_HOST && window.FAMILY_SCAN_HOST.id) || null,
          fields: extra && extra.fields ? extra.fields : undefined,
        }),
      });
      if (!res.ok) {
        let err = "Could not update the household. Try again.";
        try {
          const fail = await res.json();
          if (fail && fail.error) err = fail.error;
        } catch (e) {}
        statusEl.textContent = err;
        return;
      }
      const data = await res.json();
      resultEl.dataset.barcode = data.barcode || barcode;
      if (data.create) {
        showResult(unknownCard(data), "want");
        statusEl.textContent = "Not in the house yet.";
        return;
      }
      if (data.ask_update) {
        showResult(vinDiffCard(data), "ok");
        statusEl.textContent = "Review what would change.";
        pauseDecode = true;
        return;
      }
      if (data.attached) {
        lastUndoId = data.undo_id || lastUndoId;
        paintHostBanner();
        showResult(hostToast(data), statusClass(data));
        statusEl.textContent = data.message || "On this equipment. Undo if that’s wrong.";
        pauseDecode = false;
        unfreezeScan();
        return;
      }
      if (data.ask_install) {
        showResult(installCard(data), statusClass(data));
        statusEl.textContent = "Installed, or just save it here?";
        pauseDecode = true;
        return;
      }
      if (scanKind === "basket") {
        showResult(
          "<p><strong>" +
            encode(data.message || "Updated the basket.") +
            "</strong></p>",
          statusClass(data)
        );
        statusEl.textContent = "Scan the next thing in the cart.";
        window.dispatchEvent(new Event("family-basket-refresh"));
        return;
      }
      if (data.item_type === "grocery") {
        const liveOn = document.getElementById("scan-live") && !document.getElementById("scan-live").hidden;
        if (liveOn && !forcedAction && getScanJob() === "mix" && flashMixPick(data)) {
          pending = { barcode: data.barcode || barcode, action: "into" };
          statusEl.textContent = "Incoming, used, or needed — then how many.";
          pauseDecode = true;
          return;
        }
        if (liveOn && !forcedAction) {
          pending = { barcode: data.barcode || barcode, action: actionForJob() };
          flashToast(data);
          statusEl.textContent = "Tap 2, 4, 10… or next box = 1.";
          pauseDecode = false;
          return;
        }
        if (flashToast(data)) {
          statusEl.textContent = data.message || "Next.";
          pauseDecode = false;
          return;
        }
        showResult(groceryCard(data), statusClass(data));
        statusEl.textContent = encode(data.name || "") + " · next.";
        pauseDecode = false;
        return;
      }
      if (data.item_type === "vehicle") {
        const open =
          data.item_id
            ? ' <a class="btn sm" href="/items/' + data.item_id + '">Open</a>'
            : "";
        showResult(
          "<strong>" + encode(data.message || "Vehicle saved.") + "</strong>" + open,
          "ok"
        );
        statusEl.textContent = data.message || "Vehicle saved.";
        pauseDecode = false;
        unfreezeScan();
        return;
      }
      if (data.item_type === "tool") {
        showResult(mileageCard(data));
        statusEl.textContent = "Type the reading, or scan the next thing.";
        return;
      }
      const link = data.item_id
        ? '<p><a class="btn" href="/items/' + data.item_id + '">Open ' + encode(data.name || "item") + "</a></p>"
        : "";
      showResult("<p><strong>" + encode(data.message || "Updated.") + "</strong></p>" + link);
      statusEl.textContent = "Ready for the next scan.";
    } catch (err) {
      if (!fromQueue) enqueueScan(barcode, forcedAction || "check");
      else statusEl.textContent = "Scan failed. Try again.";
    } finally {
      busy = false;
    }
  }

  function bindResult(el) {
    if (!el || el.dataset.scanBound) return;
    el.dataset.scanBound = "1";
    el.addEventListener("click", function (e) {
      const chip = e.target.closest("[data-qty-chip]");
      if (chip) {
        const input = el.querySelector("[data-scan-qty]");
        const n = chip.getAttribute("data-qty-chip") || "1";
        if (input) input.value = n;
        el.querySelectorAll("[data-qty-chip]").forEach(function (c) {
          c.classList.toggle("on", c === chip);
        });
        const code = el.dataset.barcode;
        if (code && window.FAMILY_SCAN_INTO) {
          if (settleTimer) clearTimeout(settleTimer);
          lastAt = 0;
          applyBarcode(code, "set", false, parseFloat(n) || 1, {
            location: placeFromCard(),
          }).then(function () {
            readyNextScan("Set to " + n + ". Next.");
          });
        }
        return;
      }
      const place = e.target.closest("[data-place]");
      if (place) {
        el.querySelectorAll("[data-place]").forEach(function (c) {
          c.classList.toggle("on", c === place);
        });
        return;
      }
      const qtyNow = e.target.closest("[data-qty-now]");
      if (qtyNow) {
        const n = parseFloat(qtyNow.getAttribute("data-qty-now") || "1") || 1;
        pauseDecode = false;
        flushPending(n);
        return;
      }
      const mix = e.target.closest("[data-mix]");
      if (mix) {
        const code = el.dataset.barcode;
        pauseDecode = false;
        if (code) {
          pending = { barcode: code, action: mix.getAttribute("data-mix") || "into" };
          flashToast({ name: el.querySelector("strong") ? el.querySelector("strong").textContent : "Item", barcode: code, quantity: "" });
          statusEl.textContent = "How many this scan?";
          pauseDecode = false;
        }
        return;
      }
      const addList = e.target.closest("[data-add-list]");
      if (addList) {
        const code = addList.getAttribute("data-barcode") || el.dataset.barcode;
        if (code) applyBarcode(code, "need_more", false, 1);
        return;
      }
      const applyVin = e.target.closest("[data-apply-vin]");
      if (applyVin) {
        const code = el.dataset.barcode;
        const fields = [];
        el.querySelectorAll("[data-vin-field]:checked").forEach(function (box) {
          fields.push(box.getAttribute("data-vin-field"));
        });
        if (code) applyBarcode(code, "apply_vin", false, 1, { fields: fields });
        return;
      }
      const skipVin = e.target.closest("[data-skip-vin]");
      if (skipVin) {
        statusEl.textContent = "Kept ours.";
        readyNextScan("Kept ours. Next.");
        return;
      }
      const undoBtn = e.target.closest("[data-scan-undo]");
      if (undoBtn) {
        undoScan(undoBtn.getAttribute("data-scan-undo"));
        return;
      }
      resultEl = el;
      const quick = e.target.closest("[data-quick]");
      if (quick) {
        const code = resultEl.dataset.barcode;
        const heading = resultEl.querySelector("h2");
        quickSave({
          name: heading ? heading.textContent : "",
          type: quick.getAttribute("data-type") || "grocery",
          barcode: code,
          kind: quick.getAttribute("data-kind") || "",
          kindLabel: quick.getAttribute("data-kind-label") || "",
          linked: quick.getAttribute("data-linked") || "",
          action: quick.getAttribute("data-action") || "check",
        });
        return;
      }
      const btn = e.target.closest("[data-rescan]");
      if (!btn) return;
      const code = resultEl.dataset.barcode;
      if (!code) return;
      lastAt = 0;
      if (settleTimer) clearTimeout(settleTimer);
      applyBarcode(code, btn.getAttribute("data-rescan"), false, qtyFromCard(), {
        location: placeFromCard(),
        skip_place: !!btn.hasAttribute("data-skip-place"),
        skip_host: !!btn.hasAttribute("data-skip-host"),
      }).then(function () {
        readyNextScan("Saved. Next.");
      });
    });
    el.addEventListener("submit", function (e) {
      const qtyForm = e.target.closest("[data-qty-form]");
      if (qtyForm) {
        e.preventDefault();
        const input = qtyForm.querySelector("[data-qty-enter]");
        const n = parseFloat((input && input.value) || "0");
        if (n > 0) {
          pauseDecode = false;
          flushPending(n);
        }
        return;
      }
      const form = e.target.closest("[data-mileage-form]");
      if (!form) return;
      e.preventDefault();
      const itemId = form.getAttribute("data-item");
      if (!itemId) return;
      const fd = new FormData(form);
      fd.append("next", "scan");
      fetch("/items/" + itemId + "/mileage", {
        method: "POST",
        headers: { "X-CSRF-Token": csrfToken() },
        body: fd,
      }).then(function (res) {
        statusEl.textContent = res.ok ? "Saved the reading." : "Could not save miles.";
      }).catch(function () {
        statusEl.textContent = "Could not save miles.";
      });
    });
    el.addEventListener("change", function (e) {
      const input = e.target.closest("[data-wrong-upc]");
      if (!input || !input.files || !input.files[0]) return;
      const code = resultEl.dataset.barcode;
      const heading = resultEl.querySelector("h2");
      quickSave({
        name: heading ? heading.textContent : "Photo item",
        type: "grocery",
        barcode: code,
        kind: "",
        caption: "UPC was wrong — this is the actual item",
        photo: input.files[0],
        action: "check",
      });
    });
  }
  bindResult(pageResult);
  bindResult(liveResult);

  if (manualForm) {
    manualForm.addEventListener("submit", function (e) {
      e.preventDefault();
      const v = document.getElementById("manual-barcode").value.trim();
      lastAt = 0;
      applyBarcode(v);
    });
  }

  let qrLive = null;
  let qrPage = null;

  function decoderFormats() {
    const F = window.Html5QrcodeSupportedFormats;
    if (!F) return undefined;
    return [
      F.CODE_39,
      F.CODE_128,
      F.CODE_93,
      F.CODABAR,
      F.PDF_417,
      F.DATA_MATRIX,
      F.AZTEC,
      F.QR_CODE,
      F.ITF,
      F.UPC_A,
      F.UPC_E,
      F.EAN_13,
      F.EAN_8,
    ].filter(function (x) {
      return x != null;
    });
  }

  function scanConfig() {
    return {
      fps: 16,
      disableFlip: false,
      rememberLastUsedCamera: true,
      qrbox: function (w, h) {
        return {
          width: Math.max(Math.floor(w * 0.86), 160),
          height: Math.max(Math.floor(h * 0.7), 160),
        };
      },
    };
  }

  function startOn(readerId, instanceSlot, onReady, onFail) {
    if (typeof Html5Qrcode === "undefined") {
      if (onFail) onFail("Camera library failed to load. Type a barcode.");
      return;
    }
    const host = document.getElementById(readerId);
    if (!host) {
      if (onFail) onFail("No camera box.");
      return;
    }
    if (instanceSlot.starting) return;
    if (instanceSlot.qr && instanceSlot.qr.isScanning) return;
    try {
      host.innerHTML = "";
    } catch (e) {}
    let qr;
    try {
      qr = new Html5Qrcode(readerId, {
        verbose: false,
        formatsToSupport: decoderFormats(),
        experimentalFeatures: { useBarCodeDetectorIfSupported: false },
      });
    } catch (e) {
      if (onFail) onFail("Could not start the camera box.");
      return;
    }
    instanceSlot.qr = qr;
    instanceSlot.starting = true;
    function go(target) {
      return qr.start(target, scanConfig(), function (decoded) {
        const code = preferUpc(decoded);
        if (!code) return;
        applyBarcode(code);
      });
    }
    go({ facingMode: { ideal: "environment" }, width: { ideal: 1920 }, height: { ideal: 1080 } })
      .then(function () {
        instanceSlot.starting = false;
        if (onReady) onReady();
      })
      .catch(function () {
        return Html5Qrcode.getCameras().then(function (cameras) {
          const cam =
            (cameras || []).find(function (c) {
              return /back|rear|environment/i.test(c.label || "");
            }) || (cameras || [])[0];
          if (!cam) throw new Error("no camera");
          return go(cam.id);
        });
      })
      .then(function () {
        instanceSlot.starting = false;
        if (onReady) onReady();
      })
      .catch(function () {
        instanceSlot.starting = false;
        if (onFail) onFail("Camera permission needed, or type a barcode.");
      });
  }

  function stopQr(slot) {
    if (!slot || !slot.qr) return Promise.resolve();
    const q = slot.qr;
    slot.qr = null;
    slot.starting = false;
    try {
      return q
        .stop()
        .then(function () {
          try {
            q.clear();
          } catch (e) {}
        })
        .catch(function () {});
    } catch (e) {
      return Promise.resolve();
    }
  }

  const pageSlot = {};
  const liveSlot = {};

  function startPageCamera() {
    const readerEl = document.getElementById("reader");
    const openBtn = document.getElementById("scan-open-camera");
    if (readerEl) readerEl.hidden = false;
    if (openBtn) openBtn.hidden = true;
    statusEl = pageStatus || statusEl;
    resultEl = pageResult || resultEl;
    startOn(
      "reader",
      pageSlot,
      function () {
        if (pageStatus) pageStatus.textContent = "Camera on. Door tags and parts codes — fill the tall slot.";
      },
      function (msg) {
        if (pageStatus) pageStatus.textContent = msg;
        if (openBtn) openBtn.hidden = false;
      }
    );
  }

  function liveScanOpen() {
    const live = document.getElementById("scan-live");
    return !!(live && !live.hidden);
  }

  function restartLiveCamera() {
    if (!liveScanOpen()) return;
    if (liveSlot.restarting) return;
    liveSlot.restarting = true;
    const ready = function () {
      liveSlot.restarting = false;
      setScanJob(getScanJob());
      if (statusEl) statusEl.textContent = "Door tag / part code — fill the tall slot.";
    };
    const fail = function (msg) {
      liveSlot.restarting = false;
      if (statusEl) statusEl.textContent = msg;
    };
    stopQr(liveSlot).then(function () {
      startOn("scan-live-reader", liveSlot, ready, fail);
    });
  }

  let rotateTimer = null;
  let lastScanWH = "";
  function onScanRotate() {
    if (!liveScanOpen()) return;
    const key = String(window.innerWidth) + "x" + String(window.innerHeight);
    if (key === lastScanWH) return;
    clearTimeout(rotateTimer);
    rotateTimer = setTimeout(function () {
      lastScanWH = String(window.innerWidth) + "x" + String(window.innerHeight);
      restartLiveCamera();
    }, 450);
  }

  function openLiveScan(e) {
    if (e) {
      e.preventDefault();
      e.stopPropagation();
    }
    window.FAMILY_SCAN_INTO = true;
    const live = document.getElementById("scan-live");
    if (!live) return;
    live.hidden = false;
    document.body.classList.add("scan-live-open");
    document.documentElement.classList.add("scan-live-open");
    lastScanWH = String(window.innerWidth) + "x" + String(window.innerHeight);
    statusEl = document.getElementById("scan-live-status") || statusEl;
    resultEl = document.getElementById("scan-live-result") || resultEl;
    setScanJob(getScanJob());
    paintHostBanner();
    if (statusEl) statusEl.textContent = "Opening camera…";
    startOn(
      "scan-live-reader",
      liveSlot,
      function () {
        setScanJob(getScanJob());
      },
      function (msg) {
        if (statusEl) statusEl.textContent = msg;
      }
    );
  }
  window.familyOpenScan = openLiveScan;

  function closeLiveScan() {
    const live = document.getElementById("scan-live");
    stopQr(liveSlot);
    if (live) live.hidden = true;
    document.body.classList.remove("scan-live-open");
    document.documentElement.classList.remove("scan-live-open");
    if (pageStatus) statusEl = pageStatus;
    if (pageResult) resultEl = pageResult;
  }

  const openBtn = document.getElementById("scan-open-camera");
  if (openBtn) {
    openBtn.addEventListener("click", function (e) {
      e.preventDefault();
      startPageCamera();
    });
  }
  document.addEventListener("click", function (e) {
    const hit = e.target.closest("#scan-fab, [data-open-scan]");
    if (!hit) return;
    openLiveScan(e);
  });
  document.querySelectorAll("[data-scan-job]").forEach(function (el) {
    el.addEventListener("click", function () {
      setScanJob(el.getAttribute("data-scan-job") || "in");
    });
  });
  const liveClose = document.getElementById("scan-live-close");
  if (liveClose) liveClose.addEventListener("click", closeLiveScan);
  window.addEventListener("orientationchange", onScanRotate);
  window.addEventListener("resize", onScanRotate);
  if (screen.orientation) {
    screen.orientation.addEventListener("change", onScanRotate);
  }

  async function undoScan(aid) {
    if (!aid) return;
    try {
      const res = await fetch("/scan/undo", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken(),
        },
        body: JSON.stringify({ undo_id: aid }),
      });
      const data = await res.json().catch(function () {
        return {};
      });
      if (String(lastUndoId) === String(aid)) lastUndoId = null;
      paintHostBanner();
      if (statusEl) statusEl.textContent = data.message || (data.ok ? "Undone." : "Could not undo.");
      if (resultEl) {
        resultEl.hidden = false;
        resultEl.className = "scan-toast";
        resultEl.innerHTML = "<strong>" + encode(data.message || "Undone.") + "</strong>";
      }
      readyNextScan(data.message || "Undone. Next.");
    } catch (e) {
      if (statusEl) statusEl.textContent = "Could not undo.";
    }
  }

  const hostUndo = document.getElementById("scan-host-undo");
  if (hostUndo) {
    hostUndo.addEventListener("click", function () {
      undoScan(lastUndoId);
    });
  }
  const hostClear = document.getElementById("scan-host-clear");
  if (hostClear) {
    hostClear.addEventListener("click", function () {
      window.FAMILY_SCAN_HOST = null;
      lastUndoId = null;
      paintHostBanner();
      setScanJob(getScanJob());
      if (statusEl) statusEl.textContent = "Scanning anything.";
    });
  }
  const addFold = document.getElementById("add-vehicle");
  if (addFold) {
    addFold.addEventListener("toggle", function () {
      paintHostBanner();
      setScanJob(getScanJob());
    });
  }
  paintHostBanner();
  flushQueue();
})();
