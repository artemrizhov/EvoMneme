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
    listeners:{},addEventListener(type,fn){(this.listeners[type] ||= []).push(fn);},setAttribute(){},getBoundingClientRect(){return {width:900,height:600};},
    focus(){context.document.activeElement=this;},add(value){this.options.push(value);}};
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
async function draw(data,reset=true,slow=false) {
  context.fixture=data;
  await run("graphAction(()=>{"+(slow?'state.progress.started-=1000;':'')+"return draw(fixture,"+reset+",'fixture');})");
  assert.equal($('error').textContent,'','graph update failed: '+$('error').textContent);
  assert.equal(run('state.busy'),false);assert.equal(run('state.progress'),null);assert.equal(intervals.size,0);
}
async function main(){
  // Fast polling preserves Connected; progress appears only after one second.
  let now=0;
  context.performance={now:()=>now};
  run("setConnectionStatus('● Connected');progressStart();");
  assert.equal($('connection').textContent,'● Connected');
  now=999;await run("graphStage('Loading graph')");
  assert.equal($('connection').textContent,'● Connected');
  now=1000;run('state.progress.paint()');
  assert.match($('connection').textContent,/Loading graph.*1\.0 s/);
  run('progressStop()');
  assert.equal(intervals.size,0);
  context.performance=performance;
  statuses.length=0;
  await draw(fixture(['a','b','c','d'],[['ab','a','b'],['parallel','a','b'],['loop','c','c'],['missing','d','absent']]),true,true);
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
  // Cross the shipped 10,000-node straight-edge threshold as well as the
  // 1,500-element work-chunk threshold. Every element is retained and edges
  // switch back to curves after a smaller replacement.
  let yielded=false;setTimeout(()=>{yielded=true;},0);
  await draw(fixture(Array.from({length:10001},(_,i)=>String(i)),[['edge','0','1']]));
  assert.equal(yielded,true);assert.equal(run('cy.nodes().length'),10001);
  assert.equal(run('state.componentCount'),10000);
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
  // Session history uses the shipped ingestion/render/highlight code. Identical
  // session IDs in separate chats stay distinct; attributed rows share a group.
  await draw(fixture(['a','b','c'],[['ab','a','b']]));
  run('state.history=[];state.recorded=[];state.sessions.clear();state.seenActivities.clear();state.seenChanges.clear();');
  context.activities=[
    {source:'sql',activity_id:'call-1',activity_record_id:1,time:1,chat:'chat-a',session:'same',agent:'worker',read:['nodes'],write:[],references:[{graph_type:'nodes',graph_id:'a'}],ok:true},
    {source:'database_change',change_id:1,activity_id:'call-1',time:1,chat:'chat-a',session:'same',agent:'worker',operation:'delete',table:'nodes',changed:['n:b'],removed:['n:b'],before:{title:{type:'text',value:'old'}},after:null,ok:true},
    {source:'sql',activity_id:'call-2',time:2,chat:'chat-b',session:'same',read:[],write:[],references:[{graph_type:'nodes',graph_id:'c'}],ok:true},
    {source:'database_change',change_id:2,time:3,operation:'update',table:'nodes',changed:['n:c'],before:null,after:null,ok:true}
  ];
  await run('ingest(activities)');
  assert.equal(run('loadedSessions().length'),3);
  assert.equal(run('loadedSessions().find(g=>g.identity.chat==="chat-a").events.length'),2);
  assert.equal(run('state.sessions.size'),2,'attributed changes contribute caller metadata');
  assert.equal($('timeline').children.length,3);
  // Rebuilding the list can temporarily shrink the outer scroll container.
  const replaceTimeline=$('timeline').replaceChildren;
  $('timeline').replaceChildren=function(...children){$('activityPanel').scrollTop=0;replaceTimeline.apply(this,children);};
  $('activityPanel').scrollTop=240;
  await run('ingest([])');
  assert.equal($('activityPanel').scrollTop,240,'empty Live polls preserve the activity panel scroll');
  $('timeline').replaceChildren=replaceTimeline;
  assert.equal($('timeline').children.flatMap(s=>s.children).filter(e=>e._activity).length,0,'collapsed sessions build no activity buttons');
  assert.match($('historySummary').textContent,/2 calls · 2 row changes/);
  await run('ingest([activities[0],{...activities[0],source:"legacy"},activities[1]])');
  assert.equal(run('state.history.length'),4,'database and legacy copies deduplicate by activity_id; row changes by change_id');
  run('state.testGroup=sessionKey(activities[0]);state.expandedSessions.add(state.testGroup);renderTimeline()');
  const group=$('timeline').children.find(s=>s.children.some(e=>e._activity===context.activities[0]));
  const callButton=group.children.find(e=>e._activity===context.activities[0]);
  callButton.focus();
  context.newActivity={source:'sql',activity_id:'call-3',time:4,chat:'chat-a',session:'same',read:[],write:[],references:[{graph_type:'edges',graph_id:'ab'}],ok:true};
  await run('selectSession(state.testGroup);ingest([newActivity])');
  assert.equal(run('state.expandedSessions.has(state.testGroup)'),true);
  assert.equal(context.document.activeElement._activity,context.activities[0],'Live redraw preserves event keyboard focus');
  assert.equal(run('cy.elements(".touched").length'),3,'selected session updates its union on Live ingestion');
  assert.match($('activitySelection').textContent,/3 currently loaded activities/);
  await run('selectActivity(activities[1])');
  assert.equal(run('cy.elements(".touched").length'),1,'individual row selection keeps exact graph references');
  assert.match($('changeMeta').textContent,/DELETE/);
  assert.match($('changeDiff').children[0].children[1].children[0].children[1].textContent,/old/);
  await run('$("reset").onclick()');
  assert.equal(run('state.history.length'),5);assert.equal(run('state.selectedSession'),null);
  assert.equal(run('cy.elements(".touched").length'),0);
  run('$("record").onclick();$("record").onclick()');
  assert.equal(run('state.recording'),false);assert.equal(run('state.history.length'),5,'browser pause retains persistent history');
  // Every loaded event participates in grouping; expanded DOM is bounded to
  // 50 children until explicitly requested, independently of total history.
  context.bulk=Array.from({length:120},(_,i)=>({...context.newActivity,activity_id:'bulk-'+i,time:5+i}));
  await run('ingest(bulk)');
  const bounded=$('timeline').children.find(s=>s.children.some(e=>e._activity?.activity_id==='bulk-119'));
  assert.equal(bounded.children.filter(e=>e._activity).length,50);
  assert.equal(run('loadedSessions().find(g=>g.key===state.testGroup).events.length'),123);
  // Older loads retrieve both independent streams even with caller filters.
  run('state.testHistoryRequests=[];state.journal={version:2,enabled:true};state.activityAfter=9;state.activityBefore=4;state.activityOlder=true;state.changeAfter=8;state.changeBefore=3;state.changeOlder=true;api=async(route,request)=>{state.testHistoryRequests.push({route,...request});return route==="events"?{storage:"database",enabled:true,events:[],before_id:1,after_id:9,has_older:false,cursors:{}}:{journal:{version:2,enabled:true},events:[],before_id:1,after_id:8,has_older:false};};');
  await run('pollEvents(true)');
  assert.equal(run('state.testHistoryRequests.map(r=>r.route+":"+r.before_id).join(",")'),'events:4,changes:3');
  assert.equal(run('state.activityAfter'),9);assert.equal(run('state.changeAfter'),8);
  assert.equal($('olderChanges').disabled,true);
  assert.match($('traceStatus').textContent,/Database call history/);
  context.boundedHistory=Array.from({length:10001},(_,i)=>({...context.newActivity,activity_id:'bounded-'+i,time:200+i}));
  await run('state.expandedSessions.clear();ingest(boundedHistory)');
  assert.equal(run('state.history.length'),10000);
  assert.match($('historySummary').textContent,/browser limit reached/);
  assert.equal($('timeline').children.flatMap(s=>s.children).filter(e=>e._activity).length,0);
  run('state.history=[];state.recorded=[];state.sessions.clear();state.expandedSessions.clear();state.selectedActivity=null;state.selectedSession=null;state.seenActivities.clear();state.seenChanges.clear();document.activeElement=null;');
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
  // Experimental mode is opt-in and reports unavailable WebGL without losing
  // the graph. Renderer initialization is stubbed: no browser or GPU is opened.
  assert.equal(run('state.acceleration'),false);
  const beforeToggle=run('cy.nodes().map(n=>n.id()+":"+n.position("x")).join(",")');
  run('setAcceleration(true)');
  assert.equal(run('state.acceleration'),false);
  assert.equal($('experimentalAcceleration').checked,false);
  assert.match($('accelerationStatus').textContent,/unavailable/);
  run('setWorkerLayout(true)');
  assert.equal(run('state.workerLayoutEnabled'),false);
  assert.match($('workerStatus').textContent,/unavailable/);
  $('cy').getBoundingClientRect=()=>({width:900,height:600});
  run('const realReplaceRenderer=replaceRenderer,rendererInit=cy.initRenderer;const rendererModes=[];cy.initRenderer=options=>rendererInit.call(cy,{...options,name:"null"});replaceRenderer=enabled=>{rendererModes.push(enabled);realReplaceRenderer(enabled);};');
  const createElement=context.document.createElement;
  context.document.createElement=()=>({...element(),getContext:()=>({getExtension:()=>({loseContext(){}})})});
  let workerFailure=false;
  context.Worker=class {
    terminate(){}
    postMessage(message){
      setTimeout(()=>this.onmessage({data:workerFailure?{id:message.id,error:'synthetic layout failure'}:
        {id:message.id,layout:message.options.name,positions:message.elements.filter(e=>e.group==='nodes').map(e=>[e.data.id,e.position])}}),0);
    }
  };
  run('setAcceleration(true)');
  assert.equal(run('state.acceleration'),true);
  assert.equal($('experimentalAcceleration').checked,true);
  assert.equal(run('state.workerLayoutEnabled'),false,'GPU rendering must not enable background layouts');
  assert.equal(run('cy.nodes().map(n=>n.id()+":"+n.position("x")).join(",")'),beforeToggle);
  run('setWorkerLayout(true)');
  await run('graphAction(()=>requestedLayout({fit:false}))');
  assert.equal(run('state.acceleration'),true);
  workerFailure=true;
  await run('graphAction(()=>requestedLayout({fit:false}))');
  assert.equal(run('state.workerLayoutEnabled'),false);
  assert.equal($('experimentalWorker').checked,false);
  assert.equal(run('state.acceleration'),true,'A worker failure must not disable GPU rendering');
  assert.equal($('experimentalAcceleration').checked,true);
  assert.match($('workerStatus').textContent,/Background layout failed.*quick grid/);
  run('setAcceleration(false);setWorkerLayout(true);');
  assert.equal(run('state.acceleration'),false);
  assert.equal(run('state.workerLayoutEnabled'),true,'Background layout must also work without GPU rendering');
  run('setWorkerLayout(false);replaceRenderer=realReplaceRenderer;cy.initRenderer=rendererInit;');
  assert.equal(run('rendererModes.join(",")'),'true,false');
  delete context.Worker;context.document.createElement=createElement;
  // A full 4,644-node initial graph must never enter the blocking force layout
  // before the user has a chance to enable a worker. Keep every node and edge.
  $('layout').value='cose';
  $('onlyTouched').checked=false;
  $('error').textContent='';
  run('const blockingLayout=cy.layout;cy.layout=()=>{throw new Error("Force layout blocked the UI thread")};');
  await draw(fixture(Array.from({length:4644},(_,i)=>String(i)),Array.from({length:4643},(_,i)=>['edge'+i,String(i),String(i+1)])));
  assert.equal(run('cy.nodes().length'),4644);assert.equal(run('cy.edges().length'),4643);
  assert.equal(run('cy.scratch("memory-layout")'),'grid-overview');
  assert.equal(run('state.busy'),false);
  assert.match($('workerStatus').textContent,/Enable background layout/);
  context.Worker=class {postMessage(){}terminate(){}};
  run('setWorkerLayout(true)');
  const pendingLargeLayout=run('graphAction(()=>requestedLayout({fit:false}))');
  await new Promise(resolve=>setTimeout(resolve,20));
  run('setWorkerLayout(false)');
  await pendingLargeLayout;
  assert.equal(run('state.busy'),false,'Disabling a pending worker must release startup work');
  assert.equal(run('cy.scratch("memory-layout")'),'grid-overview');
  delete context.Worker;
  run('cy.layout=blockingLayout');$('layout').value='grid';
  // Preferences are restored before startup refresh, independently for each
  // renderer. Malformed or unavailable storage must not prevent graph loading.
  let savedPreferences='{"gpu":false,"worker":true}';
  context.localStorage={getItem:()=>savedPreferences,setItem:(key,value)=>{savedPreferences=value;}};
  context.Worker=class {};
  run('restoreVisualPreferences()');
  assert.equal(run('state.workerLayoutEnabled'),true);assert.equal(run('state.acceleration'),false);
  run('setWorkerLayout(false)');
  assert.equal(JSON.parse(savedPreferences).worker,false);
  savedPreferences='invalid JSON';run('restoreVisualPreferences()');
  delete context.Worker;delete context.localStorage;
  // Replay restores deleted entities by reversing the saved deltas; seeking
  // either direction must preserve pre-recording nodes and scoped identities.
  const row=(id,title)=>({scope_id:'main',id,title,kind:'item'});
  const packed=row=>row && Object.fromEntries(Object.entries(row).map(([k,value])=>[k,{type:'text',value,truncated:0}]));
  const base=row('base','Before recording'),one=row('a','One'),two=row('a','Two');
  const edge={scope_id:'main',id:'e',source_id:'a',target_id:'base',kind:'link'};
  const changes=[['nodes',null,one],['edges',null,edge],['nodes',one,two],['edges',edge,null],['nodes',two,null]];
  context.replayData={nodes:[base],edges:[],journal:{enabled:true},events:changes.map(([table,before,after],i)=>
    ({change_id:i+1,time:'2026-10-26T12:00:0'+i+'Z',table,before:packed(before),after:packed(after)}))};
  run('const engine=createReplayEngine(replayData);');
  assert.equal(run('engine.seek(0).nodes.length'),1);
  assert.equal(run('engine.seek(2).nodes.find(n=>n.id==="a").label'),'One');
  assert.equal(run('engine.seek(2).edges.length'),1);
  assert.equal(run('engine.seek(3).nodes.find(n=>n.id==="a").label'),'Two');
  assert.equal(run('engine.seek(5).nodes.length'),1);
  assert.equal(run('engine.seek(2).edges[0].source'),'["main","a"]');
  context.replaceData={nodes:[two],edges:[],events:[
    {table:'nodes',time:'2026-10-26T00:00:00Z',before:null,after:packed(one)},
    {table:'nodes',time:'2026-10-26T00:00:01Z',before:null,after:packed(two)}]};
  run('const replaceEngine=createReplayEngine(replaceData)');
  assert.equal(run('replaceEngine.replacements'),1);
  assert.equal(run('replaceEngine.seek(0).nodes.length'),0);
  assert.equal(run('replaceEngine.seek(1).nodes[0].label'),'One');
  assert.equal(run('replaceEngine.seek(2).nodes[0].label'),'Two');
  assert.equal(run('replaceEngine.seek(1).nodes[0].label'),'One','Undoing a repeated INSERT must restore the earlier node');
  context.renamedData={nodes:[{...two,id:'renamed'}],edges:[],events:[{table:'nodes',before:packed(two),after:packed({...two,id:'renamed'})}]};
  assert.equal(run('createReplayEngine(renamedData).seek(0).nodes[0].id'),'a');
  context.badReplay={nodes:[],edges:[],events:[{table:'nodes',before:null,after:{...packed(one),id:{value:'a',truncated:1}}}]};
  assert.throws(()=>run('createReplayEngine(badReplay)'),/truncated graph identity/);
  const settleReplay=async()=>{
    for(let i=0;i<500;i++) {
      if(run('!state.busy && (!state.replay || (!state.replay.rendering && state.replay.index===state.replay.desired))'))return;
      await new Promise(resolve=>setTimeout(resolve,10));
    }
    throw new Error('Replay did not settle');
  };
  run('api=async route=>route==="replay"?replayData:fixture;');
  $('live').checked=true;
  const querySelectorAll=context.document.querySelectorAll;
  context.document.querySelectorAll=selector=>selector.startsWith('.sidebar input')
    ?['layout','perspective','labels','edgeLabels','followGraph','experimentalAcceleration','experimentalWorker',
      'search','wholeGraph','apply','live','refresh','previous','next'].map($):[];
  await run('graphAction(openReplay)');await settleReplay();
  context.document.querySelectorAll=querySelectorAll;
  assert.equal(run('state.replay.index'),0);
  assert.equal($('live').checked,false);
  assert.match($('notice').textContent,/whole database/);
  assert.match($('replayBoundary').textContent,/Baseline: 1 nodes, 0 relationships, 1 components/);
  for(const id of ['layout','perspective','labels','edgeLabels','followGraph','experimentalAcceleration','experimentalWorker'])
    assert.equal($(id).disabled,false,id+' must remain usable in Replay');
  for(const id of ['search','wholeGraph','apply','live','refresh','previous','next'])
    assert.equal($(id).disabled,true,id+' must remain locked to the historical dataset');
  const waitFor=async(condition,message)=>{
    for(let i=0;i<500;i++){if(condition())return;await new Promise(resolve=>setTimeout(resolve,10));}
    throw new Error(message);
  };
  // Hold a real layout request interface open. Graph data and the inspector
  // must continue updating, with only the newest follow-up computation queued.
  const layoutMessages=[];
  context.Worker=class {
    terminate(){}
    postMessage(message){layoutMessages.push({worker:this,message});}
  };
  const replyLayout=({worker,message})=>worker.onmessage({data:{id:message.id,layout:message.options.name,
    positions:message.elements.filter(e=>e.group==='nodes').map(e=>[e.data.id,e.position])}});
  run('setWorkerLayout(true);seekReplay(2)');await settleReplay();
  await waitFor(()=>layoutMessages.length===1,'Background layout did not start');
  assert.equal(run('state.replay.index'),2);
  assert.equal(run('state.busy'),false,'The logical graph must not wait for layout computation');
  assert.equal(run('state.replay.layoutRunning'),true);
  run('seekReplay(3)');await settleReplay();
  assert.equal(run('cy.$id(\'n:["main","a"]\').data("attributes").title'),'Two');
  run('seekReplay(4)');await settleReplay();
  assert.equal(run('state.replay.index'),4);
  assert.equal(layoutMessages.length,1,'A slow layout must have only one in-flight worker request');
  assert.ok(run('state.replay.layoutPending'));
  assert.equal(run('state.graphActions.length'),0);
  replyLayout(layoutMessages[0]);
  await waitFor(()=>layoutMessages.length===2,'The latest pending layout was not dispatched');
  assert.equal(layoutMessages[1].message.elements.filter(e=>e.group==='edges').length,0,'The follow-up job must use the latest graph');
  replyLayout(layoutMessages[1]);
  await waitFor(()=>run('!state.replay.layoutRunning && !state.replay.layoutPending && state.replay.layoutTimer==null'),'Layout did not settle');
  run('setWorkerLayout(false);seekReplay(0)');await settleReplay();
  delete context.Worker;
  // Exercise the real range-input handler: pausing must not overwrite the
  // value before it is read (the original regression made all scrubbing inert).
  $('replayPosition').value='2';$('replayPosition').oninput();await settleReplay();
  assert.equal(run('cy.nodes().length'),2);assert.equal(run('cy.edges().length'),1);
  assert.equal(run('state.snapshot.replay.position'),2);
  assert.equal(run('cy.$id(\'n:["main","a"]\').hasClass("replayChanged")'),true);
  assert.equal(run('cy.$id(\'e:["main","e"]\').hasClass("replayChanged")'),true);
  $('layout').value='circle';await $('layout').onchange();
  assert.equal(run('cy.scratch("memory-layout")'),'circle');
  assert.equal(run('state.replay.index'),2,'Changing layout must retain the historical position');
  // Scrolling opts out of camera following. Later events and manual layout
  // changes may move nodes but must retain the user's zoom and pan.
  for(const listener of $('cy').listeners.wheel || [])listener({});
  assert.equal($('followGraph').checked,false);
  run('cy.viewport({zoom:.7,pan:{x:120,y:85}})');
  run('seekReplay(3)');await settleReplay();
  assert.equal(run('cy.zoom()'),.7);assert.equal(run('cy.pan().x'),120);assert.equal(run('cy.pan().y'),85);
  $('layout').value='grid';await $('layout').onchange();
  assert.equal(run('cy.zoom()'),.7);assert.equal(run('cy.pan().x'),120);
  $('followGraph').checked=true;await $('followGraph').onchange();
  assert.notEqual(run('cy.zoom()'),.7,'Follow graph growth must explicitly restore automatic fitting');
  // Freeze a render, then request many positions. Only the latest is retained.
  run('const replayDraw=draw;let releaseReplay;const replayGate=new Promise(resolve=>releaseReplay=resolve);draw=async(...args)=>{await replayGate;return replayDraw(...args);};seekReplay(1);');
  run('seekReplay(2);seekReplay(3);seekReplay(4);seekReplay(5);');
  assert.equal(run('state.graphActions.length'),0);
  assert.equal(run('state.replay.desired'),5);
  run('releaseReplay()');await settleReplay();run('draw=replayDraw');
  assert.equal(run('cy.nodes().not(".replayRemoved").length'),1);assert.equal(run('cy.edges().not(".replayRemoved").length'),0);
  assert.equal(run('cy.elements(".replayRemoved").length'),0,'Large seeks must not retain the previous graph as deletion markers');
  $('replayPosition').value='3';$('replayPosition').oninput();await settleReplay();
  assert.equal(run('state.replay.index'),3,'The input handler must also support backward scrubbing');
  assert.equal(run('cy.edges(".replayChanged").length'),1,'Rewinding a deletion highlights the restored relationship');
  $('replayPosition').value='4';$('replayPosition').oninput();await settleReplay();
  assert.equal(run('cy.edges(".replayRemoved").length'),1,'Removed relationships must be visible in red');
  assert.equal(run('state.componentCount'),2,'Removal markers must not join historical components');
  assert.match($('replayStatus').textContent,/1 removed \(red\)/);
  await $('layout').onchange();
  assert.equal(run('state.componentCount'),2);
  $('replayPosition').value='5';$('replayPosition').oninput();await settleReplay();
  assert.equal(run('cy.nodes(".replayRemoved").length'),1,'Single-step node deletions must remain visibly marked');
  run('seekReplay(0)');await settleReplay();
  let replayTime=0;context.performance={now:()=>replayTime};$('replaySpeed').value='10';
  run('const playbackSteps=[];const engineSeek=state.replay.engine.seek;state.replay.engine.seek=target=>{playbackSteps.push(target);return engineSeek(target);};let releaseSlowReplay;const slowReplayGate=new Promise(resolve=>releaseSlowReplay=resolve);draw=async(...args)=>{await slowReplayGate;return replayDraw(...args);};playReplay();');
  await new Promise(resolve=>setTimeout(resolve,20));
  run('cy.$id(\'n:["main","base"]\').emit("tap")');
  await new Promise(resolve=>setTimeout(resolve,0));
  assert.equal(run('state.selected?.id()'),'n:["main","base"]','Clicking during an update must open the inspector');
  assert.ok($('detail').children.length>0);
  assert.match($('selectionHint').textContent,/Historical graph attributes/);
  replayTime=60000;
  await new Promise(resolve=>setTimeout(resolve,200));
  assert.equal(run('state.replay.desired'),5,'The playback clock must advance independently of a slow renderer');
  assert.equal(run('playbackSteps.join(",")'),'1');
  assert.equal(run('state.graphActions.length'),0);
  run('releaseSlowReplay()');
  for(let i=0;i<500 && run('state.replay.playing');i++)await new Promise(resolve=>setTimeout(resolve,10));
  await settleReplay();run('draw=replayDraw');
  assert.equal(run('state.replay.playing'),false);
  assert.equal(run('state.replay.index'),5);
  assert.equal(run('playbackSteps.join(",")'),'1,5','Accrued changes must be rendered as one batch instead of an animation backlog');
  assert.equal(run('state.replay.delta.count'),4);
  assert.match($('replayStatus').textContent,/4 saved changes applied in one batch/);
  assert.equal(run('state.selected?.id()'),'n:["main","base"]','Rendering must preserve the node selected during playback');
  context.performance=performance;
  await run('exitReplay()');await settleReplay();
  assert.equal(run('state.replay'),null);assert.equal($('live').checked,true);
  assert.equal($('replayPlay').disabled,true);assert.equal(run('state.snapshot.replay'),undefined);
  run('clearTimeout(showError.timer);cy.destroy()');
  console.log('Viewer lifecycle, component, highlighting, retry and queue regressions passed');
}
main().catch(error=>{console.error(error);for(const timer of intervals)clearInterval(timer);run('pauseReplay();cancelReplayLayout(state.replay);clearTimeout(showError.timer);cy.destroy()');process.exitCode=1;});
