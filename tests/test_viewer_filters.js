'use strict';
// Run the shipped facet functions against a minimal DOM; no duplicate filter logic.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require.resolve('../scripts/viewer/app.js'), 'utf8');
const elements = new Map();
class Element {
  constructor(tag) { this.tagName = tag; this.children = []; this.dataset = {}; }
  append(...children) { for (const child of children) { child.parentElement = this; this.children.push(child); } }
  remove() { this.parentElement.children = this.parentElement.children.filter(child => child !== this); }
  setAttribute(name, value) { this[name] = value; }
  set id(value) { this._id = value; elements.set(value, this); }
  get firstChild() { return this.children[0]; }
  get lastChild() { return this.children.at(-1); }
}
const state = {offset: 0, root: '', disabledLayers: new Set(), nullField: ''};
for (const id of ['limit', 'depth', 'search', 'focus', 'aggregate', 'wholeGraph', 'filters', 'edgeFilters']) {
  const el = new Element('div'); el.id = id; el.value = ''; el.checked = false;
}
elements.get('limit').value = '500'; elements.get('depth').value = '1';
const context = vm.createContext({state, Set, Map, document: {createElement: tag => new Element(tag)},
  $: id => elements.get(id), text(tag, value, className) {
    const el = new Element(tag); el.textContent = value; el.className = className; return el;
  }});
function section(start, end) {
  const from = source.indexOf(start), to = source.indexOf(end, from);
  assert.ok(from >= 0 && to > from); return source.slice(from, to);
}
vm.runInContext(section('function filters()', 'function syncSelect(') +
  section('function facetValues(', 'function renderLayers(') +
  section('function renderEdgeFilters(', 'function metrics('), context);
const run = code => vm.runInContext(code, context);
const values = () => JSON.parse(JSON.stringify(run('filters()')));
run("renderFilters({kind:[{value:'function',count:3},{value:'module',count:2}]}); renderEdgeFilters({kind:[{value:'calls',count:4},{value:'owns',count:2}]})");
const facet = elements.get('filter-kind');
assert.equal(facet.tagName, 'details'); assert.equal(facet._all.checked, true);
assert.equal(facet._summary.textContent, 'Node type · All');
const toggle = (facet, value, checked) => {
  const input = facet._rows.get(value).firstChild; input.checked = checked; input.onchange();
};
toggle(facet, 'function', true); toggle(facet, 'module', true);
assert.deepEqual(values().kind, ['function', 'module']);
assert.equal(facet._summary.textContent, 'Node type · 2 selected');
assert.equal(facet._all.checked, false);
facet.open = true;
const focusedInput = facet._rows.get('function').firstChild;
run("renderFilters({kind:[{value:'function',count:9}]})");
assert.equal(facet.open, true);
assert.equal(facet._rows.get('function').firstChild, focusedInput);
assert.equal(facet._rows.get('module').lastChild.textContent, 'module (0)');
assert.deepEqual(values().kind, ['function', 'module']);
const edgeFacet = elements.get('edge-kind');
toggle(edgeFacet, 'calls', true); toggle(edgeFacet, 'owns', true);
assert.deepEqual(values().edge_kind, ['calls', 'owns']);
// All values and drilldown replace the Set; existing input handlers must use it.
facet._all.onchange(); assert.deepEqual(values().kind, []);
toggle(facet, 'function', true); assert.deepEqual(values().kind, ['function']);
run("setFacetValues($('filter-kind'),['new type'])");
assert.equal(facet._rows.get('new type').firstChild.checked, true);
toggle(facet, 'function', true); assert.deepEqual(values().kind, ['function', 'new type']);
run("setFacetValues($('filter-kind'),[]); state.nullField='kind'");
assert.equal(values().null_field, 'kind');
toggle(facet, 'function', true); assert.equal(values().null_field, '');
run("setFacetValues($('filter-kind'),[]); setFacetValues($('edge-kind'),[])");
assert.deepEqual(values().kind, []); assert.deepEqual(values().edge_kind, []);
console.log('Checkbox facets: combinations, refresh retention, reset, drilldown and null filters passed.');
