/* Store-mode basket: pick rows, then Got it (stock) or Drop (no stock). */
(function () {
  const root = document.getElementById("basket-live");
  if (!root) return;
  const bar = document.getElementById("basket-bulk");

  function csrfToken() {
    const m = document.querySelector('meta[name="csrf-token"]');
    return m ? m.getAttribute("content") : "";
  }

  function reasonText(reason) {
    if (reason === "out") return "Had it — now out";
    if (reason === "want" || reason === "manual") return "Want";
    if (reason === "need_more" || reason === "low" || reason === "auto_threshold") return "Need more";
    return reason || "Added";
  }
  function encode(s) {
    const d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }
  function picHtml(r) {
    const letter = encode((r.name || "?").charAt(0).toUpperCase());
    const src = r.image_url || "";
    return (
      '<span class="row-pic">' +
      (src
        ? '<img src="' +
          encodeURI(src) +
          '" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">'
        : "") +
      "<span>" +
      letter +
      "</span></span>"
    );
  }

  function boxes() {
    return Array.prototype.slice.call(root.querySelectorAll(".basket-check"));
  }
  function pickedIds() {
    return boxes()
      .filter(function (b) {
        return b.checked;
      })
      .map(function (b) {
        return b.getAttribute("data-pick");
      })
      .filter(Boolean);
  }
  function paintPicked() {
    boxes().forEach(function (b) {
      const row = b.closest(".basket-row");
      if (row) row.classList.toggle("picked", b.checked);
    });
  }

  function render(rows) {
    const want = rows.filter(function (r) { return r.reason === "want"; });
    const need = rows.filter(function (r) { return r.reason !== "want"; });
    let html = "";
    function block(title, group, list) {
      if (!list.length) return;
      html += "<h2>" + title + "</h2><div class=\"card list basket-list\" data-group=\"" + group + "\">";
      list.forEach(function (r) {
        html +=
          '<div class="basket-row" data-entry-id="' +
          r.id +
          '"><label class="basket-check-wrap"><input type="checkbox" class="basket-check" data-pick="' +
          r.id +
          '" aria-label="Select ' +
          encode(r.name || "") +
          '"></label>' +
          picHtml(r) +
          '<span class="basket-copy"><strong>' +
          encode(r.name || "") +
          '</strong><span class="muted">' +
          reasonText(r.reason) +
          (r.note ? " · " + encode(r.note) : "") +
          (r.quantity_needed ? " · get " + r.quantity_needed : "") +
          (r.place ? " · " + r.place : "") +
          '</span></span><button type="button" class="btn sm secondary basket-drop" data-drop="' +
          r.id +
          '" aria-label="Take ' +
          encode(r.name || "") +
          ' off the basket">Drop</button></div>';
      });
      html += "</div>";
    }
    block("Want", "want", want);
    block("Need", "need", need);
    if (!rows.length) {
      html =
        '<div class="card"><div class="empty"><strong>Basket is empty</strong>Scan something you want, or tap Needs more on what you have.</div></div>';
    }
    root.innerHTML = html;
  }

  async function refresh() {
    try {
      const res = await fetch("/groceries/list.json", { headers: { Accept: "application/json" } });
      if (!res.ok) return;
      const data = await res.json();
      render(data.rows || []);
    } catch (e) {}
  }

  async function runBulk(action, ids) {
    if (!ids.length) return;
    try {
      await fetch("/groceries/list/bulk", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
          "X-CSRF-Token": csrfToken(),
          "X-Requested-With": "fetch",
        },
        body: JSON.stringify({ action: action, ids: ids }),
      });
      await refresh();
      if (window.parent && window.parent !== window) {
        window.parent.postMessage({ family: "sheet-saved" }, "*");
      }
    } catch (e) {
      await refresh();
    }
  }

  async function drop(id) {
    await runBulk("drop", [id]);
  }

  root.addEventListener("change", function (e) {
    if (!e.target.closest("[data-pick]")) return;
    paintPicked();
  });
  root.addEventListener("click", function (e) {
    const btn = e.target.closest("[data-drop]");
    if (!btn) return;
    e.preventDefault();
    e.stopPropagation();
    drop(btn.getAttribute("data-drop"));
  });
  if (bar) {
    bar.addEventListener("click", function (e) {
      const all = e.target.closest("[data-basket-all]");
      if (all) {
        const on = boxes().some(function (b) {
          return !b.checked;
        });
        boxes().forEach(function (b) {
          b.checked = on;
        });
        paintPicked();
        return;
      }
      const ids = pickedIds();
      if (!ids.length) return;
      if (e.target.closest("[data-basket-got]")) {
        runBulk("got", ids);
        return;
      }
      if (e.target.closest("[data-basket-drop-sel]")) {
        runBulk("drop", ids);
      }
    });
  }

  window.addEventListener("family-basket-refresh", refresh);
  setInterval(refresh, 5000);
})();
