"use strict";
/* Installable app: registers the service worker and tells the person when they are offline, because a report cannot be sent without a connection. */
(function () {
  if ("serviceWorker" in navigator && (location.protocol === "https:" || location.hostname === "localhost" || location.hostname === "127.0.0.1")) {
    addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => { /* the site works without it */ }));
  }
  function banner() {
    let b = document.getElementById("offline-banner");
    if (navigator.onLine) { b?.remove(); return; }
    if (b) return;
    b = document.createElement("div");
    b.id = "offline-banner"; b.setAttribute("role", "status");
    b.textContent = (window.I18N ? I18N.t("You are offline. You can fill in the form, but a report can only be sent when you are back online.") : "You are offline. You can fill in the form, but a report can only be sent when you are back online.");
    document.body.prepend(b);
  }
  addEventListener("online", banner); addEventListener("offline", banner);
  document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", banner) : banner();
})();
