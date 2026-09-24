// 修正のたびにこのバージョン文字列を更新すること
const CACHE_NAME = "keiba-ev-v21";
const ASSETS = [
  "./",
  "./index.html",
  "./theme.css",
  "./ev-theme.js",
  "./app.js",
  "./manifest.json",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS)).catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const url = event.request.url;
  // APIは触らない
  const isApi =
    url.includes("/api/") ||
    url.includes("keiba-ev-tool.onrender.com") ||
    !url.includes(self.location.origin);
  if (isApi || event.request.method !== "GET") {
    return;
  }
  // index / app.js / sw.js はネットワーク優先
  const isCritical =
    url.includes("index.html") ||
    url.includes("/app.js") ||
    url.endsWith("/") ||
    url.includes("sw.js");
  if (isCritical) {
    event.respondWith(
      fetch(event.request)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE_NAME).then((c) => c.put(event.request, copy)).catch(() => {});
          return res;
        })
        .catch(() => caches.match(event.request))
    );
    return;
  }
  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request))
  );
});
