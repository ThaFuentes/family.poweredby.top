/**
 * Family OS — security-conscious service worker
 *
 * Caches /static/* (CSS, JS, images, intro clip) plus the public
 * /offline shell. Never caches household HTML, JSON, or mutating
 * requests. Uploads and tenant photos stay off this cache.
 */
const CACHE_NAME = 'family-static-v10';
const PRECACHE = [
  '/static/images/pwa-192.png',
  '/static/images/pwa-512.png',
  '/static/images/fav.jpg',
  '/static/images/intro-poster.jpg',
  '/static/images/intro-poster-phone.jpg',
  '/static/video/intro.webm',
  '/static/video/intro.mp4',
  '/static/css/family.css?v=os22',
  '/static/css/themes.css?v=os22',
  '/static/js/app.js?v=os9',
  '/static/js/pwa-install.js?v=family-os2',
  '/static/js/intro.js?v=os3',
  '/static/js/scan.js?v=os12',
  '/static/js/basket.js?v=os1',
  '/static/js/theme.js?v=os6',
  '/offline',
];

function isCacheable(url) {
  try {
    const u = new URL(url);
    if (u.origin !== self.location.origin) return false;
    if (u.pathname.startsWith('/static/')) return true;
    if (u.pathname === '/offline') return true;
    return false;
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
    caches.open(CACHE_NAME).then((cache) =>
      Promise.all(PRECACHE.map((u) => cache.add(u).catch(() => undefined)))
    ).then(() => self.skipWaiting())
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

  if (isNavigationRequest(req)) {
    event.respondWith(
      fetch(req).catch(() => caches.match('/offline'))
    );
    return;
  }

  if (!isCacheable(req.url)) return;

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
