/**
 * Install-to-home / desktop app prompt for Family OS.
 * Same behavior as Aegis / MyVineChurch: native install sheet when the
 * browser supports it, Safari Home Screen steps on iPhone, remembered
 * Yes / Not now / Don't ask again per device.
 *
 * Copy and CTA follow the browser actually in use.
 * Apple users only ever see Safari Home Screen / Dock steps.
 * Android users only ever see that browser's install steps.
 *
 * Remembers Yes / Not now / Don't ask again per device (local + server).
 * Does not nag every page. Does not re-ask after install or "don't ask".
 */
(function () {
  const HOST = (location.hostname || "").toLowerCase();
  const APP =
    "Family OS";
  const SNOOZE_MS = 14 * 24 * 60 * 60 * 1000;
  const FINAL = { installed: 1, never: 1, dismissed: 1, no: 1, yes: 1 };

  const IOS_SHARE_SVG =
    '<svg class="family-pwa-share" width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">' +
      '<path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" ' +
        'd="M12 3v12M8 7l4-4 4 4M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7"/>' +
    "</svg>";

  function detectClient() {
    const ua = String(navigator.userAgent || "");
    const platform = String(navigator.platform || "");
    const maxTouch = Number(navigator.maxTouchPoints || 0);

    const iPadOS = /ipad/i.test(ua) || (/macintosh/i.test(ua) && maxTouch > 1);
    const iPhone = /iphone|ipod/i.test(ua);
    const appleMobile = iPhone || iPadOS;
    const android = /android/i.test(ua);
    const mac = /macintosh|mac os x/i.test(ua) && !iPadOS;
    const windows = /windows nt/i.test(ua);
    const chromeOS = /cros/i.test(ua);

    const appilix =
      /appilix|app3/i.test(ua) ||
      !!(window.appilix && typeof window.appilix.postMessage === "function");
    const inApp =
      !appilix &&
      /fbav|fban|instagram|line\/|twitter|linkedinapp|snapchat|wv\)/i.test(ua);

    const edge = /edgios|edga|edg\//i.test(ua);
    const opera = /opr\/|opt\/|opios/i.test(ua);
    const samsung = /samsungbrowser/i.test(ua);
    const firefox = /fxios|firefox\//i.test(ua);
    const chromeIOS = /crios/i.test(ua);
    const chrome =
      chromeIOS ||
      (/chrome|crmo/i.test(ua) && !edge && !opera && !samsung && !firefox);
    const safari =
      /safari/i.test(ua) &&
      !chromeIOS &&
      !/chrome|crmo|edg|edgios|fxios|firefox|opr|opt|opios|samsungbrowser/i.test(ua);

    let os = "other";
    if (appleMobile) os = iPadOS ? "ipados" : "ios";
    else if (android) os = "android";
    else if (mac) os = "macos";
    else if (windows) os = "windows";
    else if (chromeOS) os = "chromeos";

    let browser = "other";
    if (appilix) browser = "appilix";
    else if (samsung) browser = "samsung";
    else if (opera) browser = "opera";
    else if (edge) browser = "edge";
    else if (chrome) browser = "chrome";
    else if (firefox) browser = "firefox";
    else if (safari) browser = "safari";

    const family = appleMobile ? "apple" : android ? "android" : "desktop";
    const chromium = chrome || edge || opera || samsung;

    return {
      ua: ua,
      platform: platform,
      os: os,
      browser: browser,
      family: family,
      appleMobile: appleMobile,
      iPadOS: iPadOS,
      iPhone: iPhone,
      android: android,
      mac: mac,
      windows: windows,
      appilix: appilix,
      inApp: inApp,
      chromium: chromium,
      safari: safari,
    };
  }

  const CLIENT = detectClient();

  function browserLabel(client) {
    if (client.browser === "edge") return "Edge";
    if (client.browser === "samsung") return "Samsung Internet";
    if (client.browser === "opera") return "Opera";
    if (client.browser === "firefox") return "Firefox";
    if (client.browser === "safari") return "Safari";
    if (client.browser === "chrome") return "Chrome";
    return "this browser";
  }

  function surface() {
    if (CLIENT.appleMobile || CLIENT.android) return "phone";
    const coarse = window.matchMedia("(pointer: coarse)").matches;
    const narrow =
      Math.min(window.innerWidth || 900, (window.screen && window.screen.width) || 900) < 768;
    return coarse || narrow ? "phone" : "desktop";
  }

  function storageKey() {
    return "pwaChoice:" + HOST + ":" + surface();
  }

  function cookieName() {
    return "pwa_" + surface();
  }

  function sessionKey() {
    return "pwaShown:" + HOST + ":" + surface();
  }

  function isStandalone() {
    return (
      window.matchMedia("(display-mode: standalone)").matches ||
      window.matchMedia("(display-mode: window-controls-overlay)").matches ||
      window.matchMedia("(display-mode: minimal-ui)").matches ||
      window.navigator.standalone === true
    );
  }

  function alreadyInNativeShell() {
    return CLIENT.appilix || isStandalone();
  }

  function needsManualHint() {
    if (CLIENT.appilix) return false;
    if (CLIENT.appleMobile) return true;
    if (CLIENT.os === "macos" && CLIENT.safari) return true;
    if (CLIENT.android && !CLIENT.chromium) return true;
    if (CLIENT.inApp) return true;
    return false;
  }

  function installCopy(mode) {
    const name = APP;
    const native = mode === "prompt";

    if (CLIENT.appleMobile) {
      if (CLIENT.inApp || !CLIENT.safari) {
        return {
          title: "Add " + name + " from Safari",
          hint:
            (CLIENT.inApp ? "This in-app browser" : browserLabel(CLIENT) + " on iPhone / iPad") +
            " cannot add a Home Screen app. Open this same page in Safari, tap Share, then Add to Home Screen.",
          steps: [],
          cta: "",
        };
      }
      return {
        title: "Add " + name + " to your Home Screen",
        hint: CLIENT.iPadOS
          ? "This stays in Safari on your iPad. It is not a Play Store or Android download."
          : "This stays in Safari on your iPhone. It is not a Play Store or Android download.",
        steps: CLIENT.iPadOS
          ? [
              "Tap Share " + IOS_SHARE_SVG,
              "Tap <strong>Add to Home Screen</strong> (or Add to Dock)",
              "Tap <strong>Add</strong>",
            ]
          : [
              "Tap Share " + IOS_SHARE_SVG,
              "Tap <strong>Add to Home Screen</strong>",
              "Tap <strong>Add</strong>",
            ],
        cta: "",
      };
    }

    if (CLIENT.os === "macos" && CLIENT.safari && !native) {
      return {
        title: "Add " + name + " to your Dock",
        hint: "In Safari: File → Add to Dock. This is a Mac app shortcut, not an Android install.",
        steps: [],
        cta: "",
      };
    }

    if (native) {
      if (CLIENT.android) {
        return {
          title: "Add " + name + " to your home screen",
          hint: browserLabel(CLIENT) + " will add an app icon. This is the website — not a Play Store APK.",
          steps: [],
          cta: "Install",
        };
      }
      return {
        title: "Install " + name + " as a desktop app",
        hint: "Opens in its own " + browserLabel(CLIENT) + " window — no browser tabs.",
        steps: [],
        cta: "Install",
      };
    }

    if (CLIENT.inApp) {
      return {
        title: "Open " + name + " in your browser to install",
        hint: CLIENT.appleMobile
          ? "Open this page in Safari, then tap Share → Add to Home Screen."
          : "Open this page in Chrome, then use Install app / Add to Home screen.",
        steps: [],
        cta: "",
      };
    }

    if (CLIENT.android) {
      return {
        title: "Add " + name + " to your home screen",
        hint:
          CLIENT.browser === "firefox"
            ? "In Firefox: tap the menu (⋮), then Install."
            : "In " + browserLabel(CLIENT) + ": tap the menu (⋮), then Install app or Add to Home screen.",
        steps: [],
        cta: "",
      };
    }

    if (CLIENT.browser === "chrome" || CLIENT.browser === "edge" || CLIENT.browser === "opera") {
      return {
        title: "Install " + name + " as a desktop app",
        hint: "Use the install icon in the " + browserLabel(CLIENT) + " address bar.",
        steps: [],
        cta: "",
      };
    }

    if (CLIENT.browser === "firefox") {
      return {
        title: "Keep " + name + " handy",
        hint: "Firefox on desktop does not install this as an app. Bookmark it, or open the site in Chrome or Edge to install.",
        steps: [],
        cta: "",
      };
    }

    return {
      title: "Add " + name + " to this device",
      hint: "Use " + browserLabel(CLIENT) + "’s Add to Home Screen or install option.",
      steps: [],
      cta: "",
    };
  }

  function parseChoice(raw) {
    const v = String(raw || "").trim().toLowerCase();
    if (!v) return "";
    if (FINAL[v]) return v === "yes" ? "installed" : v === "no" ? "never" : v;
    if (v.indexOf("snooze:") === 0) {
      const ts = parseInt(v.slice(7), 10);
      if (Number.isFinite(ts) && Date.now() < ts) return v;
      return "";
    }
    return "";
  }

  function alreadyDecided(choice) {
    return !!parseChoice(choice);
  }

  function readLocalChoice() {
    try {
      const v = parseChoice(localStorage.getItem(storageKey()));
      if (v) return v;
    } catch (e) {}
    try {
      const m = document.cookie.match(new RegExp("(?:^|; )" + cookieName() + "=([^;]*)"));
      if (m) return parseChoice(decodeURIComponent(m[1]));
    } catch (e) {}
    return "";
  }

  function writeLocalChoice(choice) {
    try {
      localStorage.setItem(storageKey(), choice);
    } catch (e) {}
    try {
      const secure = location.protocol === "https:" ? ";Secure" : "";
      document.cookie =
        cookieName() +
        "=" +
        encodeURIComponent(choice) +
        ";path=/;max-age=31536000;SameSite=Lax" +
        secure;
    } catch (e) {}
  }

  function persistChoice(choice) {
    writeLocalChoice(choice);
    fetch("/pwa/choice", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({
        surface: surface(),
        choice: choice,
        browser: CLIENT.browser,
        os: CLIENT.os,
      }),
    }).catch(function () {});
  }

  function markShownThisVisit() {
    try {
      sessionStorage.setItem(sessionKey(), "1");
    } catch (e) {}
  }

  function shownThisVisit() {
    try {
      return sessionStorage.getItem(sessionKey()) === "1";
    } catch (e) {
      return false;
    }
  }

  function registerServiceWorker() {
    if (!("serviceWorker" in navigator)) return;
    if (!(window.isSecureContext || location.hostname === "localhost" || location.hostname === "127.0.0.1")) {
      return;
    }
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(function () {});
    });
  }

  let deferredPrompt = null;

  function hideBanner() {
    const el = document.getElementById("family-pwa-install");
    if (el) el.remove();
  }

  function ensureStyles() {
    if (document.getElementById("family-pwa-style")) return;
    const style = document.createElement("style");
    style.id = "family-pwa-style";
    style.textContent =
      "#family-pwa-install{position:fixed;left:0.85rem;right:0.85rem;bottom:calc(5.4rem + env(safe-area-inset-bottom,0px));z-index:1080;max-width:28rem;margin:0 auto;font-family:system-ui,-apple-system,sans-serif}#family-pwa-install[data-surface='desktop']{left:auto;right:1rem;bottom:1rem;max-width:22rem}html.family-standalone #family-pwa-install{display:none!important}" +
      ".family-pwa-card{background:#14201a;color:#e9ecef;border:1px solid rgba(47,140,90,.5);border-radius:12px;padding:.85rem 1rem;box-shadow:0 10px 30px rgba(0,0,0,.45);display:flex;flex-direction:column;gap:.65rem}" +
      ".family-pwa-copy{display:flex;flex-direction:column;gap:.25rem;font-size:.88rem;line-height:1.35}" +
      ".family-pwa-copy strong{color:#b7ebc6}" +
      ".family-pwa-copy span{color:#adb5bd;font-size:.8rem}" +
      ".family-pwa-steps{margin:.35rem 0 0;padding-left:1.2rem;color:#ced4da;font-size:.8rem}" +
      ".family-pwa-steps li{margin:.12rem 0}" +
      ".family-pwa-share{display:inline-block;vertical-align:-2px;margin:0 .12rem}" +
      ".family-pwa-actions{display:flex;flex-wrap:wrap;gap:.45rem;justify-content:flex-end}" +
      ".family-pwa-go,.family-pwa-skip,.family-pwa-never{border-radius:8px;padding:.4rem .75rem;font-size:.85rem;font-weight:600;cursor:pointer}" +
      ".family-pwa-go{border:0;background:#2f8c5a;color:#fff}" +
      ".family-pwa-skip{border:1px solid #495057;background:transparent;color:#ced4da}" +
      ".family-pwa-never{border:0;background:transparent;color:#868e96;text-decoration:underline;font-weight:500}";
    document.head.appendChild(style);
  }

  function hydrateSettingsCard() {
    const root = document.querySelector("[data-family-pwa-settings]");
    if (!root) return;
    ensureStyles();
    const titleEl = root.querySelector("[data-family-pwa-title]");
    const hintEl = root.querySelector("[data-family-pwa-hint]");
    const extraEl = root.querySelector("[data-family-pwa-extra]");
    const btn = root.querySelector("[data-family-pwa-go]");
    const icon = root.querySelector("[data-family-pwa-icon]");
    const installed = alreadyInNativeShell() || parseChoice(readLocalChoice()) === "installed";
    root.setAttribute("data-os", CLIENT.os);
    root.setAttribute("data-browser", CLIENT.browser);
    if (icon) {
      icon.className =
        CLIENT.appleMobile || CLIENT.android
          ? "family-pwa-ico"
          : "family-pwa-ico";
    }
    if (installed) {
      if (titleEl) titleEl.textContent = APP + " is already installed on this device";
      if (hintEl) hintEl.textContent = "You are using the installed app on this " + (CLIENT.appleMobile || CLIENT.android ? "phone or tablet" : "computer") + ".";
      if (extraEl) {
        extraEl.innerHTML = "";
        extraEl.hidden = true;
      }
      if (btn) btn.hidden = true;
      return;
    }
    const copy = installCopy(deferredPrompt && !CLIENT.appleMobile ? "prompt" : "hint");
    if (titleEl) titleEl.textContent = copy.title;
    if (hintEl) hintEl.innerHTML = copy.hint;
    if (extraEl) {
      if (copy.steps && copy.steps.length) {
        extraEl.innerHTML =
          '<ol class="family-pwa-steps mb-0">' +
          copy.steps.map(function (s) { return "<li>" + s + "</li>"; }).join("") +
          "</ol>";
        extraEl.hidden = false;
      } else {
        extraEl.innerHTML = "";
        extraEl.hidden = true;
      }
    }
    if (btn) {
      if (copy.cta && deferredPrompt && !CLIENT.appleMobile) {
        btn.hidden = false;
        btn.textContent = copy.cta;
        if (!btn.getAttribute("data-bound")) {
          btn.setAttribute("data-bound", "1");
          btn.addEventListener("click", function () {
            if (window.FamilyInstall) window.FamilyInstall();
          });
        }
      } else {
        btn.hidden = true;
      }
    }
  }

  function showBanner(mode) {
    if (document.getElementById("family-pwa-install")) return;
    const copy = installCopy(mode);
    const showInstall = mode === "prompt" && deferredPrompt && copy.cta;
    const steps =
      copy.steps && copy.steps.length
        ? '<ol class="family-pwa-steps">' +
          copy.steps.map(function (s) { return "<li>" + s + "</li>"; }).join("") +
          "</ol>"
        : "";
    const wrap = document.createElement("div");
    wrap.id = "family-pwa-install";
    wrap.setAttribute("role", "dialog");
    wrap.setAttribute("data-os", CLIENT.os);
    wrap.setAttribute("data-browser", CLIENT.browser);
    wrap.setAttribute("data-surface", surface());
    wrap.innerHTML =
      '<div class="family-pwa-card">' +
        '<div class="family-pwa-copy">' +
          "<strong>" + copy.title + "</strong>" +
          "<span>" + copy.hint + "</span>" +
          steps +
        "</div>" +
        '<div class="family-pwa-actions">' +
          (showInstall ? '<button type="button" class="family-pwa-go" id="family-pwa-go">' + copy.cta + "</button>" : "") +
          '<button type="button" class="family-pwa-skip" id="family-pwa-skip">Not now</button>' +
          '<button type="button" class="family-pwa-never" id="family-pwa-never">Don\'t ask again</button>' +
        "</div>" +
      "</div>";
    ensureStyles();
    document.body.appendChild(wrap);
    markShownThisVisit();
    document.getElementById("family-pwa-skip").addEventListener("click", function () {
      persistChoice("snooze:" + (Date.now() + SNOOZE_MS));
      hideBanner();
    });
    document.getElementById("family-pwa-never").addEventListener("click", function () {
      persistChoice("never");
      hideBanner();
    });
    const go = document.getElementById("family-pwa-go");
    if (go) {
      go.addEventListener("click", async function () {
        if (!deferredPrompt) return;
        deferredPrompt.prompt();
        try {
          const { outcome } = await deferredPrompt.userChoice;
          persistChoice(outcome === "accepted" ? "installed" : "snooze:" + (Date.now() + SNOOZE_MS));
        } catch (e) {
          persistChoice("snooze:" + (Date.now() + SNOOZE_MS));
        }
        deferredPrompt = null;
        hideBanner();
        hydrateSettingsCard();
      });
    }
  }

  function maybeShow(mode) {
    if (alreadyInNativeShell() || alreadyDecided(readLocalChoice()) || shownThisVisit()) return;
    showBanner(mode);
  }

  function markInstalled() {
    persistChoice("installed");
    hideBanner();
    hydrateSettingsCard();
  }

  function setupInstallPrompt() {
    window.addEventListener("beforeinstallprompt", function (e) {
      e.preventDefault();
      // Apple browsers never fire this. If we somehow get it on iOS/iPadOS,
      // ignore the native Chromium install sheet and keep Safari steps.
      if (CLIENT.appleMobile) {
        deferredPrompt = null;
        hydrateSettingsCard();
        maybeShow("hint");
        return;
      }
      deferredPrompt = e;
      document.body.dataset.canInstall = "true";
      hydrateSettingsCard();
      maybeShow("prompt");
    });

    window.FamilyInstall = async function () {
      if (CLIENT.appleMobile || !deferredPrompt) return false;
      deferredPrompt.prompt();
      const { outcome } = await deferredPrompt.userChoice;
      deferredPrompt = null;
      persistChoice(outcome === "accepted" ? "installed" : "snooze:" + (Date.now() + SNOOZE_MS));
      hideBanner();
      hydrateSettingsCard();
      return outcome === "accepted";
    };

    window.addEventListener("appinstalled", function () {
      deferredPrompt = null;
      markInstalled();
    });

    if (navigator.getInstalledRelatedApps && !CLIENT.appleMobile) {
      navigator.getInstalledRelatedApps().then(function (apps) {
        if (apps && apps.length) markInstalled();
      }).catch(function () {});
    }

    window.addEventListener("load", function () {
      setTimeout(function () {
        if (alreadyInNativeShell() || alreadyDecided(readLocalChoice()) || shownThisVisit()) return;
        if (deferredPrompt || document.getElementById("family-pwa-install")) return;
        // Chrome/Edge already-installed does not fire beforeinstallprompt.
        // Only browsers that cannot show a native install sheet get a manual hint.
        if (needsManualHint()) maybeShow("hint");
      }, 1800);
    });
  }

  function boot() {
    registerServiceWorker();
    if (isStandalone()) {
      document.documentElement.classList.add("family-standalone");
      if (document.body) document.body.classList.add("family-standalone");
      writeLocalChoice("installed");
      persistChoice("installed");
      hydrateSettingsCard();
      return;
    }
    if (CLIENT.appilix) {
      writeLocalChoice("installed");
      persistChoice("installed");
      hydrateSettingsCard();
      return;
    }
    hydrateSettingsCard();
    if (alreadyDecided(readLocalChoice())) return;

    const start = function () {
      if (alreadyDecided(readLocalChoice())) {
        hydrateSettingsCard();
        return;
      }
      setupInstallPrompt();
    };

    fetch("/pwa/choice?surface=" + encodeURIComponent(surface()), {
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    })
      .then(function (r) {
        return r.ok ? r.json() : {};
      })
      .then(function (data) {
        const c = parseChoice(data && data.choice);
        if (alreadyDecided(c)) {
          writeLocalChoice(c);
          hydrateSettingsCard();
          return;
        }
        start();
      })
      .catch(start);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
