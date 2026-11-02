'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const cytoscape=require('../scripts/viewer/vendor/cytoscape.min.js');
const source=fs.readFileSync(require.resolve('../scripts/viewer/app.js'),'utf8');
const context=vm.createContext({});
vm.runInContext(source.match(/^const activityColors=.*$/m)[0],context);
vm.runInContext(source.slice(source.indexOf('function references(event)'),source.indexOf('// Deleted geometry')),context);
vm.runInContext(source.slice(source.indexOf('function createAccessFlashes('),source.indexOf('const accessFlashes=')),context);
const cy=cytoscape({headless:true,elements:[{data:{id:'a'}},{data:{id:'b'}},
  {data:{id:'edge',source:'a',target:'b'}}]});
let now=0;const frames=[];
const flashes=context.createAccessFlashes(cy,()=>now,callback=>frames.push(callback));
const tick=time=>{now=time;assert.equal(frames.length,1,'one shared frame loop');frames.shift()();};
const level=id=>cy.$id(id).scratch('accessFlash')?.opacity || 0;
const near=(actual,expected)=>assert.ok(Math.abs(actual-expected)<1e-8,`${actual} != ${expected}`);
flashes.flash([['a','read'],['edge','update'],['later','read']]);
tick(150);near(level('a'),.425);
tick(300);near(level('a'),.85);
assert.equal(cy.$id('edge').hasClass('accessEdgeFlash'),true,'GPU edge path uses an actual line-color class');
cy.$id('edge').addClass('touched');flashes.refresh();
assert.equal(cy.$id('edge').hasClass('accessEdgeFlash'),true,'retained GPU edges still pulse in width');
assert.equal(cy.$id('edge').hasClass('accessColorFlash'),false,'retained highlight keeps its color');
cy.$id('edge').removeClass('touched');flashes.refresh();
assert.equal(cy.$id('edge').hasClass('accessEdgeFlash'),true,'pulse resumes after retained highlighting clears');
assert.equal(cy.$id('edge').hasClass('accessColorFlash'),true);
assert.equal(cy.$id('a').scratch('accessFlash').color,'#f7cd71');
assert.equal(cy.$id('edge').scratch('accessFlash').color,'#79b8ff');
tick(2800);near(level('a'),.85*.75);
tick(4050);near(level('a'),.85*.4375);
const before=level('a');
flashes.flash([['a','read']]);
tick(4200);near(level('a'),(before+.85)/2);
tick(4350);near(level('a'),.85);
cy.add({data:{id:'later'}});
tick(5300);near(level('edge'),0);assert.equal(cy.$id('edge').hasClass('accessFlash'),false);
assert.equal(cy.$id('later').hasClass('accessFlash'),false,'expired off-page access does not light later');
tick(9350);assert.equal(level('a'),0);assert.equal(frames.length,0,'idle has no scheduled work');
flashes.flash([['edge','read']]);tick(9500);assert.ok(level('edge')>0);
flashes.clear();assert.equal(level('edge'),0);assert.equal(cy.$('.accessFlash').length,0);
frames.shift()();assert.equal(frames.length,0,'clear drains the pending frame');
const destroyRenderer=cy.destroyRenderer;
cy.destroy();
// Classify entity phases, including identity changes and deletion of attachments.
const identity=JSON.stringify(['main','item']),id='n:'+identity;
const ref=(phase,role='entity',graph_id=identity)=>({graph_type:'nodes',graph_id,phase,role});
const kinds=event=>JSON.parse(JSON.stringify([...context.accessKinds(event)]));
assert.deepEqual(kinds({references:[ref('after')]}),[[id,'read']]);
assert.deepEqual(kinds({source:'database_change',references:[ref('after')],changed:[id]}),[[id,'create']]);
assert.deepEqual(kinds({source:'database_change',references:[ref('before'),ref('after')],changed:[id]}),[[id,'update']]);
assert.deepEqual(kinds({source:'database_change',operation:'delete',references:[ref('before')],removed:[id]}),[[id,'delete']]);
assert.deepEqual(kinds({source:'database_change',operation:'delete',references:[ref('before','evidence')],changed:[id]}),[[id,'update']]);
assert.deepEqual(kinds({source:'database_change',operation:'insert',references:[ref('after','detail')],changed:[id]}),[[id,'update']]);
const renamed=JSON.stringify(['main','renamed']);
assert.deepEqual(kinds({source:'database_change',references:[ref('before'),ref('after','entity',renamed)]}),[[id,'delete'],['n:'+renamed,'create']]);
assert.deepEqual(kinds({created:['new'],changed:['old'],removed:['gone']}),[['old','update'],['gone','delete'],['new','create']]);
const accumulated=new Map();context.mergeAccess(accumulated,id,'create');context.mergeAccess(accumulated,id,'read');
assert.equal(accumulated.get(id),'create');context.mergeAccess(accumulated,id,'update');assert.equal(accumulated.get(id),'update');

// A deleted node and its edge fade on a separate layer, never rejoining the graph.
const deletedGraph=cytoscape({headless:true,elements:[{data:{id:'keep'},position:{x:10,y:10}},
  {data:{id:'gone',size:24,label:'Gone'},position:{x:40,y:10}},
  {data:{id:'removed-edge',source:'keep',target:'gone'}}]});
let ghostNow=0,scene=[];const ghostFrames=[];
const ghostFlashes=context.createAccessFlashes(deletedGraph,()=>ghostNow,fn=>ghostFrames.push(fn),entries=>scene=entries);
ghostFlashes.remember(deletedGraph.$id('gone').union(deletedGraph.$id('removed-edge')));
deletedGraph.$id('gone').remove();
ghostFlashes.flash([['gone','delete'],['removed-edge','delete']]);
const ghostTick=time=>{ghostNow=time;assert.equal(ghostFrames.length,1);ghostFrames.shift()();};
ghostTick(150);assert.equal(scene.length,2);near(scene[0].opacity,.5);
assert.equal(deletedGraph.nodes().length,1);assert.equal(deletedGraph.edges().length,0);
assert.equal(ghostFlashes.hasGhost('gone'),true);
ghostFlashes.hold(new Map([['gone','delete']]));ghostTick(450);near(scene.find(e=>e.ghost.group==='nodes').opacity,1);
ghostTick(5300);assert.equal(scene.length,1,'recorded deletion remains visible after transient expiry');
ghostFlashes.hold(new Map());ghostTick(5450);near(scene[0].opacity,.5);
ghostTick(5600);assert.equal(scene.length,0);assert.equal(ghostFrames.length,0);
ghostFlashes.hold(new Map([['gone','delete']]));ghostTick(5750);near(scene[0].opacity,.5);
ghostTick(5900);near(scene[0].opacity,1);assert.equal(ghostFrames.length,0,'steady retained deletion does not animate forever');
ghostFlashes.clear(true);assert.equal(scene.length,0);assert.equal(ghostFlashes.hasGhost('gone'),false);
deletedGraph.destroy();

// The overlay follows camera transforms and device pixel ratio in both renderers.
const drawCalls=[];const paintContext={setTransform(...args){drawCalls.push(['transform',...args]);},clearRect(){},setLineDash(){},
  beginPath(){},arc(...args){drawCalls.push(['arc',...args]);},stroke(){},fillText(){},moveTo(){},lineTo(){}};
const canvas={setAttribute(){},getContext:()=>paintContext};
context.document={createElement:()=>canvas};context.window={devicePixelRatio:2};
context.requestAnimationFrame=()=>{};
vm.runInContext(source.slice(source.indexOf('function createDeletedOverlay('),source.indexOf('// One frame loop')),context);
const overlayContainer={childNodes:[],append(child){this.childNodes.push(child);child.parentNode=this;},
  removeChild(child){this.childNodes.splice(this.childNodes.indexOf(child),1);child.parentNode=null;},
  getBoundingClientRect:()=>({width:200,height:100})};
const draw=context.createDeletedOverlay({on(){},zoom:()=>2,pan:()=>({x:10,y:20})},
  overlayContainer);
draw([{ghost:{group:'nodes',position:{x:1,y:2},size:24,label:'Deleted'},opacity:.5,kind:'delete'}]);
assert.equal(canvas.width,400);assert.equal(canvas.height,200);
assert.deepEqual(drawCalls.find(call=>call[0]==='arc').slice(1,3),[12,24]);
assert.equal(paintContext.strokeStyle,'#ff7b87');
destroyRenderer.call({notify(){},container:()=>overlayContainer,_private:{renderer:{}},mutableElements:()=>[]});
assert.equal(canvas.parentNode,null,'actual shipped renderer teardown removes custom children too');
overlayContainer.append({}); // New renderer layer.
draw([{ghost:{group:'nodes',position:{x:1,y:2},size:24,label:'Deleted'},opacity:1,kind:'delete'}]);
assert.equal(canvas.parentNode,overlayContainer,'deletion overlay returns after renderer reinitialization');
console.log('Access flashes: node/edge colors, 300ms attack, accelerating 5s fade, retrigger, expiry and cleanup passed.');
