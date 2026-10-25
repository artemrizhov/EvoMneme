'use strict';
const $ = id => document.getElementById(id);
const token = new URLSearchParams(location.hash.slice(1)).get('token') || sessionStorage.getItem('evomneme-viewer-token');
if (token) sessionStorage.setItem('evomneme-viewer-token', token);
history.replaceState(null, '', location.pathname);
const state = { snapshot: null, offset: 0, root: '', selected: null, pathStart: null, recording: false,
  recorded: [], history: [], sessions: new Map(), cursors: {}, changes: new Set(), previous: null,
  busy: false, tableOffset: 0, missed: false, view: 'graph', filterKey: '', recordingSince: Infinity, nullField:'',
  selectedActivity:null,pendingLayout:false };
const palette = ['#79b8e8','#86d8b6','#d5a0e8','#f0bf79','#e58e99','#a5b6eb','#c8d889','#88cdd7','#ccab91','#b0a3d4'];
function text(tag, value, className) { const el = document.createElement(tag); el.textContent = String(value ?? ''); if (className) el.className = className; return el; }
function showError(error) { $('error').textContent = error.message || String(error); $('error').classList.remove('hidden'); clearTimeout(showError.timer); showError.timer = setTimeout(() => $('error').classList.add('hidden'), 12000); }
async function api(route, values = {}) { const response = await fetch('/api/' + route, {method:'POST', headers:{'Content-Type':'application/json','X-Viewer-Token':token || ''}, body:JSON.stringify(values)}); const data = await response.json(); if (!response.ok) throw new Error(data.error || response.statusText); return data; }
function guarded(fn) { return (...args) => Promise.resolve().then(() => fn(...args)).catch(showError); }
const cy = cytoscape({container:$('cy'), elements:[], minZoom:.05, maxZoom:5,
  style:[
    {selector:'node',style:{'background-color':'data(color)',label:'data(displayLabel)','font-size':10,'min-zoomed-font-size':7,color:'#becde0','text-outline-color':'#101925','text-outline-width':2,'text-valign':'bottom','text-margin-y':7,width:'data(size)',height:'data(size)','border-width':1,'border-color':'#62768c','text-max-width':130,'text-wrap':'ellipsis'}},
    {selector:'edge',style:{width:1.3,'line-color':'data(color)','target-arrow-color':'data(color)','target-arrow-shape':'triangle','curve-style':'bezier',opacity:.65,label:'data(displayLabel)','font-size':9,'min-zoomed-font-size':7,color:'#b7c8dc','text-rotation':'autorotate','text-background-color':'#111b2b','text-background-opacity':.9}},
    {selector:'.touched',style:{'border-width':5,'border-color':'#f7cd71','line-color':'#f7cd71','target-arrow-color':'#f7cd71',width:4,opacity:1}},
    {selector:'node.touched',style:{width:'data(size)',height:'data(size)'}},
    {selector:'.changed, .recordedChange',style:{'border-color':'#71eab8','border-width':5,'line-color':'#71eab8','target-arrow-color':'#71eab8',opacity:1}},
    {selector:':selected',style:{'border-color':'#fff','border-width':5,'line-color':'#fff','target-arrow-color':'#fff',opacity:1}},
    {selector:'.path',style:{'border-color':'#f0a0ff','border-width':5,'line-color':'#f0a0ff','target-arrow-color':'#f0a0ff',width:4,opacity:1}},
    {selector:'node.path',style:{width:'data(size)',height:'data(size)'}},
    {selector:'.hidden',style:{display:'none'}},
    {selector:'edge:selected, edge:active, edge.hovered',style:{label:'data(label)','min-zoomed-font-size':0}}
  ]});
function filters() {
  const result = {limit:Number($('limit').value), offset:state.offset, root:state.root,
    depth:Number($('depth').value), search:$('search').value.trim(), focus:$('focus').value, aggregate:$('aggregate').value};
  for (const key of ['scope_id','kind','validity','confidence','source_path']) {
    if ($('filter-' + key)) result[key] = $('filter-' + key).value;
  }
  for (const key of ['kind','validity','confidence']) {
    if ($('edge-' + key)) result['edge_' + key] = $('edge-' + key).value;
  }
  if (state.nullField && result[state.nullField]) state.nullField = '';
  result.null_field = state.nullField;
  return result;
}
function renderEdgeFilters(facets) {
  const container = $('edgeFilters');
  const previous = {};
  container.querySelectorAll('select').forEach(el => previous[el.dataset.field] = el.value);
  container.replaceChildren();
  for (const [field, values] of Object.entries(facets)) {
    const label = text('label', 'Relationship ' + field);
    const select = document.createElement('select');
    select.id = 'edge-' + field;
    select.dataset.field = field;
    select.add(new Option('All', ''));
    for (const item of values) {
      if (item.value != null) select.add(new Option(`${item.value} (${item.count})`, item.value));
    }
    if (previous[field] && ![...select.options].some(o => o.value === previous[field])) {
      select.add(new Option(previous[field],previous[field]));
    }
    select.value = previous[field] || '';
    label.append(select);
    container.append(label);
  }
}
function renderFilters(facets) { const container = $('filters'); const previous = {}; container.querySelectorAll('select').forEach(el => previous[el.dataset.field] = el.value); container.replaceChildren(); for (const [field, values] of Object.entries(facets)) { const label = text('label', {scope_id:'Scope / version',kind:'Node type',validity:'Validity',confidence:'Confidence',source_path:'Source file'}[field]); const select = document.createElement('select'); select.id = 'filter-' + field; select.dataset.field = field; select.add(new Option('All', '')); for (const item of values) if (item.value != null) select.add(new Option(`${item.value} (${item.count})`, item.value)); if (previous[field] && ![...select.options].some(o=>o.value===previous[field])) select.add(new Option(previous[field], previous[field])); select.value = previous[field] || ''; label.append(select); container.append(label); } }
function metrics(data) { $('overview').replaceChildren(); for (const [value,label] of [[data.totals.nodes ?? '—','Nodes · whole database'],[data.totals.edges ?? '—','Relationships · whole database'],[data.isolated_total ?? '—','Isolated nodes · whole database'],[data.dangling_total ?? '—','Missing endpoints · whole database'],[data.tables.reduce((a,t)=>a+t.count,0),'Rows · all tables'],[(data.bytes/1048576).toFixed(2)+' MB','SQLite pages · logical size']]) { const metric = text('div','', 'metric'); metric.append(text('strong',typeof value==='number'?value.toLocaleString():value),text('span',label)); $('overview').append(metric); } }
function decorate() {
  const field = $('perspective').value;
  const components = new Map();
  if (field === 'components') cy.elements().components().forEach((c,i) => c.forEach(el => components.set(el.id(),String(i+1))));
  const value = el => field === 'degree' ? String(el.isNode()?el.degree():0)
    : field === 'components' ? components.get(el.id()) : String(el.data('attributes')[field] ?? 'unspecified');
  const values = [...new Set(cy.elements().map(value))].sort();
  const validityColors = {current:'#86d8b6',stale:'#f0bf79',superseded:'#7c8da4'};
  const confidenceColors = {confirmed:'#86d8b6',inferred:'#79b8e8',uncertain:'#e58e99'};
  const colors = new Map(values.map((v,i) => [v,
    (field==='validity'?validityColors[v]:field==='confidence'?confidenceColors[v]:null) || palette[i%palette.length]]));
  cy.batch(() => cy.elements().forEach(el => {
    el.data('color',colors.get(value(el)));
    el.data('displayLabel',(el.isNode()?$('labels').checked:$('edgeLabels').checked)?el.data('label'):'');
    if (el.isNode()) {
      const attrs = el.data('attributes');
      el.data('size',attrs._aggregate ? 22+Math.min(36,Math.log2(attrs.member_count+1)*4) : 14+Math.min(16,Math.log2(el.degree()+1)*4));
    }
  }));
  $('legend').replaceChildren();
  for (const v of values.slice(0,30)) {
    const item = text('span',v,'legend-item'), swatch = text('i','','swatch');
    swatch.style.backgroundColor = colors.get(v);
    item.prepend(swatch);
    $('legend').append(item);
  }
  if (values.length > 30) $('legend').append(text('span',`+${values.length-30} categories`));
}
function layout(options = {}) {
  const bounds=$('cy').getBoundingClientRect();
  if (bounds.width<1 || bounds.height<1) {state.pendingLayout=true;return;}
  state.pendingLayout=false;
  cy.resize();
  MemoryGraphLayout.arrange(cy,{name:$('layout').value,width:bounds.width,height:bounds.height,...options});
}
function signatureMap(data) { return new Map([...data.nodes.map(n=>['n:'+n.graph_id,JSON.stringify(n)]),...data.edges.map(e=>['e:'+e.graph_id,JSON.stringify(e)])]); }
function draw(data, resetLayout, key) {
  const next = signatureMap(data);
  state.changes.clear();
  if (state.previous && state.filterKey === key) {
    const changed = [];
    for (const [id, signature] of next) {
      if (state.previous.get(id) !== signature) {
        state.changes.add(id);
        changed.push(id);
      }
    }
    const removed = [...state.previous.keys()].filter(id => !next.has(id));
    if (changed.length || removed.length) {
      ingest([{source:'snapshot',time:Date.now()/1000, read:[], write:[],
        references:[], changed, removed, ok:true, elapsed_ms:0, returned_rows:0}]);
    } else if (!resetLayout) {
      // Preserve a user's layout, selection and path while the database is unchanged.
      cy.elements().removeClass('changed');
      return;
    }
  }
  state.previous = next;
  state.filterKey = key;
  const oldPositions = new Map(cy.nodes().map(n => [n.id(), n.position()]));
  const oldIds = new Set(cy.elements().map(el=>el.id()));
  const topologyChanged = oldIds.size!==next.size || [...next.keys()].some(id=>!oldIds.has(id));
  const selected = state.selected?.id();
  const ids = new Set(data.nodes.map(n => 'n:' + n.graph_id));
  const old = [...oldPositions.values()];
  const center = old.length ? {x:old.reduce((sum,p)=>sum+p.x,0)/old.length,
    y:old.reduce((sum,p)=>sum+p.y,0)/old.length} : {x:0,y:0};
  let added = 0;
  const nodes = data.nodes.map(n => {
    const id = 'n:' + n.graph_id;
    let position = oldPositions.get(id);
    if (!position) {
      const angle = ++added * 2.4, radius = 50 + 12 * Math.sqrt(added);
      position = {x:center.x+Math.cos(angle)*radius, y:center.y+Math.sin(angle)*radius};
    }
    return {group:'nodes', data:{id,label:String(n.label)+(n._aggregate?` · ${n.member_count} nodes`:''),displayLabel:'',attributes:n,color:palette[0],size:24},position};
  });
  const edges = data.edges.filter(e => ids.has('n:' + e.source) && ids.has('n:' + e.target))
    .map(e => ({group:'edges',data:{id:'e:'+e.graph_id,source:'n:'+e.source,target:'n:'+e.target,
      label:e._aggregate?`${e.member_count} links`:String(e.kind||''),displayLabel:'',attributes:e,color:'#506984'}}));
  cy.batch(() => { cy.elements().remove(); cy.add([...nodes,...edges]); });
  decorate();
  applyHighlight();
  if (!state.selectedActivity) cy.elements().filter(el => state.changes.has(el.id())).addClass('changed');
  if (selected && cy.getElementById(selected).length) {
    state.selected = cy.getElementById(selected);
    state.selected.select();
  } else {
    state.selected = null;
    $('detail').replaceChildren();
    $('selectionActions').classList.add('hidden');
    $('openGroup').classList.add('hidden');
  }
  if (resetLayout || !oldPositions.size || (topologyChanged && $('followGraph').checked)) {
    layout({seed:resetLayout || !oldPositions.size,fit:!state.selectedActivity});
  } else if (added) {
    MemoryGraphLayout.separate(cy.nodes(),new Set(data.nodes.filter(n=>!oldPositions.has('n:'+n.graph_id)).map(n=>'n:'+n.graph_id)));
  }
}
async function refresh(resetLayout=false) {
  if (state.busy) return;
  state.busy = true;
  try {
    const values = filters(), key = JSON.stringify(values), started = performance.now();
    const data = await api('snapshot', values);
    state.snapshot = data;
    metrics(data);
    renderFilters(data.facets);
    renderEdgeFilters(data.edge_facets);
    draw(data, resetLayout, key);
    $('connection').textContent = '● Connected · ' + new Date().toLocaleTimeString();
    $('performance').textContent = `Query ${data.elapsed_ms} ms · refresh ${Math.round(performance.now()-started)} ms`;
    $('sliceInfo').textContent = `${data.nodes.length} nodes · ${data.edges.length} relationships · ${cy.elements().components().length} components in slice`;
    $('pageInfo').textContent = `${data.matched_nodes?state.offset+1:0}–${state.offset+data.nodes.length} / ${data.matched_nodes||0} matching nodes`;
    $('previous').disabled = state.offset === 0;
    $('next').disabled = !data.node_has_more;
    const notices = [];
    if (!data.graph_available) notices.push('No graph projection for this schema. Inspect tables / SQL, or supply --mapping.');
    if (data.node_has_more || state.offset) notices.push('Partial graph: use filters, pagination or neighborhood focus to inspect other segments.');
    if (data.edge_has_more) notices.push('Relationships capped at 2,000 for this slice. Narrow the selection.');
    if (data.boundary_edges) notices.push(`${data.boundary_edges} relationships cross this slice boundary.`);
    if (state.root) notices.push('Neighborhood focus active. Clear filters & focus to return.');
    if (state.nullField) notices.push(`Filtering unspecified ${state.nullField}. Clear filters & focus to remove.`);
    if (data.aggregate) notices.push(`Whole filtered database grouped by ${data.aggregate}: ${data.grouped_members} members. Drill into groups for individual elements and session highlights.`);
    $('notice').textContent = notices.join(' ') || 'Showing the complete graph for this selection. Select elements to inspect evidence and stored claims.';
    renderTables(data.tables);
    if (state.view === 'tables') await loadTable();
    if (state.selected) await inspect(state.selected);
    await pollEvents();
  } catch (error) {
    $('connection').textContent = 'Connection / query error';
    showError(error);
  } finally {
    state.busy = false;
  }
}
function matches(e){return ['chat','session','agent'].every(key=>!$(key).value||e[key]===$(key).value);}
function isObservation(event) {
  return event.source === 'snapshot' || Array.isArray(event.changed);
}
function identityLabel(event, key) {
  const titles = {chat:'chat_title',session:'session_title',agent:'agent_name'};
  const title = event[titles[key]], id = event[key];
  if (title) return `${title}${id ? ' · ' + id : ''}`;
  if (key === 'chat' && event.identity?.chat === false) return 'Chat not reported';
  if (key === 'agent' && event.identity?.agent === false) return `Process ${String(id || '').slice(0,8)}`;
  return id || `${key} not reported`;
}
function selectActivity(event) {
  $('followGraph').checked=false;
  state.selectedActivity = event;
  cy.elements().unselect().removeClass('path changed');
  applyHighlight();
  const highlighted = cy.elements('.touched');
  if (highlighted.length) MemoryGraphLayout.fit(cy,highlighted.union(highlighted.edges().connectedNodes()),60);
}
function references(event){const ids=(event.references||[]).map(r=>r.graph_type?(r.graph_type==='nodes'?'n:':'e:')+r.graph_id:(r.table==='records'?'n:':'e:')+JSON.stringify([r.scope_id,r.id]));return ids.concat(event.changed||[]);}
function applyHighlight() {
  const events = state.selectedActivity ? [state.selectedActivity] : state.recorded.filter(matches);
  const touched = new Set(events.flatMap(references));
  const changed = new Set(events.flatMap(e => e.changed || []));
  cy.batch(() => {
    cy.elements().removeClass('touched hidden recordedChange');
    cy.elements().filter(el => touched.has(el.id())).addClass('touched');
    cy.elements().filter(el => changed.has(el.id())).addClass('recordedChange');
    if ($('onlyTouched').checked) {
      const visible = cy.elements('.touched');
      const context = visible.union(visible.edges().connectedNodes());
      cy.elements().difference(context).addClass('hidden');
    }
  });
  $('highlightCount').textContent = `${touched.size} accumulated IDs · ${cy.elements('.touched').length} visible`;
  const selected = state.selectedActivity;
  $('showAccumulated').classList.toggle('hidden',!selected);
  if (selected) {
    const removed = selected.removed?.length || 0;
    const visible = cy.elements('.touched').length;
    $('highlightCount').textContent = `${touched.size} event IDs · ${visible} visible`;
    $('activitySelection').textContent = touched.size
      ? `Selected activity: ${visible} / ${touched.size} IDs visible${removed?`; ${removed} removed IDs`:''}.`
        + (visible < touched.size ? ' Other IDs are outside this slice, deleted, or grouped.' : '')
      : removed ? `Selected observation: ${removed} IDs were removed from the graph.`
        : 'Selected activity has no exact node/relationship IDs; only table-level access was recorded.';
  } else $('activitySelection').textContent = '';
  renderTimeline();
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
    $(key).replaceChildren(new Option('All '+(key==='chat'?'chats':key+'s'),''));
    for (const [id,label] of [...choices.entries()].sort((a,b)=>a[1].localeCompare(b[1]))) $(key).add(new Option(label,id));
    if (choices.has(selected)) $(key).value = selected;
  }
  $('identityStatus').textContent = identities.length
    ? 'Identity filters contain SQL-call metadata only. Missing chat titles/IDs must be supplied by callers in activity_context; client names come from MCP initialization.'
    : 'Only database observations are available. No traced SQL calls with caller metadata have been loaded; no chat or agent can be identified from these changes.';
}
function ingest(events) {
  for (const event of events) {
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
  updateSessionOptions();
  applyHighlight();
}
async function pollEvents() {
  const data = await api('events',{cursors:state.cursors});
  state.cursors = data.cursors;
  ingest(data.events);
  $('traceStatus').textContent = (data.enabled ? 'Tracing configured' : 'Tracing not configured')
    + (data.has_more ? ' · catching up' : '')
    + (state.missed ? ' · history / identities limited to latest 10,000' : '');
}
function renderTimeline() {
  const list = $('timeline');
  const focused = document.activeElement?._activity;
  list.replaceChildren();
  for (const event of state.history.filter(matches).slice(-35).reverse()) {
    const row = text('button','','event');
    row.type = 'button';
    row._activity = event;
    row.setAttribute('aria-pressed',String(event === state.selectedActivity));
    row.onclick = () => selectActivity(event);
    row.append(text('span',new Date(event.time*1000).toLocaleTimeString(),'time'));
    const details = event.changed
      ? `${event.changed.length} created / modified · ${event.removed.length} removed from snapshot`
      : `${event.read.length?'read '+event.read.join(', '):''} ${event.write.length?'write attempted '+event.write.join(', '):''}`
        + ` · ${event.returned_rows} returned · ${event.elapsed_ms} ms`
        + (event.rolled_back ? ' · open transaction rolled back' : '')
        + (event.durable_effects_possible ? ' · durable effects possible' : '')
        + (event.has_more ? ' · bounded output' : '')
        + (event.references_truncated ? ' · ID limit: table-level only' : '');
    const label = isObservation(event)
      ? 'Database observation · author not reported'
      : [event.client?.name || 'SQL client not reported',identityLabel(event,'chat'),identityLabel(event,'session'),identityLabel(event,'agent')].join(' / ');
    row.append(text('span',`${label} · ${details}${event.ok?'':' · FAILED'}`,event.ok?'':'failed'));
    list.append(row);
    if (focused === event) row.focus({preventScroll:true});
  }
}
function table(container,rows){container.replaceChildren();if(!rows.length){container.append(text('p','No rows.','hint'));return;}const el=document.createElement('table'),thead=document.createElement('thead'),head=document.createElement('tr'),columns=[...new Set(rows.flatMap(Object.keys))];columns.forEach(c=>head.append(text('th',c)));thead.append(head);el.append(thead);const body=document.createElement('tbody');for(const row of rows){const tr=document.createElement('tr');columns.forEach(c=>tr.append(text('td',typeof row[c]==='object'?JSON.stringify(row[c],null,2):row[c])));body.append(tr);}el.append(body);container.append(el);}
function attributes(container,record){const dl=document.createElement('dl');for(const [key,value]of Object.entries(record)){dl.append(text('dt',key),text('dd',typeof value==='object'?JSON.stringify(value,null,2):value));}container.append(dl);}
async function inspect(el) {
  state.selected = el;
  const attrs = el.data('attributes');
  const container = $('detail');
  $('openGroup').classList.add('hidden');
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
  $('selectionHint').textContent = el.isNode() ? 'Stored node and supporting evidence' : 'Stored relationship and supporting evidence';
  $('selectionActions').classList.toggle('hidden',!el.isNode());
  data.rows.forEach(r => attributes(container,r));
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
cy.on('tap','node,edge',event => guarded(inspect)(event.target));
cy.on('dbltap','node',event => {
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
function renderTables(tables){const select=$('tableSelect'),selected=select.value;select.replaceChildren();tables.forEach(t=>select.add(new Option(`${t.name} (${t.count})`,t.name)));if(tables.some(t=>t.name===selected))select.value=selected;}
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
$('perspective').onchange = decorate;
$('labels').onchange = () => {decorate();if ($('followGraph').checked) layout();};
$('edgeLabels').onchange = decorate;
$('layout').onchange = () => layout({seed:true});
$('relayout').onclick = () => layout({seed:true});
$('followGraph').onchange = () => {if ($('followGraph').checked) layout();};
$('fit').onclick = () => MemoryGraphLayout.fit(cy,cy.elements(':visible'));
$('neighbors').onclick = () => {
  if (state.selected?.isNode()) {
    state.root=state.selected.data('attributes').graph_id;
    state.offset=0;
    refresh(true);
  }
};
$('pinPath').onclick=()=>{state.pathStart=state.selected?.id();$('pathInfo').textContent='Path start: '+(state.selected?.data('label')||'none');};$('findPath').onclick=()=>{cy.elements().removeClass('path');if(!state.pathStart||!state.selected?.isNode()||!cy.getElementById(state.pathStart).length){$('pathInfo').textContent='Select and set a path start in this slice first.';return;}const result=cy.elements().dijkstra({root:cy.getElementById(state.pathStart),directed:false}),distance=result.distanceTo(state.selected);if(Number.isFinite(distance)){result.pathTo(state.selected).addClass('path');$('pathInfo').textContent=`${distance} hops · undirected shortest path within loaded slice`;}else $('pathInfo').textContent='No path in loaded slice; expand scope to investigate.';};
$('record').onclick=()=>{state.recording=!state.recording;state.recordingSince=state.recording?Date.now()/1000:Infinity;$('record').classList.toggle('recording',state.recording);$('record').textContent=state.recording?'Ⅱ Pause recording':'● Record highlight';};
$('reset').onclick = () => {
  state.recorded=[];
  state.selectedActivity=null;
  state.recordingSince=state.recording?Date.now()/1000:Infinity;
  cy.elements().removeClass('changed');
  applyHighlight();
};
$('loadHistory').onclick = () => {state.selectedActivity=null;state.recorded=[...state.history];applyHighlight();};
$('showAccumulated').onclick = () => {state.selectedActivity=null;applyHighlight();};
for (const key of ['chat','session','agent']) $(key).onchange = () => {
  state.selectedActivity=null;
  updateSessionOptions();
  applyHighlight();
};
$('onlyTouched').onchange=applyHighlight;

// Pointer interaction opts out of following growth; programmatic fit/layout does not.
let pointerStart=null;
$('cy').addEventListener('wheel',()=>{$('followGraph').checked=false;},{passive:true});
$('cy').addEventListener('pointerdown',event=>{pointerStart={x:event.clientX,y:event.clientY};});
$('cy').addEventListener('pointermove',event=>{
  if (pointerStart && Math.hypot(event.clientX-pointerStart.x,event.clientY-pointerStart.y)>5) $('followGraph').checked=false;
});
window.addEventListener('pointerup',()=>{pointerStart=null;});
window.addEventListener('pointercancel',()=>{pointerStart=null;});
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
    if (state.pendingLayout) layout({seed:true});
    else if ($('followGraph').checked) layout({runLayout:false});
  },150);
});
graphResize.observe($('cy'));
document.querySelectorAll('.tab').forEach(button => button.onclick=guarded(async () => {
  state.view=button.dataset.view;
  document.querySelectorAll('.tab').forEach(b=>b.classList.toggle('active',b===button));
  for (const view of ['graph','tables','query']) $(view+'View').classList.toggle('hidden',view!==state.view);
  if (state.view==='graph') {
    cy.resize();
    if (state.pendingLayout) layout({seed:true});
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
$('png').onclick=guarded(exportPng);
if(!token)showError(new Error('Open the complete viewer URL printed by the server, including its token.'));
refresh(true);setInterval(()=>{if($('live').checked)refresh();},2000);
