/* YaVaKa service worker — app shell caching + offline fallback.
   Authenticated HTML is never cached, so a shared device cannot leak a project. */

const VERSION = "vaka-v3";
const STATIC_CACHE = `${VERSION}-static`;

const PRECACHE = [
  "/offline",
  "/manifest.webmanifest",
  "/static/css/app.css",
  "/static/css/portal.css",
  "/static/css/transitions.css",
  "/static/js/app.js",
  "/static/js/nav.js",
  "/static/js/modal.js",
  "/static/js/signature.js",
  "/static/js/whatsapp.js",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
  "/static/icons/apple-touch-icon.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(STATIC_CACHE)
      .then((cache) => Promise.allSettled(PRECACHE.map((url) => cache.add(url))))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => !key.startsWith(VERSION)).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;

  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request).catch(async () => {
        const offline = await caches.match("/offline");
        return (
          offline ||
          new Response("You are offline.", {
            status: 503,
            headers: { "Content-Type": "text/plain; charset=utf-8" },
          })
        );
      }),
    );
    return;
  }

  if (url.pathname.startsWith("/static/")) {
    // Network-first: updated CSS and JS always win when the device is online.
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            // Key by pathname so repeated cache-bust versions replace each other
            // instead of growing the cache without bound.
            caches.open(STATIC_CACHE).then((cache) => cache.put(url.pathname, copy));
          }
          return response;
        })
        .catch(async () => {
          // Pages request cache-busted URLs (/static/app.css?v=1712...), so the
          // precache has to be matched with the query string ignored.
          const cached = await caches.match(request, { ignoreSearch: true });
          return cached || Response.error();
        }),
    );
  }
});
