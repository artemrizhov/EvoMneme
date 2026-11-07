// Exercise consent and loading behavior without contacting Google.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const code = fs.readFileSync(require.resolve('../website/analytics.js'), 'utf8');
const key = 'evomneme.analytics-consent.v2';

function browser({choice, legacyChoice, embedded = false, hostname = 'artemrizhov.github.io', blocked = false, writeBlocked = false} = {}) {
  const scripts = [], body = [], cookies = [], events = {};
  const element = () => ({dataset: {}, listeners: {}, hidden: false,
    setAttribute(k, v) { this[k] = v; }, focus() {},
    addEventListener(k, fn) { this.listeners[k] = fn; },
    querySelector() { return this; }});
  const document = {cookie: 'evomneme_ga=123; evomneme_ga_EXAMPLE000=456; other=value',
    createElement: element,
    head: {append(x) { scripts.push(x); }}, body: {append(...xs) { body.push(...xs); }}};
  let cookie = document.cookie;
  Object.defineProperty(document, 'cookie', {get() { return cookie; }, set(v) { cookies.push(v); }});
  const storage = new Map(choice ? [[key, choice]] : []);
  if (legacyChoice) storage.set('evomneme.analytics-consent.v1', legacyChoice);
  const window = {addEventListener(k, fn) { events[k] = fn; }};
  window.self = window;
  window.top = embedded ? {} : window;
  const location = {hostname, pathname: '/EvoMneme/demo/', reloads: 0, reload() { this.reloads++; }};
  const localStorage = {getItem(k) { if (blocked) throw Error('blocked'); return storage.get(k) ?? null; },
    setItem(k, v) { if (blocked || writeBlocked) throw Error('blocked'); storage.set(k, v); },
    removeItem(k) { if (blocked || writeBlocked) throw Error('blocked'); storage.delete(k); }};
  vm.runInNewContext(code, {window, document, location, localStorage});
  const choose = (value) => body[0].listeners.click({target: {dataset: {choice: value}}});
  return {window, scripts, body, storage, cookies, events, location, choose};
}

const fresh = browser();
assert.equal(fresh.scripts.length, 0, 'no Google load before consent');
assert.equal(fresh.window.dataLayer, undefined);
assert.equal(fresh.body[0].hidden, false);
assert.match(fresh.body[0].innerHTML, /href="\/EvoMneme\/privacy\/"/);
assert.match(fresh.body[0].innerHTML, /Website operator/);
const renewed = browser({legacyChoice: 'granted'});
assert.equal(renewed.scripts.length, 0, 'legacy grant cannot bypass renewed notice');
assert.equal(renewed.body[0].hidden, false);
assert.equal(renewed.storage.has('evomneme.analytics-consent.v1'), false);
fresh.choose('denied');
assert.equal(fresh.scripts.length, 0);
assert.equal(fresh.storage.get(key), 'denied');
fresh.body[1].listeners.click();
assert.equal(fresh.body[0].hidden, false, 'settings reopens choice');
fresh.choose('granted');
assert.equal(fresh.scripts.length, 1);
assert.equal(fresh.scripts[0].src, 'https://www.googletagmanager.com/gtag/js?id=G-EXAMPLE000');
const commands = fresh.window.dataLayer.map(x => Array.from(x));
const consent = commands.filter(x => x[0] === 'consent');
assert.equal(consent[0][1], 'default');
assert.equal(consent[0][2].analytics_storage, 'denied');
assert.equal(consent[0][2].ad_user_data, 'denied');
assert.equal(consent[1][2].analytics_storage, 'granted');
const config = commands.find(x => x[0] === 'config');
assert.equal(config[1], 'G-EXAMPLE000');
assert.equal(config[2].cookie_domain, 'none');
assert.equal(config[2].cookie_path, '/EvoMneme/');
assert.equal(config[2].cookie_prefix, 'evomneme');
assert.equal(config[2].allow_google_signals, false);
const defaults = commands.find(x => x[0] === 'set');
assert.equal(defaults[1].cookie_prefix, 'evomneme');
assert.equal(defaults[1].cookie_path, '/EvoMneme/');
assert.equal(commands[0], defaults, 'shared defaults precede even consent updates that can initialize cookies');
assert.ok(commands.indexOf(defaults) < commands.indexOf(config), 'cookie defaults precede destination initialization');
fresh.choose('granted');
assert.equal(fresh.scripts.length, 1, 'repeated consent cannot double-load');
fresh.choose('denied');
assert.equal(fresh.window['ga-disable-G-EXAMPLE000'], true);
assert.equal(fresh.location.reloads, 1);
assert.equal(fresh.cookies.filter(x => x.startsWith('other=')).length, 0);
assert.ok(fresh.cookies.some(x => x.startsWith('evomneme_ga=')));
assert.ok(fresh.cookies.every(x => x.includes('Path=/EvoMneme/')));

assert.equal(browser({choice: 'granted'}).scripts.length, 1);
assert.equal(browser({choice: 'denied'}).scripts.length, 0);
for (const options of [{embedded: true, choice: 'granted'}, {hostname: 'localhost', choice: 'granted'}]) {
  const b = browser(options);
  assert.equal(b.scripts.length, 0);
  assert.equal(b.body.length, 0, 'embedded/local viewer has no analytics UI');
}
const restricted = browser({blocked: true});
restricted.choose('granted');
assert.equal(restricted.scripts.length, 1, 'blocked storage does not break a per-visit choice');
const readOnly = browser({choice: 'granted', writeBlocked: true});
readOnly.choose('denied');
assert.equal(readOnly.window['ga-disable-G-EXAMPLE000'], true);
assert.equal(readOnly.location.reloads, 0, 'cannot reload into a stale saved grant');
assert.equal(readOnly.scripts.length, 1, 'no additional Google load');
assert.match(readOnly.body[1].textContent, /choice not saved/);
readOnly.choose('granted');
assert.equal(readOnly.window['ga-disable-G-EXAMPLE000'], false, 'can re-enable without double-loading');
assert.equal(readOnly.scripts.length, 1);
const tabs = browser({choice: 'granted'});
tabs.events.storage({key, newValue: 'denied'});
assert.equal(tabs.location.reloads, 1);
assert.equal(tabs.window['ga-disable-G-EXAMPLE000'], true);
console.log('Website analytics: consent, persistence, withdrawal, scoped cookies, cross-tab and embed/local exclusion passed.');
