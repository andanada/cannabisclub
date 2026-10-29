// Només emmagatzema l'estructura de l'aplicació. Mai desa respostes de l'API (hi ha dades de socis).
const CACHE = 'club-shell-v23';
const SHELL = ['/', '/i18n-es.js', '/i18n-en.js', '/i18n.js', '/util.js', '/bascula.js', '/app.js', '/views-dispensar.js', '/views-gestio.js', '/views-socis.js', '/views-descomptes.js', '/views-regles.js', '/views-linies-preu.js', '/views-contenidors.js', '/views-magatzems.js', '/views-inventari.js', '/views-informes.js', '/views-historial.js', '/views-config.js', '/diagnostic.js', '/views-dispositius.js', '/views-diagnostic.js', '/views-carnets.js', '/views-admin.js', '/style.css', '/manifest.webmanifest', '/icon.svg'];

self.addEventListener('install', (e) => e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())));
self.addEventListener('activate', (e) => e.waitUntil(
  caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin || !SHELL.includes(url.pathname)) return;
  e.respondWith(fetch(e.request).then((r) => {
    const copy = r.clone();
    caches.open(CACHE).then((c) => c.put(e.request, copy));
    return r;
  }).catch(() => caches.match(e.request)));
});
