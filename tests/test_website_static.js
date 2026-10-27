'use strict';
// Run with node tests/test_website_static.js. Exercise the browser's actual API
// implementation without a DOM or a second implementation of graph behavior.
const assert = require('node:assert/strict');
const {createAPI, sourceLink} = require('../website/demo/static-api.js');
const metadata = {repository: 'https://github.com/example/memory', revision: 'a'.repeat(40), public_revision: 'a'.repeat(40)};
const node = (id, extra = {}) => ({graph_id: id, label: id, layer: 'code', kind: 'function', scope_id: 'v1',
  validity: 'current', confidence: 'confirmed', evidence_count: 1, source_path: 'src/main.py', ...extra});
const edge = (id, source, target, extra = {}) => ({graph_id: id, source, target, layer: 'code', kind: 'calls', ...extra});
const api = createAPI({metadata, nodes: [node('a', {summary: 'Entry point'}), node('b'), node('c', {source_path: null}),
  node('d', {layer: 'knowledge', kind: 'claim', evidence_count: 0, validity: 'stale'}), node('z', {evidence_count: 0})],
edges: [edge('ab', 'a', 'b'), edge('bc', 'b', 'c'), edge('ca', 'c', 'a'), edge('cd', 'c', 'd', {layer: 'cross', kind: 'supports'})]});
const ids = result => result.nodes.map(n => n.graph_id);
assert.deepEqual(ids(api.snapshot({whole_graph: true, limit: 1, offset: 999})), ['a', 'b', 'c', 'd', 'z']);
const first = api.request('snapshot', {limit: 2});
assert.deepEqual(ids(first), ['a', 'b']); assert.equal(first.node_has_more, true);
assert.equal(first.edges.length, 1); assert.equal(first.boundary_edges, 2);
assert.deepEqual(ids(api.snapshot({limit: 2, offset: 2})), ['c', 'd']);
assert.equal(api.snapshot({offset: 99}).nodes.length, 0);
assert.deepEqual(ids(api.snapshot({search: 'ENTRY'})), ['a']);
assert.deepEqual(ids(api.snapshot({source_path: 'src/main.py', kind: 'claim'})), ['d']);
assert.deepEqual(ids(api.snapshot({null_field: 'source_path'})), ['c']);
assert.deepEqual(ids(api.snapshot({kind: ['function', 'claim'], validity: ['stale']})), ['d']);
assert.deepEqual(ids(api.snapshot({kind: [], scope_id: ['v1']})), ['a', 'b', 'c', 'd', 'z']);
assert.equal(api.snapshot({edge_kind: ['calls', 'supports']}).edges.length, 4);
assert.equal(api.snapshot({edge_kind: ['supports', 'missing']}).edges.length, 1);
assert.equal(api.snapshot({aggregate: 'kind', kind: ['function', 'claim']}).grouped_members, 5);
for (const kind of [false, 5, {}, [null], ['function', 7], Array(1001).fill('x'), ['x'.repeat(10001)]]) {
  assert.throws(() => api.snapshot({kind}), /Invalid filter/);
}
assert.deepEqual(ids(api.snapshot({focus: 'isolated'})), ['z']);
assert.deepEqual(ids(api.snapshot({focus: 'unsupported'})), ['d', 'z']);
assert.equal(api.snapshot({}).isolated_total, 1);
assert.deepEqual(ids(api.snapshot({root: 'a', depth: 0})), ['a']);
assert.deepEqual(ids(api.snapshot({root: 'a', depth: 1})), ['a', 'b', 'c']);
assert.deepEqual(ids(api.snapshot({root: 'a', depth: 2})), ['a', 'b', 'c', 'd']);
assert.deepEqual(ids(api.snapshot({root: 'a', depth: 99})), ['a', 'b', 'c', 'd']);
// Traversal uses edge filters and applies node filters after finding reachability.
assert.deepEqual(ids(api.snapshot({root: 'a', depth: 4, kind: 'claim'})), ['d']);
assert.deepEqual(ids(api.snapshot({root: 'a', depth: 4, edge_kind: 'supports'})), ['a']);
const hidden = api.snapshot({excluded_layers: ['knowledge']});
assert.equal(hidden.nodes.length, 4); assert.equal(hidden.edges.length, 3);
assert.equal(hidden.layers.find(l => l.id === 'knowledge').nodes, 1);
assert.equal(hidden.facets.kind.find(f => f.value === 'claim').count, 1);
assert.equal(api.snapshot({excluded_layers: ['cross']}).edges.length, 3);
assert.throws(() => api.snapshot({excluded_layers: 'code'}), /Invalid excluded/);
const grouped = api.snapshot({aggregate: 'layer', whole_graph: true});
assert.equal(grouped.grouped_members, 5); assert.equal(grouped.nodes.length, 2);
assert.equal(grouped.nodes.find(n => n.group_value === 'code').member_count, 4);
assert.equal(grouped.edges.reduce((n, e) => n + e.member_count, 0), 4);
const nullGroup = api.snapshot({aggregate: 'source_path'}).nodes.find(n => n.group_value === null);
assert.equal(nullGroup.member_count, 1);
assert.equal(api.snapshot({aggregate: 'layer', limit: 1}).boundary_edges, 1);
assert.throws(() => api.snapshot({aggregate: 'invalid'}), /Grouping field/);
assert.equal(api.detail({type: 'nodes', id: 'a'}).rows[0].summary, 'Entry point');
assert.equal(api.detail({type: 'edges', id: 'ab'}).rows[0].target, 'b');
assert.deepEqual(api.detail({type: 'nodes', id: 'missing'}).rows, []);
assert.throws(() => api.detail({type: 'table', id: 'a'}), /Unknown graph/);
const evidenceAPI = createAPI({metadata,
  nodes: [node('opaque-member', {scope_id: 'scope', id: 'member'}), node('opaque-file', {scope_id: 'scope', id: 'file', kind: 'file'})],
  edges: [edge('opaque-edge', 'opaque-member', 'opaque-file', {scope_id: 'scope', id: 'member'})],
  evidence: [...Array.from({length: 205}, (_, index) => ({scope_id: 'scope', id: 'node-proof-' + index, node_id: 'member', edge_id: null, description: 'Stored node evidence ' + index})),
    {scope_id: 'scope', id: 'edge-proof', node_id: null, edge_id: 'member', description: 'Stored edge evidence'},
    {scope_id: 'other-scope', id: 'foreign-proof', node_id: 'member', edge_id: null, description: 'Different scope'}],
  symbol_details: [{scope_id: 'scope', node_id: 'member', qualified_name: 'module.member', signature: 'member()', language: 'python'}],
  file_details: [{scope_id: 'scope', node_id: 'file', inspected_at: '2026-10-27', notes: 'Stored file review'}]});
const nodeDetails = evidenceAPI.detail({type: 'nodes', id: 'opaque-member'});
assert.equal(nodeDetails.evidence.length, 205, 'all exported attachments are inspectable without a hidden cap');
assert.equal(nodeDetails.evidence_has_more, false);
assert.ok(nodeDetails.evidence.every(item => item.description.startsWith('Stored node evidence')));
assert.equal(nodeDetails.rows[0].qualified_name, 'module.member');
assert.equal(nodeDetails.coverage[0].node_id, 'file', 'file coverage follows owner identity and source path, not graph ID encoding');
assert.equal(evidenceAPI.detail({type: 'edges', id: 'opaque-edge'}).evidence[0].id, 'edge-proof');
assert.equal(evidenceAPI.detail({type: 'edges', id: 'opaque-edge'}).coverage.length, 0);
assert.equal(evidenceAPI.snapshot({}).nodes.find(row => row.graph_id === 'opaque-member').qualified_name, undefined, 'detail enrichment does not mutate the graph snapshot');
assert.equal(api.request('events', {}).enabled, false);
const history = {journal: {version: 3, enabled: true},
  changes: Array.from({length: 5}, (_, index) => ({change_id: index + 1, source: 'database_change'})),
  calls: Array.from({length: 5}, (_, index) => ({activity_record_id: index + 1, source: 'sql'}))};
for (const [route, field] of [['changes', 'change_id'], ['events', 'activity_record_id']]) {
  const latest = api.request(route, {limit: 2}, history);
  assert.deepEqual(latest.events.map(event => event[field]), [4, 5]);
  assert.equal(latest.before_id, 4); assert.equal(latest.after_id, 5); assert.equal(latest.has_older, true);
  assert.deepEqual(api.request(route, {before_id: 4, limit: 2}, history).events.map(event => event[field]), [2, 3]);
  const next = api.request(route, {after_id: 2, limit: 2}, history);
  assert.deepEqual(next.events.map(event => event[field]), [3, 4]); assert.equal(next.has_more, true);
  assert.equal(api.request(route, {before_id: 1}, history).events.length, 0);
  assert.throws(() => api.request(route, {after_id: 1, before_id: 4}, history), /Choose/);
  assert.throws(() => api.request(route, {after_id: -1}, history), /Invalid/);
}
assert.throws(() => api.request('replay', {}), /No saved graph history/);
const savedReplay = {journal: history.journal, nodes: [], edges: [], events: []};
assert.equal(api.request('replay', {}, savedReplay), savedReplay);
assert.throws(() => api.request('query', {sql: 'SELECT 1'}), /graph exploration only/);
const pinned = (path, revision = metadata.revision) => metadata.repository + '/blob/' + revision + '/' + path;
assert.equal(sourceLink(metadata, {source_path: 'src/a b.py', source_url: pinned('src/a%20b.py#L4-L7'), line_start: 4, line_end: 7}), pinned('src/a%20b.py#L4-L7'));
assert.equal(sourceLink(metadata, {source_path: 'src/main.py'}), null); // Unverified source stays unlinked.
for (const path of ['../secret', '/private', 'C:\\secret', 'https://evil.test/x', 'src/../secret']) assert.equal(sourceLink(metadata, {source_path: path}), null);
for (const url of [pinned('src/main.py', 'main'), pinned('src/main.py?download=1'), pinned('src/main.py.evil'),
  'https://evil.test/src/main.py', metadata.repository + '-other/blob/' + metadata.revision + '/src/main.py']) {
  assert.equal(sourceLink(metadata, {source_path: 'src/main.py', source_url: url}), null);
}
assert.equal(sourceLink(metadata, {source_path: 'src/main.py', source_url: pinned('src/main.py', 'b'.repeat(40))}), null); // Undeclared/unpublished pins.
assert.equal(sourceLink({...metadata, revision: 'b'.repeat(40)}, {source_path: 'src/main.py', source_url: pinned('src/main.py')}), pinned('src/main.py')); // Analysis and public revisions may differ.
assert.equal(sourceLink({...metadata, repository: 'https://evil.test/repo'}, {source_path: 'src/main.py'}), null);
assert.throws(() => createAPI({nodes: [node('a'), node('a')], edges: []}), /unique/);
// Validate the checked-in exporter/adapter contract on the actual public slice.
const published = require('../website/data/demo.json');
const publicAPI = createAPI(published), publicGraph = publicAPI.snapshot({whole_graph: true});
const renderedPublicSlice = `${publicGraph.nodes.length} nodes · ${publicGraph.edges.length} relationships`;
assert.equal(published.metadata.repository, 'https://github.com/artemrizhov/EvoMneme');
assert.equal(publicGraph.nodes.length, published.metadata.counts.nodes);
assert.equal(publicGraph.edges.length, published.metadata.counts.edges);
assert.equal(publicGraph.dangling_total, 0);
assert.ok(Array.isArray(published.evidence));
assert.ok(Array.isArray(published.symbol_details)); assert.ok(Array.isArray(published.file_details));
assert.equal(published.evidence.length, published.metadata.counts.source_evidence);
const exposedEvidence = [];
for (const [type, rows] of [['nodes', publicGraph.nodes], ['edges', publicGraph.edges]]) {
  for (const row of rows) {
    const details = publicAPI.detail({type, id: row.graph_id});
    for (const item of details.evidence) {
      assert.equal(item.scope_id, row.scope_id);
      assert.equal(item[type === 'nodes' ? 'node_id' : 'edge_id'], row.id);
      assert.equal(typeof item.description, 'string');
      exposedEvidence.push(JSON.stringify([item.scope_id, item.id]));
    }
    assert.equal(details.evidence_has_more, false);
  }
}
assert.deepEqual(exposedEvidence.sort(), published.evidence.map(item => JSON.stringify([item.scope_id, item.id])).sort(), 'all current evidence attachments and descriptions are exposed exactly once');
assert.ok(publicGraph.nodes.some(n => n.layer === 'knowledge' && n.summary));
assert.ok(publicGraph.nodes.some(n => publicAPI.sourceLink(n)));
for (const row of [...publicGraph.nodes, ...publicGraph.edges, ...published.evidence]) {
  const link = publicAPI.sourceLink(row);
  if (row.source_url) assert.ok(link?.startsWith(published.metadata.repository + '/blob/' + published.metadata.public_revision + '/'));
  else assert.equal(link, null);
}
const publicGrouped = publicAPI.snapshot({whole_graph: true, aggregate: 'layer'});
assert.equal(publicGrouped.nodes.reduce((sum, n) => sum + n.member_count, 0), publicGraph.nodes.length);
assert.equal(publicGrouped.edges.reduce((sum, e) => sum + e.member_count, 0), publicGraph.edges.length);
const claim = publicGraph.nodes.find(n => n.layer === 'knowledge' && publicGraph.edges.some(e => e.source === n.graph_id || e.target === n.graph_id));
assert.ok(publicAPI.snapshot({root: claim.graph_id, depth: 1}).nodes.length > 1);
assert.equal(publicAPI.detail({type: 'nodes', id: claim.graph_id}).rows[0].summary, claim.summary);
// Graph IDs are opaque across schema versions: exercise the same traversal and
// detail operations with both former prefixed IDs and v3 (scope,id) IDs.
for (const makeId of [id => JSON.stringify(['code', 'scope', id]), id => JSON.stringify(['scope', id])]) {
  const from = makeId('source'), to = makeId('target');
  const opaque = createAPI({nodes: [node(from), node(to)], edges: [edge(makeId('link'), from, to)]});
  assert.equal(opaque.snapshot({root: from, depth: 1}).nodes.length, 2);
  assert.equal(opaque.detail({type: 'nodes', id: to}).rows[0].graph_id, to);
  assert.equal(opaque.detail({type: 'edges', id: makeId('link')}).rows[0].source, from);
  assert.equal(opaque.snapshot({}).journal?.version, undefined);
}
// Run public chrome initialization against a small DOM double. In particular,
// a refresh in the shared app must not relabel this public snapshot as LOCAL.
const fs = require('node:fs'), vm = require('node:vm');
const actualReplay = require('../website/data/replay.json'), actualHistory = require('../website/data/history.json');
assert.equal(actualReplay.events.length, published.metadata.history.counts.replay_changes);
assert.equal(actualHistory.changes.length, published.metadata.history.counts.changes);
assert.equal(actualHistory.calls.length, published.metadata.history.counts.calls);
assert.equal(publicAPI.snapshot({}).journal.version, published.metadata.history.journal.version);
assert.equal(publicAPI.request('replay', {}, actualReplay), actualReplay);
for (const route of ['events', 'changes']) {
  const field = route === 'events' ? 'activity_record_id' : 'change_id';
  const exactLatest = publicAPI.request(route, {limit: 100}, actualHistory);
  const initial = publicAPI.initialHistory(route, {});
  assert.ok(initial, 'the graph export includes a bounded exact initial history page');
  assert.deepEqual(initial.events, exactLatest.events);
  assert.equal(initial.after_id, exactLatest.after_id); assert.equal(initial.before_id, exactLatest.before_id);
  assert.equal(initial.has_older, exactLatest.has_older);
  assert.deepEqual(publicAPI.initialHistory(route, {limit: 3}).events.map(row => row[field]), exactLatest.events.slice(-3).map(row => row[field]));
  assert.equal(publicAPI.initialHistory(route, {after_id: initial.after_id}).events.length, 0);
  assert.equal(publicAPI.initialHistory(route, {before_id: initial.before_id}), null);
  assert.equal(publicAPI.initialHistory(route, {after_id: 0}), null);
  assert.equal(publicAPI.initialHistory(route, {limit: 200}), null);
}
// Use the unmodified shared replay engine itself to reconstruct the actual
// baseline, every saved delta and an intermediate seek in both directions.
const shippedApp = fs.readFileSync(require.resolve('../scripts/viewer/app.js'), 'utf8');
const engineStart = shippedApp.indexOf('function createReplayEngine('), engineEnd = shippedApp.indexOf('\nfunction replayDelta(', engineStart);
assert.ok(engineStart >= 0 && engineEnd > engineStart);
const sharedReplayEngine = vm.runInNewContext(shippedApp.slice(engineStart, engineEnd) + '\ncreateReplayEngine;');
const replayEngine = sharedReplayEngine(actualReplay);
assert.ok(replayEngine.events.length > 0);
const baseline = replayEngine.seek(0);
assert.equal(baseline.nodes.length, 0, 'the actual saved journal reconstructs an empty starting graph');
assert.equal(baseline.edges.length, 0);
const midpoint = Math.floor(replayEngine.events.length / 2);
const signature = graph => JSON.stringify(['nodes', 'edges'].map(table => Array.from(graph[table], row => [row.graph_id, row.title, row.kind, row.summary, row.source_id, row.target_id]).sort((a, b) => a[0].localeCompare(b[0]))));
const middleSignature = signature(replayEngine.seek(midpoint));
let finalGraph = replayEngine.seek(replayEngine.events.length);
assert.equal(finalGraph.nodes.length, publicGraph.nodes.length);
assert.equal(finalGraph.edges.length, publicGraph.edges.length);
assert.deepEqual(Array.from(finalGraph.nodes, row => row.graph_id).sort(), publicGraph.nodes.map(row => row.graph_id).sort());
assert.deepEqual(Array.from(finalGraph.edges, row => row.graph_id).sort(), publicGraph.edges.map(row => row.graph_id).sort());
assert.equal(signature(replayEngine.seek(midpoint)), middleSignature, 'backward seek restores exact intermediate graph values');
finalGraph = replayEngine.seek(replayEngine.events.length);
for (const table of ['nodes', 'edges']) {
  const expected = new Map(actualReplay[table].map(row => [JSON.stringify([row.scope_id, row.id]), row]));
  for (const row of finalGraph[table]) {
    assert.equal(row.title, expected.get(row.graph_id).title);
    assert.equal(row.summary, expected.get(row.graph_id).summary);
  }
}
for (const [route, rows, field] of [['events', actualHistory.calls, 'activity_record_id'], ['changes', actualHistory.changes, 'change_id']]) {
  const loaded = []; let after = 0;
  for (;;) {
    const page = publicAPI.request(route, {after_id: after, limit: 200}, actualHistory);
    loaded.push(...page.events.map(row => row[field]));
    if (!page.has_more) break;
    assert.ok(page.after_id > after, 'history cursor progresses'); after = page.after_id;
  }
  assert.deepEqual(loaded, rows.map(row => row[field]).sort((a, b) => a - b), 'all exported history is reachable without omission');
  assert.equal(new Set(loaded).size, rows.length);
}
function element() {
  const classes = new Set();
  return {textContent: '', checked: true, children: [], classList: {add(name) { classes.add(name); }, contains(name) { return classes.has(name); }}, parentElement: {lastChild: {textContent: ''}},
    append(...children) { this.children.push(...children); }, prepend(...children) { this.children.unshift(...children); },
    setAttribute() {}, querySelectorAll() { return []; }};
}
function initializeChrome(href, fetchSnapshot = () => new Promise(() => {})) {
const elements = new Map(), selectors = new Map(), observers = [];
const getElement = id => { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); };
const documentDouble = {body: element(), documentElement: {dataset: {}}, createElement: element, getElementById: getElement,
  querySelector(selector) { if (!selectors.has(selector)) selectors.set(selector, element()); return selectors.get(selector); }};
const chromeWindow = {fetch: fetchSnapshot};
vm.runInNewContext(fs.readFileSync(require.resolve('../website/demo/demo.js'), 'utf8'), {
  window: chromeWindow, document: documentDouble, URL, Response, EvoMnemeStatic: {createAPI},
  location: {href, pathname: '/project/demo/', origin: 'https://example.test'},
  history: {replaceState() {}},
  MutationObserver: class { constructor(callback) { this.callback = callback; this.targets = []; observers.push(this); } observe(target) { this.targets.push(target); } }
});
return {getElement, observers, body: documentDouble.body, html: documentDouble.documentElement, window: chromeWindow};
}
const {getElement, observers, body} = initializeChrome('https://example.test/project/demo/');
assert.equal(body.classList.contains('demo-embed'), false);
assert.equal(initializeChrome('https://example.test/project/demo/?embed=0').body.classList.contains('demo-embed'), false);
const embedded = initializeChrome('https://example.test/project/demo/?embed=1');
assert.equal(embedded.body.classList.contains('demo-embed'), true);
assert.equal(embedded.getElement('live').checked, false);
assert.equal(getElement('live').checked, false);
assert.equal(getElement('storageMode').textContent, 'PUBLIC SNAPSHOT · READ ONLY');
const statusObserver = observers.find(observer => observer.targets.includes(getElement('storageMode')));
assert.ok(statusObserver);
getElement('storageMode').textContent = 'LOCAL · READ ONLY';
getElement('connection').textContent = '● Connected · 12:00';
getElement('journalStatus').textContent = 'Database history recording · since today';
statusObserver.callback();
assert.equal(getElement('storageMode').textContent, 'PUBLIC SNAPSHOT · READ ONLY');
assert.equal(getElement('connection').textContent, '● Published snapshot');
assert.equal(getElement('journalStatus').textContent, 'Saved row history · fixed public export');
async function readinessTests() {
  const href = 'https://example.test/project/demo/?embed=1';
  const success = initializeChrome(href, async () => new Response(JSON.stringify(published)));
  const marker = () => success.html.dataset.publicSnapshotState;
  const notify = sample => sample.observers.find(observer => observer.targets.includes(sample.getElement('connection'))).callback();
  assert.equal(marker(), 'loading');
  const response = await success.window.fetch('/api/snapshot', {body: JSON.stringify({whole_graph: true})});
  assert.equal(response.status, 200);
  assert.equal(marker(), 'loading'); // Parsed JSON alone does not mean draw completed.
  success.getElement('connection').textContent = '● Connected · 12:00'; notify(success);
  assert.equal(marker(), 'loading'); // Nor does status without the rendered slice.
  success.getElement('sliceInfo').textContent = renderedPublicSlice; notify(success);
  assert.equal(marker(), 'ready');
  await success.window.fetch('/api/query', {body: '{}'});
  success.getElement('connection').textContent = 'Connection / query error'; notify(success);
  assert.equal(marker(), 'ready'); // An unrelated later control cannot invalidate readiness.

  for (const fetchSnapshot of [async () => { throw new Error('Snapshot fetch rejected'); },
    async () => new Response('{invalid JSON'), async () => new Response('{}')]) {
    const failed = initializeChrome(href, fetchSnapshot);
    const result = await failed.window.fetch('/api/snapshot', {body: '{}'});
    assert.equal(result.status, 400);
    assert.equal(failed.html.dataset.publicSnapshotState, 'error');
    failed.getElement('connection').textContent = '● Connected · 12:00';
    failed.getElement('sliceInfo').textContent = renderedPublicSlice; notify(failed);
    assert.equal(failed.html.dataset.publicSnapshotState, 'error'); // Sticky until document reload.
  }
  const renderFailed = initializeChrome(href, async () => new Response(JSON.stringify(published)));
  await renderFailed.window.fetch('/api/snapshot', {body: '{}'});
  renderFailed.getElement('connection').textContent = 'Refresh failed · Live paused'; notify(renderFailed);
  assert.equal(renderFailed.html.dataset.publicSnapshotState, 'error');
  const requests = [];
  const initial = {events: api.request('events', {limit: 100}, history), changes: api.request('changes', {limit: 100}, history)};
  const lazyData = {...published, metadata: {...published.metadata, history: {replay: 'replay.json', timeline: 'history.json', journal: history.journal, initial}}};
  const lazy = initializeChrome(href, async url => {
    requests.push(String(url));
    return new Response(JSON.stringify(String(url).endsWith('replay.json') ? savedReplay : String(url).endsWith('history.json') ? history : lazyData));
  });
  await lazy.window.fetch('/api/snapshot', {body: '{}'});
  assert.deepEqual(requests, ['https://example.test/project/data/demo.json']);
  assert.equal(lazy.body.classList.contains('demo-history'), true);
  const calls = await (await lazy.window.fetch('/api/events', {body: '{"limit":2}'})).json();
  assert.equal(calls.events.length, 2);
  await lazy.window.fetch('/api/changes', {body: '{}'});
  await lazy.window.fetch('/api/events', {body: '{"after_id":5}'});
  assert.equal(requests.length, 1, 'initial and automatic immutable latest polls do not fetch full history');
  await lazy.window.fetch('/api/changes', {body: '{"before_id":4}'});
  await lazy.window.fetch('/api/events', {body: '{"before_id":4}'});
  assert.equal(requests.filter(url => url.endsWith('history.json')).length, 1);
  assert.equal(requests.some(url => url.endsWith('replay.json')), false);
  const replay = await (await lazy.window.fetch('/api/replay', {body: '{}'})).json();
  assert.equal(replay.journal.version, 3);
  assert.equal(requests.filter(url => url.endsWith('replay.json')).length, 1);
  await lazy.window.fetch('/api/replay', {body: '{}'});
  assert.equal(requests.length, 3); // Graph, timeline and replay each fetched once.
  console.log('Static viewer API and chrome: graph behavior, embed opt-in, successful readiness and terminal load/render failures passed.');
}
readinessTests().catch(error => { console.error(error); process.exitCode = 1; });
