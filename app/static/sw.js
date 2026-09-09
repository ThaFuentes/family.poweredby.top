/**
 * Family OS — security-conscious service worker
 *
 * Caches only /static/* (CSS, JS, images).
 * Never caches HTML, JSON, or mutating requests.
 */
const CACHE_NAME = 'family-static-v2';
const PRECACHE = [
  '/static/images/pwa-192.png',
  '/static/images/pwa-512.png',
  '/static/css/family.css?v=os10',
  '/static/js/pwa-install.js?v=family-os2',
];

function isStaticAsset(url) {
  try {
    const u = new URL(url);
    if (u.origin !== self.location.origin) return false;
    return u.pathname.startsWith('/static/');
  } catch (e) {
    return false;
  }
}

function isNavigationRequest(request) {
  return request.mode === 'navigate' ||
    (request.method === 'GET' && request.headers.get('accept') &&
      request.headers.get('accept').includes('text/html'));
}

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(PRECACHE).catch(() => undefined))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  if (isNavigationRequest(req)) return;
  if (!isStaticAsset(req.url)) return;

  event.respondWith(
    caches.open(CACHE_NAME).then(async (cache) => {
      const cached = await cache.match(req, { ignoreSearch: false });
      const networkPromise = fetch(req).then((response) => {
        if (response && response.ok && response.type === 'basic') {
          cache.put(req, response.clone());
        }
        return response;
      }).catch(() => cached);
      return cached || networkPromise;
    })
  );
});
