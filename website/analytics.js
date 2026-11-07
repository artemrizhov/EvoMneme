// Optional GA4 for the public website only. The embedded graph never counts
// as a separate visit, and local previews/viewers never contact Google.
(function () {
  'use strict';
  if (window.self !== window.top || location.hostname !== 'artemrizhov.github.io'
      || !location.pathname.startsWith('/EvoMneme/')) return;

  const measurementId = 'G-EXAMPLE000';
  const storageKey = 'evomneme.analytics-consent.v1';
  const disableKey = 'ga-disable-' + measurementId;
  let loaded = false;
  let choice;
  try { choice = localStorage.getItem(storageKey); } catch { /* Per-visit choice still works. */ }

  const panel = document.createElement('section');
  panel.className = 'analytics-consent';
  panel.setAttribute('aria-label', 'Analytics preferences');
  panel.innerHTML = '<h2>Optional analytics</h2>'
    + '<p>Allow Google Analytics cookies to help us understand visits to EvoMneme? '
    + 'Google receives usage information such as pages viewed, device information and approximate location. '
    + 'Advertising features are disabled. You can decline or change your choice at any time. '
    + '<a href="https://policies.google.com/technologies/partner-sites">How Google uses this information</a>.</p>'
    + '<div><button type="button" data-choice="granted">Allow analytics</button>'
    + '<button type="button" data-choice="denied">Decline</button></div>';
  const settings = document.createElement('button');
  settings.type = 'button';
  settings.className = 'analytics-settings';
  settings.textContent = 'Analytics settings';
  settings.setAttribute('aria-expanded', 'false');
  document.body.append(panel, settings);

  const showPanel = (visible) => {
    panel.hidden = !visible;
    settings.setAttribute('aria-expanded', String(visible));
  };
  const load = () => {
    window[disableKey] = false;
    if (loaded) return;
    loaded = true;
    window.dataLayer = window.dataLayer || [];
    window.gtag = function () { window.dataLayer.push(arguments); };
    window.gtag('consent', 'default', {
      analytics_storage: 'denied', ad_storage: 'denied',
      ad_user_data: 'denied', ad_personalization: 'denied'
    });
    window.gtag('consent', 'update', { analytics_storage: 'granted' });
    window.gtag('js', new Date());
    const configuration = {
      cookie_domain: 'none', cookie_path: '/EvoMneme/', cookie_prefix: 'evomneme',
      cookie_flags: 'SameSite=Lax;Secure',
      allow_google_signals: false, allow_ad_personalization_signals: false
    };
    // Set shared defaults before the destination initializes. The loaded tag
    // can initialize its cookies before processing destination-only settings.
    window.gtag('set', configuration);
    window.gtag('config', measurementId, configuration);
    const script = document.createElement('script');
    script.async = true;
    script.src = 'https://www.googletagmanager.com/gtag/js?id=' + measurementId;
    document.head.append(script);
  };
  const apply = (value, persisted = true) => {
    choice = value;
    settings.textContent = persisted ? 'Analytics settings' : 'Analytics settings (choice not saved)';
    settings.title = persisted ? '' : 'Your browser could not save this choice. It applies only to this page.';
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
    settings.focus();
  });
  settings.addEventListener('click', () => {
    showPanel(panel.hidden);
    if (!panel.hidden) panel.querySelector('button').focus();
  });
  window.addEventListener('storage', (event) => {
    if (event.key === storageKey || event.key === null) apply(event.newValue);
  });
  apply(choice);
})();
