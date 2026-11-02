'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const cytoscape=require('../scripts/viewer/vendor/cytoscape.min.js');
const layout=require('../scripts/viewer/graph-layout.js');
const source=fs.readFileSync(require.resolve('../scripts/viewer/app.js'),'utf8');
const frames=[];
const state={elementScale:1,acceleration:false,workerLayoutEnabled:false};
const scaleControl={value:'100'};
let preferences=null;
const context=vm.createContext({
  state,
  $:id=>id==='elementScale'?scaleControl:null,
  localStorage:{getItem:()=>preferences,setItem:(_key,value)=>{preferences=value;}},
  requestAnimationFrame:callback=>{frames.push(callback);return frames.length;},
  cytoscape:options=>cytoscape({...options,container:undefined,headless:true,styleEnabled:true})
});
const start=source.indexOf('const elementScales=');
vm.runInContext(source.match(/^const activityColors=.*$/m)[0],context);
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
node.style('transition-property','none');
for(const [name,color] of [['touched','rgb(247,205,113)'],['recordedChange','rgb(121,184,255)'],
  ['recordedCreate','rgb(113,234,184)'],['recordedDelete','rgb(255,123,135)']]) {
  node.addClass('touched '+name);assert.equal(node.style('border-color'),color);
  node.removeClass('touched '+name);
}
node.removeStyle('transition-property');
assert.equal(node.numericStyle('transition-duration'),300);
assert.equal(edge.numericStyle('transition-duration'),300);
edge.scratch('accessFlash',{opacity:.85,color:'#71eab8'}).addClass('accessFlash accessEdgeFlash accessColorFlash');
assert.equal(edge.style('line-color'),'rgb(113,234,184)','GPU edge path receives the actual flash color');
assert.equal(edge.style('target-arrow-color'),'rgb(113,234,184)');
edge.scratch('accessFlash',{opacity:.425,color:'#71eab8'}).updateStyle();
assert.equal(edge.style('line-color'),'rgb(117,209,208)','line color fades continuously with the halo');
edge.removeClass('accessColorFlash').addClass('touched');
const pulsedWidth=edge.numericStyle('width');
edge.scratch('accessFlash',{opacity:0,color:'#71eab8'}).updateStyle();
assert.ok(pulsedWidth>edge.numericStyle('width'),'retained GPU edge still visibly pulses in width');
edge.removeClass('accessFlash accessEdgeFlash accessColorFlash touched').removeScratch('accessFlash');
assert.equal(edge.numericStyle('transition-duration'),300,'history color transitions remain visible after a pulse');
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
function atFont(pixels) {
  let low=cy.minZoom(),high=cy.maxZoom();
  for(let i=0;i<50;i++) {
    const middle=(low+high)/2;zoom(middle);
    if(rendered(node,'font-size')<pixels)low=middle;else high=middle;
  }
  zoom(high);near(rendered(node,'font-size'),pixels);
}
// Reproduce the actual GPU contract: alpha is baked by setupTextStyle, but
// Cytoscape's labelStyleKey stays unchanged when text-opacity alone changes.
vm.runInContext(source.slice(source.indexOf('function fixGpuLabelOpacity('),source.indexOf('function replaceRenderer(')),context);
const labelTypes=new Map(['label','edge-source-label','edge-target-label'].map(type=>[type,{
  getKey:element=>[`${element._private.labelStyleKey}_0`,`${element._private.labelStyleKey}_1`],isVisible:()=>true
}]));
const renderer={drawing:{atlasManager:{getRenderTypeOpts:type=>labelTypes.get(type)}}};
context.testRenderer=renderer;
vm.runInContext('fixGpuLabelOpacity(testRenderer)',context);
const canvas=cytoscape('renderer','canvas').prototype;
const paint={colorFillStyle(_context,_r,_g,_b,alpha){this.alpha=alpha;},colorStrokeStyle(){}};
const keys=new Set();let baseKey;
// Resolve initial function-mapped font/outline styles before comparing atlas keys.
node.style('text-opacity',1);canvas.setupTextStyle.call(paint,{},node,true);
for(const alpha of [1,.75,.5,.25,0,.5,1]) {
  zoom(1);node.style('text-opacity',alpha);
  canvas.setupTextStyle.call(paint,{},node,true);
  near(paint.alpha,alpha);
  const currentBase=node._private.labelStyleKey;
  if(baseKey===undefined)baseKey=currentBase;else assert.equal(currentBase,baseKey);
  for(const options of labelTypes.values()) {
    const parts=options.getKey(node),key=parts[0];
    assert.ok(key.startsWith(`alpha=${paint.alpha};`),'GPU atlas key must identify the alpha it bakes');
    // The shipped atlas bounds parser takes the suffix after the first underscore.
    parts.forEach((part,index)=>assert.equal(Number(part.substring(part.indexOf('_')+1)),index));
    assert.equal(!!options.isVisible(node),alpha>0);
    keys.add(key);
  }
}
assert.equal(keys.size,5,'Fade in and out must revisit the matching cached alpha');
node.style('text-opacity',.5);node.style('opacity',.4);
assert.ok(labelTypes.get('label').getKey(node)[0].startsWith('alpha=0.2;'));
node.removeStyle('text-opacity opacity');
for(const z of [.001,.05,.3,.7,.85,1,1.5,3,5]) {
  zoom(z);
  for(const n of cy.nodes()) {
    assert.ok(n.renderedWidth()>=1.5-1e-5&&n.renderedWidth()<=18+1e-5);
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
  near(node.renderedWidth(),Math.max(1.5,Math.min(18,14*.325*z)));
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
near(node.renderedWidth(),1.5);
let workerInput;
const worker=layout.createWorkerLayout(()=>({postMessage(message){workerInput=message;},terminate(){}}));
void worker.arrange(cy,{fit:false});
near(parseFloat(workerInput.elements.find(el=>el.data.id==='small').style.width),14);
worker.cancel();
near(node.renderedWidth(),1.5);
zoom(.6);near(node.numericStyle('text-opacity'),0);
zoom(1);near(node.numericStyle('text-opacity'),.5);near(rendered(node,'font-size'),5);
zoom(1.4);near(node.numericStyle('text-opacity'),1);
zoom(3/4.5);near(edge.numericStyle('text-opacity'),0);
zoom(5/4.5);near(edge.numericStyle('text-opacity'),.5);
edge.addClass('hovered');near(edge.numericStyle('text-opacity'),.5);
edge.select();zoom(.1);near(edge.numericStyle('text-opacity'),0);
zoom(1);near(node.renderedWidth(),4.55);near(cy.$id('hub').renderedWidth(),9.75);
near(rendered(node,'font-size'),5);near(rendered(edge,'font-size'),4.5);
zoom(.1);near(rendered(node,'font-size'),2);near(rendered(edge,'font-size'),2);
zoom(5);near(rendered(node,'font-size'),14);near(rendered(edge,'font-size'),14);near(node.renderedWidth(),18);
for(const className of ['touched','path','replayChanged','replayRemoved','changed','recordedChange']) {
  node.addClass(className);edge.addClass(className);
  near(node.renderedWidth(),18);
  assert.ok(rendered(node,'border-width')<=2+1e-5);
  assert.ok(rendered(edge,'width')<=3+1e-5);
  assert.ok(arrowPixels()>=6-1e-5&&arrowPixels()<=12+1e-5);
  node.removeClass(className);edge.removeClass(className);
}
node.select();near(node.renderedWidth(),18);near(rendered(node,'border-width'),2);
// Newly loaded and redecorated nodes must inherit the current zoom without another gesture.
zoom(.001);
const added=cy.add({data:{id:'new',size:24,color:'#79b8e8',displayLabel:'New'}});
near(added.renderedWidth(),1.5);
added.data('size',58);near(added.renderedWidth(),1.5);
zoom(2);near(added.renderedWidth(),18);
const before=node.renderedPosition().x;
node.position({x:100,y:0});
near(node.renderedPosition().x-before,200);
cy.zoom(3);cy.zoom(4);cy.zoom(5);assert.equal(frames.length,1);frames.shift()();
near(node.renderedWidth(),18);
// Drive the shipped selector handler, including persistence and every offered size.
vm.runInContext(source.slice(source.indexOf('function saveVisualPreferences('),source.indexOf('function setAcceleration(')),context);
const html=fs.readFileSync(require.resolve('../scripts/viewer/index.html'),'utf8');
const select=html.match(/<select id="elementScale">([\s\S]*?)<\/select>/)[1];
const choices=[...select.matchAll(/<option value="(\d+)"[^>]*>/g)].map(match=>Number(match[1]));
assert.deepEqual(choices,[30,40,50,65,80,100,125,150,200,250,300,400]);
assert.match(select,/<option value="100" selected>/);
zoom(1);
const modelBoxes=layout.boxes(cy.nodes());
const positions=JSON.stringify(cy.nodes().map(n=>n.position()));
for(const percent of choices) {
  const factor=percent/100,viewport=JSON.stringify({zoom:cy.zoom(),pan:cy.pan()});
  scaleControl.value=String(percent);scaleControl.onchange();
  near(state.elementScale,factor);
  assert.equal(JSON.parse(preferences).elementScale,percent);
  assert.equal(JSON.stringify({zoom:cy.zoom(),pan:cy.pan()}),viewport);
  assert.equal(JSON.stringify(cy.nodes().map(n=>n.position())),positions);
  zoom(1);near(node.renderedWidth(),Math.max(1.5,4.55*factor));
  near(rendered(node,'font-size'),Math.max(2,5*factor));
  layout.boxes(cy.nodes()).forEach((box,index)=>{near(box.w,modelBoxes[index].w);near(box.h,modelBoxes[index].h);});
  zoom(.001);near(node.renderedWidth(),1.5);near(rendered(node,'font-size'),2);
  near(node.numericStyle('text-opacity'),0);
  zoom(5);near(node.renderedWidth(),18*factor);near(rendered(node,'font-size'),14*factor);
  const fade=Math.max(0,Math.min(1,(14*factor-3)/4));
  near(node.numericStyle('text-opacity'),fade*fade*(3-2*fade));
  atFont(3);near(node.numericStyle('text-opacity'),0);
  if(percent>=40){atFont(5);near(node.numericStyle('text-opacity'),.5);}
  if(percent>=50){atFont(7);near(node.numericStyle('text-opacity'),1);}
  zoom(2.24);near(rendered(node,'font-size'),11.2*factor);
  zoom(2.8);near(rendered(node,'font-size'),13.3*factor);
  zoom(3.36);near(rendered(node,'font-size'),14*factor);
  zoom(14/4.5);near(rendered(edge,'font-size'),13.3*factor);
  let previous=0,previousSlope=Infinity;
  for(let i=0;i<=40;i++) {
    const z=2.24+i*.04;zoom(z);
    const value=rendered(node,'font-size');
    assert.ok(value>=previous-1e-5&&value<=14*factor+1e-5);
    if(i>0){const slope=(value-previous)/.04;assert.ok(slope<=previousSlope+1e-5);previousSlope=slope;}
    previous=value;
  }
  const step=.00001;
  for(const point of [2.24,3.36]) {
    zoom(point-step);const left=rendered(node,'font-size');
    zoom(point);const center=rendered(node,'font-size');
    zoom(point+step);const right=rendered(node,'font-size');
    assert.ok(Math.abs((center-left)/step-(right-center)/step)<.001,'Font growth must join smoothly');
  }
}
assert.equal(vm.runInContext('setElementScale(99)',context),false);
preferences=JSON.stringify({elementScale:150});vm.runInContext('restoreVisualPreferences()',context);
near(state.elementScale,1.5);assert.equal(scaleControl.value,'150');
preferences='{"elementScale":999}';vm.runInContext('restoreVisualPreferences()',context);
near(state.elementScale,1.5);
context.localStorage={getItem(){throw new Error('blocked');},setItem(){throw new Error('blocked');}};
assert.equal(vm.runInContext('setElementScale(100)',context),true);
vm.runInContext('restoreVisualPreferences()',context);near(state.elementScale,1);
cy.destroy();
console.log('Graph zoom: bounded screen sizes, smooth label fade, highlights, new nodes and camera spacing passed.');
