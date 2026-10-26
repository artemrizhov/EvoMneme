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
    for(const n of cy.nodes())assert.ok(Number.isFinite(n.position('x')) && Number.isFinite(n.position('y')));
  }
  graphLayout.separate(cy.nodes());
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
  const positions=chain.nodes().map(n=>({...n.position()}));
  graphLayout.arrange(chain,{width:1200,height:400,runLayout:false,fit:false});
  assert.deepEqual(chain.nodes().map(n=>({...n.position()})),positions,
    'Fit-only updates must not rotate or reposition nodes');
  graphLayout.arrange(chain,{width:400,height:1200,runLayout:false,fit:false});
  assert.deepEqual(chain.nodes().map(n=>({...n.position()})),positions);
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
  const oldMotionAt32ms=200*(1-(1+12*.032)*Math.exp(-12*.032));
  assert.ok(Math.abs(a.position('x')-oldMotionAt32ms)<1e-6,
    '160 ms of wall time must advance geometry by 32 ms of the original animation');
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
  graphLayout.transition(animated,()=>a.position({x:1200,y:50}));
  step(now);advance(160);
  assert.ok(a.position('x')<1200);
  graphLayout.arrange(animated,{name:'grid',incremental:true,affected:[],fit:false});
  assert.equal(graphLayout.targetPositions(animated).get('a').x,1200,
    'New calculations must retain the previous destination rather than an intermediate frame');
  graphLayout.arrange(animated,{name:'grid',runLayout:false,fit:false});
  assert.equal(graphLayout.targetPositions(animated).get('a').x,1200,
    'Resize or fit-only updates must not replace a destination with an intermediate frame');
  let workerInput;
  const controller=graphLayout.createWorkerLayout(()=>({postMessage(message){workerInput=message;},terminate(){}}));
  void controller.arrange(animated,{incremental:true,fit:false});
  assert.equal(workerInput.elements.find(n=>n.data.id==='a').position.x,1200,
    'Background calculations must also receive target coordinates');
  controller.cancel();
  graphLayout.stop(animated);
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
  const nativeLayout=islands.layout;
  let nativePositions,calls;
  islands.layout=options=>{
    calls++;
    assert.equal(options.eles.nodes().length,7,'Native layout must receive all components together');
    assert.equal(options.eles.edges().length,4);
    const solver=nativeLayout.call(islands,options),nativeRun=solver.run;
    solver.run=function(){
      const result=nativeRun.call(this);
      nativePositions=islands.nodes().map(n=>({...n.position()}));
      return result;
    };
    return solver;
  };
  for(const name of ['grid','circle','concentric','breadthfirst','cose','overview']) {
    calls=0;
    graphLayout.arrange(islands,{name:name==='overview'?'cose':name,overview:name==='overview',width:1200,height:600,fit:false,seed:true});
    assert.equal(calls,name==='overview'?1:2,'Only native seed and selected layout should run');
    assert.deepEqual(islands.nodes().map(n=>({...n.position()})),nativePositions,
      'Native coordinates must not be rotated, separated or repacked afterwards');
    for(const n of islands.nodes())assert.ok(Number.isFinite(n.position('x')) && Number.isFinite(n.position('y')));
    assert.equal(islands.edges().length,4);
    assert.equal(islands.elements().components().length,3);
  }
} finally {islands.destroy();}

const stable=graph();
try {
  stable.add([{data:{id:'b',label:'B'},position:{x:0,y:0}},
    {data:{id:'c',label:'C'},position:{x:240,y:0}},
    {data:{id:'d',label:'D'},position:{x:480,y:0}},
    {data:{id:'e',label:'E'},position:{x:720,y:0}},
    {data:{id:'cd',source:'c',target:'d'}},{data:{id:'de',source:'d',target:'e'}},
    {data:{id:'remote',label:'Remote'},position:{x:1000,y:500}}]);
  const old=new Map(stable.nodes().map(n=>[n.id(),{...n.position()}]));
  // An ID that sorts before existing nodes must not reshuffle their slots.
  stable.add({data:{id:'a',label:'A'},position:{x:0,y:0}});
  graphLayout.arrange(stable,{name:'grid',incremental:true,newNodes:['a'],affected:['a'],fit:false});
  for(const [id,p] of old)assert.deepEqual(stable.$id(id).position(),p,'New isolated nodes must preserve old positions');
  assertSeparated(stable);
  stable.add({data:{id:'bc',source:'b',target:'c'}});
  graphLayout.arrange(stable,{name:'cose',incremental:true,affected:['b','c'],fit:false});
  assert.deepEqual(stable.$id('remote').position(),old.get('remote'),'An unrelated node must remain fixed');
  const center=stable.nodes().filter(n=>['b','c','d','e'].includes(n.id())).reduce((s,n)=>s+n.position('x')/4,0);
  assert.ok(Math.abs(center-360)<1e-6,'The changed connected structure must retain its center');
  assert.notDeepEqual(stable.$id('e').position(),old.get('e'),'The whole connected structure must be free to settle');
  assert.equal(stable.nodes(':locked').length,0,'Layout must not introduce permanent locks');
} finally {stable.destroy();}

const star=graph();
try {
  star.add({data:{id:'hub',label:'Hub'},position:{x:0,y:0}});
  for(let i=0;i<16;i++)star.add({data:{id:'leaf'+i,label:'Leaf '+i},
    position:{x:1200*Math.cos(i*Math.PI/8),y:1200*Math.sin(i*Math.PI/8)}});
  for(let i=0;i<16;i++)star.add({data:{id:'link'+i,source:'hub',target:'leaf'+i}});
  graphLayout.arrange(star,{name:'cose',incremental:true,affected:['hub'],fit:false});
  const mean=star.edges().reduce((s,e)=>{
    const a=e.source().position(),b=e.target().position();return s+Math.hypot(a.x-b.x,a.y-b.y)/16;
  },0);
  assert.ok(mean<600,'New links must actually gather dispersed nodes into a connected structure');
  assertSeparated(star);
} finally {star.destroy();}

const expanding=graph();
try {
  expanding.add([{data:{id:'a',label:'Group A'},position:{x:-60,y:0}},
    {data:{id:'b',label:'Group A child'},position:{x:60,y:0}},
    {data:{id:'c',label:'Group B'},position:{x:-60,y:0}},
    {data:{id:'d',label:'Group B child'},position:{x:60,y:0}},
    {data:{id:'ab',source:'a',target:'b'}},{data:{id:'cd',source:'c',target:'d'}}]);
  const fixed=new Map(['c','d'].map(id=>[id,{...expanding.$id(id).position()}]));
  graphLayout.arrange(expanding,{name:'cose',incremental:true,affected:['a','b'],fit:false});
  for(const [id,p] of fixed)assert.deepEqual(expanding.$id(id).position(),p,'Unchanged disconnected regions must retain their positions');
  assertSeparated(expanding);
  expanding.add([{data:{id:'growing',label:'A long label on a newly added group member'},position:{x:0,y:0}},
    {data:{id:'bg',source:'b',target:'growing'}}]);
  graphLayout.arrange(expanding,{name:'cose',incremental:true,affected:['b','growing'],newNodes:['growing'],fit:false});
  for(const [id,p] of fixed)assert.deepEqual(expanding.$id(id).position(),p,'Growth must make room without moving an unrelated group');
  assertSeparated(expanding);
  const settled=new Map(expanding.nodes().map(n=>[n.id(),{...n.position()}]));
  graphLayout.arrange(expanding,{name:'cose',incremental:true,affected:[],fit:false});
  for(const [id,p] of settled)assert.deepEqual(expanding.$id(id).position(),p,'Settled groups must not be repacked on later unchanged updates');
} finally {expanding.destroy();}

const split=graph();
try {
  split.add([{data:{id:'left',label:'Left'},position:{x:0,y:0}},
    {data:{id:'right',label:'Right'},position:{x:10,y:0}},
    {data:{id:'bridge',source:'left',target:'right'}}]);
  split.$id('bridge').remove();
  graphLayout.arrange(split,{name:'cose',incremental:true,affected:['left','right'],fit:false});
  assertSeparated(split);
} finally {split.destroy();}

const spiralOutside=graph();
try {
  // A wide existing component occupies the center. New isolated nodes must
  // continue searching spiral slots rather than being pushed to its top edge.
  spiralOutside.add([{data:{id:'wide-left',label:'X'},position:{x:-600,y:0}},
    {data:{id:'wide-right',label:'X'},position:{x:600,y:0}},
    {data:{id:'wide-link',source:'wide-left',target:'wide-right'}}]);
  const added=[];
  for(let i=0;i<12;i++) {
    const id='free'+i;added.push(id);
    spiralOutside.add({data:{id,label:'X'},position:{x:0,y:0}});
  }
  graphLayout.arrange(spiralOutside,{name:'cose',incremental:true,newNodes:added,affected:added,
    placementOrigin:{x:0,y:0},fit:false});
  for(const id of added) {
    const p=spiralOutside.$id(id).position(),index=Math.round((p.x*p.x+p.y*p.y)/(70*70));
    const radius=70*Math.sqrt(index),angle=index*2.399963229728653;
    assert.ok(Math.hypot(p.x-Math.cos(angle)*radius,p.y-Math.sin(angle)*radius)<1e-6,
      'Component avoidance must retain spiral placement for new isolated nodes');
  }
  assertSeparated(spiralOutside);
} finally {spiralOutside.destroy();}

const bulk=graph();
try {
  bulk.add(Array.from({length:100},(_,i)=>({data:{id:'bulk'+i,label:'X'},position:{x:0,y:0}})));
  graphLayout.separate(bulk.nodes());
  const onAxis=bulk.nodes().filter(n=>Math.abs(n.position('x'))<1e-6 || Math.abs(n.position('y'))<1e-6).length;
  assert.ok(onAxis<10,'A coincident bulk insertion must not eject nodes along four compass directions');
  assertSeparated(bulk);
} finally {bulk.destroy();}

const bulkRegions=graph();
try {
  bulkRegions.add([{data:{id:'obstacle-left',label:'X'},position:{x:-600,y:0}},
    {data:{id:'obstacle-right',label:'X'},position:{x:600,y:0}},
    {data:{id:'obstacle-edge',source:'obstacle-left',target:'obstacle-right'}}]);
  const affected=[];
  for(let i=0;i<20;i++) {
    const a='group'+i+'-a',b='group'+i+'-b';affected.push(a,b);
    bulkRegions.add([{data:{id:a,label:'X'},position:{x:-40,y:0}},
      {data:{id:b,label:'X'},position:{x:40,y:0}},
      {data:{id:'group-edge'+i,source:a,target:b}}]);
  }
  graphLayout.arrange(bulkRegions,{name:'cose',incremental:true,affected,placementOrigin:{x:0,y:0},fit:false});
  let axis=0;
  for(let i=0;i<20;i++) {
    const a=bulkRegions.$id('group'+i+'-a').position(),b=bulkRegions.$id('group'+i+'-b').position();
    if(Math.abs(a.x+b.x)<1e-6 || Math.abs(a.y+b.y)<1e-6)axis++;
  }
  assert.ok(axis<4,'A large seek must not send entire connected groups along four compass directions');
  assertSeparated(bulkRegions);
} finally {bulkRegions.destroy();}

const vacancies=graph();
try {
  vacancies.add([{data:{id:'moving',label:'X'},position:{x:1000,y:1000}},
    {data:{id:'first',label:'X'},position:{x:2000,y:2000}}]);
  const targets=new Map([['moving',{x:0,y:0}]]);
  const first=graphLayout.vacantPositions(vacancies.nodes(),new Set(['first']),{x:0,y:0},targets);
  assert.notDeepEqual(first.get('first'),{x:0,y:0},'An occupied destination must not be mistaken for free space');
  vacancies.$id('first').position(first.get('first'));
  vacancies.add({data:{id:'second',label:'X'},position:{x:3000,y:3000}});
  const frozen=vacancies.nodes().not('#second').map(n=>[n.id(),{...n.position()}]);
  const second=graphLayout.vacantPositions(vacancies.nodes(),new Set(['second']),{x:0,y:0});
  assert.deepEqual(second.get('second'),{x:0,y:0},'New nodes must reuse the center after it becomes free');
  vacancies.$id('second').position(second.get('second'));
  for(const [id,p] of frozen)assert.deepEqual(vacancies.$id(id).position(),p,'Reusing holes must not move previous nodes');
  assertSeparated(vacancies);
} finally {vacancies.destroy();}

const spanRatio=points=>{
  const width=Math.max(...points.map(p=>p.x))-Math.min(...points.map(p=>p.x));
  const height=Math.max(...points.map(p=>p.y))-Math.min(...points.map(p=>p.y));
  return width/height;
};
const aspectSlots=graph();
try {
  aspectSlots.add(Array.from({length:150},(_,i)=>({data:{id:'slot'+i,label:'X'},position:{x:0,y:0}})));
  const moving=new Set(aspectSlots.nodes().map(n=>n.id()));
  const wide=graphLayout.vacantPositions(aspectSlots.nodes(),moving,{x:0,y:0},new Map(),16,{width:1200,height:400});
  const tall=graphLayout.vacantPositions(aspectSlots.nodes(),moving,{x:0,y:0},new Map(),16,{width:400,height:1200});
  assert.ok(spanRatio([...wide.values()])>2,'New slots must use the width of a landscape viewport');
  assert.ok(spanRatio([...tall.values()])<.7,'New slots must follow a portrait viewport too');
} finally {aspectSlots.destroy();}

function regionAspect(width,height) {
  const cy=graph(),affected=[];
  try {
    for(let i=0;i<30;i++) {
      const a='aspect-a'+i,b='aspect-b'+i;affected.push(a,b);
      cy.add([{data:{id:a,label:'X'},position:{x:-40,y:0}},
        {data:{id:b,label:'X'},position:{x:40,y:0}},
        {data:{id:'aspect-edge'+i,source:a,target:b}}]);
    }
    graphLayout.arrange(cy,{name:'cose',incremental:true,affected,width,height,fit:false,placementOrigin:{x:0,y:0}});
    assertSeparated(cy);
    return spanRatio(Array.from({length:30},(_,i)=>{
      const a=cy.$id('aspect-a'+i).position(),b=cy.$id('aspect-b'+i).position();
      return {x:(a.x+b.x)/2,y:(a.y+b.y)/2};
    }));
  } finally {cy.destroy();}
}
assert.ok(regionAspect(1200,400)>1.3,'Component centers must favor the width of a landscape viewport');
assert.ok(regionAspect(400,1200)<.8,'Component centers must favor the height of a portrait viewport');

function fillEstablishedLayout(portrait) {
  const cy=graph();
  const point=(x,y)=>portrait?{x:y,y:x}:{x,y};
  try {
    cy.add([{data:{id:'fixed-a',label:'X'},position:point(-40,-900)},
      {data:{id:'fixed-b',label:'X'},position:point(40,900)},
      {data:{id:'fixed-edge',source:'fixed-a',target:'fixed-b'}},
      {data:{id:'moving-a',label:'X'},position:point(-40,1900)},
      {data:{id:'moving-b',label:'X'},position:point(40,1900)},
      {data:{id:'moving-edge',source:'moving-a',target:'moving-b'}}]);
    const frozen=new Map(['fixed-a','fixed-b'].map(id=>[id,{...cy.$id(id).position()}]));
    const options={name:'cose',incremental:true,affected:['moving-a','moving-b'],fit:false,
      width:portrait?400:1200,height:portrait?1200:400,placementOrigin:{x:0,y:0}};
    graphLayout.arrange(cy,options);
    const a=cy.$id('moving-a').position(),b=cy.$id('moving-b').position();
    const center={x:(a.x+b.x)/2,y:(a.y+b.y)/2};
    assert.ok(Math.abs(portrait?center.x:center.y)<900,
      'Placement must improve the bounds of an established graph even without an immediate collision');
    assert.ok(Math.abs(portrait?center.y:center.x)>150,
      'A changed group must consider free space beside the occupied graph');
    for(const [id,p] of frozen)assert.deepEqual(cy.$id(id).position(),p,'Global placement must preserve unaffected groups');
    assertSeparated(cy);
    graphLayout.arrange(cy,options);
    const a2=cy.$id('moving-a').position(),b2=cy.$id('moving-b').position();
    assert.ok(Math.hypot((a2.x+b2.x)/2-center.x,(a2.y+b2.y)/2-center.y)<1e-6,
      'An already satisfactory location must not oscillate on the next calculation');
  } finally {cy.destroy();}
}
fillEstablishedLayout(false);fillEstablishedLayout(true);

console.log('Graph layout regressions passed: geometry, inertia, native layout and reduced motion.');
