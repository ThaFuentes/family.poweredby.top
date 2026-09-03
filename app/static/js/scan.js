/* Full-screen camera scan → POST /scan/apply → route by result */
(function () {
  const statusEl = document.getElementById("scan-status");
  const resultEl = document.getElementById("scan-result");
  const actionEl = document.getElementById("scan-action");
  const manualForm = document.getElementById("manual-form");
  let busy = false;

  function csrfToken() {
    const m = document.querySelector('meta[name="csrf-token"]');
    return m ? m.getAttribute("content") : "";
  }

  function showResult(html) {
    resultEl.hidden = false;
    resultEl.className = "scan-result";
    resultEl.innerHTML = html;
  }

  async function applyBarcode(barcode) {
    if (!barcode || busy) return;
    busy = true;
    statusEl.textContent = "Updating household…";
    try {
      const res = await fetch("/scan/apply", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken(),
        },
        body: JSON.stringify({
          barcode: barcode,
          action: actionEl ? actionEl.value : "auto",
          amount: 1,
        }),
      });
      const data = await res.json();
      if (data.create) {
        showResult(
          "<p><strong>New to this household.</strong></p>" +
            "<p>Barcode " +
            encode(data.barcode) +
            "</p>" +
            '<p><a class="btn" href="/items/new?barcode=' +
            encodeURIComponent(data.barcode) +
            '">Create item</a></p>'
        );
        statusEl.textContent = "Unknown barcode.";
        return;
      }
      const msg = data.message || "Updated.";
      const extra = data.hint ? "<p class='muted'>" + encode(data.hint) + "</p>" : "";
      const link = data.item_id
        ? '<p><a class="btn" href="/items/' + data.item_id + '">Open ' + encode(data.name || "item") + "</a></p>"
        : "";
      showResult("<p><strong>" + encode(msg) + "</strong></p>" + extra + link);
      statusEl.textContent = "Ready for the next scan.";
      if (data.item_type && data.item_type !== "grocery" && data.item_id) {
        window.location.href = "/items/" + data.item_id;
      }
    } catch (err) {
      statusEl.textContent = "Scan failed. Try again.";
    } finally {
      busy = false;
    }
  }

  function encode(s) {
    const d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }

  if (manualForm) {
    manualForm.addEventListener("submit", function (e) {
      e.preventDefault();
      const v = document.getElementById("manual-barcode").value.trim();
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

  startCamera();
})();
