const CACHE='keiba-ev-v2';self.addEventListener('install',e=>{self.skipWaiting()});self.addEventListener('fetch',e=>{e.respondWith(caches.match(e.request).then(r=>r||fetch(e.request)))});
