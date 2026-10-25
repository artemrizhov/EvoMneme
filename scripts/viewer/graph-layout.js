/* Viewport-aware layout using only the bundled Cytoscape core. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.MemoryGraphLayout = factory();
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

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

  function orient(nodes, width, height) {
    if (nodes.length<2 || nodes.some(n=>n.locked())) return;
    const items=boxes(nodes);
    const cx=items.reduce((s,b)=>s+b.x,0)/items.length;
    const cy=items.reduce((s,b)=>s+b.y,0)/items.length;
    const score = rotate => {
      let x1=Infinity,y1=Infinity,x2=-Infinity,y2=-Infinity;
      for (const b of items) {
        const x=(rotate?b.y-cy:b.x-cx)+b.dx;
        const y=(rotate?cx-b.x:b.y-cy)+b.dy;
        x1=Math.min(x1,x-b.w/2);x2=Math.max(x2,x+b.w/2);
        y1=Math.min(y1,y-b.h/2);y2=Math.max(y2,y+b.h/2);
      }
      return Math.min(width/Math.max(1,x2-x1),height/Math.max(1,y2-y1));
    };
    // Rotate rigidly, preserving topology and distances instead of stretching nodes.
    if (score(true)>score(false)*1.05) {
      nodes.positions(node => {const p=node.position();return {x:cx+p.y-cy,y:cy+cx-p.x};});
    }
  }

  function fit(cy, elements, padding = 36) {
    if (!elements.length) return;
    // Fitting a tiny initial graph must not magnify every node several-fold.
    cy.fit(elements,padding);
    if (cy.zoom()>1) {cy.zoom(1);cy.center(elements);}
  }

  function arrange(cy, options = {}) {
    const elements=cy.elements(':visible'), nodes=elements.nodes();
    if (!nodes.length) return;
    const width=Math.max(100,options.width || cy.width());
    const height=Math.max(100,options.height || cy.height());
    if (nodes.length>1000) {
      // Full stores can contain tens of thousands of symbols. Keep this overview
      // linear rather than running an O(n²) force simulation or collision pass.
      const cols=Math.max(1,Math.ceil(Math.sqrt(nodes.length*width/height*110/180)));
      nodes.positions((node,i)=>({x:(i%cols)*180,y:Math.floor(i/cols)*110}));
      cy.scratch('memory-layout','grid-large');
      if (options.fit!==false) fit(cy,elements);
      return;
    }
    cy.scratch('memory-layout',options.name || 'cose');
    if (options.runLayout!==false) {
      const common={eles:elements,animate:false,fit:false,padding:36,
        nodeDimensionsIncludeLabels:true,avoidOverlap:true};
      if (options.seed) {
        cy.layout({...common,name:'grid',cols:Math.max(1,Math.ceil(Math.sqrt(nodes.length*width/height))),
          avoidOverlapPadding:28,condense:true}).run();
      }
      cy.layout({...common,name:options.name || 'cose',randomize:false,
        nodeRepulsion:()=>6500,nodeOverlap:24,idealEdgeLength:()=>120,
        componentSpacing:100,gravity:.2,numIter:nodes.length>800?120:nodes.length>250?350:800,minNodeSpacing:28,
        spacingFactor:1.25,cols:Math.max(1,Math.ceil(Math.sqrt(nodes.length*width/height)))}).run();
    }
    orient(nodes,Math.max(1,width-72),Math.max(1,height-72));
    separate(nodes);
    if (options.fit!==false) fit(cy,elements);
  }

  return {arrange,fit,separate,boxes};
});
