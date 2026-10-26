/* Viewport-aware layout using only the bundled Cytoscape core. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.MemoryGraphLayout = factory();
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const transitions = new WeakMap();

  function directionFor(key) {
    let hash=2166136261;
    for(let i=0;i<key.length;i++)hash=Math.imul(hash^key.charCodeAt(i),16777619);
    // Avalanche nearby identities too: sequential IDs must not all choose
    // almost the same angle and gradually form a vertical or horizontal strip.
    hash=Math.imul(hash^(hash>>>16),0x85ebca6b);
    hash=Math.imul(hash^(hash>>>13),0xc2b2ae35);
    hash^=hash>>>16;
    const angle=(hash>>>0)/4294967296*Math.PI*2;
    return {x:Math.cos(angle),y:Math.sin(angle)};
  }

  function placementShape(viewport={}) {
    const ratio=Number.isFinite(viewport.width) && Number.isFinite(viewport.height) && viewport.width>0 && viewport.height>0
      ?viewport.width/viewport.height:1;
    const x=Math.sqrt(ratio);
    return {x,y:1/x};
  }

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

  function vacantPositions(nodes,movable,origin,targets=new Map(),gap=16,viewport={}) {
    const shape=placementShape(viewport);
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
      const size=[b.w,b.h,b.dx,b.dy].join(',');
      let index=cursors.get(size) || 0;
      do {
        const radius=70*Math.sqrt(index),angle=index*2.399963229728653;
        b.x=origin.x+Math.cos(angle)*radius*shape.x;b.y=origin.y+Math.sin(angle)*radius*shape.y;
        index++;
      } while(!free(b));
      cursors.set(size,index);insert(b);
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
            const length=Math.hypot(dx,dy);
            const direction=length>1e-6?{x:dx/length,y:dy/length}
              :directionFor(a.node.id()+'|'+b.node.id());
            // Escape along the line between centers. Coincident nodes get a
            // stable direction derived from their identities, rather than all
            // choosing the same vertical or horizontal axis.
            const distance=(Math.min(overlapX/Math.max(Math.abs(direction.x),1e-12),
              overlapY/Math.max(Math.abs(direction.y),1e-12))+.5)*share;
            if(moveA){a.x+=direction.x*distance;a.y+=direction.y*distance;}
            if(moveB){b.x-=direction.x*distance;b.y-=direction.y*distance;}
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
        const direction=directionFor(b.node.id()),phase=Math.atan2(direction.y,direction.x);
        for(let index=1;!free(b);index++) {
          const radius=Math.max(32,Math.min(b.w,b.h)+gap)*Math.sqrt(index);
          const angle=phase+index*2.399963229728653;
          b.x=origin.x+Math.cos(angle)*radius;b.y=origin.y+Math.sin(angle)*radius;
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

  // Native solvers handle the interiors; component bounds are used only to
  // make room for changed regions without repacking unaffected regions.
  function connectedRegions(elements) {
    const nodes=new Map(elements.nodes().map(n=>[n.id(),n]));
    const adjacent=new Map([...nodes.keys()].map(id=>[id,[]]));
    for(const edge of elements.edges()) {
      const a=edge.data('source'),b=edge.data('target');
      if(!nodes.has(a) || !nodes.has(b))continue;
      adjacent.get(a).push([b,edge]);adjacent.get(b).push([a,edge]);
    }
    const seen=new Set(),regions=[];
    for(const id of nodes.keys()) {
      if(seen.has(id) || !nodes.has(id))continue;
      const stack=[id],members=[],edges=new Map();seen.add(id);
      while(stack.length) {
        const current=stack.pop();members.push(nodes.get(current));
        for(const [other,edge] of adjacent.get(current)) {
          edges.set(edge.id(),edge);
          if(!seen.has(other)){seen.add(other);stack.push(other);}
        }
      }
      regions.push(elements.cy().collection([...members,...edges.values()]));
    }
    return regions;
  }

  function separateRegions(regions,changed,placementOrigin,viewport) {
    const shape=placementShape(viewport);
    const items=regions.map(region=>{
      const members=region.nodes(),bounds=boxes(members);
      const x1=Math.min(...bounds.map(b=>b.x+b.dx-b.w/2)),y1=Math.min(...bounds.map(b=>b.y+b.dy-b.h/2));
      const x2=Math.max(...bounds.map(b=>b.x+b.dx+b.w/2)),y2=Math.max(...bounds.map(b=>b.y+b.dy+b.h/2));
      return {members,x1,y1,x2,y2,movable:members.some(n=>changed.has(n.id())) && !members.some(n=>n.locked())};
    });
    const placed=[],large=[],grid=new Map(),cellSize=256;
    const cells=b=>({x1:Math.floor(b.x1/cellSize),x2:Math.floor(b.x2/cellSize),
      y1:Math.floor(b.y1/cellSize),y2:Math.floor(b.y2/cellSize)});
    const tooLarge=r=>(r.x2-r.x1+1)*(r.y2-r.y1+1)>4096;
    const insert=b=>{
      placed.push(b);const r=cells(b);
      if(tooLarge(r)){large.push(b);return;}
      for(let x=r.x1;x<=r.x2;x++)for(let y=r.y1;y<=r.y2;y++) {
        const key=x+','+y;
        if(!grid.has(key))grid.set(key,[]);
        grid.get(key).push(b);
      }
    };
    const overlaps=b=>{
      const r=cells({x1:b.x1-70,y1:b.y1-70,x2:b.x2+70,y2:b.y2+70});
      const candidates=new Set(tooLarge(r)?placed:large);
      if(!tooLarge(r))for(let x=r.x1;x<=r.x2;x++)for(let y=r.y1;y<=r.y2;y++)
        for(const a of grid.get(x+','+y) || [])candidates.add(a);
      return [...candidates].filter(a=>{
        const gap=a.members.length>1 || b.members.length>1?70:16;
        return a.x1-gap<b.x2 && a.x2+gap>b.x1 && a.y1-gap<b.y2 && a.y2+gap>b.y1;
      });
    };
    items.filter(b=>!b.movable).forEach(insert);
    const moving=items.filter(b=>b.movable).sort((a,b)=>(b.x2-b.x1)*(b.y2-b.y1)-(a.x2-a.x1)*(a.y2-a.y1));
    const spiralCursors=new Map();
    for(const item of moving) {
      const origin={x1:item.x1,y1:item.y1,x2:item.x2,y2:item.y2};
      const center=placementOrigin || {x:0,y:0};
      const centroid=item.members.reduce((s,n)=>{
        const p=n.position();return {x:s.x+p.x/item.members.length,y:s.y+p.y/item.members.length};
      },{x:0,y:0});
      const radial={x:centroid.x-center.x,y:centroid.y-center.y};
      const length=Math.hypot(radial.x,radial.y);
      const fallback=directionFor(item.members[0].id());
      const fallbackLength=Math.hypot(fallback.x*shape.x,fallback.y*shape.y);
      const direction=length>1e-6?{x:radial.x/length,y:radial.y/length}
        :{x:fallback.x*shape.x/fallbackLength,y:fallback.y*shape.y/fallbackLength};
      let blocked=null,collisions;
      if(item.members.length===1 && overlaps(item).length) {
        const p=item.members[0].position(),center=placementOrigin || p;
        const size=[origin.x2-origin.x1,origin.y2-origin.y1,origin.x1-p.x,origin.y1-p.y,center.x,center.y].join(',');
        let index=spiralCursors.get(size) || 0;
        // Avoid group envelopes using the same central spiral as initial
        // placement. Axis-only escape would turn a batch into a vertical queue.
        do {
          const radius=70*Math.sqrt(index),angle=index*2.399963229728653;
          const dx=center.x+Math.cos(angle)*radius*shape.x-p.x,dy=center.y+Math.sin(angle)*radius*shape.y-p.y;
          item.x1=origin.x1+dx;item.x2=origin.x2+dx;
          item.y1=origin.y1+dy;item.y2=origin.y2+dy;
          index++;
        } while(overlaps(item).length);
        spiralCursors.set(size,index);
      }
      // Grow the obstacle envelope on each collision. Every candidate lies
      // outside all obstacles seen so far, so this cannot bounce indefinitely.
      while((collisions=overlaps(item)).length) {
        for(const a of collisions) {
          const gap=a.members.length>1 || item.members.length>1?70:16;
          const b={x1:a.x1-gap,y1:a.y1-gap,x2:a.x2+gap,y2:a.y2+gap};
          blocked=blocked?{x1:Math.min(blocked.x1,b.x1),y1:Math.min(blocked.y1,b.y1),
            x2:Math.max(blocked.x2,b.x2),y2:Math.max(blocked.y2,b.y2)}:b;
        }
        const tx=Math.abs(direction.x)<1e-12?Infinity:(direction.x>0
          ?blocked.x2-origin.x1+1:blocked.x1-origin.x2-1)/direction.x;
        const ty=Math.abs(direction.y)<1e-12?Infinity:(direction.y>0
          ?blocked.y2-origin.y1+1:blocked.y1-origin.y2-1)/direction.y;
        const distance=Math.min(tx,ty),move={x:direction.x*distance,y:direction.y*distance};
        item.x1=origin.x1+move.x;item.x2=origin.x2+move.x;
        item.y1=origin.y1+move.y;item.y2=origin.y2+move.y;
      }
      const dx=item.x1-origin.x1,dy=item.y1-origin.y1;
      if(dx || dy)item.members.positions(n=>{const p=n.position();return {x:p.x+dx,y:p.y+dy};});
      insert(item);
    }
  }

  function arrangeIncremental(cy,elements,options) {
    const nodes=elements.nodes(),newNodes=new Set(options.newNodes || []);
    const before=new Map(nodes.map(n=>[n.id(),{...n.position()}]));
    const changed=new Set([...(options.affected || []),...newNodes]);
    const name=options.name || 'cose';
    if(name==='cose' && !options.overview) {
      const regions=connectedRegions(elements);
      for(const region of regions.filter(r=>r.edges().length && r.nodes().some(n=>changed.has(n.id())))) {
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
        // Existing members need room too when a component grows or reconnects.
        separate(members);
        if(!members.some(n=>n.locked())) {
          const destination=reference.reduce((s,n)=>{
            const p=n.position();return {x:s.x+p.x/reference.length,y:s.y+p.y/reference.length};
          },{x:0,y:0});
          // Preserve the region's location without rotating or squeezing it.
          members.positions(n=>{const p=n.position();return {
            x:p.x+center.x-destination.x,y:p.y+center.y-destination.y};});
        }
      }
      separateRegions(regions,changed,options.placementOrigin,options);
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
