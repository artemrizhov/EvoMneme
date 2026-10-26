/* Viewport-aware layout using only the bundled Cytoscape core. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.MemoryGraphLayout = factory();
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const transitions = new WeakMap();

  function runForce(cy,options) {
    const solver=cy.layout(options);
    // The bundled CoSE calls components() during initialization. Its general
    // collection traversal is expensive on large connected graphs, independently
    // of the iteration count. Supply the same components from our linear walk
    // on this solver-owned collection; leave Cytoscape's global prototype alone.
    const components=connectedRegions(solver.options.eles);
    solver.options.eles.components=()=>components;
    solver.run();
  }

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

  function layoutElements(cy) {
    const elements=cy.elements().not('.replayRemoved');
    // :visible also excludes opacity zero. New nodes start there while fading
    // in, but their edges can already be visible. Opacity is presentation, not
    // graph membership; explicit display/visibility filters still apply.
    const shown=el=>el.takesUpSpace() && el.style('visibility')!=='hidden';
    const nodes=elements.nodes().filter(n=>shown(n) && !n.ancestors().some(p=>p.style('visibility')==='hidden'));
    const ids=new Set(nodes.map(n=>n.id()));
    const edges=elements.edges().filter(e=>shown(e) && ids.has(e.data('source')) && ids.has(e.data('target')));
    return nodes.union(edges);
  }

  function stop(cy) {
    const active=transitions.get(cy);
    if (!active) return;
    for(const item of active.items.values()) {
      item.node.stop(true,false);
      if(item.fadeEnd)item.node.removeStyle('opacity');
    }
    if(active.viewport)cy.stop(true,false);
    transitions.delete(cy);
  }

  // Compute a destination in one batch, restore the displayed frame, and let
  // Cytoscape own interpolation and its renderer animation loop.
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
    let targets,destination;
    cy.startBatch();
    try {
      update();
      targets=new Map(nodes.map(n=>[n.id(),{...n.position()}]));
      destination={zoom:cy.zoom(),pan:{...cy.pan()}};
      nodes.positions(n=>from.get(n.id()));
      cy.viewport(viewport);
    } finally {cy.endBatch();}

    const active=transitions.get(cy) || {items:new Map(),viewport:null};
    transitions.set(cy,active);
    const duration=options.duration ?? 5000,easing='ease-out-cubic';
    const samePosition=(a,b)=>Math.abs(a.x-b.x)<1e-6 && Math.abs(a.y-b.y)<1e-6;
    const sameViewport=(a,b)=>Math.abs(a.zoom-b.zoom)<1e-9 && samePosition(a.pan,b.pan);
    const retire=()=>{
      if(!active.items.size && !active.viewport && transitions.get(cy)===active)transitions.delete(cy);
    };
    const retireItem=item=>{
      if(!item.motion && !item.fade && active.items.get(item.node.id())===item)
        active.items.delete(item.node.id());
      retire();
    };
    for(const [id,item] of active.items) {
      if(item.node.removed() || cy.getElementById(id)!==item.node) {
        item.node.stop(true,false);
        if(item.fadeEnd)item.node.removeStyle('opacity');
        active.items.delete(id);
      }
    }
    for(const node of nodes) {
      const id=node.id(),target=targets.get(id),previous=active.items.get(id);
      // Unrelated nodes keep their existing native transition and its end time.
      if(previous && samePosition(previous.target,target))continue;
      const fadeEnd=previous?.fadeEnd || (options.newIds?.has(id)?Date.now()+400:0);
      node.stop(true,false); // Clear both current animations and the queue.
      if(fadeEnd && !previous)node.style('opacity',0);
      const item={node,target,fadeEnd,motion:null,fade:null};
      active.items.set(id,item);
      if(!node.locked() && !samePosition(from.get(id),target)) {
        const motion=node.animation({position:target,duration,easing,queue:false});
        item.motion=motion;
        motion.promise().then(()=>{
          if(active.items.get(id)!==item || item.motion!==motion)return;
          item.motion=null;retireItem(item);
        });
        motion.play();
      }
      if(fadeEnd>Date.now()) {
        const fade=node.animation({style:{opacity:1},duration:fadeEnd-Date.now(),easing:'linear',queue:false});
        item.fade=fade;
        fade.promise().then(()=>{
          if(active.items.get(id)!==item || item.fade!==fade)return;
          item.fade=null;item.fadeEnd=0;node.removeStyle('opacity');retireItem(item);
        });
        fade.play();
      } else if(fadeEnd) {node.removeStyle('opacity');item.fadeEnd=0;}
      retireItem(item);
    }
    if(!active.viewport || !sameViewport(active.viewport.target,destination)) {
      cy.stop(true,false);
      active.viewport=null;
      if(!sameViewport(viewport,destination)) {
        const animation=cy.animation({...destination,duration,easing,queue:false});
        const entry={animation,target:destination};active.viewport=entry;
        animation.promise().then(()=>{
          if(active.viewport!==entry)return;
          active.viewport=null;retire();
        });
        animation.play();
      }
    }
    // retireItem may have temporarily emptied the map while constructing it.
    if(active.items.size || active.viewport)transitions.set(cy,active);
    else retire();
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
    const elements=layoutElements(cy), nodes=elements.nodes();
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
      const largeForce=(options.name || 'cose')==='cose' && nodes.length>800;
      const common={eles:elements,animate:false,fit:false,padding:36,
        boundingBox:largeForce?undefined:{x1:0,y1:0,w:width,h:height},
        nodeDimensionsIncludeLabels:true,avoidOverlap:true};
      if (options.seed) {
        const cols=Math.max(1,Math.ceil(Math.sqrt(nodes.length*width/height)));
        cy.layout({...common,name:'grid',cols,
          boundingBox:largeForce?{x1:0,y1:0,w:Math.max(width,cols*180),
            h:Math.max(height,Math.ceil(nodes.length/cols)*110)}:common.boundingBox,
          avoidOverlapPadding:28,condense:true}).run();
      }
      const settings={...common,name:options.name || 'cose',randomize:false,
        nodeRepulsion:()=>6500,nodeOverlap:24,idealEdgeLength:()=>120,
        componentSpacing:100,gravity:.2,numIter:350,minNodeSpacing:28,
        ...(nodes.length>800?{initialTemp:200,coolingFactor:.99}:{}),
        // Cytoscape's spacing transform expects a layout position for every
        // node; locked nodes have none in grid layouts and can produce NaNs.
        spacingFactor:largeForce || nodes.some(n=>n.locked())?1:1.25,
        cols:Math.max(1,Math.ceil(Math.sqrt(nodes.length*width/height)))};
      if(settings.name==='cose')runForce(cy,settings);
      else cy.layout(settings).run();
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
    const mergeBounds=(a,b)=>!a?b && {...b}:!b?{...a}:{
      x1:Math.min(a.x1,b.x1),y1:Math.min(a.y1,b.y1),x2:Math.max(a.x2,b.x2),y2:Math.max(a.y2,b.y2)};
    let occupiedBounds=null;
    const cells=b=>({x1:Math.floor(b.x1/cellSize),x2:Math.floor(b.x2/cellSize),
      y1:Math.floor(b.y1/cellSize),y2:Math.floor(b.y2/cellSize)});
    const tooLarge=r=>(r.x2-r.x1+1)*(r.y2-r.y1+1)>4096;
    const insert=b=>{
      occupiedBounds=mergeBounds(occupiedBounds,b);
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
    // Include not-yet-placed changed regions in the overall footprint too.
    // Copy bounds so later translations cannot mutate these suffix envelopes.
    const remaining=Array(moving.length+1).fill(null);
    for(let i=moving.length-1;i>=0;i--)remaining[i]=mergeBounds(moving[i],remaining[i+1]);
    const spiralCursors=new Map();
    for(let movingIndex=0;movingIndex<moving.length;movingIndex++) {
      const item=moving[movingIndex];
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
      const others=mergeBounds(occupiedBounds,remaining[movingIndex+1]);
      if(item.members.length>1 && others && viewport?.width>72 && viewport?.height>72) {
        const vw=viewport.width-72,vh=viewport.height-72;
        const score=b=>{
          const bounds=mergeBounds(others,b),w=(bounds.x2-bounds.x1)/vw,h=(bounds.y2-bounds.y1)/vh;
          const dx=(b.x1-origin.x1)/vw,dy=(b.y1-origin.y1)/vh;
          // Uniform fit is limited by the larger normalized dimension. Penalize
          // wasted area and travel as well, rather than stretching a group.
          return Math.max(w,h)**2+.03*w*h+.08*(dx*dx+dy*dy);
        };
        let best={...item},bestScore=score(best);
        const original={...item,...origin},originalFree=!overlaps(original).length;
        const originalScore=score(original);
        if(originalFree && originalScore<bestScore){best=original;bestScore=originalScore;}
        const width=origin.x2-origin.x1,height=origin.y2-origin.y1;
        const consider=(x,y)=>{
          const candidate={...item,x1:x-width/2,x2:x+width/2,y1:y-height/2,y2:y+height/2};
          const value=score(candidate);
          if(value<bestScore && !overlaps(candidate).length){best=candidate;bestScore=value;}
        };
        // Search around the current occupied graph, not the original spawn
        // ellipse. Test both interior gaps and its outer neighbourhood.
        const cx=(others.x1+others.x2)/2,cy=(others.y1+others.y2)/2;
        const ow=(others.x2-others.x1)/shape.x,oh=(others.y2-others.y1)/shape.y;
        const step=Math.max(70,Math.min(ow,oh)/6);
        const outer=.65*Math.max(ow,oh,width/shape.x,height/shape.y,140);
        const phase=Math.atan2(fallback.y,fallback.x);
        consider(cx,cy);
        for(let i=1;i<=96;i++) {
          const angle=phase+i*2.399963229728653,radius=step*Math.sqrt(i);
          consider(cx+Math.cos(angle)*radius*shape.x,cy+Math.sin(angle)*radius*shape.y);
        }
        for(let i=1;i<=48;i++) {
          const angle=phase+i*2.399963229728653,radius=outer*Math.sqrt(i/48);
          consider(cx+Math.cos(angle)*radius*shape.x,cy+Math.sin(angle)*radius*shape.y);
        }
        // Keep an already free location unless the improvement is material.
        // Small edits must not alternate between nearly equivalent positions.
        if(originalFree && bestScore>originalScore*.94)best=original;
        item.x1=best.x1;item.x2=best.x2;item.y1=best.y1;item.y2=best.y2;
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
        runForce(cy,{name:'cose',eles:region,animate:false,fit:false,randomize:false,
          nodeDimensionsIncludeLabels:true,nodeRepulsion:()=>6500,nodeOverlap:24,
          idealEdgeLength:()=>120,componentSpacing:100,gravity:.2,
          numIter:350,initialTemp:200,minTemp:1,coolingFactor:.99});
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

  function createWorkerLayout(createWorker, timeout=30*60*1000) {
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
      const id=++serial,elements=layoutElements(cy).map(el=>{
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
        if(options.fit!==false)fitViewport(cy,layoutElements(cy));
      },options);
      cy.emit('memorylayoutprogress',[{id,progress:false,update:1}]);
      return true;
    }
    return {arrange:arrangeAsync,cancel};
  }

  return {arrange,fit,separate,boxes,vacantPositions,transition,stop,targetPositions,layoutElements,createWorkerLayout};
});
