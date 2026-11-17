// background.js - small on purpose.
// 1. Opens the side panel when the toolbar icon is clicked.
// 2. Lets content scripts read the Shield vault in chrome.storage.session.
// 3. Relays name-detection requests from Shield mode to an offscreen document,
//    which hosts the BERT worker (content scripts can't run it themselves).

chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
chrome.storage.session.setAccessLevel({ accessLevel: 'TRUSTED_AND_UNTRUSTED_CONTEXTS' }).catch(() => {});

async function ensureOffscreen() {
  if (await chrome.offscreen.hasDocument()) return;
  await chrome.offscreen.createDocument({
    url: 'offscreen/ner.html',
    reasons: ['WORKERS'],
    justification: 'Run the on-device name-detection model in a Web Worker',
  });
}

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg.ps !== 'ner') return false;
  ensureOffscreen()
    .then(() => chrome.runtime.sendMessage({ ps: 'ner-run', texts: msg.texts }))
    .then((res) => reply(res || { results: [] }))
    .catch(() => reply({ results: [] }));
  return true;
});
