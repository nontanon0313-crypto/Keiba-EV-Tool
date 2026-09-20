const CACHE = "keiba-ev-v1";
const ASSETS = ["./", "./index.html", "./theme.css", "./ev-theme.js", "./app.js", "./manifest.json"];
self.addEventListener("install", function(e){
  e.waitUntil(caches.open(CACHE).then(function(c){ return c.addAll(ASSETS); }));
});
self.addEventListener("activate", function(e){
  e.waitUntil(caches.keys().then(function(keys){
    return Promise.all(keys.filter(function(k){ return k !== CACHE; }).map(function(k){ return caches.delete(k); }));
  }));
});
self.addEventListener("fetch", function(e){
  e.respondWith(caches.match(e.request).then(function(r){ return r || fetch(e.request); }));
});
