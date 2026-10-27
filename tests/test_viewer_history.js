'use strict';
// Exercise the shipped history ingestion and both cursor streams, without
// constructing a graph or duplicating the viewer's bounded-window algorithm.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require.resolve('../scripts/viewer/app.js'), 'utf8');
function section(start, end) {
  const from = source.indexOf(start), to = source.indexOf(end, from);
  assert.ok(from >= 0 && to > from, 'shared history function boundaries');
  return source.slice(from, to);
}
const elements = new Map();
const state = {history: [], recorded: [], sessions: new Map(), seenChanges: new Set(), seenActivities: new Set(),
  activitiesReady: false, recording: false, recordingSince: Infinity, cursors: {}, journal: {version: 3, enabled: true},
  activityAfter: 10000, activityBefore: 100, activityOlder: true, changeAfter: 50, changeBefore: 10, changeOlder: true};
const context = vm.createContext({state,
  $(id) { if (!elements.has(id)) elements.set(id, {}); return elements.get(id); },
  isObservation: event => event.source === 'database_change', updateSessionOptions() {}, renderTimeline() {}, async applyHighlight() {}});
vm.runInContext(section('async function ingest(', 'async function pollEvents(') +
  section('async function pollEvents(', 'function renderTimeline('), context);
const run = code => vm.runInContext(code, context);
const call = (id, time = id) => ({source: 'sql', activity_id: 'call-' + id, activity_record_id: id, time});
async function main() {
  context.recent = Array.from({length: 10000}, (_, index) => call(index + 1));
  await run('ingest(recent)');
  assert.equal(state.history.length, 10000);
  const requests = [];
  context.api = async (route, values) => {
    requests.push({route, ...values});
    return route === 'events' ? {events: [call(-2), call(-1)], cursors: {}, before_id: 1, after_id: 10000, has_older: false} :
      {journal: state.journal, events: [{source: 'database_change', change_id: 1, time: -0.5}, {source: 'database_change', change_id: 2, time: 0}], before_id: 1, after_id: 50, has_older: false};
  };
  await run('pollEvents(true)');
  assert.deepEqual(requests.map(r => [r.route, r.before_id]), [['events', 100], ['changes', 10]]);
  assert.equal(state.history.length, 10000);
  assert.ok(state.history.some(event => event.activity_id === 'call--2'), 'requested older calls remain inspectable');
  assert.ok(state.history.some(event => event.change_id === 1), 'requested older changes remain inspectable');
  assert.ok(!state.history.some(event => event.activity_id === 'call-10000'), 'older browsing trims the newest end');
  assert.equal(state.activityAfter, 10000); assert.equal(state.changeAfter, 50);
  assert.equal(state.activityBefore, 1); assert.equal(state.changeBefore, 1);
  assert.ok(!state.seenActivities.has('call-10000'), 'evicted identities can be loaded again');
  assert.ok(state.seenChanges.has(1));
  const retained = state.history.length;
  context.duplicates = [call(-2), {source: 'database_change', change_id: 1, time: -0.5}];
  await run('ingest(duplicates,true,true)');
  assert.equal(state.history.length, retained, 'older page duplicates are deduplicated');

  context.newer = [call(10000), call(10001)];
  await run('ingest(newer)');
  assert.equal(state.history.length, 10000);
  assert.ok(state.history.some(event => event.activity_id === 'call-10001'));
  assert.ok(!state.history.some(event => event.activity_id === 'call--2'), 'ordinary polling trims the oldest end');
  assert.ok(!state.seenActivities.has('call--2'));
  // Loading an older page also leaves the independent recording limit intact.
  state.recording = true; state.recordingSince = -Infinity; state.recorded = Array.from(context.recent);
  context.anotherOld = [call(-3)];
  await run('ingest(anotherOld,true,true)');
  assert.equal(state.history.length, 10000); assert.equal(state.recorded.length, 10000);
  assert.ok(state.history.some(event => event.activity_id === 'call--3'));
  assert.equal(state.recorded[0].activity_id, 'call-2', 'recording retains its existing append-window behavior');
  console.log('Shared viewer history: bounded older/newer windows, both cursor streams and deduplication passed.');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
