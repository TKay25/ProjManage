/* YaVaKa service worker — app shell caching + offline fallback.

   Authenticated HTML is never cached implicitly, so a shared device cannot leak
   a project. The only exception is a snapshot the user explicitly saves: it
   lives in its own cache, is read-only, and is wiped on sign-out. */

const VERSION = "vaka-v4";
const STATIC_CACHE = `${VERSION}-static`;
// Offline snapshots are opt-in and live in their own cache so a version bump
// never resurrects or discards them.
const SNAPSHOT_CACHE = "vaka-snapshots";

const PRECACHE = [
  "/offline",
  "/manifest.webmanifest",
  "/static/css/app.css",
  "/static/css/portal.css",
  "/static/css/theme.css",
  "/static/css/transitions.css",
  "/static/js/app.js",
  "/static/js/theme.js",
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
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key !== SNAPSHOT_CACHE && !key.startsWith(VERSION))
            .map((key) => caches.delete(key)),
        ),
      )
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
        // A project the user chose to keep offline opens from its snapshot;
        // everything else falls back to the generic offline page.
        const snapshots = await caches.open(SNAPSHOT_CACHE);
        const saved = await snapshots.match(url.pathname);
        if (saved) return saved;

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
