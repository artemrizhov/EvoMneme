/* Geometry regressions using real, vendored Cytoscape. No npm dependencies. */
'use strict';
const assert = require('node:assert/strict');
const cytoscape = require('../scripts/viewer/vendor/cytoscape.min.js');
const graphLayout = require('../scripts/viewer/graph-layout.js');

function graph() {
  return cytoscape({headless:true,styleEnabled:true,elements:[],style:[
    {selector:'node',style:{label:'data(label)',width:24,height:24,'font-size':10,
      'text-valign':'bottom','text-margin-y':7,'text-max-width':130,'text-wrap':'ellipsis'}},
    {selector:'edge',style:{width:1}}
  ]});
}

function assertSeparated(cy) {
  const boxes = graphLayout.boxes(cy.nodes());
  for (let i=0;i<boxes.length;i++) for (let j=0;j<i;j++) {
    const a=boxes[i],b=boxes[j];
    const dx=Math.abs(a.x+a.dx-b.x-b.dx),dy=Math.abs(a.y+a.dy-b.y-b.dy);
    assert.ok(dx>=(a.w+b.w)/2 || dy>=(a.h+b.h)/2,
      `Overlapping node/label boxes: ${a.node.id()} and ${b.node.id()}`);
  }
  for (const n of cy.nodes()) assert.ok(Number.isFinite(n.position('x')) && Number.isFinite(n.position('y')));
}

function addBatch(cy,start,end) {
  for (let i=start;i<end;i++) {
    cy.add({data:{id:'n'+i,label:'A long synthetic architecture title '+i},position:{x:0,y:0}});
    if (i) cy.add({data:{id:'e'+i,source:'n'+Math.floor((i-1)/3),target:'n'+i}});
    if (i>4 && i%3===0) cy.add({data:{id:'cross'+i,source:'n'+(i-4),target:'n'+i}});
  }
}

const cy=graph();
try {
  for (const [start,end] of [[0,1],[1,12],[12,35],[35,65]]) {
    addBatch(cy,start,end);
    graphLayout.arrange(cy,{width:1200,height:500,seed:start===0});
    assertSeparated(cy);
  }
  const firstPositions=cy.nodes().map(n=>({...n.position()}));
  const frozen=new Map(cy.nodes().map(n=>[n.id(),{...n.position()}]));
  addBatch(cy,65,70);
  graphLayout.separate(cy.nodes(),new Set(['n65','n66','n67','n68','n69']));
  for (const [id,p] of frozen) assert.deepEqual(cy.getElementById(id).position(),p,'Manual positions must remain unchanged');
  assertSeparated(cy);
  assert.equal(firstPositions.length,65);
} finally {cy.destroy();}

const chain=graph();
try {
  for (let i=0;i<18;i++) chain.add({data:{id:'n'+i,label:'Node '+i},position:{x:0,y:i*110}});
  graphLayout.arrange(chain,{width:1200,height:400,runLayout:false,fit:false});
  let bounds=chain.nodes().boundingBox();
  assert.ok(bounds.w>bounds.h*2,'Portrait graph should rotate to use a landscape viewport');
  assertSeparated(chain);
  graphLayout.arrange(chain,{width:400,height:1200,runLayout:false,fit:false});
  bounds=chain.nodes().boundingBox();
  assert.ok(bounds.h>bounds.w*2,'Landscape graph should rotate to use a portrait viewport');
  assertSeparated(chain);
} finally {chain.destroy();}

const large=graph();
try {
  large.add(Array.from({length:10001},(_,i)=>({data:{id:'large'+i,label:'Large graph node '+i}})));
  graphLayout.arrange(large,{width:1200,height:500,fit:false});
  assert.equal(large.scratch('memory-layout'),'grid-large');
  assert.equal(new Set(large.nodes().map(n=>n.position('x')+','+n.position('y'))).size,10001);
  assertSeparated(large);
} finally {large.destroy();}

// Drive renderer frames explicitly to verify intermediate geometry, cancellation
// and reduced motion without wall-clock sleeps or a browser dependency.
const animated=graph();
try {
  animated.add([{data:{id:'a',label:'A'},position:{x:0,y:0}},
    {data:{id:'b',label:'B'},position:{x:100,y:0}},
    {data:{id:'ab',source:'a',target:'b'}}]);
  const frames=new Map();let nextFrame=0,reduced=false;
  animated.window=()=>({requestAnimationFrame:fn=>{frames.set(++nextFrame,fn);return nextFrame;},
    cancelAnimationFrame:id=>frames.delete(id),matchMedia:()=>({matches:reduced})});
  const step=time=>{const pending=[...frames.values()];frames.clear();pending.forEach(fn=>fn(time));};
  const a=animated.getElementById('a'),b=animated.getElementById('b');
  graphLayout.transition(animated,()=>{
    a.position({x:200,y:100});b.position({x:300,y:100});
    animated.viewport({zoom:2,pan:{x:100,y:50}});
  },{newIds:new Set(['b'])});
  assert.deepEqual(a.position(),{x:0,y:0},'Destination must not flash before animation');
  assert.equal(animated.zoom(),1);
  assert.equal(Number(b.style('opacity')),0);
  let now=0;
  const advance=ms=>{for(let remaining=ms;remaining>0;){const dt=Math.min(16,remaining);now+=dt;step(now);remaining-=dt;}};
  step(now);advance(160);
  assert.ok(a.position('x')>0 && a.position('x')<200);
  const oldMotionAt16ms=200*(1-(1+12*.016)*Math.exp(-12*.016));
  assert.ok(Math.abs(a.position('x')-oldMotionAt16ms)<1e-6,
    '160 ms of wall time must advance geometry by only 16 ms of the original animation');
  assert.ok(animated.zoom()>1 && animated.zoom()<2);
  assert.ok(animated.pan('x')>0 && animated.pan('x')<100);
  assert.ok(Math.abs(Number(b.style('opacity'))-.4)<.001);
  // Retarget to the displayed position itself: movement can continue only if
  // the old velocity survives. A fresh easing transition would stop instantly.
  const current={...a.position()},opacity=Number(b.style('opacity'));
  graphLayout.transition(animated,()=>a.position(current));
  assert.equal(frames.size,1);
  assert.deepEqual(a.position(),current);
  assert.equal(Number(b.style('opacity')),opacity,'Retargeting must preserve the ongoing fade');
  advance(5);
  assert.ok(a.position('x')>current.x,'Retargeting must retain node momentum');
  const turning=a.position('x');
  graphLayout.transition(animated,()=>a.position({x:-300,y:50}));
  advance(5);
  assert.ok(a.position('x')>turning,'Direction changes must decelerate before reversing');
  advance(20000);
  assert.deepEqual(a.position(),{x:-300,y:50});
  assert.equal(Number(b.style('opacity')),1);
  assert.equal(frames.size,0);
  graphLayout.transition(animated,()=>a.position({x:800,y:50}));
  step(now);advance(160);graphLayout.stop(animated);
  const stopped={...a.position()};advance(1000);
  assert.deepEqual(a.position(),stopped);
  assert.equal(frames.size,0,'Pointer interruption must leave no queued frame');
  reduced=true;
  graphLayout.transition(animated,()=>a.position({x:900,y:50}));
  assert.deepEqual(a.position(),{x:900,y:50});
  assert.equal(frames.size,0);
  reduced=false;
  graphLayout.arrange(animated,{name:'grid',width:900,height:600,fit:false});
  assert.deepEqual(a.position(),{x:900,y:50},'All layout stages must restore the initial frame');
  step(now);advance(20000);
  assertSeparated(animated);
  graphLayout.transition(animated,()=>a.position({x:1500,y:200}));
  const beforeStall={...a.position()};
  step(now);now+=10000;step(now);
  assert.ok(Math.abs(a.position('x')-beforeStall.x)<Math.abs(1500-beforeStall.x)*.1,
    'A stalled renderer resumes with a bounded physics step instead of teleporting');
  assert.equal(frames.size,1,'Only one animation loop exists after a stall');
  for(let i=0;i<100;i++)graphLayout.transition(animated,()=>a.position({x:1600+i,y:200}));
  assert.equal(frames.size,1,'Rapid retargeting must not queue animation frames');
  advance(20000);
  assert.deepEqual(a.position(),{x:1699,y:200});
  assert.equal(frames.size,0);
  // Manual Fit interrupts both node and camera inertia, including when the
  // camera was still heading towards a very different layout destination.
  for(const zoom of [.2,4]) {
    graphLayout.transition(animated,()=>{
      a.position({x:a.position('x')+500,y:200});
      animated.viewport({zoom,pan:{x:800,y:-200}});
    });
    step(now);advance(160);
    graphLayout.fit(animated,animated.elements());
    const fitted={zoom:animated.zoom(),pan:{...animated.pan()},position:{...a.position()}};
    assert.equal(frames.size,0,'Fit must cancel the previous animation frame');
    advance(20000);
    assert.deepEqual({zoom:animated.zoom(),pan:{...animated.pan()},position:{...a.position()}},fitted,
      'A previous layout must not change the fitted viewport afterwards');
  }
} finally {graphLayout.stop(animated);animated.destroy();}

const islands=graph();
try {
  islands.add(Array.from({length:7},(_,i)=>({data:{id:'i'+i,label:'Island '+i}})));
  islands.add([{data:{id:'ia',source:'i0',target:'i1'}},{data:{id:'ib',source:'i1',target:'i2'}},
    {data:{id:'ic',source:'i3',target:'i4'}},{data:{id:'id',source:'i4',target:'i5'}}]);
  for(const name of ['grid','circle','concentric','breadthfirst','cose','overview']) {
    graphLayout.arrange(islands,{name:name==='overview'?'cose':name,overview:name==='overview',width:1200,height:600,fit:false,seed:true});
    assertSeparated(islands);
    const groups=[['i0','i1','i2'],['i3','i4','i5'],['i6']].map(ids=>{
      const boxes=graphLayout.boxes(islands.nodes().filter(n=>ids.includes(n.id())));
      return {x1:Math.min(...boxes.map(b=>b.x+b.dx-b.w/2)),x2:Math.max(...boxes.map(b=>b.x+b.dx+b.w/2)),
        y1:Math.min(...boxes.map(b=>b.y+b.dy-b.h/2)),y2:Math.max(...boxes.map(b=>b.y+b.dy+b.h/2))};
    });
    for(let i=0;i<groups.length;i++)for(let j=0;j<i;j++) {
      const a=groups[i],b=groups[j];
      assert.ok(a.x1>=b.x2+80 || b.x1>=a.x2+80 || a.y1>=b.y2+80 || b.y1>=a.y2+80,
        name+' must keep disconnected components in separate islands');
    }
    assert.equal(islands.edges().length,4);
    assert.equal(islands.elements().components().length,3);
  }
} finally {islands.destroy();}

console.log('Graph layout regressions passed: geometry, inertia, disconnected islands and reduced motion.');
