// Optional GA4 for the public website only. The embedded graph never counts
// as a separate visit, and local previews/viewers never contact Google.
(function () {
  'use strict';
  const measurementId = window.evomnemeDeployment?.measurementId;
  if (!/^G-[A-Z0-9]+$/.test(measurementId || '') || window.self !== window.top || location.hostname !== 'artemrizhov.github.io'
      || !location.pathname.startsWith('/EvoMneme/')) return;

  const storageKey = 'evomneme.analytics-consent.v2';
  const disableKey = 'ga-disable-' + measurementId;
  let loaded = false;
  let choice;
  try { choice = localStorage.getItem(storageKey); } catch { /* Per-visit choice still works. */ }
  // Ask again for the owner-specific privacy notice; never migrate a prior grant.
  try { localStorage.removeItem('evomneme.analytics-consent.v1'); } catch { /* Optional cleanup. */ }

  const panel = document.createElement('section');
  panel.id = 'cookie-consent';
  panel.className = 'analytics-consent';
  panel.setAttribute('aria-label', 'Cookie preferences');
  panel.innerHTML = '<div class="cookie-banner-content"><div class="cookie-banner-copy">'
    + '<h2>Cookies on this site</h2>'
    + '<p>We use optional cookies to measure visits and improve this website. '
    + 'You can accept or reject them and change your choice at any time. '
    + 'Read our <a href="/EvoMneme/privacy/">Privacy &amp; Cookies</a> for details.</p></div>'
    + '<div class="cookie-banner-actions"><button type="button" data-choice="granted">Accept optional cookies</button>'
    + '<button type="button" data-choice="denied">Reject optional cookies</button></div></div>';
  const settingsLinks = [...document.querySelectorAll('[data-cookie-settings]')];
  let settingsOpener;
  for (const link of settingsLinks) link.setAttribute('aria-controls', panel.id);
  document.body.append(panel);

  const showPanel = (visible) => {
    panel.hidden = !visible;
    for (const link of settingsLinks) link.setAttribute('aria-expanded', String(visible));
  };
  const load = () => {
    window[disableKey] = false;
    if (loaded) return;
    loaded = true;
    window.dataLayer = window.dataLayer || [];
    window.gtag = function () { window.dataLayer.push(arguments); };
    const configuration = {
      cookie_domain: 'none', cookie_path: '/EvoMneme/', cookie_prefix: 'evomneme',
      cookie_flags: 'SameSite=Lax;Secure',
      allow_google_signals: false, allow_ad_personalization_signals: false
    };
    // Set shared defaults first: even consent updates can initialize cookies
    // before destination config is processed by the loaded Google tag.
    window.gtag('set', configuration);
    window.gtag('consent', 'default', {
      analytics_storage: 'denied', ad_storage: 'denied',
      ad_user_data: 'denied', ad_personalization: 'denied'
    });
    window.gtag('consent', 'update', { analytics_storage: 'granted' });
    window.gtag('js', new Date());
    window.gtag('config', measurementId, configuration);
    const script = document.createElement('script');
    script.async = true;
    script.src = 'https://www.googletagmanager.com/gtag/js?id=' + measurementId;
    document.head.append(script);
  };
  const apply = (value, persisted = true) => {
    choice = value;
    for (const link of settingsLinks) {
      link.textContent = persisted ? 'Cookie settings' : 'Cookie settings (choice not saved)';
      link.title = persisted ? '' : 'Your browser could not save this choice. It applies only to this page.';
    }
    showPanel(value !== 'granted' && value !== 'denied');
    if (value === 'granted') {
      load();
    } else {
      window[disableKey] = true;
      // These cookies are host-only and project-scoped, matching config above.
      for (const cookie of document.cookie.split(';')) {
        const name = cookie.trim().split('=')[0];
        if (name.startsWith('evomneme_ga')) {
          document.cookie = name + '=; Max-Age=0; Path=/EvoMneme/; SameSite=Lax; Secure';
        }
      }
      // Unload an already-running Google tag on withdrawal. The saved denial
      // prevents loading it again; no consent-denied measurement is requested.
      if (loaded && persisted) location.reload();
    }
  };
  panel.addEventListener('click', (event) => {
    const value = event.target.dataset.choice;
    if (value !== 'granted' && value !== 'denied') return;
    let persisted = true;
    try { localStorage.setItem(storageKey, value); } catch {
      persisted = false;
      // Remove an older grant if possible; never reload into it after a failed
      // denial write. The disable flag still stops collection on this page.
      try { localStorage.removeItem(storageKey); } catch { /* Storage is inaccessible. */ }
    }
    apply(value, persisted);
    settingsOpener?.focus({ preventScroll: true });
  });
  for (const link of settingsLinks) {
    link.addEventListener('click', (event) => {
      event.preventDefault();
      settingsOpener = link;
      showPanel(true);
      panel.querySelector('button').focus({ preventScroll: true });
    });
  }
  window.addEventListener('storage', (event) => {
    if (event.key === storageKey || event.key === null) apply(event.newValue);
  });
  apply(choice);
})();
