/* ============================================================================
 * Service worker for the EM Waveguide & RCS Simulator PWA.
 *
 * DESIGN RULES (they matter — get these wrong and the app breaks subtly):
 *  1. The solver is a LIVE local service. Never touch /run*, /upload*, /progress,
 *     /results/*, /cad/*, /fullwave_figures/* — those must always hit the network so a
 *     phone triggering an openEMS solve gets the real answer, never a cached one.
 *  2. Only GET is ever handled. Any POST (uploads, solves) passes straight through.
 *  3. The HTML document is NETWORK-FIRST. The file is edited constantly and pulled onto
 *     the Windows box with git; a cache-first shell would keep serving yesterday's app.
 *     Cache is only the offline fallback.
 *  4. The CDN libs (Chart.js / Three.js / MathJax / JSZip) are immutable versioned URLs,
 *     so they are cache-first — that is what makes a second launch fast on mobile data.
 *  5. Bump CACHE_VERSION to retire every old cache.
 * ==========================================================================*/
// Bump on ANY change to the icons, the manifest or this file — the shell cache holds
// the icons and manifest, so without a bump an installed phone keeps the old artwork.
const CACHE_VERSION = 'emsim-v4.0.0';
const SHELL_CACHE   = CACHE_VERSION + '-shell';
const LIB_CACHE     = CACHE_VERSION + '-lib';

// Same-origin paths that must ALWAYS go to the network (live solver + generated output).
// KEEP THIS IN STEP WITH THE FLASK ROUTES. The rule is: anything that is produced by a run, or
// that FEEDS a physics calculation, is never cached — a cached copy would be shown as a fresh
// result. /demo_cad/ belongs here even though the files look static: they are the shipped example
// STEP models, they are regenerable by demo_cad/make_demo_cad.py, and a phone holding an old copy
// would silently compute an RCS for the wrong geometry.
const NEVER_CACHE = [
  '/run', '/run_horn', '/run_rcs', '/upload_rcs', '/upload_cad',
  '/progress', '/results/', '/cad/', '/fullwave_figures/', '/demo_cad/'
];

const SHELL = ['/', '/manifest.webmanifest', '/icons/icon-192-sq.png', '/icons/icon-512-sq.png',
               '/icons/apple-touch-icon.png', '/icons/apple-touch-icon-180.png',
               '/icons/apple-touch-icon-167.png', '/icons/apple-touch-icon-152.png',
               '/icons/apple-touch-icon-120.png'];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(SHELL_CACHE)
      .then((c) => Promise.allSettled(SHELL.map((u) => c.add(new Request(u, { cache: 'reload' })))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.indexOf(CACHE_VERSION) !== 0).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// let the page ask for an immediate update
self.addEventListener('message', (e) => { if (e.data === 'skipWaiting') self.skipWaiting(); });

function isNeverCache(url) {
  return NEVER_CACHE.some((p) => (p.endsWith('/') ? url.pathname.startsWith(p) : url.pathname === p));
}

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;                       // uploads / solves pass through

  let url;
  try { url = new URL(req.url); } catch (_) { return; }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return;

  const sameOrigin = (url.origin === self.location.origin);

  // 1. live solver + generated output: never intercepted at all
  if (sameOrigin && isNeverCache(url)) return;

  // 2. the app document: network-first so a redeploy is picked up immediately
  const wantsHTML = req.mode === 'navigate' ||
                    (req.headers.get('accept') || '').includes('text/html');
  if (sameOrigin && wantsHTML) {
    const HTML_TIMEOUT_MS = 3500;
    const shellFallback = () => caches.match('/', { ignoreSearch: true });
    const timedOut = new Promise((resolve) => setTimeout(() => resolve(null), HTML_TIMEOUT_MS));
    event.respondWith(
      Promise.race([
        fetch(req)
          .then((res) => {
            if (res && res.ok) {
              const copy = res.clone();
              caches.open(SHELL_CACHE).then((c) => c.put('/', copy)).catch(() => {});
            }
            return res;
          })
          .catch(() => null),
        timedOut
      ])
      .then((res) => res || shellFallback().then((hit) => hit || fetch(req)))
      .catch(() => shellFallback())
      .then((res) => res || new Response(
        '<h1 style="font-family:sans-serif">Offline</h1><p>Open this once while connected to the bridge, then it will work offline for the analytical tabs.</p>',
        { headers: { 'Content-Type': 'text/html' } }))
    );
    return;
  }
  // 3. immutable third-party libs (cdnjs) + our icons/manifest: cache-first
  const isLib  = !sameOrigin;
  const isIcon = sameOrigin && (url.pathname.startsWith('/icons/') || url.pathname === '/manifest.webmanifest');
  if (isLib || isIcon) {
    const cacheName = isLib ? LIB_CACHE : SHELL_CACHE;
    event.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).then((res) => {
        // opaque cross-origin responses are fine to store and replay
        if (res && (res.ok || res.type === 'opaque')) {
          const copy = res.clone();
          caches.open(cacheName).then((c) => c.put(req, copy)).catch(() => {});
        }
        return res;
      }).catch(() => hit))
    );
    return;
  }

  // 4. anything else same-origin (fonts, misc static): stale-while-revalidate
  if (sameOrigin) {
    event.respondWith(
      caches.match(req).then((hit) => {
        const net = fetch(req).then((res) => {
          if (res && res.ok) {
            const copy = res.clone();
            caches.open(SHELL_CACHE).then((c) => c.put(req, copy)).catch(() => {});
          }
          return res;
        }).catch(() => hit);
        return hit || net;
      })
    );
  }
});
