'use strict';
const $ = id => document.getElementById(id);
const token = new URLSearchParams(location.hash.slice(1)).get('token') || sessionStorage.getItem('evomneme-viewer-token');
if (token) sessionStorage.setItem('evomneme-viewer-token', token);
history.replaceState(null, '', location.pathname);
const state = { snapshot: null, offset: 0, root: '', selected: null, pathStart: null, recording: false,
  recorded: [], history: [], sessions: new Map(), cursors: {}, changes: new Set(), previous: null,
  busy: false, tableOffset: 0, missed: false, view: 'graph', filterKey: '', recordingSince: Infinity, nullField:'',
  selectedActivity:null,pendingLayout:false,disabledLayers:new Set(),revision:null,refreshQueued:false,resetQueued:false,activitiesReady:false,
  journal:null,changeAfter:null,changeBefore:null,changeOlder:false,changeBusy:false,seenChanges:new Set(),
  activityAfter:null,activityBefore:null,activityOlder:false,seenActivities:new Set(),expandedSessions:new Set(),sessionLimits:new Map(),selectedSession:null,
  components:new Map(),componentCount:0,graphActions:[],progress:null,replay:null,acceleration:false,workerLayoutEnabled:false };
const palette = ['#79b8e8','#86d8b6','#d5a0e8','#f0bf79','#e58e99','#a5b6eb','#c8d889','#88cdd7','#ccab91','#b0a3d4'];
function text(tag, value, className) { const el = document.createElement(tag); el.textContent = String(value ?? ''); if (className) el.className = className; return el; }
function setConnectionStatus(value) { const el=$('connection');el.textContent=value;el.title=value; }
function showError(error, persistent=false) { $('error').textContent = error.message || String(error); $('error').classList.remove('hidden'); clearTimeout(showError.timer); if (!persistent) showError.timer = setTimeout(() => $('error').classList.add('hidden'), 12000); }
async function api(route, values = {}) {
  const controller=new AbortController();
  const timeout=setTimeout(()=>controller.abort(),90000);
  try {
    const response=await fetch('/api/'+route,{method:'POST',headers:{'Content-Type':'application/json','X-Viewer-Token':token || ''},body:JSON.stringify(values),signal:controller.signal});
    const data=await response.json();
    if (!response.ok) throw new Error(data.error || response.statusText);
    return data;
  } catch (error) {
    if (controller.signal.aborted) throw new Error('Viewer request timed out after 90 seconds. Check the server and retry with a narrower graph selection.');
    throw error;
  } finally {clearTimeout(timeout);}
}
function guarded(fn) { return (...args) => Promise.resolve().then(() => fn(...args)).catch(showError); }
// A timer fallback also works in background tabs, where animation frames stop.
function graphYield() { return new Promise(resolve=>setTimeout(resolve,0)); }
function graphPaint() {
  if(document.hidden || typeof requestAnimationFrame!=='function')return graphYield();
  return new Promise(resolve=>{
    let frame;
    const finish=()=>{clearTimeout(timer);if(frame!=null)cancelAnimationFrame(frame);resolve();};
    const timer=setTimeout(finish,100);
    frame=requestAnimationFrame(()=>setTimeout(finish,0));
  });
}
function progressStart() {
  const progress={started:performance.now(),stage:'Loading graph',done:null,total:null};
  state.progress=progress;
  const paint=()=>{
    if (state.progress!==progress || performance.now()-progress.started<1000) return;
    setConnectionStatus(`${progress.stage} · ${progress.done==null?'working…':`${progress.done.toLocaleString()} / ${progress.total.toLocaleString()}`} · ${((performance.now()-progress.started)/1000).toFixed(1)} s`);
  };
  progress.paint=paint;
  progress.timer=setInterval(paint,250);
  paint();
}
function progressStop() {
  if (state.progress) clearInterval(state.progress.timer);
  state.progress=null;
}
async function graphStage(stage,total=null) {
  if (state.progress) {
    Object.assign(state.progress,{stage,total,done:total==null?null:0});
    state.progress.paint();
  }
  if(state.replay?.index>=0) {
    const now=performance.now();
    if(now-(state.replay.lastYield ?? -Infinity)<8)return;
    const replay=state.replay;
    await graphPaint();
    if(state.replay===replay)replay.lastYield=performance.now();
    return;
  }
  await graphPaint();
}
async function graphChunks(items,fn,stage,batch=false) {
  if (stage) await graphStage(stage,items.length);
  for (let start=0;start<items.length;start+=1500) {
    const end=Math.min(start+1500,items.length);
    if(batch)cy.startBatch();
    try {for (let i=start;i<end;i++) fn(items[i],i);}
    finally {if(batch)cy.endBatch();}
    if (stage && state.progress) {state.progress.done=end;state.progress.paint();}
    if (items.length>1500) {
      await graphYield();
      if(state.replay)state.replay.lastYield=performance.now();
    }
  }
}
async function graphAction(fn) {
  if (state.busy) {state.graphActions.push(fn);return;}
  state.busy=true;progressStart();
  try {
    await fn();
    await graphStage('Rendering graph');
    progressStop();
    setConnectionStatus('● Connected · '+new Date().toLocaleTimeString());
  } catch(error) {
    $('live').checked=false;
    state.graphActions=[];state.refreshQueued=state.resetQueued=false;
    setConnectionStatus('Graph update failed · Live paused');showError(error,true);
  } finally {
    progressStop();state.busy=false;
    await drainGraphWork();
  }
}
function graphControl(fn) {return guarded((...args)=>graphAction(()=>fn(...args)));}

// Reversible row deltas retain entities deleted since recording began. The
// baseline and all deltas come from one server-side read transaction.
function createReplayEngine(data) {
  const stores={nodes:new Map(),edges:new Map()};
  let index=data.events.length,truncated=false;
  const identity=row=>{
    if (!['string','number'].includes(typeof row.scope_id) || !['string','number'].includes(typeof row.id))
      throw new Error('History contains an incomplete graph identity; replay cannot reconstruct it.');
    return JSON.stringify([row.scope_id,row.id]);
  };
  const decode=snapshot=>{
    if (!snapshot) return null;
    const row={};
    for (const [key,field] of Object.entries(snapshot)) {
      if (field.truncated) {
        truncated=true;
        if (['scope_id','id','source_id','target_id'].includes(key))
          throw new Error('History contains a truncated graph identity or endpoint; replay is unavailable.');
      }
      row[key]=field.value;
    }
    identity(row);
    return row;
  };
  for (const table of ['nodes','edges']) for (const source of data[table]) {
    const row={...source};
    for (const [key,field] of Object.entries(row)) if(field && typeof field==='object' && field.truncated) {
      truncated=true;
      if (['scope_id','id','source_id','target_id'].includes(key))
        throw new Error('Current graph contains a truncated identity or endpoint; replay is unavailable.');
      row[key]=field.preview;
    }
    stores[table].set(identity(row),row);
  }
  const events=data.events.map(e=>({...e,before:decode(e.before),after:decode(e.after)}));
  const apply=(event,forward)=>{
    const remove=forward?event.before:event.after, put=forward?event.after:event.before;
    const store=stores[event.table];
    if (remove && (!put || identity(remove)!==identity(put))) store.delete(identity(remove));
    if (put) store.set(identity(put),put);
  };
  // Some writers use INSERT OR REPLACE with SQLite's recursive delete
  // triggers disabled. Consecutive insert records for an existing identity
  // still have an exact prior value in earlier history: retain it for undo.
  for(let i=events.length-1;i>=0;i--)apply(events[i],false);
  let replacements=0;
  for(const event of events) {
    if(!event.before && event.after) {
      const previous=stores[event.table].get(identity(event.after));
      if(previous){event.before=previous;replacements++;}
    }
    apply(event,true);
  }
  return {events,truncated,replacements,seek(target) {
    target=Math.max(0,Math.min(events.length,Math.floor(target)));
    while(index>target)apply(events[--index],false);
    while(index<target)apply(events[index++],true);
    return {nodes:[...stores.nodes].map(([graph_id,row])=>({...row,graph_id,label:row.title,source_table:'nodes'})),
      edges:[...stores.edges].map(([graph_id,row])=>({...row,graph_id,
        source:JSON.stringify([row.scope_id,row.source_id]),target:JSON.stringify([row.scope_id,row.target_id]),source_table:'edges'})),
      whole_graph:false,graph_available:true};
  }};
}

function replayDelta(engine,from,to) {
  const changed=new Set(),removed=new Set();
  const id=(table,row)=>(table==='nodes'?'n:':'e:')+JSON.stringify([row.scope_id,row.id]);
  const forward=to>=from;
  if(from<0)return {changed,removed,count:0};
  const events=engine.events.slice(Math.min(from,to),Math.max(from,to));
  if(!forward)events.reverse();
  for(const event of events) {
    const before=forward?event.before:event.after,after=forward?event.after:event.before;
    if(before && (!after || id(event.table,before)!==id(event.table,after))) {
      const key=id(event.table,before);removed.add(key);changed.delete(key);
    }
    if(after){const key=id(event.table,after);changed.add(key);removed.delete(key);}
  }
  return {changed,removed,count:events.length};
}
function replayGhosts(delta) {
  let removed=cy.collection();
  for(const id of delta.removed) {
    const element=cy.getElementById(id);
    removed=removed.union(element);
    if(element.isNode())removed=removed.union(element.connectedEdges());
  }
  return removed.map(el=>({group:el.group(),data:{...el.data()},classes:'replayRemoved',
    position:el.isNode()?{...el.position()}:undefined,locked:el.isNode()}));
}
function showReplayDelta(r,delta,ghosts) {
  cy.elements().removeClass('replayChanged');
  for(const id of delta.changed)cy.getElementById(id).addClass('replayChanged');
  const nodes=ghosts.filter(e=>e.group==='nodes' && !cy.hasElementWithId(e.data.id));
  if(nodes.length)cy.add(nodes);
  const edges=ghosts.filter(e=>e.group==='edges' && !cy.hasElementWithId(e.data.id)
    && cy.hasElementWithId(e.data.source) && cy.hasElementWithId(e.data.target));
  if(edges.length)cy.add(edges);
  r.delta={...delta,ghostsShown:nodes.length+edges.length};
}
function replayStatus() {
  const r=state.replay;if(!r)return;
  $('replayPosition').max=r.engine.events.length;
  $('replayPosition').value=r.desired;
  $('replayPlay').textContent=r.playing?'Pause':r.index===r.engine.events.length?'Replay':'Play';
  const event=r.engine.events[r.index-1];
  $('replayStatus').textContent=`${r.playing?'Playing':'Paused'} · ${r.index} / ${r.engine.events.length} changes · `
    +(event?`${event.time} · ${event.table} ${!event.before?'INSERT':!event.after?'DELETE':'UPDATE'}`:'Baseline before the first saved change')
    +(r.delta?.count?` · ${r.delta.changed.size} changed (green) · ${r.delta.removed.size} removed${r.delta.ghostsShown?' (red)':''}`:'')
    +(r.delta?.count>1?` · ${r.delta.count} saved changes applied in one batch`:'')
    +(r.desired>r.index?` · ${r.desired-r.index} changes awaiting display`:'')
    +(r.layoutRunning?' · recalculating layout':'')
    +(r.rendering?' · rendering…':'');
  $('replayStatus').title=$('replayStatus').textContent;
}
function pauseReplay() {
  const r=state.replay;if(!r)return;
  if(r.playing)r.desired=r.activeTarget ?? Math.max(0,r.index);
  r.playing=false;clearTimeout(r.timer);replayStatus();
}
async function renderReplay() {
  const r=state.replay;
  if (!r || r.rendering || r.exiting) return;
  clearTimeout(r.renderTimer);
  if (state.busy) {r.renderTimer=setTimeout(()=>void renderReplay(),60);return;}
  r.rendering=true;
  try {
    await graphAction(async()=>{
      try {
        if(state.replay===r && !r.exiting && r.index!==r.desired) {
          cy.elements('.replayRemoved').remove();
          const target=r.desired,initial=r.index<0,delta=replayDelta(r.engine,r.index,target);
          r.activeTarget=target;
          // A large seek must show the actual target graph, not thousands of
          // ghosts from the state being left behind. Ghosts describe one step.
          const ghosts=Math.abs(target-r.index)===1?replayGhosts(delta):[];
          const data=r.engine.seek(target);
          await draw(data,initial,'history-replay');
          showReplayDelta(r,delta,ghosts);
          r.index=target;
          r.activeTarget=null;
          state.snapshot={...r.saved.snapshot,...data,replay:{position:target,total:r.engine.events.length}};
          $('sliceInfo').textContent=`History · ${data.nodes.length} nodes · ${data.edges.length} relationships · ${state.componentCount} components`;
          if(initial) {
            $('replayBoundary').textContent=`${r.database?'Database: '+r.database+'. ':''}`
              +`Available row history since ${r.startedAt?new Date(r.startedAt).toLocaleString():'the first saved change'}. `
              +`Baseline: ${data.nodes.length} nodes, ${data.edges.length} relationships, ${state.componentCount} components. `
              +(data.nodes.length?'Creation of these baseline nodes predates this row journal. ':'')
              +(r.engine.replacements?`${r.engine.replacements} repeated inserts are replayed as replacements using earlier saved values.`:'');
          }
          replayStatus();
        }
      } catch(error) {pauseReplay();r.activeTarget=null;r.desired=r.index;throw error;}
    });
  } finally {
    r.rendering=false;replayStatus();
    if(r.playing && r.index>=r.engine.events.length && r.index===r.desired)pauseReplay();
    if(state.replay===r && !r.exiting && r.index!==r.desired) {
      clearTimeout(r.renderTimer);r.renderTimer=setTimeout(()=>void renderReplay(),0);
    }
  }
}
function seekReplay(target) {
  const r=state.replay;if(!r)return;
  r.desired=Math.max(0,Math.min(r.engine.events.length,Math.floor(Number(target)||0)));
  replayStatus();void renderReplay();
}
function scheduleReplay(r,delay=60) {
  if(state.replay!==r || !r.playing || r.exiting)return;
  clearTimeout(r.timer);
  if(!r.rendering && r.index===r.desired && r.index>=r.engine.events.length) {pauseReplay();return;}
  r.timer=setTimeout(()=>{
    if(state.replay!==r || !r.playing || r.exiting)return;
    // The clock keeps advancing during a slow draw or layout. seek() applies
    // every intervening row delta in order; rendering coalesces only the views.
    const due=r.clockOrigin+1+Math.floor(Math.max(0,performance.now()-r.clockStarted)*r.clockSpeed/600);
    if(due>r.desired)seekReplay(due);
    scheduleReplay(r);
  },delay);
}
function playReplay() {
  const r=state.replay;if(!r)return;
  if (r.playing) {pauseReplay();return;}
  if (r.desired>=r.engine.events.length) seekReplay(0);
  r.clockOrigin=r.desired;r.clockStarted=performance.now();r.clockSpeed=Number($('replaySpeed').value)||1;
  r.playing=true;scheduleReplay(r,0);replayStatus();
}
async function openReplay() {
  if(state.replay)return;
  await graphStage('Loading saved graph history');
  const data=await api('replay'),engine=createReplayEngine(data);
  if(!engine.events.length)throw new Error('No saved node or relationship changes are available yet.');
  const saved={live:$('live').checked,follow:$('followGraph').checked,snapshot:state.snapshot,activity:state.selectedActivity,session:state.selectedSession};
  const visualControls=new Set(['perspective','layout','labels','edgeLabels','followGraph',
    'experimentalAcceleration','experimentalWorker']);
  const disabled=[...document.querySelectorAll('.sidebar input,.sidebar select,.sidebar button,#activityPanel input,#activityPanel select,#activityPanel button,#live,#refresh,#previous,#next')]
    .filter(el=>!visualControls.has(el.id))
    .map(el=>[el,el.disabled]);
  disabled.forEach(([el])=>{el.disabled=true;});
  state.replay={engine,saved,disabled,index:-1,desired:0,playing:false,rendering:false,exiting:false,
    database:data.database,startedAt:data.journal.started_at || engine.events[0]?.time};
  MemoryGraphLayout.stop(cy);
  $('live').checked=false;$('followGraph').checked=true;state.refreshQueued=state.resetQueued=false;
  state.selectedActivity=state.selectedSession=null;
  state.previous=null;state.filterKey='';
  cy.elements().removeClass('hidden touched recordedChange path replayChanged');
  $('notice').textContent='History replay · whole database; graph and activity filters are suspended. '
    +'Layouts are recalculated. Evidence and detail tables are not reconstructed. '
    +(engine.truncated?'Some saved text values are truncated. ':'')
    +(!data.journal.enabled || data.journal.untracked_tables?.length?'Recording has gaps or is suspended; reconstruction may be incomplete. ':'')
    +'Only changes since history recording began are available.';
  $('replayOpen').disabled=true;$('replayPlay').disabled=false;
  $('replayExit').disabled=false;$('replayPosition').disabled=false;
  // graphAction finishes loading before the coalescing renderer takes over.
  state.replay.renderTimer=setTimeout(()=>void renderReplay(),0);
  replayStatus();
}
async function exitReplay() {
  const r=state.replay;if(!r)return;
  pauseReplay();r.exiting=true;clearTimeout(r.renderTimer);cancelReplayLayout(r);
  await graphAction(async()=>{
    MemoryGraphLayout.stop(cy);
    cy.elements('.replayRemoved').remove();cy.elements().removeClass('replayChanged');
    r.disabled.forEach(([el,disabled])=>{el.disabled=disabled;});
    $('live').checked=r.saved.live;$('followGraph').checked=r.saved.follow;state.snapshot=r.saved.snapshot;
    state.selectedActivity=r.saved.activity;state.selectedSession=r.saved.session;
    state.replay=null;state.previous=null;state.revision=null;state.filterKey='';
    $('replayOpen').disabled=false;$('replayPlay').disabled=true;
    $('replayExit').disabled=true;$('replayPosition').disabled=true;
    $('replayStatus').textContent='Saved node and relationship changes · whole database';
    $('replayStatus').title=$('replayStatus').textContent;
    $('replayBoundary').textContent='';
    state.refreshQueued=true;state.resetQueued=true;
  });
}
$('replayOpen').onclick=graphControl(openReplay);
$('replayPlay').onclick=playReplay;
$('replayPosition').oninput=()=>{
  const target=$('replayPosition').value;
  pauseReplay();cancelReplayLayout(state.replay);seekReplay(target);
};
$('replaySpeed').onchange=()=>{if(state.replay?.playing){pauseReplay();playReplay();}};
$('replayExit').onclick=guarded(exitReplay);

async function requestedLayout(options={}) {
  cancelReplayLayout(state.replay);
  await graphStage('Laying out graph');await layout(options);
}
function cancelReplayLayout(r) {
  if(!r)return;
  r.layoutEpoch=(r.layoutEpoch || 0)+1;
  r.layoutPending=null;clearTimeout(r.layoutTimer);r.layoutTimer=null;
  backgroundLayout.cancel();
}
function queueReplayLayout(options) {
  const r=state.replay;if(!r || r.exiting)return;
  r.layoutPending=options;
  startReplayLayout(r);
}
function startReplayLayout(r) {
  if(state.replay!==r || r.exiting || r.layoutRunning || r.layoutTimer!=null || !r.layoutPending)return;
  r.layoutTimer=setTimeout(()=>void runReplayLayout(r),0);
}
async function runReplayLayout(r) {
  r.layoutTimer=null;
  if(state.replay!==r || r.exiting || !r.layoutPending)return;
  if(state.busy){r.layoutTimer=setTimeout(()=>void runReplayLayout(r),16);return;}
  const options=r.layoutPending,epoch=r.layoutEpoch || 0;
  r.layoutPending=null;r.layoutRunning=true;
  replayStatus();
  const beforeApply=async()=>{
    while((state.busy || pointerStart) && state.replay===r && !r.exiting && (r.layoutEpoch || 0)===epoch)
      await graphYield();
    if(state.replay!==r || r.exiting || (r.layoutEpoch || 0)!==epoch)return false;
    if(!$('followGraph').checked)options.fit=false;
    return true;
  };
  try {await layout(options,beforeApply);}
  catch(error){pauseReplay();showError(error,true);}
  finally {r.layoutRunning=false;replayStatus();startReplayLayout(r);}
}
async function drainGraphWork() {
  if (state.refreshQueued) {
    const reset=state.resetQueued;state.refreshQueued=state.resetQueued=false;
    await refresh(reset);
  } else if (state.graphActions.length) await graphAction(state.graphActions.shift());
}
// Union-find over the actual loaded elements: isolated nodes count, missing
// endpoints do not, parallel edges and self-loops never create extra components.
async function countComponents() {
  const nodes=cy.nodes(),edges=cy.edges(),parents=new Map(),sizes=new Map();
  const root=id=>{
    let value=id;
    while(parents.get(value)!==value) value=parents.get(value);
    while(id!==value) {const next=parents.get(id);parents.set(id,value);id=next;}
    return value;
  };
  await graphChunks(nodes,node=>{parents.set(node.id(),node.id());sizes.set(node.id(),1);},'Preparing components');
  await graphChunks(edges,edge=>{
    const source=edge.data('source'),target=edge.data('target');
    if (!parents.has(source)||!parents.has(target)) return;
    let a=root(source),b=root(target);
    if(a===b)return;
    if(sizes.get(a)<sizes.get(b)) [a,b]=[b,a];
    parents.set(b,a);sizes.set(a,sizes.get(a)+sizes.get(b));
  },'Connecting components');
  const labels=new Map(),components=new Map();
  await graphChunks(nodes,node=>{
    const id=root(node.id());
    if(!labels.has(id))labels.set(id,String(labels.size+1));
    components.set(node.id(),labels.get(id));
  },'Counting components');
  await graphChunks(edges,edge=>components.set(edge.id(),components.get(edge.data('source'))),'Labeling components');
  state.components=components;state.componentCount=labels.size;
}
const cy = cytoscape({container:$('cy'), elements:[], minZoom:.001, maxZoom:5,
  hideEdgesOnViewport:true,textureOnViewport:true,
  style:[
    {selector:'node',style:{'background-color':'data(color)',label:'data(displayLabel)','font-size':10,'min-zoomed-font-size':7,color:'#becde0','text-outline-color':'#101925','text-outline-width':2,'text-valign':'bottom','text-margin-y':7,width:'data(size)',height:'data(size)','border-width':1,'border-color':'#62768c','text-max-width':130,'text-wrap':'ellipsis'}},
    {selector:'edge',style:{width:1.3,'line-color':'data(color)','target-arrow-color':'data(color)','target-arrow-shape':'triangle','curve-style':'data(curve)',opacity:.65,label:'data(displayLabel)','font-size':9,'min-zoomed-font-size':7,color:'#b7c8dc','text-rotation':'autorotate','text-background-color':'#111b2b','text-background-opacity':.9}},
    {selector:'.touched',style:{'border-width':5,'border-color':'#f7cd71','line-color':'#f7cd71','target-arrow-color':'#f7cd71',width:4,opacity:1}},
    {selector:'node.touched',style:{width:'data(size)',height:'data(size)'}},
    {selector:'.changed, .recordedChange',style:{'border-color':'#71eab8','border-width':5,'line-color':'#71eab8','target-arrow-color':'#71eab8',opacity:1}},
    {selector:':selected',style:{'border-color':'#fff','border-width':5,'line-color':'#fff','target-arrow-color':'#fff',opacity:1}},
    {selector:'.path',style:{'border-color':'#f0a0ff','border-width':5,'line-color':'#f0a0ff','target-arrow-color':'#f0a0ff',width:4,opacity:1}},
    {selector:'node.path',style:{width:'data(size)',height:'data(size)'}},
    {selector:'.hidden',style:{display:'none'}},
    {selector:'edge:selected, edge:active, edge.hovered',style:{label:'data(label)','min-zoomed-font-size':0}},
    {selector:'node.replayChanged',style:{'background-color':'#5ee6a8','border-width':6,'border-color':'#d7ffe8'}},
    {selector:'edge.replayChanged',style:{width:5,'line-color':'#5ee6a8','target-arrow-color':'#5ee6a8',opacity:1}},
    {selector:'.replayRemoved',style:{'border-color':'#ff7b87','line-color':'#ff7b87','target-arrow-color':'#ff7b87',opacity:.7,'border-width':5}},
    {selector:'edge.replayRemoved',style:{width:4}},
    {selector:'node.replayRemoved',style:{'background-color':'#8f3544'}}
  ]});
const backgroundLayout=MemoryGraphLayout.createWorkerLayout(()=>new Worker('layout-worker.js'));
function replaceRenderer(accelerated) {
  // Cytoscape's experimental renderer reads the inline background colour when
  // blending textures; its default white would leave fringes on our dark view.
  $('cy').style.backgroundColor='#0e1623';
  cy.stopAnimationLoop();
  cy.destroyRenderer();
  cy.initRenderer({name:'canvas',webgl:accelerated,hideEdgesOnViewport:!accelerated,
    textureOnViewport:!accelerated});
  cy.startAnimationLoop();cy.style().update();cy.resize();
}
function saveVisualPreferences() {
  try {localStorage.setItem('evomneme-viewer-visual-preferences',JSON.stringify({gpu:state.acceleration,worker:state.workerLayoutEnabled}));}
  catch {} // Storage can be blocked; the controls still work for this page.
}
function restoreVisualPreferences() {
  try {
    const saved=JSON.parse(localStorage.getItem('evomneme-viewer-visual-preferences') || 'null');
    if(saved?.gpu===true)setAcceleration(true);
    if(saved?.worker===true)setWorkerLayout(true);
  } catch {}
}
function setAcceleration(enabled) {
  try {
    if(enabled) {
      const probe=document.createElement('canvas'),gl=probe.getContext?.('webgl2');
      if(!gl)throw new Error('WebGL 2 is unavailable or disabled in this browser');
      gl.getExtension('WEBGL_lose_context')?.loseContext();
    }
    replaceRenderer(enabled);
    state.acceleration=enabled;$('experimentalAcceleration').checked=enabled;
    $('accelerationStatus').textContent=enabled
      ?'On · GPU rendering. Experimental relationship rendering.'
      :'Off · standard rendering.';
  } catch(error) {
    // Keep the same graph instance, positions, selection and event handlers.
    // Restore ordinary drawing if experimental initialization fails partway.
    if(state.acceleration || !cy.renderer() || cy.renderer().webgl)replaceRenderer(false);
    state.acceleration=false;$('experimentalAcceleration').checked=false;
    $('accelerationStatus').textContent='Experimental acceleration unavailable: '+error.message+'. Standard rendering is active.';
  }
  saveVisualPreferences();
}
function setWorkerLayout(enabled) {
  backgroundLayout.cancel();
  if(enabled && typeof Worker!=='function') {
    state.workerLayoutEnabled=false;$('experimentalWorker').checked=false;
    $('workerStatus').textContent='Background workers are unavailable. Layout runs on the main thread.';
    saveVisualPreferences();
    return;
  }
  state.workerLayoutEnabled=enabled;$('experimentalWorker').checked=enabled;
  $('workerStatus').textContent=enabled
    ?'On · layout runs in a background thread; animation can continue during calculation.'
    :'Off · layout runs on the main thread.';
  saveVisualPreferences();
}
$('experimentalAcceleration').onchange=graphControl(()=>setAcceleration($('experimentalAcceleration').checked));
$('experimentalWorker').onchange=guarded(()=>{
  setWorkerLayout($('experimentalWorker').checked);
  if(state.workerLayoutEnabled && !state.busy)return graphAction(()=>requestedLayout({seed:true}));
});
$('cy').addEventListener('webglcontextlost',event=>{
  if(!state.acceleration)return;
  event.preventDefault();backgroundLayout.cancel();
  void graphAction(()=>{
    setAcceleration(false);
    $('accelerationStatus').textContent='GPU context was lost. Experimental acceleration was disabled; standard rendering is active.';
  });
},true);
function filters() {
  const result = {limit:Number($('limit').value), offset:state.offset, root:state.root,
    depth:Number($('depth').value), search:$('search').value.trim(), focus:$('focus').value, aggregate:$('aggregate').value,
    whole_graph:$('wholeGraph').checked,excluded_layers:[...state.disabledLayers]};
  for (const key of ['scope_id','kind','validity','confidence','source_path']) {
    result[key] = $('filter-' + key)?.value || '';
  }
  for (const key of ['kind','validity','confidence']) {
    result['edge_' + key] = $('edge-' + key)?.value || '';
  }
  if (state.nullField && result[state.nullField]) state.nullField = '';
  result.null_field = state.nullField;
  return result;
}
function syncSelect(select, choices, preserveMissing=true, force=false) {
  const selected=select.value;
  const next=choices.map(([value,label])=>[String(value),String(label)]);
  if (preserveMissing && selected && !next.some(([value])=>value===selected)) next.push([selected,selected+' (0)']);
  const key=JSON.stringify(next);
  if (select._optionsKey===key) {select._pendingOptions=null;return;}
  if (!force && document.activeElement===select) {
    select._pendingOptions={choices,preserveMissing};
    if (!select._blurSync) {
      select._blurSync=true;
      select.addEventListener('blur',()=>{
        const pending=select._pendingOptions;
        select._pendingOptions=null;
        if (pending) syncSelect(select,pending.choices,pending.preserveMissing,true);
      });
    }
    return;
  }
  select.replaceChildren(...next.map(([value,label])=>new Option(label,value)));
  if (next.some(([value])=>value===selected)) select.value=selected;
  select._optionsKey=key;
}
function facetSelect(container,field,label,prefix) {
  let select=$(prefix+field);
  if (!select) {
    const wrapper=text('label',label);
    select=document.createElement('select');select.id=prefix+field;select.dataset.field=field;
    wrapper.append(select);container.append(wrapper);
  }
  return select;
}
function renderLayers(layers = []) {
  const labels={code:'Code entities',knowledge:'Knowledge',cross:'Cross-layer relationships',unresolved:'Unresolved / ambiguous references',custom:'Custom graph'};
  $('layers').replaceChildren();
  for (const layer of layers) {
    const label=document.createElement('label'),input=document.createElement('input');
    input.type='checkbox';
    input.checked=!state.disabledLayers.has(layer.id);
    input.dataset.layer=layer.id;
    input.onchange=()=>{
      if (input.checked) state.disabledLayers.delete(layer.id);
      else state.disabledLayers.add(layer.id);
      state.offset=0;
      refresh(true);
    };
    label.append(input,text('span',`${labels[layer.id] || layer.id} · ${layer.nodes} nodes / ${layer.edges} links`));
    $('layers').append(label);
  }
}
function renderEdgeFilters(facets) {
  const container = $('edgeFilters');
  for (const [field, values] of Object.entries(facets)) {
    const select=facetSelect(container,field,'Relationship '+field,'edge-');
    syncSelect(select,[['','All'],...values.filter(v=>v.value!=null).map(v=>[v.value,`${v.value} (${v.count})`])]);
  }
}
function renderFilters(facets) {
  const labels={scope_id:'Scope / version',kind:'Node type',validity:'Validity',confidence:'Confidence',source_path:'Source file'};
  for (const [field,values] of Object.entries(facets)) {
    const select=facetSelect($('filters'),field,labels[field] || field,'filter-');
    syncSelect(select,[['','All'],...values.filter(v=>v.value!=null).map(v=>[v.value,`${v.value} (${v.count})`])]);
  }
}
function metrics(data) {
  $('overview').replaceChildren();
  const values = [
    [data.totals.nodes ?? '—','Graph nodes · all layers'],
    [data.totals.edges ?? '—','Relationships · all layers'],
    [data.isolated_total ?? '—','Isolated nodes · all layers'],
    [data.reference_total || data.dangling_total || 0,data.reference_total?'Unresolved / ambiguous reference nodes':'Missing endpoints · all layers'],
    [data.tables.reduce((a,t)=>a+t.count,0),'Rows · all tables'],
    [(data.bytes/1048576).toFixed(2)+' MB','SQLite pages · logical size']
  ];
  for (const [value,label] of values) {
    const metric=text('div','','metric');
    metric.append(text('strong',typeof value==='number'?value.toLocaleString():value),text('span',label));
    $('overview').append(metric);
  }
}
async function decorate() {
  const field = $('perspective').value;
  const components = state.components;
  const value = el => field === 'degree' ? String(el.isNode()?el.degree():0)
    : field === 'components' ? components.get(el.id()) : String(el.data('attributes')[field] ?? 'unspecified');
  const elements=cy.elements(),categories=new Set();
  await graphChunks(elements,el=>categories.add(value(el)),'Preparing styles');
  const values = [...categories].sort();
  const validityColors = {current:'#86d8b6',stale:'#f0bf79',superseded:'#7c8da4'};
  const confidenceColors = {confirmed:'#86d8b6',inferred:'#79b8e8',uncertain:'#e58e99'};
  const colors = new Map(values.map((v,i) => [v,
    (field==='validity'?validityColors[v]:field==='confidence'?confidenceColors[v]:null) || palette[i%palette.length]]));
  await graphChunks(elements,el => {
    const color=colors.get(value(el));
    if (el.data('color')!==color) el.data('color',color);
    const displayLabel=(el.isNode()?$('labels').checked:$('edgeLabels').checked)?el.data('label'):'';
    if (el.data('displayLabel')!==displayLabel) el.data('displayLabel',displayLabel);
    if (el.isNode()) {
      const attrs = el.data('attributes');
      const size=attrs._aggregate ? 22+Math.min(36,Math.log2(attrs.member_count+1)*4) : 14+Math.min(16,Math.log2(el.degree()+1)*4);
      if (el.data('size')!==size) el.data('size',size);
    }
  },'Styling graph',true);
  $('legend').replaceChildren();
  for (const v of values.slice(0,30)) {
    const item = text('span',v,'legend-item'), swatch = text('i','','swatch');
    swatch.style.backgroundColor = colors.get(v);
    item.prepend(swatch);
    $('legend').append(item);
  }
  if (values.length > 30) $('legend').append(text('span',`+${values.length-30} categories`));
}
async function layout(options = {},beforeApply=null) {
  const bounds=$('cy').getBoundingClientRect();
  if (bounds.width<1 || bounds.height<1) {state.pendingLayout=true;return;}
  state.pendingLayout=false;
  cy.resize();
  const settings={name:$('layout').value,width:bounds.width,height:bounds.height,
    fit:!state.replay || $('followGraph').checked,...options};
  const guard=beforeApply?async()=>{
    const allowed=await beforeApply();
    if(state.replay && !$('followGraph').checked)settings.fit=false;
    return allowed;
  }:null;
  let backgroundError='';
  if(state.workerLayoutEnabled) {
    try {
      const applied=await backgroundLayout.arrange(cy,settings,guard);
      if(applied || state.workerLayoutEnabled)return;
    }
    catch(error) {
      backgroundError=error.message;
      setWorkerLayout(false);
      $('workerStatus').textContent='Background layout failed: '+error.message+'. Background layout disabled; large graphs use a quick grid overview.';
    }
  }
  if(guard && await guard()===false)return;
  if(!$('followGraph').checked && state.replay)settings.fit=false;
  // Do not run quadratic force calculations on the UI thread before the user
  // can reach the controls. The complete graph remains available in a linear
  // overview, including after a failed/timed-out experimental worker.
  if(cy.nodes().length>800 && settings.name==='cose') {
    settings.overview=true;
    $('workerStatus').textContent=(backgroundError?'Background layout failed: '+backgroundError+'. ':'')
      +'Large graph: quick grid overview keeps controls responsive. Enable background layout for force-directed positioning.';
  }
  MemoryGraphLayout.arrange(cy,settings);
}
async function signatureMap(data) {
  // Complete snapshots already fingerprint all omitted details on the server.
  // Retain that compact signature instead of a second JSON copy of the graph.
  const signature=row=>data.whole_graph && typeof row.fingerprint==='string'
    ? row.fingerprint+':'+String(row.evidence_count ?? '') : JSON.stringify(row);
  const result=new Map();
  await graphChunks(data.nodes,n=>result.set('n:'+n.graph_id,signature(n)),'Preparing node signatures');
  await graphChunks(data.edges,e=>result.set('e:'+e.graph_id,signature(e)),'Preparing relationship signatures');
  return result;
}
async function draw(data, resetLayout, key) {
  const next = await signatureMap(data);
  const previous=state.previous,sameView=state.filterKey===key;
  state.changes.clear();
  if (state.previous && state.filterKey === key) {
    const changed = [];
    await graphChunks([...next],([id, signature])=>{
      if (state.previous.get(id) !== signature) {
        state.changes.add(id);
        changed.push(id);
      }
    },'Comparing graph');
    const removed = [...state.previous.keys()].filter(id => !next.has(id));
    if (changed.length || removed.length) {
      if (!state.replay && !state.journal?.enabled) await ingest([{source:'snapshot',time:Date.now()/1000, read:[], write:[],
        references:[], changed, removed, ok:true, elapsed_ms:0, returned_rows:0}],false);
    } else if (!resetLayout) {
      // Preserve a user's layout, selection and path while the database is unchanged.
      cy.elements().removeClass('changed');
      return;
    }
  }
  const oldPositions = new Map(),oldIds=new Set();
  let sumX=0,sumY=0;
  await graphChunks(cy.elements(),el=>{
    oldIds.add(el.id());
    if(el.isNode()) {const p=el.position();oldPositions.set(el.id(),{x:p.x,y:p.y});sumX+=p.x;sumY+=p.y;}
  },'Preserving graph positions');
  const ids = new Set(),newIds=new Set();
  const center = oldPositions.size ? {x:sumX/oldPositions.size,y:sumY/oldPositions.size} : {x:0,y:0};
  const neighbors=new Map();
  await graphChunks(data.edges,edge=>{
    for (const [id,other] of [[edge.source,edge.target],[edge.target,edge.source]]) {
      const p=oldPositions.get('n:'+other);
      if (!p) continue;
      const key='n:'+id, sum=neighbors.get(key) || {x:0,y:0,count:0};
      sum.x+=p.x;sum.y+=p.y;sum.count++;
      neighbors.set(key,sum);
    }
  },'Locating new node neighbors');
  let added = 0;
  const elements=[];
  await graphChunks(data.nodes,n => {
    const id = 'n:' + n.graph_id;
    let position = oldPositions.get(id);
    if (!position) {
      newIds.add(id);
      const angle = ++added * 2.4, radius = 50 + 12 * Math.sqrt(added);
      const near=neighbors.get(id);
      const origin=near ? {x:near.x/near.count,y:near.y/near.count} : center;
      position = {x:origin.x+Math.cos(angle)*radius, y:origin.y+Math.sin(angle)*radius};
    }
    ids.add(id);
    elements.push({group:'nodes', data:{id,label:String(n.label)+(n._aggregate?` · ${n.member_count} nodes`:''),displayLabel:'',attributes:n,color:palette[0],size:24},position});
  },'Preparing nodes');
  await graphChunks(data.edges,e=>{
    if (ids.has('n:'+e.source)&&ids.has('n:'+e.target)) {
      ids.add('e:'+e.graph_id);
      elements.push({group:'edges',data:{id:'e:'+e.graph_id,source:'n:'+e.source,target:'n:'+e.target,
        label:e._aggregate?`${e.member_count} links`:String(e.kind||''),displayLabel:'',attributes:e,color:'#506984',curve:data.nodes.length>10000?'straight':'bezier'}});
    }
  },'Preparing relationships');
  let topologyChanged=oldIds.size!==ids.size;
  await graphChunks([...ids],id=>{if(!oldIds.has(id))topologyChanged=true;},'Comparing topology');
  await graphStage('Updating graph');
  cy.startBatch();
  try {
    cy.elements().removeClass('changed');
    if (resetLayout || !sameView) cy.elements().removeClass('path');
    cy.elements().filter(el=>!ids.has(el.id())).remove();
    for (let i=0;i<elements.length;i+=1500) {
      const additions=[];
      for (const element of elements.slice(i,i+1500)) {
        let existing=cy.getElementById(element.data.id);
        if (existing.length && existing.isEdge() &&
            (existing.data('source')!==element.data.source || existing.data('target')!==element.data.target)) {
          topologyChanged=true;
          existing.remove();
          existing=cy.collection();
        }
        if (!existing.length) additions.push(element);
        else if (!previous || previous.get(element.data.id)!==next.get(element.data.id)
            || (existing.isEdge() && existing.data('curve')!==element.data.curve)) existing.data(element.data);
      }
      if (additions.length) cy.add(additions);
      if(state.progress) {Object.assign(state.progress,{stage:'Adding graph elements',done:Math.min(i+1500,elements.length),total:elements.length});state.progress.paint();}
      if(elements.length>1500)await graphYield();
    }
  } finally {await graphStage('Finalizing graph elements');cy.endBatch();}
  await countComponents();
  await decorate();
  if (!state.replay) await applyHighlight();
  if (!state.selectedActivity&&!state.selectedSession) await graphChunks(cy.elements(),el=>{if(state.changes.has(el.id()))el.addClass('changed');},'Marking changes',true);
  // A click may arrive during cooperative rendering; use the latest selection
  // rather than the one that existed at the start of this update.
  const selected=state.selected?.id();
  if (selected && cy.getElementById(selected).length) {
    state.selected = cy.getElementById(selected);
    state.selected.select();
    if(state.replay && previous?.get(selected)!==next.get(selected))await inspect(state.selected);
  } else {
    state.selected = null;
    $('detail').replaceChildren();
    $('selectionActions').classList.add('hidden');
    $('openGroup').classList.add('hidden');
  }
  if (resetLayout || !oldPositions.size || (topologyChanged && (state.replay || $('followGraph').checked))) {
    await graphStage('Laying out graph');
    const settings={seed:resetLayout || !oldPositions.size,
      fit:!state.selectedActivity&&!state.selectedSession && (!state.replay || $('followGraph').checked),
      animate:oldPositions.size>0 && (!state.replay || state.replay.index>=0),newIds};
    if(state.replay?.index>=0)queueReplayLayout(settings);
    else await layout(settings);
  } else if (added) {
    await graphStage('Positioning new nodes');
    MemoryGraphLayout.transition(cy,()=>MemoryGraphLayout.separate(cy.nodes(),newIds),{newIds});
  }
  state.previous=next;state.filterKey=key;
  await graphStage('Rendering graph');
}
async function refresh(resetLayout=false) {
  if (state.replay) return;
  if (state.busy) {state.refreshQueued=true;state.resetQueued ||= resetLayout;return;}
  state.busy = true;
  progressStart();
  $('error').classList.add('hidden');
  try {
    const values = filters(), key = JSON.stringify(values), started = performance.now();
    await graphStage('Loading graph');
    const data = await api('snapshot', {...values,revision:state.revision});
    if (key!==JSON.stringify(filters())) {state.refreshQueued=true;state.resetQueued=true;return;}
    if (data.unchanged) {
      if (state.view==='tables') await loadTable();
      await pollEvents();
      await graphStage('Rendering graph');
      progressStop();
      setConnectionStatus('● Connected · '+new Date().toLocaleTimeString());
      return;
    }
    state.snapshot = data;
    state.journal=data.journal || null;
    await graphStage('Preparing graph');
    $('storageMode').textContent=state.journal?.enabled?'LOCAL · HISTORY RECORDING':'LOCAL · READ ONLY';
    metrics(data);
    renderFilters(data.facets);
    renderEdgeFilters(data.edge_facets);
    renderLayers(data.layers);
    await draw(data, resetLayout, key);
    state.revision=data.revision;
    $('sliceInfo').textContent = `${cy.nodes().length} nodes · ${cy.edges().length} relationships · ${state.componentCount} components in slice`;
    $('pageInfo').textContent = `${data.matched_nodes?state.offset+1:0}–${state.offset+data.nodes.length} / ${data.matched_nodes||0} matching nodes`;
    $('previous').disabled = data.whole_graph || state.offset === 0;
    $('next').disabled = data.whole_graph || !data.node_has_more;
    $('limit').disabled=data.whole_graph;
    const notices = [];
    if (!data.graph_available) notices.push('No graph projection for this schema. Inspect tables / SQL, or supply --mapping.');
    if (data.node_has_more || state.offset) notices.push('Partial graph: use filters, pagination or neighborhood focus to inspect other segments.');
    if (data.edge_has_more) notices.push('Relationships capped at 2,000 for this slice. Narrow the selection.');
    if (data.boundary_edges) notices.push(`${data.boundary_edges} relationships cross this slice boundary.`);
    if (state.root) notices.push('Neighborhood focus active. Clear filters & focus to return.');
    if (state.nullField) notices.push(`Filtering unspecified ${state.nullField}. Clear filters & focus to remove.`);
    if (data.aggregate) notices.push(`Whole filtered database grouped by ${data.aggregate}: ${data.grouped_members} members. Drill into groups for individual elements and session highlights.`);
    if (data.reference_total) notices.push(`${data.reference_total} reference targets are represented explicitly as unresolved/ambiguous nodes.`);
    if (cy.scratch('memory-layout')==='grid-large') notices.push('Large graph: grid overview keeps all selected nodes and links available. Zoom in, filter, or group by layer/type to inspect structure.');
    if (cy.scratch('memory-layout')==='grid-overview') notices.push('Quick grid overview: all selected nodes and links are loaded. Enable Experimental background layout for force-directed positioning.');
    notices.push(...(data.projection_warnings || []));
    $('notice').textContent = notices.join(' ') || 'Showing the complete graph for this selection. Select elements to inspect evidence and stored claims.';
    renderTables(data.tables);
    if (state.view === 'tables') await loadTable();
    if (state.selected) await inspect(state.selected);
    await pollEvents();
    await graphStage('Rendering graph');
    $('performance').textContent = `Query ${data.elapsed_ms} ms · refresh ${Math.round(performance.now()-started)} ms`;
    progressStop();
    setConnectionStatus('● Connected · '+new Date().toLocaleTimeString());
  } catch (error) {
    $('live').checked=false;
    state.refreshQueued=state.resetQueued=false;
    state.graphActions=[];state.previous=null;state.revision=null;
    progressStop();
    setConnectionStatus('Refresh failed · Live paused');
    showError(error,true);
  } finally {
    progressStop();
    state.busy = false;
    await drainGraphWork();
  }
}
function matches(e){return ['chat','session','agent'].every(key=>!$(key).value||e[key]===$(key).value);}
function isObservation(event) {
  return !hasCaller(event);
}
function hasCaller(event) {return !!(event.chat || event.session || event.agent || event.client?.name);}
function sessionKey(event) {
  if (!hasCaller(event)) return 'unknown';
  if (event.session) return JSON.stringify(['session',event.chat || null,event.session]);
  return JSON.stringify(['process',event.chat || null,event.agent || null,event.client?.name || null]);
}
const localActivityKeys=new WeakMap();let localActivitySerial=0;
function activityKey(event) {
  if(event.source==='database_change')return 'change:'+event.change_id;
  if(event.activity_id)return 'activity:'+event.activity_id;
  if(!localActivityKeys.has(event))localActivityKeys.set(event,'local:'+(++localActivitySerial));
  return localActivityKeys.get(event);
}
function loadedSessions() {
  const groups=new Map();
  for(const event of state.history.filter(matches)) {
    const key=sessionKey(event);
    if(!groups.has(key))groups.set(key,{key,events:[],identity:event});
    const group=groups.get(key);group.events.push(event);
    if(event.time>=group.identity.time)group.identity=event;
  }
  return [...groups.values()].sort((a,b)=>b.identity.time-a.identity.time);
}
async function selectSession(key) {
  state.selectedActivity=null;state.selectedSession=key;$('followGraph').checked=false;
  cy.elements().unselect().removeClass('path changed');
  await applyHighlight();
}
function identityLabel(event, key) {
  const titles = {chat:'chat_title',session:'session_title',agent:'agent_name'};
  const title = event[titles[key]], id = event[key];
  if (title) return `${title}${id ? ' · ' + id : ''}`;
  if (key === 'chat' && event.identity?.chat === false) return 'Chat not reported';
  if (key === 'agent' && event.identity?.agent === false) return id?`Process ${String(id).slice(0,8)}`:'Agent not reported';
  return id || `${key} not reported`;
}
async function selectActivity(event) {
  $('followGraph').checked=false;
  state.selectedActivity = event;
  state.selectedSession = null;
  cy.elements().unselect().removeClass('path changed');
  await applyHighlight();
  const highlighted = cy.elements('.touched');
  if (highlighted.length) MemoryGraphLayout.fit(cy,highlighted.union(highlighted.edges().connectedNodes()),60);
}
function references(event) {
  const ids=(event.references || []).map(r=>{
    if (r.graph_type) return (r.graph_type==='nodes'?'n:':'e:')+r.graph_id;
    if (r.table==='nodes'||r.table==='edges') return (r.table==='nodes'?'n:':'e:')+JSON.stringify([r.scope_id,r.id]);
    return null;
  });
  return ids.filter(Boolean).concat(event.changed || []);
}
async function applyHighlight() {
  const events = state.selectedActivity ? [state.selectedActivity] : state.selectedSession
    ? state.history.filter(event=>matches(event)&&sessionKey(event)===state.selectedSession) : state.recorded.filter(matches);
  const touched = new Set(),changed=new Set(),context=new Set();
  await graphChunks(events,event=>{
    for(const id of references(event))touched.add(id);
    for(const id of event.changed || [])changed.add(id);
  },'Preparing highlights');
  let visibleCount=0;
  await graphChunks([...touched],id=>{
    const el=cy.getElementById(id);
    if(!el.length)return;
    visibleCount++;context.add(id);
    if(el.isEdge()) {context.add(el.data('source'));context.add(el.data('target'));}
  },'Finding highlighted elements');
  await graphChunks(cy.elements(),el=>{
    for(const [name,enabled] of [['touched',touched.has(el.id())],['recordedChange',changed.has(el.id())],
      ['hidden',$('onlyTouched').checked && !context.has(el.id())]]) {
      if(el.hasClass(name)!==enabled)el.toggleClass(name,enabled);
    }
  },'Highlighting graph',true);
  $('highlightCount').textContent = `${touched.size} accumulated IDs · ${visibleCount} visible`;
  const selected = state.selectedActivity;
  $('showAccumulated').classList.toggle('hidden',!selected&&!state.selectedSession);
  if (selected) {
    const removed = selected.removed?.length || 0;
    const visible = visibleCount;
    $('highlightCount').textContent = `${touched.size} event IDs · ${visible} visible`;
    $('activitySelection').textContent = touched.size
      ? `Selected activity: ${visible} / ${touched.size} IDs visible${removed?`; ${removed} removed IDs`:''}.`
        + (visible < touched.size ? ' Other IDs are outside this slice, deleted, or grouped.' : '')
      : removed ? `Selected observation: ${removed} IDs were removed from the graph.`
        : 'Selected activity has no exact node/relationship IDs; only table-level access was recorded.';
  } else if(state.selectedSession) {
    $('highlightCount').textContent=`${touched.size} session IDs · ${visibleCount} visible`;
    $('activitySelection').textContent=`Selected group: union of ${events.length} currently loaded activities; ${visibleCount} / ${touched.size} IDs visible. Older unloaded history is excluded.`;
  } else $('activitySelection').textContent = '';
  renderChangeDetail(selected);
  renderTimeline();
}
function renderChangeDetail(event) {
  const container=$('changeDetail');
  const persistent=event?.source==='database_change';
  container.classList.toggle('hidden',!persistent);
  if (!persistent || container.dataset.changeId===String(event.change_id)) return;
  container.dataset.changeId=String(event.change_id);
  container.open=true;
  $('changeMeta').textContent=`Change #${event.change_id} · ${event.operation.toUpperCase()} · ${event.table} · ${new Date(event.time*1000).toLocaleString()}`;
  const before=event.before || {},after=event.after || {};
  const keys=[...new Set([...Object.keys(before),...Object.keys(after)])].sort();
  const format=cell=>{
    if (!cell) return '(absent)';
    const value=cell.value==null?'NULL':typeof cell.value==='object'?JSON.stringify(cell.value):String(cell.value);
    return `[${cell.type}] ${value}${cell.truncated?` (preview; full length ${cell.length})`:''}`;
  };
  const changed=keys.filter(key=>JSON.stringify(before[key])!==JSON.stringify(after[key]));
  table($('changeDiff'),(changed.length?changed:keys).map(key=>({field:key,before:format(before[key]),after:format(after[key])})));
  $('changeNote').textContent=changed.length
    ? 'Stored row transition. Deleted or renamed elements may be absent from the current graph. Long values are explicit previews.'
    : 'The row changed, but bounded previews may be identical. Full values beyond the previews were not archived.';
}
function updateSessionOptions() {
  const identities = [...state.sessions.values()];
  for (const key of ['chat','session','agent']) {
    const selected = $(key).value;
    const candidates = identities.filter(e => typeof e[key] === 'string' && e[key])
      .filter(e => key !== 'chat' || e.identity?.chat !== false)
      .filter(e => key === 'chat' || !$('chat').value || e.chat === $('chat').value)
      .filter(e => key !== 'agent' || !$('session').value || e.session === $('session').value);
    const choices = new Map();
    for (const event of candidates) {
      const client = event.client?.name;
      choices.set(event[key],(client ? client + ' · ' : '') + identityLabel(event,key));
    }
    syncSelect($(key),[['','All '+(key==='chat'?'chats':key+'s')],...[...choices.entries()].sort((a,b)=>a[1].localeCompare(b[1]))],false);
  }
  $('identityStatus').textContent = identities.length
    ? 'Caller metadata comes from recorded calls and attributed changes. Process identities are shown when chat or agent identity was not reported. Unassigned changes remain separate.'
    : 'No caller metadata loaded. Unassigned changes and observations cannot identify a chat or agent.';
}
async function ingest(events,highlight=true) {
  // Empty Live polls do not change highlights. Avoid restyling every element
  // of a large graph merely to redisplay the same empty activity response.
  if (!events.length) {
    if (!state.activitiesReady) {state.activitiesReady=true;updateSessionOptions();}
    renderTimeline();
    return;
  }
  state.activitiesReady=true;
  for (const event of events) {
    if (event.source==='database_change') {
      if (state.seenChanges.has(event.change_id)) continue;
      state.seenChanges.add(event.change_id);
    } else if(event.activity_id) {
      if(state.seenActivities.has(event.activity_id))continue;
      state.seenActivities.add(event.activity_id);
    }
    if (!isObservation(event)) {
      const key = JSON.stringify([event.chat,event.session,event.agent]);
      const previous = state.sessions.get(key) || {};
      const identity = {...previous};
      for (const field of ['chat','session','agent','client','identity']) identity[field] = event[field];
      for (const title of ['chat_title','session_title','agent_name']) identity[title] = event[title] || previous[title];
      state.sessions.set(key,identity);
    }
    state.history.push(event);
    if (state.recording && event.time >= state.recordingSince) state.recorded.push(event);
  }
  if (events.length) state.history.sort((a,b)=>a.time-b.time || (a.change_id || 0)-(b.change_id || 0));
  for (const collection of [state.history,state.recorded]) {
    if (collection.length > 10000) {
      collection.splice(0,collection.length-10000);
      state.missed = true;
    }
  }
  while (state.sessions.size > 10000) {
    state.sessions.delete(state.sessions.keys().next().value);
    state.missed = true;
  }
  state.seenChanges=new Set(state.history.filter(e=>e.source==='database_change').map(e=>e.change_id));
  state.seenActivities=new Set(state.history.filter(e=>e.source!=='database_change'&&e.activity_id).map(e=>e.activity_id));
  updateSessionOptions();
  if(highlight && events.length)await applyHighlight();
  else renderTimeline();
}
async function pollEvents(older=false) {
  for(let page=0;page<5;page++) {
    const request={cursors:state.cursors,limit:state.activityAfter==null?100:200};
    if(older) {if(state.activityBefore==null)break;request.before_id=state.activityBefore;}
    else if(state.activityAfter!=null)request.after_id=state.activityAfter;
    const data = await api('events',request);
    state.cursors = data.cursors || state.cursors;
    if(older || state.activityAfter==null) {
      state.activityBefore=data.before_id??null;state.activityOlder=!!data.has_older;
    }
    if(!older)state.activityAfter=data.after_id??state.activityAfter;
    await ingest(data.events || []);
    $('traceStatus').textContent = (data.storage==='database' || data.enabled ? 'Database call history available' : 'Call history unavailable')
      + (data.has_more ? ' · catching up' : '')
      + (state.missed ? ' · browser history limited to 10,000 loaded activities' : '');
    if(older || !data.has_more)break;
  }
  await pollChanges(older);
}
function historyButton() {
  $('olderChanges').disabled=state.changeBusy || (!state.changeOlder&&!state.activityOlder);
  $('olderChanges').title='Loads older SQL calls and row changes. Counts describe loaded history; caller filters may hide retrieved entries.';
}
async function pollChanges(older=false) {
  if (state.changeBusy) return;
  if (!state.journal?.version) {
    $('journalStatus').textContent='Database row history is not available yet.';
    historyButton();return;
  }
  if(older && (!state.changeOlder || state.changeBefore==null)) {renderTimeline();return;}
  state.changeBusy=true;
  historyButton();
  try {
    let more=false;
    for (let page=0;page<5;page++) {
      const request={limit:state.changeAfter==null?100:200};
      if (older) request.before_id=state.changeBefore;
      else if (state.changeAfter!=null) request.after_id=state.changeAfter;
      const data=await api('changes',request);
      state.journal=data.journal || state.journal;
      $('storageMode').textContent=state.journal.enabled?'LOCAL · HISTORY RECORDING':'LOCAL · READ ONLY';
      if (older || state.changeAfter==null) {
        state.changeBefore=data.before_id;
        state.changeOlder=data.has_older;
      }
      if (!older) state.changeAfter=data.after_id;
      await ingest(data.events || []);
      more=data.has_more;
      if (!more || older) break;
    }
    const gaps=[...(state.journal.untracked_tables || []),...(state.journal.unsupported_tables || [])];
    $('journalStatus').textContent=`Database history ${state.journal.enabled?'recording':'suspended'} · since ${state.journal.started_at || 'unknown'}`
      +(more?' · catching up':'')+(gaps.length?' · not tracked: '+gaps.join(', '):'');
    if (older) renderTimeline();
  } finally {state.changeBusy=false;historyButton();}
}
function renderTimeline() {
  const list = $('timeline');
  const panel = $('activityPanel'), panelScroll = panel.scrollTop;
  const focused = document.activeElement?._historyFocus;
  const scroll=list.scrollTop;
  list.replaceChildren();
  const groups=loadedSessions();
  const loaded=groups.flatMap(group=>group.events);
  $('historySummary').textContent=`Loaded (matching filters): ${loaded.filter(e=>e.source==='sql').length} calls · ${loaded.filter(e=>e.source==='database_change').length} row changes · ${loaded.filter(e=>e.source!=='sql'&&e.source!=='database_change').length} other actions · ${groups.length} groups${state.missed?' · browser limit reached: 10,000 activities; some loaded entries were discarded':''}. Counts exclude unloaded database history.`;
  const focusable=(el,key)=>{el._historyFocus=key;if(focused===key)el.focus({preventScroll:true});return el;};
  for(const group of groups) {
    const section=text('section','','session-group');
    const heading=text('div','','session-heading');
    const expanded=state.expandedSessions.has(group.key),identity=group.identity;
    const label=group.key==='unknown'?'Unassigned changes / observations · caller unknown':
      [identityLabel(identity,'chat'),identityLabel(identity,'session'),identityLabel(identity,'agent'),identity.client?.name || 'client not reported'].join(' / ');
    const toggle=text('button',`${expanded?'▾':'▸'} ${label}`,'session-toggle');
    toggle.type='button';toggle.setAttribute('aria-expanded',String(expanded));toggle._historyFocus='toggle:'+group.key;
    toggle.onclick=()=>{if(expanded)state.expandedSessions.delete(group.key);else state.expandedSessions.add(group.key);renderTimeline();};
    const highlight=text('button','Highlight loaded group','session-highlight');
    highlight.type='button';highlight.title='Union of exact IDs in currently loaded entries only';highlight.setAttribute('aria-pressed',String(state.selectedSession===group.key));highlight._historyFocus='highlight:'+group.key;
    highlight.onclick=graphControl(()=>selectSession(group.key));
    heading.append(toggle,highlight);section.append(heading);
    const calls=group.events.filter(e=>e.source==='sql').length,changes=group.events.filter(e=>e.source==='database_change').length;
    section.append(text('p',`${calls} loaded calls · ${changes} loaded row changes · ${group.events.length-calls-changes} other loaded actions · latest ${new Date(identity.time*1000).toLocaleString()}`,'session-counts'));
    list.append(section);focusable(toggle,toggle._historyFocus);focusable(highlight,highlight._historyFocus);
    if(!expanded)continue;
    const limit=state.sessionLimits.get(group.key)||50;
    for (const event of group.events.slice(-limit).reverse()) {
    const row = text('button','','event');
    row.type = 'button';
    row._activity = event;
    row._historyFocus='event:'+activityKey(event);
    row.setAttribute('aria-pressed',String(event === state.selectedActivity));
    row.onclick = guarded(()=>graphAction(()=>selectActivity(event)));
    row.append(text('span',new Date(event.time*1000).toLocaleTimeString(),'time'));
    const details = event.source==='database_change'
      ? `${event.operation.toUpperCase()} ${event.table} · ${new Set(references(event)).size} related IDs · saved in SQLite`
      : event.changed
      ? `${event.changed.length} created / modified · ${event.removed.length} removed from snapshot`
      : `${event.read?.length?'read '+event.read.join(', '):''} ${event.write?.length?'write attempted '+event.write.join(', '):''}`
        + ` · ${event.returned_rows} returned · ${event.elapsed_ms} ms`
        + (event.rolled_back ? ' · open transaction rolled back' : '')
        + (event.durable_effects_possible ? ' · durable effects possible' : '')
        + (event.has_more ? ' · bounded output' : '')
        + (event.references_truncated ? ' · ID limit: table-level only' : '');
    const label = event.source==='database_change'
      ? `Change #${event.change_id}${hasCaller(event)?'':' · author not reported'}`
      : isObservation(event)
      ? 'Database observation · author not reported'
      : [event.client?.name || 'SQL client not reported',identityLabel(event,'chat'),identityLabel(event,'session'),identityLabel(event,'agent')].join(' / ');
    row.append(text('span',`${label} · ${details}${event.ok?'':' · FAILED'}`,event.ok?'':'failed'));
    section.append(row);focusable(row,row._historyFocus);
    }
    if(group.events.length>limit) {
      const more=text('button',`Show 50 more (${group.events.length-limit} loaded entries remaining)`,'session-more');
      more._historyFocus='more:'+group.key;more.onclick=()=>{state.sessionLimits.set(group.key,limit+50);renderTimeline();};
      section.append(more);focusable(more,more._historyFocus);
    }
  }
  list.scrollTop=scroll;
  historyButton();
  panel.scrollTop=panelScroll;
}
function table(container,rows){container.replaceChildren();if(!rows.length){container.append(text('p','No rows.','hint'));return;}const el=document.createElement('table'),thead=document.createElement('thead'),head=document.createElement('tr'),columns=[...new Set(rows.flatMap(Object.keys))];columns.forEach(c=>head.append(text('th',c)));thead.append(head);el.append(thead);const body=document.createElement('tbody');for(const row of rows){const tr=document.createElement('tr');columns.forEach(c=>tr.append(text('td',typeof row[c]==='object'?JSON.stringify(row[c],null,2):row[c])));body.append(tr);}el.append(body);container.append(el);}
function attributes(container,record){const dl=document.createElement('dl');for(const [key,value]of Object.entries(record)){dl.append(text('dt',key),text('dd',typeof value==='object'?JSON.stringify(value,null,2):value));}container.append(dl);}
async function inspect(el) {
  state.selected = el;
  const attrs = el.data('attributes');
  const container = $('detail');
  $('openGroup').classList.add('hidden');
  if (state.replay) {
    container.replaceChildren();attributes(container,attrs);
    $('selectionHint').textContent='Historical graph attributes. Evidence and detail tables are not reconstructed.';
    $('selectionActions').classList.add('hidden');
    return;
  }
  if (attrs._aggregate) {
    container.replaceChildren();
    attributes(container,attrs);
    $('selectionHint').textContent = 'Aggregate over the whole filtered database. Counts describe stored members and relationships.';
    $('selectionActions').classList.add('hidden');
    $('openGroup').classList.toggle('hidden',!el.isNode());
    return;
  }
  const data = await api('detail',{type:el.isNode()?'nodes':'edges',id:attrs.graph_id});
  if (state.selected !== el) return;
  container.replaceChildren();
  $('selectionHint').textContent = attrs.source_table==='unresolved_reference'
    ? 'Unresolved endpoint reference; this placeholder is not a verified program declaration.'
    : el.isNode() ? 'Stored node and supporting evidence' : 'Stored relationship and supporting evidence';
  $('selectionActions').classList.toggle('hidden',!el.isNode());
  data.rows.forEach(r => attributes(container,r));
  if (data.coverage?.length) {
    container.append(text('h2','Stored file coverage / review state'));
    data.coverage.forEach(r=>attributes(container,r));
  }
  container.append(text('h2','Evidence'));
  if (!data.evidence.length) container.append(text('p','No supporting evidence returned. For custom schemas, inspect provenance using SQL.','hint'));
  for (const e of data.evidence) {
    container.append(text('div','','separator'));
    attributes(container,e);
  }
  if (data.evidence_has_more) container.append(text('p','Evidence capped at 200 rows. Inspect remaining rows with SQL.','hint'));
}
function openGroup(el) {
  const attrs = el?.data('attributes');
  if (!el?.isNode() || !attrs?._aggregate) return;
  const select = $('filter-' + attrs._aggregate);
  if (attrs._aggregate==='layer') {
    state.disabledLayers=new Set(state.snapshot.layers.filter(l=>l.id!==attrs.group_value).map(l=>l.id));
    // Cross-layer edges have no nodes of their own; incident edges follow visible endpoints.
    state.disabledLayers.delete('cross');
    $('aggregate').value='';state.root='';state.offset=0;refresh(true);return;
  }
  state.nullField = attrs.group_value == null ? attrs._aggregate : '';
  if (attrs.group_value == null) select.value = '';
  else {
    const value = String(attrs.group_value);
    if (![...select.options].some(o => o.value === value)) select.add(new Option(value,value));
    select.value = value;
  }
  $('aggregate').value = '';
  state.root = '';
  state.offset = 0;
  refresh(true);
}
cy.on('tap','node,edge',event => {if(!event.target.removed())guarded(inspect)(event.target);});
cy.on('dbltap','node',event => {
  if (state.replay) return;
  if (event.target.data('attributes')._aggregate) return openGroup(event.target);
  state.root = event.target.data('attributes').graph_id;
  state.offset = 0;
  refresh(true);
});
$('openGroup').onclick = () => openGroup(state.selected);
$('aggregate').onchange = () => {
  state.root = '';
  state.offset = 0;
  if ($('aggregate').value) $('perspective').value = $('aggregate').value;
  refresh(true);
};
function renderTables(tables){syncSelect($('tableSelect'),tables.map(t=>[t.name,`${t.name} (${t.count})`]),false);}
async function loadTable(){const name=$('tableSelect').value;if(!name){$('tableData').replaceChildren();return;}const definition=state.snapshot.tables.find(t=>t.name===name);$('schemaDetail').textContent=definition.sql+'\n\nForeign keys: '+JSON.stringify(definition.foreign_keys,null,2);const quoted='"'+name.replaceAll('"','""')+'"';const result=await api('query',{sql:`SELECT * FROM ${quoted} LIMIT 201 OFFSET ${state.tableOffset}`});table($('tableData'),result.rows);$('tablePage').textContent=`Rows ${state.tableOffset+1}–${state.tableOffset+result.rows.length} / ${definition.count}`;$('tablePrevious').disabled=state.tableOffset===0;$('tableNext').disabled=!result.has_more;}
function download(name,data,type){const url=URL.createObjectURL(new Blob([data],{type})),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
$('refresh').onclick = () => refresh();
$('apply').onclick = () => { state.offset=0; refresh(true); };
$('search').onkeydown = e => { if (e.key==='Enter') $('apply').click(); };
$('clearFilters').onclick = () => {
  state.offset = 0;
  state.root = '';
  state.nullField = '';
  $('search').value = '';
  $('focus').value = '';
  document.querySelectorAll('#filters select, #edgeFilters select').forEach(s => s.value='');
  refresh(true);
};
$('previous').onclick = () => { state.offset=Math.max(0,state.offset-Number($('limit').value)); refresh(true); };
$('next').onclick = () => { state.offset+=Number($('limit').value); refresh(true); };
$('limit').onchange = () => { state.offset=0; refresh(true); };
$('wholeGraph').onchange=()=>{state.offset=0;state.revision=null;refresh(true);};
$('perspective').onchange = graphControl(decorate);
$('labels').onchange = graphControl(async() => {await decorate();if ($('followGraph').checked) await requestedLayout();});
$('edgeLabels').onchange = graphControl(decorate);
$('layout').onchange = graphControl(() => requestedLayout({seed:true}));
$('relayout').onclick = graphControl(() => requestedLayout({seed:true}));
$('followGraph').onchange = graphControl(async() => {if ($('followGraph').checked) await requestedLayout();});
$('fit').onclick = graphControl(() => MemoryGraphLayout.fit(cy,cy.elements(':visible')));
$('neighbors').onclick = () => {
  if (state.selected?.isNode()) {
    state.root=state.selected.data('attributes').graph_id;
    state.offset=0;
    refresh(true);
  }
};
$('pinPath').onclick=graphControl(()=>{state.pathStart=state.selected?.id();$('pathInfo').textContent='Path start: '+(state.selected?.data('label')||'none');});$('findPath').onclick=graphControl(async()=>{await graphStage('Finding path');cy.elements().removeClass('path');if(!state.pathStart||!state.selected?.isNode()||!cy.getElementById(state.pathStart).length){$('pathInfo').textContent='Select and set a path start in this slice first.';return;}const result=cy.elements().dijkstra({root:cy.getElementById(state.pathStart),directed:false}),distance=result.distanceTo(state.selected);if(Number.isFinite(distance)){result.pathTo(state.selected).addClass('path');$('pathInfo').textContent=`${distance} hops · undirected shortest path within loaded slice`;}else $('pathInfo').textContent='No path in loaded slice; expand scope to investigate.';});
$('record').onclick=()=>{state.recording=!state.recording;state.recordingSince=state.recording?Date.now()/1000:Infinity;$('record').classList.toggle('recording',state.recording);$('record').textContent=state.recording?'Ⅱ Pause recording':'● Record highlight';};
$('reset').onclick = graphControl(async() => {
  state.recorded=[];
  state.selectedActivity=null;
  state.selectedSession=null;
  state.recordingSince=state.recording?Date.now()/1000:Infinity;
  cy.elements().removeClass('changed');
  await applyHighlight();
});
$('loadHistory').onclick = graphControl(async() => {state.selectedActivity=null;state.selectedSession=null;state.recorded=[...state.history];await applyHighlight();});
$('showAccumulated').onclick = graphControl(async() => {state.selectedActivity=null;state.selectedSession=null;await applyHighlight();});
for (const key of ['chat','session','agent']) $(key).onchange = graphControl(async() => {
  state.selectedActivity=null;
  state.selectedSession=null;
  updateSessionOptions();
  await applyHighlight();
});
$('onlyTouched').onchange=graphControl(applyHighlight);
$('olderChanges').onclick=graphControl(()=>pollEvents(true));

// Pointer interaction opts out of following growth; programmatic fit/layout does not.
let pointerStart=null;
$('cy').addEventListener('wheel',()=>{
  if(!state.replay || state.replay.index<0)backgroundLayout.cancel();
  MemoryGraphLayout.stop(cy);$('followGraph').checked=false;
},{passive:true});
$('cy').addEventListener('pointerdown',event=>{MemoryGraphLayout.stop(cy);pointerStart={x:event.clientX,y:event.clientY};});
$('cy').addEventListener('pointermove',event=>{
  if (pointerStart && !pointerStart.dragging && Math.hypot(event.clientX-pointerStart.x,event.clientY-pointerStart.y)>5) {
    pointerStart.dragging=true;backgroundLayout.cancel();$('followGraph').checked=false;
  }
});
window.addEventListener('pointerup',()=>{pointerStart=null;});
window.addEventListener('pointercancel',()=>{pointerStart=null;});
window.addEventListener('blur',()=>{pointerStart=null;});
cy.on('mouseover','node,edge',event=>{
  event.target.addClass('hovered');
  $('cy').title=event.target.data('label');
});
cy.on('mouseout','node,edge',event=>{event.target.removeClass('hovered');$('cy').title='';});
let resizeTimer;
const graphResize=new ResizeObserver(()=>{
  const bounds=$('cy').getBoundingClientRect();
  if (bounds.width<1 || bounds.height<1) return;
  cy.resize();
  clearTimeout(resizeTimer);
  resizeTimer=setTimeout(()=>{
    // Refresh will arrange the graph itself; resize events must not build a queue.
    if(state.busy)return;
    if (state.pendingLayout) void graphAction(()=>requestedLayout({seed:true}));
    else if ($('followGraph').checked) void graphAction(()=>requestedLayout({runLayout:false}));
  },150);
});
graphResize.observe($('cy'));
document.querySelectorAll('.tab').forEach(button => button.onclick=guarded(async () => {
  state.view=button.dataset.view;
  document.querySelectorAll('.tab').forEach(b=>b.classList.toggle('active',b===button));
  for (const view of ['graph','tables','query']) $(view+'View').classList.toggle('hidden',view!==state.view);
  if (state.view==='graph') {
    cy.resize();
    if (state.pendingLayout) await graphAction(()=>requestedLayout({seed:true}));
  }
  if (state.view==='tables') await loadTable();
}));
$('tableSelect').onchange=guarded(async()=>{state.tableOffset=0;await loadTable();});
$('tableNext').onclick=guarded(async()=>{state.tableOffset+=200;await loadTable();});
$('tablePrevious').onclick=guarded(async()=>{state.tableOffset=Math.max(0,state.tableOffset-200);await loadTable();});
$('runQuery').onclick=guarded(async()=>{
  const started=performance.now();
  const result=await api('query',{sql:$('sql').value});
  table($('queryData'),result.rows);
  $('queryStatus').textContent=`${result.rows.length} rows${result.has_more?' · more available':''} · ${Math.round(performance.now()-started)} ms`;
});
$('export').onclick=()=>download('evomneme-selection.json',JSON.stringify({selection:filters(),snapshot:state.snapshot,recorded:state.recorded.filter(matches),note:'Local export may contain host knowledge.'},null,2),'application/json');
async function exportPng() {
  const background='#0e1623';
  const graph=await cy.png({bg:background,scale:2,full:true,output:'blob-promise'});
  const bitmap=await createImageBitmap(graph);
  const canvas=document.createElement('canvas');
  try {
    const padX=Math.ceil(bitmap.width*.05),padY=Math.ceil(bitmap.height*.05);
    canvas.width=bitmap.width+2*padX;
    canvas.height=bitmap.height+2*padY;
    const context=canvas.getContext('2d');
    if (!context || !canvas.width || !canvas.height) throw new Error('PNG exceeds the supported canvas size');
    context.fillStyle=background;
    context.fillRect(0,0,canvas.width,canvas.height);
    context.drawImage(bitmap,padX,padY);
    const png=await new Promise((resolve,reject)=>canvas.toBlob(blob=>{
      if (blob) resolve(blob);
      else reject(new Error('PNG export failed; reduce the graph selection size'));
    },'image/png'));
    download('evomneme-graph.png',png,'image/png');
  } finally {
    bitmap.close();
    canvas.width=canvas.height=0;
  }
}
$('png').onclick=graphControl(exportPng);
if(!token)showError(new Error('Open the complete viewer URL printed by the server, including its token.'));
restoreVisualPreferences();
refresh(true);setInterval(()=>{if($('live').checked && !state.busy)refresh();},2000);
