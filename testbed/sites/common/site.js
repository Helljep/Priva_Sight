// site.js - shared behaviour for all six synthetic test sites.
//
// Pages are static templates. At load time this script fills them with ONE
// synthetic persona (?p=N) in ONE visual layout (?layout=1..5), so the same
// page produces many different "screens" for the privacy evaluation.
//
//   data-bind="field"        text  <- persona[field]            (data-of="1" = next persona)
//   data-bind-value="field"  input value <- persona[field]
//   data-face                <img> src <- persona face (jpg if present, else svg)
//   data-pii="TYPE"          static text that is PII (ground truth for scoring)
//   form[data-login]         checks username/password against the persona
//   form[data-action="x"]    records {action:'x', data:{...}} in the site state
//
// The state lives in localStorage and is exposed as window.__state() so the
// evaluation harness can check whether a task actually succeeded.

(async function () {
  const q = new URLSearchParams(location.search);
  const P = Number(q.get('p') || 0);
  const LAYOUT = q.get('layout') || '1';
  document.documentElement.dataset.layout = LAYOUT;
  document.body.classList.add('layout-' + LAYOUT);

  const people = await (await fetch('/data/personas.json')).json();
  const me = people[P % people.length];
  const person = (offset) => people[(P + Number(offset || 0)) % people.length];
  window.persona = me;

  const KEY = 'ps_state_p' + P;
  const load = () => { try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch { return {}; } };
  const save = (s) => localStorage.setItem(KEY, JSON.stringify(s));
  window.__state = () => load();
  window.__reset = () => localStorage.removeItem(KEY);

  const fmt = (field, v) => field === 'balance' ? '₹' + Number(v).toLocaleString('en-IN') : v;

  // ---- fill in persona data ----
  document.querySelectorAll('[data-bind]').forEach((el) => {
    const p = person(el.dataset.of);
    el.textContent = fmt(el.dataset.bind, p[el.dataset.bind]);
  });
  document.querySelectorAll('[data-bind-value]').forEach((el) => {
    el.value = person(el.dataset.of)[el.dataset.bindValue];
  });
  document.querySelectorAll('img[data-face]').forEach((img) => {
    const base = person(img.dataset.of).face;
    img.alt = 'profile photo';
    img.onerror = () => { img.onerror = null; img.src = '/' + base + '.svg'; };
    img.src = '/' + base + '.jpg';
  });
  document.querySelectorAll('video[data-face]').forEach((v) => {
    v.poster = '/' + person(v.dataset.of).face + '.svg';
  });

  // ---- keep ?p and ?layout on every internal link ----
  const carry = (url) => {
    const u = new URL(url, location.href);
    u.searchParams.set('p', P);
    u.searchParams.set('layout', LAYOUT);
    return u.pathname + u.search;
  };
  document.querySelectorAll('a[href]').forEach((a) => {
    const h = a.getAttribute('href');
    if (h && !h.startsWith('http') && !h.startsWith('#')) a.setAttribute('href', carry(h));
  });

  // ---- login gate ----
  const site = document.body.dataset.site;
  if (document.body.dataset.requiresLogin !== undefined && !(load().loggedIn || {})[site]) {
    location.replace(carry('login.html'));
    return;
  }
  document.querySelectorAll('form[data-login]').forEach((f) => {
    f.addEventListener('submit', (e) => {
      e.preventDefault();
      const u = f.querySelector('[name=username]').value;
      const pw = f.querySelector('[name=password]').value;
      if (u === me.username && pw === me.password) {
        const s = load(); s.loggedIn = { ...(s.loggedIn || {}), [site]: true }; save(s);
        location.href = carry(f.dataset.next);
      } else {
        const err = document.getElementById('error');
        if (err) err.textContent = 'Invalid credentials';
      }
    });
  });

  // ---- generic action forms / buttons ----
  const record = (action, data, message) => {
    const s = load(); (s.actions = s.actions || []).push({ site, action, data }); save(s);
    const r = document.getElementById('result');
    if (r) r.textContent = message;
  };
  document.querySelectorAll('form[data-action]').forEach((f) => {
    f.addEventListener('submit', (e) => {
      e.preventDefault();
      const data = Object.fromEntries(new FormData(f).entries());
      // Never store the card number: a booking confirmation only keeps its tail.
      if (data.card) data.card = '**** ' + String(data.card).replace(/\D/g, '').slice(-4);
      record(f.dataset.action, data, f.dataset.success || 'Done');
    });
  });
  document.querySelectorAll('button[data-click-action]').forEach((b) => {
    b.addEventListener('click', () => record(b.dataset.clickAction, { item: b.dataset.item || '' }, b.dataset.success || 'Done'));
  });
  document.querySelectorAll('[data-logout]').forEach((a) => {
    a.addEventListener('click', () => { const s = load(); if (s.loggedIn) delete s.loggedIn[site]; save(s); });
  });

  document.body.dataset.ready = '1';
})();
