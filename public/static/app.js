// ふたり暮らし: 画面の小さな動き。ライブラリは使わない。
(() => {
  const page = () => document.getElementById('page');
  const csrf = () => document.querySelector('meta[name=csrf-token]')?.content || '';
  let busy = false; // 入力中や編集を開いている間は、自動更新で画面を書き換えない

  // ---- 取得した HTML で画面の中身だけ差し替える ----
  function swap(html, finalUrl) {
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const next = doc.getElementById('page');
    if (!next || !page()) { location.href = finalUrl; return; }
    page().innerHTML = next.innerHTML;
    const bar = doc.querySelector('.tabbar');
    if (bar && document.querySelector('.tabbar')) document.querySelector('.tabbar').innerHTML = bar.innerHTML;
    const token = doc.querySelector('meta[name=csrf-token]');
    if (token) document.querySelector('meta[name=csrf-token]').content = token.content;
    busy = false;
    setupPush();
  }

  async function submitAsync(form, submitter) {
    const data = new FormData(form);
    if (submitter && submitter.name) data.append(submitter.name, submitter.value);
    const action = (submitter && submitter.getAttribute('formaction')) || form.action;
    const refocus = form.dataset.refocus;
    try {
      const res = await fetch(action, { method: 'POST', body: data, headers: { 'X-Requested-With': 'fetch' } });
      const html = await res.text();
      if (new URL(res.url).pathname !== location.pathname) { location.href = res.url; return; }
      swap(html, res.url);
      if (refocus) page().querySelector(`[data-refocus] [name="${refocus}"]`)?.focus();
    } catch (e) {
      form.removeAttribute('data-async'); // 通信できないときは通常の送信に任せる
      alert('通信できませんでした。電波の良い場所でもう一度お試しください。');
    }
  }

  document.addEventListener('submit', (ev) => {
    const form = ev.target;
    const submitter = ev.submitter;
    const message = submitter?.dataset.confirm;
    if (message && !confirm(message)) { ev.preventDefault(); return; }
    if (!form.matches('[data-async]')) return;
    ev.preventDefault();
    const check = form.querySelector('.check');
    if (check) { // 押した瞬間に見た目を切り替える
      check.classList.toggle('on');
      check.closest('.row')?.classList.toggle('done');
    }
    submitAsync(form, submitter);
  });

  // ---- 行の「編集」を開いたら、その下のフォームを表示する ----
  document.addEventListener('toggle', (ev) => {
    const d = ev.target;
    if (!(d instanceof HTMLDetailsElement)) return;
    if (d.open) busy = true;
    if (d.matches('[data-move-form]')) {
      const form = d.parentElement.querySelector('.edit-form');
      if (form) form.hidden = !d.open;
    }
  }, true);

  document.addEventListener('input', (ev) => { if (ev.target.closest('#page')) busy = true; });

  // 家事のくり返し: 選んだ種類に合わせて入力欄を出し分ける
  document.addEventListener('change', (ev) => {
    const sel = ev.target.closest('[data-toggle-freq]');
    if (!sel) return;
    sel.closest('form').querySelectorAll('[data-freq]').forEach((el) => { el.hidden = el.dataset.freq !== sel.value; });
  });

  document.addEventListener('click', async (ev) => {
    const btn = ev.target.closest('[data-copy]');
    if (!btn) return;
    ev.preventDefault();
    const input = document.querySelector(btn.dataset.copy);
    try { await navigator.clipboard.writeText(input.value); } catch (e) { input.select(); document.execCommand('copy'); }
    const label = btn.textContent;
    btn.textContent = 'コピーしました';
    setTimeout(() => { btn.textContent = label; }, 1800);
  });

  // ---- 相手の変更を反映するための自動更新（12秒ごと） ----
  async function refresh() {
    if (!page()?.hasAttribute('data-poll') || busy || document.hidden || !navigator.onLine) return;
    const active = document.activeElement;
    if (active && active.closest('#page') && /^(INPUT|TEXTAREA|SELECT)$/.test(active.tagName)) return;
    try {
      const res = await fetch(location.href, { headers: { 'X-Requested-With': 'fetch' } });
      if (!res.ok || new URL(res.url).pathname !== location.pathname) return;
      const html = await res.text();
      if (!busy) swap(html, res.url);
    } catch (e) { /* 圏外のときは何もしない */ }
  }
  setInterval(refresh, 12000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });

  // ---- 通知（設定画面） ----
  function keyBytes(base64url) {
    const pad = '='.repeat((4 - (base64url.length % 4)) % 4);
    const raw = atob((base64url + pad).replace(/-/g, '+').replace(/_/g, '/'));
    return Uint8Array.from(raw, (c) => c.charCodeAt(0));
  }
  const post = (url, body) => fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf() },
    body: JSON.stringify(body || {}),
  });

  async function setupPush() {
    const status = document.getElementById('push-status');
    if (!status || status.dataset.ready) return;
    status.dataset.ready = '1';
    const on = document.getElementById('push-on');
    const off = document.getElementById('push-off');
    const test = document.getElementById('push-test');
    if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) {
      status.textContent = 'この開き方では通知を使えません。iPhoneでは、Safariの共有メニューから「ホーム画面に追加」し、そのアイコンから開いてください。';
      return;
    }
    const reg = await Promise.race([
      navigator.serviceWorker.ready,
      new Promise((resolve) => setTimeout(() => resolve(null), 5000)),
    ]);
    if (!reg) {
      status.textContent = '通知の準備ができませんでした。アプリを開き直してからもう一度お試しください。';
      return;
    }
    const show = async () => {
      const sub = await reg.pushManager.getSubscription();
      on.hidden = !!sub; off.hidden = !sub; test.hidden = !sub;
      if (Notification.permission === 'denied') {
        status.textContent = '通知がブロックされています。端末の設定でこのアプリの通知を許可してください。';
        on.hidden = true;
      } else {
        status.textContent = sub ? 'この端末で通知を受け取っています。' : 'この端末では、まだ通知を受け取っていません。';
      }
    };
    on.addEventListener('click', async () => {
      const permission = await Notification.requestPermission();
      if (permission !== 'granted') { await show(); return; }
      try {
        const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(status.dataset.vapid) });
        const res = await post('/push/subscribe', sub.toJSON());
        if (!res.ok) throw new Error('subscribe failed');
      } catch (e) {
        status.textContent = '通知をオンにできませんでした。時間をおいてもう一度お試しください。';
        return;
      }
      await show();
    });
    off.addEventListener('click', async () => {
      const sub = await reg.pushManager.getSubscription();
      if (sub) { await post('/push/unsubscribe', { endpoint: sub.endpoint }); await sub.unsubscribe(); }
      await show();
    });
    test.addEventListener('click', async () => {
      const res = await post('/push/test');
      const data = await res.json().catch(() => ({}));
      status.textContent = data.sent ? 'テスト通知を送りました。数秒で届きます。' : '送信できませんでした。一度「通知をやめる」を押してから、もう一度オンにしてください。';
    });
    await show();
  }

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
    // ログイン画面に戻ったら、端末に残した画面の控えを消す
    if (document.querySelector('.gate') && window.caches) caches.keys().then((keys) => keys.forEach((k) => caches.delete(k)));
  }
  setupPush();
})();
