const CACHE_NAME = 'thaw-v2';
const ASSETS = [
  '/static/icon-192.png',
  '/static/icon-512.png',
  '/static/icon-maskable-512.png'
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)));
    })
  );
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET") return;
  // Only cache images, never HTML or JS
  if (e.request.url.match(/\.(png|jpg|jpeg|svg|woff2)$/)) {
    e.respondWith(
      caches.match(e.request).then((cached) => cached || fetch(e.request))
    );
  }
});