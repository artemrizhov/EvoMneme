/* Exercise the shipped app with real Cytoscape and a minimal, headless DOM. */
'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const graphLayout=require('../scripts/viewer/graph-layout.js');
const elements=new Map(),statuses=[],intervals=new Set();
function element(id='') {
  let content='';
  return {id,value:'',checked:false,disabled:false,dataset:{},style:{},options:[],children:[],
    classList:{add(){},remove(){},toggle(){}},
    set textContent(value) {content=value;if(id==='connection')statuses.push(value);},get textContent(){return content;},
    replaceChildren(...children){this.children=children;},append(...children){this.children.push(...children);},prepend(){},
    addEventListener(){},setAttribute(){},getBoundingClientRect(){return {width:900,height:600};},
    focus(){},add(value){this.options.push(value);}};
}
function $(id){if(!elements.has(id))elements.set(id,element(id));return elements.get(id);}
const context=vm.createContext({console,performance,setTimeout,clearTimeout,
  setInterval(fn,ms){const timer=setInterval(fn,ms);intervals.add(timer);return timer;},
  clearInterval(timer){intervals.delete(timer);clearInterval(timer);},
  document:{hidden:true,getElementById:$,createElement:()=>element(),querySelectorAll:()=>[],activeElement:null},
  location:{hash:'#token=fixture',pathname:'/'},sessionStorage:{getItem(){},setItem(){}},history:{replaceState(){}},
  URLSearchParams,Option:function(value,label){this.value=value;this.label=label;},
  window:{addEventListener(){}},ResizeObserver:class{observe(){}},MemoryGraphLayout:graphLayout});
vm.runInContext(fs.readFileSync(require.resolve('../scripts/viewer/vendor/cytoscape.min.js'),'utf8'),context);
vm.runInContext('const cytoscapeCore=cytoscape;cytoscape=options=>cytoscapeCore({...options,container:undefined,headless:true,styleEnabled:true});',context);
let source=fs.readFileSync(require.resolve('../scripts/viewer/app.js'),'utf8');
source=source.replace(/refresh\(true\);setInterval\(\(\)=>\{if\(\$\('live'\)\.checked && !state\.busy\)refresh\(\);\},2000\);\s*$/,'');
assert.ok(!source.endsWith('},2000);\n'),'automatic polling disabled in harness');
vm.runInContext(source,context);
const run=code=>vm.runInContext(code,context);
$('layout').value='grid';$('perspective').value='kind';$('limit').value='100';$('depth').value='1';
$('followGraph').checked=true;
const fixture=(nodes,edges=[])=>({nodes:nodes.map(id=>({graph_id:id,label:id,kind:'item'})),
  edges:edges.map(([id,source,target])=>({graph_id:id,source,target,kind:'link'})),
  graph_available:true,whole_graph:true,revision:'r1',tables:[],facets:{},edge_facets:{},layers:[],
  totals:{nodes:nodes.length,edges:edges.length},matched_nodes:nodes.length,bytes:0,elapsed_ms:1});
async function draw(data,reset=true) {
  context.fixture=data;
  await run("graphAction(()=>draw(fixture,"+reset+",'fixture'))");
  assert.equal($('error').textContent,'','graph update failed: '+$('error').textContent);
  assert.equal(run('state.busy'),false);assert.equal(run('state.progress'),null);assert.equal(intervals.size,0);
}
async function main(){
  await draw(fixture(['a','b','c','d'],[['ab','a','b'],['parallel','a','b'],['loop','c','c'],['missing','d','absent']]));
  assert.equal(run('state.componentCount'),3);
  assert.equal(run('cy.nodes().length'),4);assert.equal(run('cy.edges().length'),3);
  assert.equal(run("state.components.get('n:a')===state.components.get('n:b')"),true);
  assert.notEqual(run("state.components.get('n:c')"),run("state.components.get('n:d')"));
  assert.equal(run("state.components.get('e:parallel')"),run("state.components.get('n:a')"));
  assert.ok(statuses.some(s=>s.startsWith('Adding graph elements · 7 / 7')));
  assert.ok(statuses.some(s=>s.startsWith('Styling graph · 7 / 7')));
  assert.ok(statuses.some(s=>s.startsWith('Counting components · 4 / 4')));
  assert.ok(statuses.some(s=>/working… · \d+\.\d s/.test(s)));
  const order=['Preparing node signatures','Adding graph elements','Finalizing graph elements','Counting components','Styling graph','Highlighting graph','Laying out graph','Rendering graph','● Connected'];
  let last=-1;
  for(const stage of order){const index=statuses.findIndex((value,i)=>i>last&&value.startsWith(stage));assert.ok(index>last,stage);last=index;}
  // Component perspective uses the cached membership rather than Cytoscape's
  // expensive traversal, while activity highlighting retains endpoint context.
  await run("graphAction(async()=>{$('perspective').value='components';await decorate();state.recorded=[{changed:['e:ab']}];$('onlyTouched').checked=true;await applyHighlight();})");
  assert.equal(run("cy.getElementById('n:a').data('color')===cy.getElementById('n:b').data('color')"),true);
  assert.equal(run("cy.elements('.hidden').length"),4);
  assert.equal(run("cy.elements('.touched').length"),1);
  // Cached redraw keeps a manually moved/selected node and its path.
  await run("cy.getElementById('n:a').position({x:432,y:123}).select().addClass('path');state.selected=cy.getElementById('n:a')");
  await draw(context.fixture,false);
  assert.equal(run("cy.getElementById('n:a').position('x')"),432);
  assert.equal(run("cy.getElementById('n:a').hasClass('path')"),true);
  // A large input yields during preparation/addition/styling. Every element is
  // retained and edges switch back to curves after a smaller replacement.
  let yielded=false;setTimeout(()=>{yielded=true;},0);
  await draw(fixture(Array.from({length:1601},(_,i)=>String(i)),[['edge','0','1']]));
  assert.equal(yielded,true);assert.equal(run('cy.nodes().length'),1601);
  assert.equal(run('state.componentCount'),1600);
  assert.equal(run("cy.edges()[0].data('curve')"),'straight');
  await draw(fixture(['a','b'],[['edge','a','b']]));
  assert.equal(run("cy.edges()[0].data('curve')"),'bezier');
  await draw(fixture(['a','b'],[['edge','a','missing']]));
  assert.equal(run('cy.edges().length'),0,'an existing edge with a now-missing endpoint is removed');
  assert.equal(run('state.componentCount'),2);
  // Hidden graph panels defer geometry but never wait for a renderer frame.
  $('cy').getBoundingClientRect=()=>({width:0,height:0});
  await draw(fixture(['hidden']));assert.equal(run('state.pendingLayout'),true);
  await draw(fixture([]));assert.equal(run('state.componentCount'),0);
  // Full refresh lifecycle: ready follows component count/render handoff; an
  // exception cleans timers and busy state and a later request can retry.
  run('metrics=()=>{};renderFilters=()=>{};renderEdgeFilters=()=>{};renderLayers=()=>{};renderTables=()=>{};pollEvents=async()=>{};');
  context.fixture=fixture(['retry']);
  run('api=async()=>{throw new Error("synthetic failure")};');
  await run('refresh(true)');
  assert.equal(run('state.busy'),false);assert.equal(run('state.progress'),null);assert.equal(intervals.size,0);
  assert.equal($('live').checked,false);assert.match($('connection').textContent,/failed/);
  run('api=async()=>fixture;');await run('refresh(true)');
  assert.match($('sliceInfo').textContent,/1 nodes · 0 relationships · 1 components/);
  assert.match($('connection').textContent,/Connected/);assert.equal(intervals.size,0);
  context.fixture=fixture(['after-add-failure']);
  run('const realAdd=cy.add;cy.add=()=>{throw new Error("synthetic addition failure")};');
  await run('refresh(true)');
  assert.match($('connection').textContent,/failed/);
  assert.equal(run('cy._private.batchCount'),0);
  assert.equal(run('state.previous'),null);assert.equal(run('state.revision'),null);
  assert.equal(run('state.busy'),false);assert.equal(intervals.size,0);
  // A foreground page with suspended animation frames uses the bounded timer
  // fallback too (e.g. a hidden panel or a renderer that has not started).
  context.requestAnimationFrame=()=>123;context.cancelAnimationFrame=()=>{};
  run('document.hidden=false');await run("graphAction(()=>graphStage('Fallback handoff'))");
  assert.equal(run('state.busy'),false);assert.equal(intervals.size,0);
  run('document.hidden=true');
  run('cy.add=realAdd');await run('refresh(true)');
  assert.equal(run("cy.getElementById('n:after-add-failure').length"),1);
  assert.match($('connection').textContent,/Connected/);assert.equal(intervals.size,0);
  // Server-side unchanged responses retain component cache and skip graph work.
  run('const realComponents=countComponents;countComponents=()=>{throw new Error("unexpected traversal")};api=async()=>({unchanged:true});');
  await run('refresh()');
  assert.equal(run('state.componentCount'),1);assert.match($('connection').textContent,/Connected/);
  run('countComponents=realComponents;state.testRequests=0;api=async()=>{state.testRequests++;return fixture;};');
  await run('graphAction(async()=>{await refresh(true);await refresh(false);})');
  assert.equal(run('state.testRequests'),1,'manual refresh requests coalesce while busy');
  // Manual work queues once behind in-flight work and drains; automatic live
  // polling is guarded by busy in the shipped source.
  run('state.testActions=[]');
  await Promise.all([run("graphAction(async()=>{await graphYield();state.testActions.push('first')})"),run("graphAction(()=>state.testActions.push('second'))")]);
  assert.equal(run('state.testActions.join(",")'),'first,second');
  assert.equal(run('state.busy'),false);assert.equal(intervals.size,0);
  run('clearTimeout(showError.timer);cy.destroy()');
  console.log('Viewer lifecycle, component, highlighting, retry and queue regressions passed');
}
main().catch(error=>{console.error(error);for(const timer of intervals)clearInterval(timer);run('clearTimeout(showError.timer);cy.destroy()');process.exitCode=1;});
