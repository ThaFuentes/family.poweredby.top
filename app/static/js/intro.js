/**
 * Installed-app flash intro. Only loaded when the boot script
 * set family-intro-on (standalone / desktop PWA). Builds the
 * overlay here so browser tabs never fetch the clip.
 */
(function () {
  var KEY = "family.intro.v1";
  var HOLD_MS = 3400;
  var BRAND_AT = 2100;
  var FADE_MS = 400;

  function markSeen() {
    try {
      sessionStorage.setItem(KEY, "1");
    } catch (e) {}
  }

  function finish() {
    var html = document.documentElement;
    if (!html.classList.contains("family-intro-on")) return;
    markSeen();
    html.classList.add("family-intro-out");
    setTimeout(function () {
      html.classList.remove("family-intro-on", "family-intro-brand", "family-intro-out");
      var el = document.getElementById("family-intro");
      if (el) el.remove();
    }, FADE_MS);
  }

  function ensureRoot() {
    var root = document.getElementById("family-intro");
    if (root) return root;
    root = document.createElement("div");
    root.id = "family-intro";
    root.setAttribute("role", "dialog");
    root.setAttribute("aria-label", "Family OS");
    root.innerHTML =
      '<div class="family-intro-scan" aria-hidden="true"></div>' +
      '<div class="family-intro-veil" aria-hidden="true"></div>' +
      '<div class="family-intro-mark">' +
        '<img src="/static/images/fav.jpg" alt="">' +
        "<strong>Family OS</strong>" +
        "<span>Scan it. Know it.</span>" +
      "</div>" +
      '<button type="button" class="family-intro-skip" id="family-intro-skip">Skip</button>';
    var video = document.createElement("video");
    video.id = "family-intro-video";
    video.muted = true;
    video.defaultMuted = true;
    video.setAttribute("muted", "");
    video.setAttribute("playsinline", "");
    video.playsInline = true;
    video.preload = "auto";
    video.poster = "/static/images/intro-poster.jpg";
    var webm = document.createElement("source");
    webm.src = "/static/video/intro.webm";
    webm.type = "video/webm";
    var mp4 = document.createElement("source");
    mp4.src = "/static/video/intro.mp4";
    mp4.type = "video/mp4";
    video.appendChild(webm);
    video.appendChild(mp4);
    root.insertBefore(video, root.firstChild);
    document.body.insertBefore(root, document.body.firstChild);
    return root;
  }

  function boot() {
    if (!document.documentElement.classList.contains("family-intro-on")) return;
    var root = ensureRoot();
    var video = document.getElementById("family-intro-video");
    var skip = document.getElementById("family-intro-skip");
    if (skip) skip.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      finish();
    });
    root.addEventListener("click", finish);
    if (video) {
      var play = video.play();
      if (play && play.catch) play.catch(function () {});
    }
    setTimeout(function () {
      document.documentElement.classList.add("family-intro-brand");
    }, BRAND_AT);
    setTimeout(finish, HOLD_MS);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
