// vault.js
// The Local Token Vault. Real values never leave this object.
//
//   tokenFor('PHONE', '98765 43210')  -> '[PHONE_1]'   (same value -> same token)
//   resolve('type [PHONE_1] now')     -> 'type 98765 43210 now'
//
// Two kinds of entries:
//   * detected PII  - created automatically while sanitising a page
//   * user secrets  - set by the user (e.g. {PASSWORD}) so the agent can log
//                     in without the model ever seeing the real password.
// The vault lives only in memory of the side-panel page. Nothing is written
// to disk or sent to the server.

export class Vault {
  constructor() {
    this.byToken = new Map();
    this.byKey = new Map();
    this.counters = {};
  }

  static normalise(type, value) {
    const v = String(value).trim();
    return type + '|' + (type === 'EMAIL' ? v.toLowerCase() : v.replace(/[\s-]/g, '').toLowerCase());
  }

  /** Placeholder for a detected value, creating it on first sight. */
  tokenFor(type, value) {
    const key = Vault.normalise(type, value);
    if (this.byKey.has(key)) return this.byKey.get(key);
    const n = (this.counters[type] = (this.counters[type] || 0) + 1);
    const token = `[${type}_${n}]`;
    this.byKey.set(key, token);
    this.byToken.set(token, String(value));
    return token;
  }

  /** A user-defined secret under a fixed token such as {PASSWORD}. */
  setSecret(token, value) {
    this.byToken.set(token, String(value));
  }

  hasToken(token) {
    return this.byToken.has(token);
  }

  /** Replace every known token in `text` with its real value (local use only). */
  resolve(text) {
    let out = String(text);
    for (const [token, value] of this.byToken) out = out.split(token).join(value);
    return out;
  }

  /**
   * Find every place where a value the vault already protects appears in
   * `text` (e.g. the username the agent just typed into a field). These are
   * hidden regardless of what any detector thinks of them.
   */
  findKnown(text) {
    const found = [];
    for (const [token, value] of this.byToken) {
      if (value.length < 4) continue;
      let at = text.indexOf(value);
      while (at !== -1) {
        found.push({ start: at, end: at + value.length, type: 'KNOWN', value, token, source: 'vault' });
        at = text.indexOf(value, at + value.length);
      }
    }
    return found;
  }

  /** Real values, used by the privacy gate to look for leaks. */
  realValues() {
    return [...this.byToken.values()].filter((v) => v.length >= 4);
  }

  /** Plain-object form, so Shield mode can share one vault across page loads
   *  through chrome.storage.session (memory only, wiped when the browser closes). */
  toJSON() {
    return { byToken: [...this.byToken], byKey: [...this.byKey], counters: this.counters };
  }

  static fromJSON(obj) {
    const v = new Vault();
    if (!obj) return v;
    v.byToken = new Map(obj.byToken || []);
    v.byKey = new Map(obj.byKey || []);
    v.counters = obj.counters || {};
    return v;
  }

  clear() {
    this.byToken.clear();
    this.byKey.clear();
    this.counters = {};
  }
}
