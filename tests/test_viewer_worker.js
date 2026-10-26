/* Run the shipped classic worker in an actual Node worker thread, no browser. */
'use strict';
const assert=require('node:assert/strict');
const {Worker}=require('node:worker_threads');
const path=require('node:path');
const fs=require('node:fs');
const vm=require('node:vm');
const cytoscape=require('../scripts/viewer/vendor/cytoscape.min.js');
const layout=require('../scripts/viewer/graph-layout.js');
const directory=path.resolve(__dirname,'../scripts/viewer');
const bootstrap=`
  const {parentPort,workerData}=require('node:worker_threads');
  const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
  const sandbox={console,setTimeout,clearTimeout};
  sandbox.self=sandbox;
  sandbox.postMessage=data=>parentPort.postMessage(data);
  const context=vm.createContext(sandbox);
  sandbox.importScripts=(...names)=>names.forEach(name=>vm.runInContext(fs.readFileSync(path.join(workerData,name==='cytoscape.min.js'?'vendor/cytoscape.min.js':name),'utf8'),context));
  vm.runInContext(fs.readFileSync(path.join(workerData,'layout-worker.js'),'utf8'),context);
  parentPort.on('message',data=>{sandbox.messageJSON=JSON.stringify(data);vm.runInContext('self.onmessage({data:JSON.parse(messageJSON)})',context);});
`;
function realWorker() {
  const thread=new Worker(bootstrap,{eval:true,workerData:directory});
  const worker={postMessage:data=>thread.postMessage(data),terminate:()=>void thread.terminate()};
  thread.on('message',data=>worker.onmessage?.({data}));
  thread.on('error',error=>worker.onerror?.({message:error.message}));
  return worker;
}
async function main() {
  const cy=cytoscape({headless:true,styleEnabled:true,elements:[
    {data:{id:'a',label:'Long architecture label'},position:{x:0,y:0}},
    {data:{id:'b',label:'Second label'},position:{x:0,y:0}},
    {data:{id:'c',label:'Locked node'},position:{x:700,y:700},locked:true},
    {data:{id:'ab',source:'a',target:'b'}},
    {data:{id:'bc',source:'b',target:'c'}}],
    style:[{selector:'node',style:{label:'data(label)',width:24,height:24,'font-size':10,'text-valign':'bottom'}}]});
  const controller=layout.createWorkerLayout(realWorker);
  try {
    let yielding=false;setTimeout(()=>{yielding=true;},0);
    assert.equal(await controller.arrange(cy,{name:'grid',width:900,height:600,fit:false}),true);
    assert.equal(yielding,true,'Main thread must remain available while worker calculates');
    assert.equal(cy.scratch('memory-layout'),'grid');
    assert.deepEqual(cy.$id('c').position(),{x:700,y:700});
    assert.notDeepEqual(cy.$id('a').position(),cy.$id('b').position());
    for(const node of cy.nodes())assert.ok(Number.isFinite(node.position('x')));
    const boxes=layout.boxes(cy.nodes());
    for(let i=0;i<boxes.length;i++)for(let j=0;j<i;j++) {
      const a=boxes[i],b=boxes[j];
      assert.ok(Math.abs(a.x+a.dx-b.x-b.dx)>=(a.w+b.w)/2 || Math.abs(a.y+a.dy-b.y-b.dy)>=(a.h+b.h)/2);
    }
    // A newly inserted endpoint can still be at opacity zero while its edge
    // is already visible. The worker must receive a structurally closed graph.
    cy.$id('b').style('opacity',0);
    assert.equal(cy.$id('b').visible(),false);
    assert.equal(cy.$id('ab').visible(),true);
    assert.equal(layout.layoutElements(cy).nodes().length,3);
    assert.equal(layout.layoutElements(cy).edges().length,2);
    assert.equal(await controller.arrange(cy,{name:'grid',width:900,height:600,fit:false}),true,
      'A fading endpoint must remain in the worker snapshot with its edges');
    cy.$id('b').removeStyle('opacity');
    cy.$id('b').style('display','none');
    assert.equal(layout.layoutElements(cy).nodes().length,2,'Explicitly filtered nodes must remain excluded');
    assert.equal(layout.layoutElements(cy).edges().length,0,'Edges to filtered endpoints must not leak into the snapshot');
    assert.equal(await controller.arrange(cy,{name:'grid',width:900,height:600,fit:false}),true);
    cy.$id('b').removeStyle('display');
    // Cancellation and replacement must not apply a stale result, even if the
    // terminated worker had already sent it before the next microtask.
    const before={...cy.$id('a').position()};
    const cancelled=controller.arrange(cy,{name:'circle',width:900,height:600,fit:false});
    controller.cancel();assert.equal(await cancelled,false);
    assert.deepEqual(cy.$id('a').position(),before);
    const superseded=controller.arrange(cy,{name:'circle',width:900,height:600,fit:false});
    const replacement=controller.arrange(cy,{name:'grid',width:900,height:600,fit:false});
    assert.equal(await superseded,false);assert.equal(await replacement,true);
    assert.equal(cy.scratch('memory-layout'),'grid');
    for(const name of ['circle','concentric','breadthfirst','cose']) {
      assert.equal(await controller.arrange(cy,{name,width:900,height:600,fit:false}),true);
      for(const node of cy.nodes())assert.ok(Number.isFinite(node.position('x')) && Number.isFinite(node.position('y')),name);
      assert.deepEqual(cy.$id('c').position(),{x:700,y:700},name+' must preserve locked nodes');
    }
    cy.$id('c').unlock();cy.$id('bc').remove();
    cy.add({data:{id:'removed-bc',source:'b',target:'c'},classes:'replayRemoved'});
    assert.equal(await controller.arrange(cy,{name:'grid',width:900,height:600,fit:false}),true);
    assert.equal(cy.nodes().length,3,'Worker must retain disconnected nodes');
    assert.equal(cy.elements('.replayRemoved').length,1,'Historical removal markers must remain intact');
    const oldPositions=new Map(cy.nodes().map(n=>[n.id(),{...n.position()}]));
    cy.add({data:{id:'new-first',label:'New isolated node'},position:{...cy.$id('a').position()}});
    assert.equal(await controller.arrange(cy,{name:'grid',incremental:true,newNodes:['new-first'],affected:['new-first'],fit:false}),true);
    for(const [id,p] of oldPositions)assert.deepEqual(cy.$id(id).position(),p,
      'A worker update must not reshuffle existing nodes when an isolated node appears');
    cy.$id('new-first').remove();
    cy.$id('a').position({x:-600,y:0});cy.$id('b').position({x:600,y:0});cy.$id('c').position({x:0,y:0});
    const spiralOrigin={x:35,y:20};
    assert.equal(await controller.arrange(cy,{name:'cose',incremental:true,affected:['c'],newNodes:['c'],
      placementOrigin:spiralOrigin,fit:false}),true);
    const slot=cy.$id('c').position(),sx=slot.x-spiralOrigin.x,sy=slot.y-spiralOrigin.y;
    const slotIndex=Math.round((sx*sx+sy*sy)/(70*70)),slotRadius=70*Math.sqrt(slotIndex),slotAngle=slotIndex*2.399963229728653;
    assert.ok(Math.hypot(sx-slotRadius*Math.cos(slotAngle),sy-slotRadius*Math.sin(slotAngle))<1e-6,
      'The actual worker must preserve spiral placement when avoiding component envelopes');
    // A changed connected region must get room around an unrelated island,
    // including when the calculation runs in the actual background worker.
    cy.$id('c').position({...cy.$id('a').position()});
    const island={...cy.$id('c').position()};
    assert.equal(await controller.arrange(cy,{name:'cose',incremental:true,affected:['a','b'],fit:false}),true);
    assert.deepEqual(cy.$id('c').position(),island,'An unrelated island must remain anchored');
    const settledBoxes=layout.boxes(cy.nodes());
    for(let i=0;i<settledBoxes.length;i++)for(let j=0;j<i;j++) {
      const a=settledBoxes[i],b=settledBoxes[j];
      assert.ok(Math.abs(a.x+a.dx-b.x-b.dx)>=(a.w+b.w)/2 || Math.abs(a.y+a.dy-b.y-b.dy)>=(a.h+b.h)/2,
        'A background layout must separate changed groups from unrelated islands');
    }
    const established=cytoscape({headless:true,styleEnabled:true,elements:[
      {data:{id:'fixed-a'},position:{x:-40,y:-900}},
      {data:{id:'fixed-b'},position:{x:40,y:900}},
      {data:{id:'fixed-edge',source:'fixed-a',target:'fixed-b'}},
      {data:{id:'moving-a'},position:{x:-40,y:1900}},
      {data:{id:'moving-b'},position:{x:40,y:1900}},
      {data:{id:'moving-edge',source:'moving-a',target:'moving-b'}}],layout:{name:'preset'}});
    try {
      assert.equal(await controller.arrange(established,{name:'cose',incremental:true,affected:['moving-a','moving-b'],
        width:1200,height:400,placementOrigin:{x:0,y:0},fit:false}),true);
      const a=established.$id('moving-a').position(),b=established.$id('moving-b').position();
      assert.ok(Math.abs((a.y+b.y)/2)<900 && Math.abs((a.x+b.x)/2)>150,
        'The actual worker must account for the full occupied frame, not just initial placement');
      assert.deepEqual(established.$id('fixed-a').position(),{x:-40,y:-900});
      assert.deepEqual(established.$id('fixed-b').position(),{x:40,y:900});
    } finally {established.destroy();}
    let releaseApply,enterApply;
    const applyGate=new Promise(resolve=>releaseApply=resolve),entered=new Promise(resolve=>enterApply=resolve);
    const guarded=controller.arrange(cy,{name:'circle',width:900,height:600,fit:false},()=>{enterApply();return applyGate;});
    await entered;
    const heldPosition={...cy.$id('a').position()};
    controller.cancel();releaseApply(true);
    assert.equal(await guarded,false,'Cancelling a ready result must still prevent stale geometry application');
    assert.deepEqual(cy.$id('a').position(),heldPosition);
    let dead=false;
    const failing=layout.createWorkerLayout(()=>({terminate(){dead=true;},postMessage(){this.onmessage({data:{id:1,error:'synthetic worker failure'}});}}));
    await assert.rejects(failing.arrange(cy,{fit:false}),/synthetic worker failure/);
    assert.equal(dead,true);
    const timeout=layout.createWorkerLayout(()=>({terminate(){},postMessage(){}}),10);
    await assert.rejects(timeout.arrange(cy,{fit:false}),/timed out/);
    timeout.cancel();
  } finally {controller.cancel();cy.destroy();}
  const largeElements=[];
  for(let i=0;i<6000;i++) {
    largeElements.push({data:{id:'large'+i},position:{x:(i%80)*180,y:Math.floor(i/80)*110}});
    if(i)largeElements.push({data:{id:'large-edge'+i,source:'large'+(i-1),target:'large'+i}});
  }
  const large=cytoscape({headless:true,styleEnabled:true,layout:{name:'preset'},elements:largeElements});
  const largeController=layout.createWorkerLayout(realWorker);
  try {
    const pending=largeController.arrange(large,{name:'cose',seed:false,width:1200,height:400,fit:false});
    await new Promise(resolve=>setTimeout(resolve,100));
    largeController.cancel();
    assert.equal(await pending,false,'A full large-component calculation must remain cancellable without awaiting completion');
    assert.equal(large.nodes().length,6000);assert.equal(large.edges().length,5999);
    for(const n of large.nodes())assert.ok(Number.isFinite(n.position('x')) && Number.isFinite(n.position('y')));
    const bounds=large.nodes().boundingBox();
    assert.ok(bounds.w>1200 || bounds.h>400,'Cancelling a full calculation must preserve the displayed geometry');
    const requested=[];
    const probe=cytoscape({headless:true,styleEnabled:true,elements:[{data:{id:'probe'}}]});
    try {
      for(const graph of [probe,large]) {
        const native=graph.layout;
        graph.layout=options=>{requested.push(options.numIter);return {options,run(){}};};
        try {layout.arrange(graph,{name:'cose',seed:false,fit:false});}
        finally {graph.layout=native;}
      }
      assert.ok(requested[0]>1,'Force layout must retain a full iteration budget');
      assert.equal(requested[1],requested[0],'Growing to 6000 nodes must not reduce the iteration count');
      const native=large.layout;
      large.layout=options=>{requested.push(options.numIter);return {options,run(){}};};
      try {layout.arrange(large,{name:'cose',incremental:true,affected:['large0'],fit:false});}
      finally {large.layout=native;}
      assert.equal(requested[2],requested[0],'Incremental layout must retain the same full budget');
    } finally {probe.destroy();}
  } finally {largeController.cancel();large.destroy();}
  // Virtual time verifies that a valid long calculation survives the former
  // 45-second cutoff, without making the test itself wait for minutes.
  let clock=0,nextTimer=0,worker;
  const timers=new Map(),scope={module:{exports:{}},
    setTimeout(fn,delay){const id=++nextTimer;timers.set(id,{fn,at:clock+delay});return id;},
    clearTimeout(id){timers.delete(id);}};
  vm.runInNewContext(fs.readFileSync(path.join(directory,'graph-layout.js'),'utf8'),scope);
  const slow=cytoscape({headless:true,styleEnabled:true,elements:[{data:{id:'slow'}}]});
  const patient=scope.module.exports.createWorkerLayout(()=>worker={postMessage(){},terminate(){}});
  try {
    let settled=false;
    const pending=patient.arrange(slow,{fit:false});
    pending.then(()=>{settled=true;},()=>{settled=true;});
    clock=120000;
    for(const [id,timer] of timers)if(timer.at<=clock){timers.delete(id);timer.fn();}
    await Promise.resolve();
    assert.equal(settled,false,'A long background calculation must not be killed after 45 seconds');
    worker.onmessage({data:{id:1,layout:'cose',positions:[['slow',{x:10,y:20}]]}});
    assert.equal(await pending,true,'A result arriving after two minutes must still apply');
    assert.deepEqual(slow.$id('slow').position(),{x:10,y:20});
  } finally {patient.cancel();slow.destroy();}
  console.log('Background layout passed: real worker computation, geometry, cancellation, replacement, failure and timeout.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
