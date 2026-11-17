// shield_loader.js - tiny classic content script that starts Shield mode.
// Content scripts cannot use static `import`, so it loads the real module
// (src/shield/shield.js) dynamically. Shield is on or off for all tabs,
// controlled by the side panel and stored in chrome.storage.session.
(async () => {
  if (window.__privasightShieldLoader) return;
  window.__privasightShieldLoader = true;
  const mod = await import(chrome.runtime.getURL('src/shield/shield.js'));

  async function apply() {
    const s = await chrome.storage.session.get('shield');
    const cfg = s.shield || { enabled: false };
    if (cfg.enabled) mod.startShield({ strict: !!cfg.strict }); else mod.stopShield();
  }
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === 'session' && changes.shield) apply();
  });
  if (document.body) apply(); else document.addEventListener('DOMContentLoaded', apply);
})();
