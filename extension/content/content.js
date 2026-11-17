// content.js - runs inside the page the agent is driving.
//
// Two jobs, and neither involves any network access or any detection logic:
//   1. SNAPSHOT: describe what is on screen (text runs, form fields, media,
//      their on-screen rectangles). The side panel decides what is sensitive.
//   2. ACT: carry out one action (click / type / scroll ...) chosen by the
//      planner. Real values arrive here already resolved from the local vault.
//
// This file is a classic script (content scripts cannot use static imports),
// so it is self-contained.

(() => {
  if (window.__privasightLoaded) return;
  window.__privasightLoaded = true;

  const SKIP_TAGS = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'HEAD', 'TITLE', 'META', 'LINK', 'OPTION']);
  const INTERACTIVE = 'a[href],button,input,select,textarea,[role=button],[role=link],[role=tab],[role=menuitem],[onclick],summary';

  let runNodes = new Map(); // run id -> Text node (or Element for input values)
  let elementsById = new Map(); // ps id -> Element

  function rectOf(r) {
    return { x: r.left, y: r.top, w: r.width, h: r.height };
  }

  function inViewport(r) {
    return r.width > 1 && r.height > 1 && r.bottom > 0 && r.right > 0 &&
      r.top < window.innerHeight && r.left < window.innerWidth;
  }

  function isVisible(el) {
    if (!el || !el.isConnected) return false;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || Number(cs.opacity) === 0) return false;
    // Text hidden off-screen or at 1px is the usual vehicle for injected
    // instructions, so it is excluded from what the agent can read.
    if (cs.fontSize && parseFloat(cs.fontSize) < 4) return false;
    return true;
  }

  function labelFor(el) {
    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label');
    if (el.id) {
      const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (l) return l.textContent.trim();
    }
    const wrap = el.closest('label');
    if (wrap) return wrap.textContent.trim();
    const prev = el.previousElementSibling;
    if (prev && prev.tagName === 'LABEL') return prev.textContent.trim();
    return '';
  }

  function snapshot() {
    runNodes = new Map();
    elementsById = new Map();
    const runs = [];
    const fields = [];
    const media = [];
    let runId = 0;
    let psId = 0;

    // ---- text runs (visible text nodes) ----
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      const text = node.nodeValue;
      const parent = node.parentElement;
      if (!parent || SKIP_TAGS.has(parent.tagName) || !text.trim()) continue;
      if (!isVisible(parent)) continue;
      const range = document.createRange();
      range.selectNodeContents(node);
      const box = range.getBoundingClientRect();
      if (!inViewport(box)) continue;
      const id = 'r' + runId++;
      runNodes.set(id, node);
      runs.push({ id, text, rect: rectOf(box) });
    }

    // ---- interactive elements and form fields ----
    for (const el of document.querySelectorAll(INTERACTIVE)) {
      if (!isVisible(el)) continue;
      const box = el.getBoundingClientRect();
      if (!inViewport(box)) continue;
      const id = psId++;
      el.setAttribute('data-ps-id', String(id));
      elementsById.set(id, el);
      const isInput = ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName);
      const entry = {
        id,
        tag: el.tagName.toLowerCase(),
        type: el.getAttribute('type') || '',
        role: el.getAttribute('role') || '',
        name: el.getAttribute('name') || '',
        domId: el.id || '',
        label: labelFor(el),
        placeholder: el.getAttribute('placeholder') || '',
        autocomplete: el.getAttribute('autocomplete') || '',
        text: isInput ? '' : (el.innerText || el.textContent || '').trim().slice(0, 120),
        href: el.tagName === 'A' ? (el.getAttribute('href') || '') : '',
        checked: el.type === 'checkbox' || el.type === 'radio' ? !!el.checked : undefined,
        rect: rectOf(box),
      };
      if (isInput && el.type !== 'checkbox' && el.type !== 'radio' && el.type !== 'submit' && el.type !== 'button') {
        entry.value = String(el.value || '');
        if (entry.value) {
          const rid = 'v' + id;
          runNodes.set(rid, el);
          entry.valueRun = rid;
        }
      }
      fields.push(entry);
    }

    // ---- media that can contain faces or text ----
    for (const el of document.querySelectorAll('img,video,canvas,svg image,[style*="background-image"]')) {
      if (!isVisible(el.parentElement || el)) continue;
      const box = el.getBoundingClientRect();
      if (!inViewport(box) || box.width < 24 || box.height < 24) continue;
      const id = 'm' + media.length;
      el.setAttribute('data-ps-media', id);
      media.push({
        id,
        kind: el.tagName.toLowerCase() === 'video' ? 'video' : el.tagName.toLowerCase() === 'canvas' ? 'canvas' : 'image',
        alt: el.getAttribute('alt') || '',
        hint: [el.className && el.className.baseVal === undefined ? el.className : '', el.getAttribute('alt') || '', el.getAttribute('src') || ''].join(' ').slice(0, 200),
        rect: rectOf(box),
      });
    }

    return {
      url: location.href,
      title: document.title,
      viewport: { w: window.innerWidth, h: window.innerHeight, dpr: window.devicePixelRatio || 1 },
      scroll: { y: window.scrollY, max: Math.max(0, document.documentElement.scrollHeight - window.innerHeight) },
      runs, fields, media,
    };
  }

  // Exact on-screen rectangles for character ranges inside a text run.
  function rects(requests) {
    return requests.map((req) => {
      const target = runNodes.get(req.runId);
      if (!target) return [];
      if (target.nodeType !== Node.TEXT_NODE) return [rectOf(target.getBoundingClientRect())]; // input value: box the whole field
      const range = document.createRange();
      const len = target.nodeValue.length;
      range.setStart(target, Math.min(req.start, len));
      range.setEnd(target, Math.min(req.end, len));
      return [...range.getClientRects()].filter((r) => r.width > 0).map(rectOf);
    });
  }

  function setNativeValue(el, value) {
    const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, value);
  }

  function act(a) {
    try {
      if (a.type === 'scroll') {
        window.scrollBy({ top: (a.direction === 'up' ? -1 : 1) * Math.round(window.innerHeight * 0.8), behavior: 'instant' });
        return { ok: true };
      }
      if (a.type === 'navigate') { location.href = a.url; return { ok: true }; }
      if (a.type === 'wait') return { ok: true };
      const el = elementsById.get(Number(a.id)) || document.querySelector(`[data-ps-id="${a.id}"]`);
      if (!el) return { ok: false, error: `element ${a.id} not found` };
      el.scrollIntoView({ block: 'center', behavior: 'instant' });
      if (a.type === 'click') { el.click(); return { ok: true }; }
      if (a.type === 'type') {
        el.focus();
        setNativeValue(el, '');
        el.dispatchEvent(new Event('input', { bubbles: true }));
        setNativeValue(el, a.text);
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        if (a.submit) {
          el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
          if (el.form) el.form.requestSubmit ? el.form.requestSubmit() : el.form.submit();
        }
        return { ok: true };
      }
      if (a.type === 'select') {
        const opt = [...el.options].find((o) => o.text.trim() === a.text || o.value === a.text);
        if (!opt) return { ok: false, error: `option "${a.text}" not found` };
        el.value = opt.value;
        el.dispatchEvent(new Event('change', { bubbles: true }));
        return { ok: true };
      }
      return { ok: false, error: `unknown action ${a.type}` };
    } catch (err) {
      return { ok: false, error: String(err && err.message ? err.message : err) };
    }
  }

  chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
    if (!msg || !msg.ps) return false;
    if (msg.ps === 'snapshot') reply(snapshot());
    else if (msg.ps === 'rects') reply(rects(msg.requests));
    else if (msg.ps === 'act') reply(act(msg.action));
    else if (msg.ps === 'ping') reply({ ok: true });
    return false;
  });
})();
