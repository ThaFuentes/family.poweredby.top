/* Scan identifies the item. Kids then tap Just used / Needs more / Got more. */
(function () {
  const statusEl = document.getElementById("scan-status");
  const resultEl = document.getElementById("scan-result");
  const manualForm = document.getElementById("manual-form");
  const canCreate = window.FAMILY_CAN_CREATE === true;
  const scanKind = window.FAMILY_SCAN_KIND || "any";
  if (!statusEl || !resultEl) return;
  let busy = false;
  let lastCode = "";
  let lastAt = 0;
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
    resultEl.hidden = false;
    resultEl.className = "scan-result" + (tone ? " " + tone : "");
    resultEl.innerHTML = html;
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
    const img = data.image_url
      ? '<img class="detail-photo" src="' + encodeURI(data.image_url) + '" alt="">'
      : "";
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
      tone === "want"
        ? '<button type="button" class="btn warn" data-rescan="want">Want this</button>' +
          '<button type="button" class="btn" data-rescan="got_more">Got more</button>'
        : '<button type="button" class="btn terracotta" data-rescan="just_used">Just used</button>' +
          '<button type="button" class="btn warn" data-rescan="need_more">Needs more</button>' +
          '<button type="button" class="btn" data-rescan="got_more">Got more</button>';
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
      listLine +
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
    const img = data.image_url
      ? '<img class="detail-photo" src="' + encodeURI(data.image_url) + '" alt="">'
      : "";
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
      encode(data.message || "Not in the household yet. Scan captured the code — type the rest, or tap Want.") +
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

  async function applyBarcode(barcode, forcedAction, fromQueue) {
    if (!barcode || busy) return;
    const now = Date.now();
    if (!forcedAction && barcode === lastCode && now - lastAt < 2500) return;
    lastCode = barcode;
    lastAt = now;
    busy = true;
    const verb =
      forcedAction === "just_used" || forcedAction === "consume"
        ? "Marking just used…"
        : forcedAction === "need_more"
          ? "Marking needs more…"
          : forcedAction === "want"
            ? "Adding to the want list…"
            : forcedAction === "got_more" || forcedAction === "restock"
            ? "Adding what you got…"
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
          action: forcedAction || (scanKind === "basket" ? "got_more" : "check"),
          amount: 1,
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
        showResult(groceryCard(data), statusClass(data));
        statusEl.textContent = "Scan another, or tap what happened.";
        return;
      }
      if (data.item_type === "vehicle" || data.item_type === "tool") {
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

  if (resultEl) {
    resultEl.addEventListener("click", function (e) {
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
      applyBarcode(code, btn.getAttribute("data-rescan"));
    });
    resultEl.addEventListener("submit", function (e) {
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
    resultEl.addEventListener("change", function (e) {
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

  if (manualForm) {
    manualForm.addEventListener("submit", function (e) {
      e.preventDefault();
      const v = document.getElementById("manual-barcode").value.trim();
      lastAt = 0;
      applyBarcode(v);
    });
  }

  function startCamera() {
    if (typeof Html5Qrcode === "undefined") {
      statusEl.textContent = "Camera library failed to load. Type a barcode below.";
      return;
    }
    const qr = new Html5Qrcode("reader");
    Html5Qrcode.getCameras()
      .then(function (cameras) {
        const cam =
          cameras.find(function (c) {
            return /back|rear|environment/i.test(c.label);
          }) || cameras[0];
        if (!cam) {
          statusEl.textContent = "No camera found.";
          return;
        }
        return qr.start(
          cam.id,
          { fps: 8, qrbox: { width: 260, height: 260 } },
          function (decoded) {
            applyBarcode(decoded);
          }
        );
      })
      .then(function () {
        statusEl.textContent = "Camera on. Hold a barcode in the box.";
      })
      .catch(function () {
        statusEl.textContent = "Camera permission needed, or type a barcode.";
      });
  }

  const openBtn = document.getElementById("scan-open-camera");
  const readerEl = document.getElementById("reader");
  if (window.FAMILY_SCAN_AUTOSTART === false && openBtn) {
    openBtn.addEventListener("click", function () {
      if (readerEl) readerEl.hidden = false;
      openBtn.hidden = true;
      startCamera();
    });
  } else {
    startCamera();
  }
  flushQueue();
})();
