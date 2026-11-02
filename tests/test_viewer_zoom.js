'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const cytoscape=require('../scripts/viewer/vendor/cytoscape.min.js');
const layout=require('../scripts/viewer/graph-layout.js');
const source=fs.readFileSync(require.resolve('../scripts/viewer/app.js'),'utf8');
const frames=[];
const context=vm.createContext({
  $:()=>null,requestAnimationFrame:callback=>{frames.push(callback);return frames.length;},
  cytoscape:options=>cytoscape({...options,container:undefined,headless:true,styleEnabled:true})
});
const start=source.indexOf('function zoomLength(');
const end=source.indexOf('const backgroundLayout=',start);
assert.ok(start>=0&&end>start);
vm.runInContext(source.slice(start,end),context);
const cy=vm.runInContext('cy',context);
cy.add([
  {data:{id:'small',size:14,color:'#79b8e8',displayLabel:'Small'}},
  {data:{id:'hub',size:30,color:'#79b8e8',displayLabel:'Hub'}},
  {data:{id:'group',size:58,color:'#79b8e8',displayLabel:'Group'}},
  {data:{id:'link',source:'small',target:'hub',color:'#79b8e8',curve:'bezier',label:'calls',displayLabel:'calls'}}
]);
const node=cy.$id('small'),edge=cy.$id('link');
const getArrowWidth=cytoscape('renderer','base').prototype.getArrowWidth;
const arrowPixels=()=>getArrowWidth.call({arrowWidthCache:{}},edge.numericStyle('width'),
  edge.numericStyle('arrow-scale'))*cy.zoom();
function zoom(value) {
  cy.zoom(value);
  assert.ok(frames.length<=1,'zoom events coalesce');
  while(frames.length)frames.shift()();
}
const rendered=(element,property)=>element.numericStyle(property)*cy.zoom();
const near=(actual,expected)=>assert.ok(Math.abs(actual-expected)<1e-5,`${actual} != ${expected}`);
for(const z of [.001,.05,.3,.7,.85,1,1.5,3,5]) {
  zoom(z);
  for(const n of cy.nodes()) {
    assert.ok(n.renderedWidth()>=3-1e-5&&n.renderedWidth()<=24+1e-5);
    near(n.renderedWidth(),n.renderedHeight());
    assert.ok(rendered(n,'font-size')<=14+1e-5);
  }
  assert.ok(rendered(edge,'width')>=.6-1e-5&&rendered(edge,'width')<=2+1e-5);
  assert.ok(arrowPixels()>=6-1e-5&&arrowPixels()<=12+1e-5);
  for(const className of ['touched','path','replayChanged','replayRemoved']) {
    edge.addClass(className);
    assert.ok(arrowPixels()>=6-1e-5&&arrowPixels()<=12+1e-5);
    edge.removeClass(className);
  }
  edge.select();assert.ok(arrowPixels()<=12+1e-5);edge.unselect();
}
// Screen clamps must never feed inflated model sizes back to collision/force layout.
zoom(1);
const boxes=layout.boxes(cy.nodes());
for(const z of [.001,.05,5]) {
  zoom(z);
  const measured=layout.boxes(cy.nodes());
  measured.forEach((box,index)=>{near(box.w,boxes[index].w);near(box.h,boxes[index].h);});
  near(node.renderedWidth(),Math.max(3,Math.min(24,14*.65*z)));
}
zoom(.001);
node.outerWidth(); // Prime the same compensated style cache that the renderer reads.
const originalWindow=cy.window;
cy.window=()=>({requestAnimationFrame(){},matchMedia:()=>({matches:false})});
layout.transition(cy,()=>{
  const measured=layout.boxes(cy.nodes());
  measured.forEach((box,index)=>{near(box.w,boxes[index].w);near(box.h,boxes[index].h);});
});
cy.window=originalWindow;
near(node.renderedWidth(),3);
let workerInput;
const worker=layout.createWorkerLayout(()=>({postMessage(message){workerInput=message;},terminate(){}}));
void worker.arrange(cy,{fit:false});
near(parseFloat(workerInput.elements.find(el=>el.data.id==='small').style.width),14);
worker.cancel();
near(node.renderedWidth(),3);
zoom(.7);near(node.numericStyle('text-opacity'),0);
zoom(.85);near(node.numericStyle('text-opacity'),.5);near(rendered(node,'font-size'),8.5);
zoom(1);near(node.numericStyle('text-opacity'),1);
zoom(7/9);near(edge.numericStyle('text-opacity'),0);
zoom(8.5/9);near(edge.numericStyle('text-opacity'),.5);
edge.addClass('hovered');near(edge.numericStyle('text-opacity'),.5);
edge.select();zoom(.1);near(edge.numericStyle('text-opacity'),0);
zoom(1);near(node.renderedWidth(),9.1);near(cy.$id('hub').renderedWidth(),19.5);
zoom(5);near(rendered(node,'font-size'),14);near(node.renderedWidth(),24);
for(const className of ['touched','path','replayChanged','replayRemoved','changed','recordedChange']) {
  node.addClass(className);edge.addClass(className);
  near(node.renderedWidth(),24);
  assert.ok(rendered(node,'border-width')<=4+1e-5);
  assert.ok(rendered(edge,'width')<=3+1e-5);
  assert.ok(arrowPixels()>=6-1e-5&&arrowPixels()<=12+1e-5);
  node.removeClass(className);edge.removeClass(className);
}
node.select();near(node.renderedWidth(),24);near(rendered(node,'border-width'),4);
// Newly loaded and redecorated nodes must inherit the current zoom without another gesture.
zoom(.001);
const added=cy.add({data:{id:'new',size:24,color:'#79b8e8',displayLabel:'New'}});
near(added.renderedWidth(),3);
added.data('size',58);near(added.renderedWidth(),3);
zoom(2);near(added.renderedWidth(),24);
const before=node.renderedPosition().x;
node.position({x:100,y:0});
near(node.renderedPosition().x-before,200);
cy.zoom(3);cy.zoom(4);cy.zoom(5);assert.equal(frames.length,1);frames.shift()();
near(node.renderedWidth(),24);
cy.destroy();
console.log('Graph zoom: bounded screen sizes, smooth label fade, highlights, new nodes and camera spacing passed.');
