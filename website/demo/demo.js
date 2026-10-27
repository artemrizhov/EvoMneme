(function () {
  'use strict';
  // This script is deferred immediately before the unchanged local app.js.
  // Read the opt-in before app.js normalizes the URL. Keep every shared DOM ID:
  // the embedded presentation only hides controls; the renderer is unchanged.
  if (new URL(location.href).searchParams.get('embed') === '1') document.body.classList.add('demo-embed');
  const snapshotState = document.documentElement.dataset;
  snapshotState.publicSnapshotState = 'loading';
  let snapshotAccepted = false;
  const failSnapshot = () => {
    if (snapshotState.publicSnapshotState !== 'ready') snapshotState.publicSnapshotState = 'error';
  };
  const originalFetch = window.fetch.bind(window);
  const snapshotURL = new URL('../data/demo.json', location.href);
  const loaded = originalFetch(snapshotURL).then(response => {
    if (!response.ok) throw new Error('The published graph snapshot could not be loaded.');
    return response.json();
  }).then(data => EvoMnemeStatic.createAPI(data)).catch(error => {
    failSnapshot();
    throw error;
  });
  const resourceLoads = new Map();
  async function historyResource(api, route) {
    const kind = route === 'replay' ? 'replay' : ['changes', 'events'].includes(route) ? 'timeline' : null;
    const name = kind && api.metadata.history?.[kind];
    if (!name) return undefined;
    // History assets belong beside the graph export, including on subpath hosts.
    if (!/^[\w-]+\.json$/.test(name)) throw new Error('Invalid public history resource path');
    if (!resourceLoads.has(name)) resourceLoads.set(name, originalFetch(new URL(name, snapshotURL)).then(response => {
      if (!response.ok) throw new Error('The published history could not be loaded.');
      return response.json();
    }));
    return resourceLoads.get(name);
  }
  window.fetch = async function (input, options = {}) {
    const url = new URL(typeof input === 'string' || input instanceof URL ? input : input.url, location.href);
    if (url.origin !== location.origin || !url.pathname.startsWith('/api/')) return originalFetch(input, options);
    try {
      const api = await loaded;
      const values = JSON.parse(options.body || '{}');
      const route = url.pathname.slice(5);
      const initial = api.initialHistory(route, values);
      const resource = initial ? undefined : await historyResource(api, route);
      const response = new Response(JSON.stringify(initial || api.request(route, values, resource)), {status: 200, headers: {'Content-Type': 'application/json'}});
      if (route === 'snapshot') snapshotAccepted = true;
      return response;
    } catch (error) {
      if (url.pathname === '/api/snapshot') failSnapshot();
      return new Response(JSON.stringify({error: error.message}), {status: 400, headers: {'Content-Type': 'application/json'}});
    }
  };
  // app.js requires a local access token. A public marker only satisfies its UI
  // guard; requests above are resolved from JSON, with no server or credentials.
  history.replaceState(null, '', location.pathname + '#token=public-snapshot');
  const byId = id => document.getElementById(id);
  byId('live').checked = false;
  const chrome = document.createElement('section');
  chrome.className = 'demo-chrome'; chrome.setAttribute('aria-label', 'Public demo information');
  const back = document.createElement('a'); back.href = '../'; back.textContent = '← EvoMneme';
  const title = document.createElement('div');
  const heading = document.createElement('strong'); heading.textContent = 'Explore a real memory graph';
  const caption = document.createElement('p'); caption.textContent = 'Read-only public snapshot · search, filter, select a node, or double-click to follow its relationships.';
  title.append(heading, caption);
  const provenance = document.createElement('details');
  const summary = document.createElement('summary'); summary.textContent = 'Snapshot provenance'; provenance.append(summary);
  const provenanceBody = document.createElement('div'); provenanceBody.className = 'demo-provenance'; provenance.append(provenanceBody);
  chrome.append(back, title, provenance); document.body.prepend(chrome);
  document.title = 'EvoMneme · Interactive public graph';
  const storageMode = byId('storageMode') || document.querySelector('.badge');
  const publicMode = 'PUBLIC SNAPSHOT · READ ONLY';
  storageMode.textContent = publicMode;
  document.querySelector('.graph-caption span:last-child').textContent = 'Drag to move · scroll to zoom · select to inspect';
  byId('followGraph').parentElement.lastChild.textContent = ' Refit after filter changes';
  byId('refresh').textContent = 'Refresh graph';
  byId('selectionHint').textContent = 'Select a node or relationship to inspect its attributes and repository source. Double-click a node to explore its neighborhood.';
  const connection = byId('connection');
  const sliceInfo = byId('sliceInfo');
  const journalStatus = byId('journalStatus');
  const statusObserver = new MutationObserver(() => {
    const connected = connection.textContent.startsWith('● Connected') || connection.textContent === '● Published snapshot';
    // sliceInfo is populated by the shared renderer after awaiting draw().
    // Require both its result and the completed status, not a pre-created canvas.
    if (snapshotAccepted && connected && /^\d+ nodes\b/.test(sliceInfo.textContent) && snapshotState.publicSnapshotState !== 'error') snapshotState.publicSnapshotState = 'ready';
    if (connection.textContent.startsWith('● Connected')) {
      connection.textContent = '● Published snapshot';
    } else if (/^(Connection \/ query error|Refresh failed|Graph update failed)/.test(connection.textContent)) failSnapshot();
    // The shared viewer updates this badge on every refresh. Static publishing
    // has neither a live database nor a persistent change journal.
    if (storageMode.textContent !== publicMode) storageMode.textContent = publicMode;
    if (journalStatus.textContent.startsWith('Database history ')) journalStatus.textContent = 'Saved row history · fixed public export';
  });
  statusObserver.observe(connection, {childList: true});
  statusObserver.observe(storageMode, {childList: true});
  statusObserver.observe(sliceInfo, {childList: true});
  statusObserver.observe(journalStatus, {childList: true});
  loaded.then(api => {
    const metadata = api.metadata;
    if (metadata.history?.timeline) {
      document.body.classList.add('demo-history');
      const activityHeading = document.querySelector('.activity-heading h2');
      if (activityHeading) activityHeading.textContent = 'Saved calls & changes';
      const activityHint = document.querySelector('#activityPanel > p.hint');
      if (activityHint) activityHint.textContent = 'All exported calls and row changes are available through Load older calls & changes. Highlighting is local to this browser. Caller identities are omitted from this public export; the browser retains a window of up to 10,000 loaded activities.';
    }
    if (!metadata.history?.replay) {
      byId('replayOpen').disabled = true;
      byId('replayStatus').textContent = 'No saved graph replay in this export.';
    }
    const revision = String(metadata.revision || metadata.commit || '');
    const publicRevision = String(metadata.public_revision || '');
    const description = document.createElement('p');
    description.textContent = 'A fixed export of a real EvoMneme project-memory database. This is a published snapshot, not a live project connection.';
    provenanceBody.append(description);
    for (const [label, value] of [['Project', metadata.title], ['Analyzed revision', revision], ['Verified public source revision', publicRevision], ['Generated', metadata.generated_at], ['Counts', metadata.counts], ['Saved history', metadata.history?.counts], ['Selection', metadata.selection], ['Provenance', metadata.provenance], ['Limitations', metadata.limitations], ['Privacy', metadata.privacy]]) {
      if (value == null) continue;
      const p = document.createElement('p'); p.textContent = label + ': ' + (typeof value === 'object' ? JSON.stringify(value) : String(value)); provenanceBody.append(p);
    }
    if (/^https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/?$/.test(metadata.repository || '') && /^[a-f0-9]{40}$/i.test(publicRevision)) {
      const source = document.createElement('a'); source.href = metadata.repository.replace(/\/$/, '') + '/tree/' + publicRevision;
      source.textContent = 'Browse the pinned source ↗'; source.target = '_blank'; source.rel = 'noopener noreferrer'; provenanceBody.append(source);
    }
    const detail = byId('detail');
    new MutationObserver(() => {
      for (const hint of detail.querySelectorAll('p.hint')) {
        if (hint.textContent.startsWith('No supporting evidence returned.')) hint.textContent = 'No supporting evidence is attached to this stored element.';
      }
      for (const dl of detail.querySelectorAll('dl')) {
        if (dl.dataset.demoLinked) continue;
        dl.dataset.demoLinked = 'true';
        const row = {};
        for (const dt of dl.querySelectorAll('dt')) row[dt.textContent] = dt.nextElementSibling?.textContent;
        const href = api.sourceLink(row);
        if (!href) continue;
        const dt = document.createElement('dt'); dt.textContent = 'Pinned repository source';
        const dd = document.createElement('dd'), link = document.createElement('a');
        link.href = href; link.textContent = row.source_path + (Number(row.line_start) > 0 ? ':' + row.line_start : '') + ' ↗';
        link.target = '_blank'; link.rel = 'noopener noreferrer'; dd.append(link); dl.append(dt, dd);
      }
    }).observe(detail, {childList: true, subtree: true});
  }).catch(error => { provenanceBody.textContent = error.message; });
})();
