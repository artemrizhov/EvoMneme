/* Run the shipped classic worker in an actual Node worker thread, no browser. */
'use strict';
const assert=require('node:assert/strict');
const {Worker}=require('node:worker_threads');
const path=require('node:path');
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
    const group=layout.boxes(cy.nodes().filter(n=>n.id()!=='c'));
    const isolated=layout.boxes(cy.$id('c'))[0];
    const bounds={x1:Math.min(...group.map(b=>b.x+b.dx-b.w/2)),x2:Math.max(...group.map(b=>b.x+b.dx+b.w/2)),
      y1:Math.min(...group.map(b=>b.y+b.dy-b.h/2)),y2:Math.max(...group.map(b=>b.y+b.dy+b.h/2))};
    assert.ok(isolated.x+isolated.dx-isolated.w/2>=bounds.x2+80 || isolated.y+isolated.dy-isolated.h/2>=bounds.y2+80,
      'Worker must separate islands and ignore historical removal markers');
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
  console.log('Background layout passed: real worker computation, geometry, cancellation, replacement, failure and timeout.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
