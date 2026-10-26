/* Viewport-aware layout using only the bundled Cytoscape core. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.MemoryGraphLayout = factory();
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const transitions = new WeakMap();

  function targetPositions(cy) {
    const active=transitions.get(cy);
    return new Map(cy.nodes().map(node=>{
      const item=active?.items.get(node.id());
      return [node.id(),{...(item?.node===node?item.target:node.position())}];
    }));
  }

  function stop(cy) {
    const active=transitions.get(cy);
    if (!active) return;
    active.cancel();
    for (const item of active.items.values()) if(item.opacity<1)item.node.removeStyle('opacity');
    transitions.delete(cy);
  }

  // Compute the entire destination synchronously in one batch, then restore the
  // displayed geometry before the renderer paints. All layout stages share one
  // spring motion, including collision correction and viewport fitting.
  function transition(cy, update, options = {}) {
    const win=cy.window();
    if (options.animate===false || !win?.requestAnimationFrame ||
        win.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
      stop(cy);update();
      return;
    }
    const nodes=cy.nodes();
    const from=new Map(nodes.map(n=>[n.id(),{...n.position()}]));
    const viewport={zoom:cy.zoom(),pan:{...cy.pan()}};
    let targets, destination;
    cy.startBatch();
    try {
      update();
      targets=new Map(nodes.map(n=>[n.id(),{...n.position()}]));
      destination={zoom:cy.zoom(),pan:{...cy.pan()}};
      nodes.positions(n=>from.get(n.id()));
      cy.viewport(viewport);
    } finally {cy.endBatch();}
    let active=transitions.get(cy);
    const items=new Map(nodes.map(node=>{
      const old=active?.items.get(node.id());
      const item=old?.node===node ? old : {node,vx:0,vy:0,opacity:options.newIds?.has(node.id())?0:1};
      item.target=targets.get(node.id());
      if(item.opacity<1)node.style('opacity',item.opacity);
      return [node.id(),item];
    }));
    if (active) {active.items=items;active.destination=destination;return;}
    active={items,destination,velocity:{zoom:0,x:0,y:0},last:undefined};
    let frame;
    // Exact critically damped spring integration. Cap simulation time per
    // renderer frame so a stalled tab resumes slowly without a catch-up jump.
    const spring=(value,target,velocity,dt,tolerance=.1)=>{
      const omega=12, offset=value-target, c=velocity+omega*offset, decay=Math.exp(-omega*dt);
      const position=target+(offset+c*dt)*decay;
      const speed=(velocity-omega*c*dt)*decay;
      const settled=Math.abs(position-target)<tolerance && Math.abs(speed)<tolerance*5;
      return settled?[target,0,true]:[position,speed,false];
    };
    const tick=now=>{
      if (cy.destroyed()) {stop(cy);return;}
      const dt=active.last===undefined?0:Math.min(32,Math.max(0,now-active.last))/1000;
      // Geometry runs at one fifth of real time. Keep appearances responsive
      // while retaining the existing spring state when a new target arrives.
      const motionDt=dt/5;
      active.last=now;
      let settled=true;
      cy.batch(()=>{
        for (const item of active.items.values()) {
          const node=item.node;
          if(node.removed())continue;
          if(!node.locked()) {
            const p=node.position();
            const [x,vx,sx]=spring(p.x,item.target.x,item.vx,motionDt);
            const [y,vy,sy]=spring(p.y,item.target.y,item.vy,motionDt);
            item.vx=vx;item.vy=vy;node.position({x,y});
            settled &&= sx && sy;
          } else {item.vx=item.vy=0;}
          if(item.opacity<1) {
            item.opacity=Math.min(1,item.opacity+dt/.4);
            if(item.opacity===1)node.removeStyle('opacity');
            else {node.style('opacity',item.opacity);settled=false;}
          }
        }
        const pan=cy.pan(),velocity=active.velocity,target=active.destination;
        const [zoom,vz,sz]=spring(cy.zoom(),target.zoom,velocity.zoom,motionDt,.00001);
        const [x,vx,sx]=spring(pan.x,target.pan.x,velocity.x,motionDt);
        const [y,vy,sy]=spring(pan.y,target.pan.y,velocity.y,motionDt);
        active.velocity={zoom:vz,x:vx,y:vy};
        cy.viewport({zoom,pan:{x,y}});settled &&= sz && sx && sy;
      });
      if (!settled) frame=win.requestAnimationFrame(tick);
      else transitions.delete(cy);
    };
    active.cancel=()=>win.cancelAnimationFrame(frame);
    transitions.set(cy,active);
    frame=win.requestAnimationFrame(tick);
  }

  function boxes(nodes) {
    return nodes.map(node => {
      const p = node.position();
      const bodyWidth = node.outerWidth(), bodyHeight = node.outerHeight();
      const fontSize = parseFloat(node.style('font-size')) || 10;
      const label = node.style('label');
      const labelWidth = label ? Math.min(parseFloat(node.style('text-max-width')) || 140,
        String(label).length * fontSize * .65) : 0;
      const extraHeight = label ? fontSize * 1.5 + 9 : 0;
      const measured = node.boundingBox({includeLabels:true,includeOverlays:false,includeUnderlays:false});
      const left = Math.min(-Math.max(bodyWidth,labelWidth)/2,measured.x1-p.x);
      const right = Math.max(Math.max(bodyWidth,labelWidth)/2,measured.x2-p.x);
      const top = Math.min(-bodyHeight/2,measured.y1-p.y);
      const bottom = Math.max(bodyHeight/2+extraHeight,measured.y2-p.y);
      return {node,x:p.x,y:p.y,dx:(left+right)/2,dy:(top+bottom)/2,
        w:right-left,h:bottom-top,locked:node.locked()};
    });
  }

  function vacantPositions(nodes,movable,origin,targets=new Map(),gap=16) {
    const items=boxes(nodes);
    for(const item of items) {
      const target=targets.get(item.node.id());
      if(target){item.x=target.x;item.y=target.y;}
    }
    const cellSize=Math.max(32,...items.map(b=>Math.max(b.w,b.h)+gap));
    const occupied=new Map(),result=new Map(),cursors=new Map();
    const insert=b=>{
      const key=Math.floor((b.x+b.dx)/cellSize)+','+Math.floor((b.y+b.dy)/cellSize);
      if(!occupied.has(key))occupied.set(key,[]);
      occupied.get(key).push(b);
    };
    const free=b=>{
      const gx=Math.floor((b.x+b.dx)/cellSize),gy=Math.floor((b.y+b.dy)/cellSize);
      for(let x=gx-1;x<=gx+1;x++)for(let y=gy-1;y<=gy+1;y++) {
        for(const a of occupied.get(x+','+y) || []) {
          if(Math.abs(a.x+a.dx-b.x-b.dx)<(a.w+b.w)/2+gap &&
             Math.abs(a.y+a.dy-b.y-b.dy)<(a.h+b.h)/2+gap)return false;
        }
      }
      return true;
    };
    const canPlace=b=>movable.has(b.node.id()) && !b.locked;
    items.filter(b=>!canPlace(b)).forEach(insert);
    for(const b of items.filter(canPlace)) {
      // Restart from the center on every update, so deleted or relocated
      // nodes leave reusable holes. Share scans for equally sized new nodes
      // within a batch; occupancy can only grow during this call.
      const shape=[b.w,b.h,b.dx,b.dy].join(',');
      let index=cursors.get(shape) || 0;
      do {
        const radius=70*Math.sqrt(index),angle=index*2.399963229728653;
        b.x=origin.x+Math.cos(angle)*radius;b.y=origin.y+Math.sin(angle)*radius;
        index++;
      } while(!free(b));
      cursors.set(shape,index);insert(b);
      result.set(b.node.id(),{x:b.x,y:b.y});
    }
    return result;
  }

  function separate(nodes, movable, gap = 16) {
    const items = boxes(nodes);
    const cellSize = Math.max(32,...items.map(b => Math.max(b.w,b.h)+gap));
    // Spatial hashing keeps collision work local even for thousands of nodes.
    for (let pass=0;pass<40;pass++) {
      const grid = new Map();
      let collisions = 0;
      for (let i=0;i<items.length;i++) {
        const a = items[i], ax=a.x+a.dx, ay=a.y+a.dy;
        const gx=Math.floor(ax/cellSize), gy=Math.floor(ay/cellSize);
        for (let x=gx-1;x<=gx+1;x++) for (let y=gy-1;y<=gy+1;y++) {
          for (const b of grid.get(x+','+y) || []) {
            const dx=a.x+a.dx-b.x-b.dx, dy=a.y+a.dy-b.y-b.dy;
            const overlapX=(a.w+b.w)/2+gap-Math.abs(dx);
            const overlapY=(a.h+b.h)/2+gap-Math.abs(dy);
            if (overlapX<=0 || overlapY<=0) continue;
            const moveA=!a.locked && (!movable || movable.has(a.node.id()));
            const moveB=!b.locked && (!movable || movable.has(b.node.id()));
            if (!moveA && !moveB) continue;
            collisions++;
            const share = moveA && moveB ? .5 : 1;
            if (overlapX<overlapY) {
              const step=(dx<0?-1:1)*(overlapX+.5)*share;
              if (moveA) a.x+=step;
              if (moveB) b.x-=step;
            } else {
              const step=(dy<0?-1:1)*(overlapY+.5)*share;
              if (moveA) a.y+=step;
              if (moveB) b.y-=step;
            }
          }
        }
        const key=Math.floor((a.x+a.dx)/cellSize)+','+Math.floor((a.y+a.dy)/cellSize);
        if (!grid.has(key)) grid.set(key,[]);
        grid.get(key).push(a);
      }
      if (!collisions) break;
    }
    // Relaxation can stop with residual collisions in a dense cluster. Place only
    // those residual boxes into nearby free space rather than leaving overlaps.
    const occupied=new Map();
    const keyFor=b => Math.floor((b.x+b.dx)/cellSize)+','+Math.floor((b.y+b.dy)/cellSize);
    const insert=b => {
      const key=keyFor(b);
      if (!occupied.has(key)) occupied.set(key,[]);
      occupied.get(key).push(b);
    };
    const free=b => {
      const gx=Math.floor((b.x+b.dx)/cellSize),gy=Math.floor((b.y+b.dy)/cellSize);
      for (let x=gx-1;x<=gx+1;x++) for (let y=gy-1;y<=gy+1;y++) {
        for (const a of occupied.get(x+','+y) || []) {
          if (Math.abs(a.x+a.dx-b.x-b.dx)<(a.w+b.w)/2+gap &&
              Math.abs(a.y+a.dy-b.y-b.dy)<(a.h+b.h)/2+gap) return false;
        }
      }
      return true;
    };
    const canMove=b => !b.locked && (!movable || movable.has(b.node.id()));
    items.filter(b=>!canMove(b)).forEach(insert);
    for (const b of items.filter(canMove)) {
      if (!free(b)) {
        const origin={x:b.x,y:b.y};
        let placed=false;
        for (let ring=1;ring<=items.length && !placed;ring++) {
          for (let x=-ring;x<=ring && !placed;x++) for (let y=-ring;y<=ring && !placed;y++) {
            if (Math.abs(x)!==ring && Math.abs(y)!==ring) continue;
            b.x=origin.x+x*(b.w+gap+1);
            b.y=origin.y+y*(b.h+gap+1);
            placed=free(b);
          }
        }
      }
      insert(b);
    }
    const positions = new Map(items.map(b => [b.node.id(),{x:b.x,y:b.y}]));
    nodes.positions(node => positions.get(node.id()));
  }

  function fit(cy, elements, padding = 36) {
    // An explicit fit owns the viewport immediately; an old spring must not
    // pull it back towards a layout destination on the next renderer frame.
    stop(cy);
    fitViewport(cy,elements,padding);
  }

  function fitViewport(cy, elements, padding = 36) {
    if (!elements.length) return;
    // Fitting a tiny initial graph must not magnify every node several-fold.
    cy.fit(elements,padding);
    if (cy.zoom()>1) {cy.zoom(1);cy.center(elements);}
  }

  function arrangeNow(cy, options = {}) {
    const elements=cy.elements(':visible').not('.replayRemoved'), nodes=elements.nodes();
    if (!nodes.length) return;
    const width=Math.max(100,options.width || cy.width());
    const height=Math.max(100,options.height || cy.height());
    if(options.incremental) {
      arrangeIncremental(cy,elements,options);
      if(options.fit!==false)fitViewport(cy,elements);
      return;
    }
    // Let Cytoscape place the complete visible graph, including components.
    // Automatic updates must not rotate or repack its result afterwards.
    if (options.overview || nodes.length>10000) {
      // Full stores can contain tens of thousands of symbols. Keep this overview
      // linear rather than running an O(n²) force simulation or collision pass.
      const cols=Math.max(1,Math.ceil(Math.sqrt(nodes.length*width/height*110/180)));
      if(options.runLayout!==false)cy.layout({name:'grid',eles:elements,animate:false,fit:false,cols,
        avoidOverlap:false,boundingBox:{x1:0,y1:0,w:Math.max(width,cols*180),
          h:Math.max(height,Math.ceil(nodes.length/cols)*110)}}).run();
      cy.scratch('memory-layout',options.overview?'grid-overview':'grid-large');
      if (options.fit!==false) fitViewport(cy,elements);
      return;
    }
    cy.scratch('memory-layout',options.name || 'cose');
    if (options.runLayout!==false) {
      const common={eles:elements,animate:false,fit:false,padding:36,boundingBox:{x1:0,y1:0,w:width,h:height},
        nodeDimensionsIncludeLabels:true,avoidOverlap:true};
      if (options.seed) {
        cy.layout({...common,name:'grid',cols:Math.max(1,Math.ceil(Math.sqrt(nodes.length*width/height))),
          avoidOverlapPadding:28,condense:true}).run();
      }
      cy.layout({...common,name:options.name || 'cose',randomize:false,
        nodeRepulsion:()=>6500,nodeOverlap:24,idealEdgeLength:()=>120,
        componentSpacing:100,gravity:.2,numIter:nodes.length>800?120:nodes.length>250?350:800,minNodeSpacing:28,
        // Cytoscape's spacing transform expects a layout position for every
        // node; locked nodes have none in grid layouts and can produce NaNs.
        spacingFactor:nodes.some(n=>n.locked())?1:1.25,
        cols:Math.max(1,Math.ceil(Math.sqrt(nodes.length*width/height)))}).run();
    }
    if (options.fit!==false) fitViewport(cy,elements);
  }

  function arrange(cy, options = {}) {
    const targets=options.incremental || options.runLayout===false?targetPositions(cy):null;
    transition(cy,()=>{
      if(targets)cy.nodes().positions(n=>targets.get(n.id()));
      arrangeNow(cy,options);
    },options);
  }

  // Traverse only connected regions touched by a topology change. Each is
  // solved natively; there is no shelf packing or rotation of other regions.
  function changedRegions(elements,changed) {
    const nodes=new Map(elements.nodes().map(n=>[n.id(),n]));
    const adjacent=new Map([...nodes.keys()].map(id=>[id,[]]));
    for(const edge of elements.edges()) {
      const a=edge.data('source'),b=edge.data('target');
      if(!nodes.has(a) || !nodes.has(b))continue;
      adjacent.get(a).push([b,edge]);adjacent.get(b).push([a,edge]);
    }
    const seen=new Set(),regions=[];
    for(const id of changed) {
      if(seen.has(id) || !nodes.has(id))continue;
      const stack=[id],members=[],edges=new Map();seen.add(id);
      while(stack.length) {
        const current=stack.pop();members.push(nodes.get(current));
        for(const [other,edge] of adjacent.get(current)) {
          edges.set(edge.id(),edge);
          if(!seen.has(other)){seen.add(other);stack.push(other);}
        }
      }
      if(edges.size)regions.push(elements.cy().collection([...members,...edges.values()]));
    }
    return regions;
  }

  function arrangeIncremental(cy,elements,options) {
    const nodes=elements.nodes(),newNodes=new Set(options.newNodes || []);
    const before=new Map(nodes.map(n=>[n.id(),{...n.position()}]));
    const changed=new Set([...(options.affected || []),...newNodes]);
    const name=options.name || 'cose';
    if(name==='cose' && !options.overview) {
      for(const region of changedRegions(elements,changed)) {
        const members=region.nodes();
        const anchors=members.filter(n=>!newNodes.has(n.id()));
        const reference=anchors.length?anchors:members;
        const center=reference.reduce((s,n)=>{
          const p=before.get(n.id());return {x:s.x+p.x/reference.length,y:s.y+p.y/reference.length};
        },{x:0,y:0});
        // Allow the entire connected structure to settle. Artificially locking
        // its outer nodes or clipping every step prevents new links from forming
        // a coherent layout after the nodes were initially unconnected.
        cy.layout({name:'cose',eles:region,animate:false,fit:false,randomize:false,
          nodeDimensionsIncludeLabels:true,nodeRepulsion:()=>6500,nodeOverlap:24,
          idealEdgeLength:()=>120,componentSpacing:100,gravity:.2,
          numIter:members.length>800?120:350,initialTemp:200,minTemp:1,coolingFactor:.99}).run();
        if(!members.some(n=>n.locked())) {
          const destination=reference.reduce((s,n)=>{
            const p=n.position();return {x:s.x+p.x/reference.length,y:s.y+p.y/reference.length};
          },{x:0,y:0});
          // Preserve the region's location without rotating or squeezing it.
          members.positions(n=>{const p=n.position();return {
            x:p.x+center.x-destination.x,y:p.y+center.y-destination.y};});
        }
      }
    }
    // Discrete layouts retain their slots on automatic updates. Only new
    // nodes need a vacant position; explicit Relayout still runs the full solver.
    if(newNodes.size)separate(nodes,newNodes);
    cy.scratch('memory-layout',options.overview?'grid-overview':nodes.length>10000?'grid-large':name);
  }

  function createWorkerLayout(createWorker, timeout=45000) {
    let worker,pending,serial=0;
    function cancel() {
      serial++;
      if(worker)worker.terminate();
      worker=null;
      if(pending){clearTimeout(pending.timer);pending.resolve(false);pending=null;}
    }
    async function arrangeAsync(cy,options={},beforeApply=null) {
      // A replacement request cancels outstanding computation rather than
      // building an unbounded queue or applying an obsolete destination.
      if(pending)cancel();
      if(!worker)worker=createWorker();
      const targets=options.incremental || options.runLayout===false?targetPositions(cy):null;
      const id=++serial,elements=cy.elements(':visible').not('.replayRemoved').map(el=>{
        if(el.isEdge())return {group:'edges',data:{id:el.id(),source:el.data('source'),target:el.data('target')}};
        const style={};
        for(const key of ['width','height','border-width','padding','label','font-size','text-valign',
          'text-halign','text-margin-x','text-margin-y','text-max-width','text-wrap'])style[key]=el.style(key);
        return {group:'nodes',data:{id:el.id()},position:{...(targets?.get(el.id()) || el.position())},locked:el.locked(),style};
      });
      const result=await new Promise((resolve,reject)=>{
        const fail=message=>{
          if(!pending || pending.id!==id)return;
          clearTimeout(pending.timer);pending=null;worker.terminate();worker=null;
          reject(new Error(message));
        };
        pending={id,resolve,timer:setTimeout(()=>fail('Background layout timed out'),timeout)};
        worker.onmessage=event=>{
          if(!pending || event.data.id!==pending.id)return;
          if(event.data.error){fail(event.data.error);return;}
          clearTimeout(pending.timer);pending=null;resolve(event.data);
        };
        worker.onerror=event=>{event.preventDefault?.();fail(event.message || 'Background layout worker failed');};
        worker.onmessageerror=()=>fail('Background layout response could not be decoded');
        try {
          const {newIds,...settings}=options;
          worker.postMessage({id,elements,options:settings});
        } catch(error) {fail(error.message);}
      });
      if(!result || cy.destroyed() || id!==serial)return false;
      if(beforeApply && await beforeApply()===false)return false;
      if(cy.destroyed() || id!==serial)return false;
      const positions=new Map(result.positions);
      transition(cy,()=>{
        cy.nodes().positions(n=>positions.get(n.id()) || n.position());
        cy.scratch('memory-layout',result.layout);
        if(options.fit!==false)fitViewport(cy,cy.elements(':visible').not('.replayRemoved'));
      },options);
      cy.emit('memorylayoutprogress',[{id,progress:false,update:1}]);
      return true;
    }
    return {arrange:arrangeAsync,cancel};
  }

  return {arrange,fit,separate,boxes,vacantPositions,transition,stop,targetPositions,createWorkerLayout};
});
