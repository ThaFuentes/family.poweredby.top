/**
 * Installed-app flash intro. Only runs when the HTML boot script
 * already put family-intro-on on <html> (standalone / desktop PWA).
 * Once per session. Tap anywhere to skip.
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

  function boot() {
    if (!document.documentElement.classList.contains("family-intro-on")) return;
    var root = document.getElementById("family-intro");
    if (!root) return;

    var video = document.getElementById("family-intro-video");
    var skip = document.getElementById("family-intro-skip");
    if (skip) skip.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      finish();
    });
    root.addEventListener("click", finish);

    if (video) {
      video.muted = true;
      video.defaultMuted = true;
      video.setAttribute("muted", "");
      video.playsInline = true;
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
