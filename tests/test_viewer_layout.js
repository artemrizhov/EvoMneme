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
  step(0);step(200);
  assert.deepEqual(a.position(),{x:100,y:50});
  assert.equal(animated.zoom(),1.5);
  assert.deepEqual(animated.pan(),{x:50,y:25});
  assert.equal(Number(b.style('opacity')),.5);
  // A new destination starts at the displayed midpoint, cancelling the old one.
  graphLayout.transition(animated,()=>a.position({x:400,y:50}));
  assert.equal(frames.size,1);
  assert.deepEqual(a.position(),{x:100,y:50});
  assert.equal(Number(b.style('opacity')),1);
  step(300);step(500);
  assert.deepEqual(a.position(),{x:250,y:50});
  step(700);
  assert.deepEqual(a.position(),{x:400,y:50});
  assert.equal(frames.size,0);
  graphLayout.transition(animated,()=>a.position({x:800,y:50}));
  step(800);step(1000);graphLayout.stop(animated);
  assert.deepEqual(a.position(),{x:600,y:50});
  assert.equal(frames.size,0,'Pointer interruption must leave no queued frame');
  reduced=true;
  graphLayout.transition(animated,()=>a.position({x:900,y:50}));
  assert.deepEqual(a.position(),{x:900,y:50});
  assert.equal(frames.size,0);
  reduced=false;
  graphLayout.arrange(animated,{name:'grid',width:900,height:600,fit:false});
  assert.deepEqual(a.position(),{x:900,y:50},'All layout stages must restore the initial frame');
  step(1100);step(1500);
  assertSeparated(animated);
  graphLayout.transition(animated,()=>a.position({x:1500,y:200}));
  step(1600);step(10000);
  assert.deepEqual(a.position(),{x:1500,y:200},'A stalled renderer skips missed frames and finishes immediately');
  assert.equal(frames.size,0,'Slow frames must not create an animation backlog');
} finally {graphLayout.stop(animated);animated.destroy();}

console.log('Graph layout regressions passed: geometry, animated transitions, interruption and reduced motion.');
