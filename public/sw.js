// ふたり暮らし: 通知の受信と、圏外のときに直前の画面を表示するための Service Worker
const CACHE = 'futari-v1';

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== location.origin) return;
  if (url.pathname.startsWith('/cal/') || url.pathname.startsWith('/cron/') || url.pathname.startsWith('/auth/') || url.pathname.endsWith('.json')) return;

  if (url.pathname.startsWith('/static/')) {
    // CSS・JS・アイコン: 控えがあればすぐ返し、裏で新しいものに更新する
    event.respondWith(
      caches.open(CACHE).then(async (cache) => {
        const hit = await cache.match(req);
        const fresh = fetch(req).then((res) => { if (res.ok) cache.put(req, res.clone()); return res; }).catch(() => hit);
        return hit || fresh;
      })
    );
    return;
  }

  // 画面: まず通信し、つながらないときだけ直前に見た内容を返す
  event.respondWith(
    fetch(req)
      .then((res) => {
        if (res.ok && !res.redirected && res.headers.get('content-type')?.includes('text/html')) {
          const copy = res.clone();
          caches.open(CACHE).then((cache) => cache.put(url.pathname, copy));
        }
        return res;
      })
      .catch(async () => {
        const hit = await caches.match(url.pathname);
        return hit || new Response('<meta charset="utf-8"><p style="font-family:sans-serif;padding:2rem">圏外のようです。電波の良い場所でもう一度開いてください。</p>', { headers: { 'Content-Type': 'text/html; charset=utf-8' } });
      })
  );
});

self.addEventListener('push', (event) => {
  let data = {};
  try { data = event.data.json(); } catch (e) { data = { title: 'ふたり暮らし', body: event.data ? event.data.text() : '' }; }
  event.waitUntil(
    self.registration.showNotification(data.title || 'ふたり暮らし', {
      body: data.body || '',
      icon: '/static/icon-192.png',
      badge: '/static/icon-192.png',
      data: { url: data.url || '/' },
    })
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = event.notification.data?.url || '/';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
      for (const client of list) {
        if ('focus' in client) { client.navigate(target); return client.focus(); }
      }
      return self.clients.openWindow(target);
    })
  );
});
