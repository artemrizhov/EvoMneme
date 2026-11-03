'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const cytoscape=require('../scripts/viewer/vendor/cytoscape.min.js');
const source=fs.readFileSync(require.resolve('../scripts/viewer/app.js'),'utf8');
const elements=new Map(),windowEvents=new Map(),pending=[];
let document;
function element(id='') {
  const classes=new Set(),listeners=new Map();
  return {id,children:[],inert:false,attributes:{},
    classList:{add:name=>classes.add(name),remove:name=>classes.delete(name),
      contains:name=>classes.has(name),toggle(name,on){if(on)classes.add(name);else classes.delete(name);}},
    append(...items){this.children.push(...items);},prepend(){},before(){},
    replaceChildren(...items){this.children=items;},
    setAttribute(name,value){this.attributes[name]=value;},
    contains(target){return target===this || this.children.some(child=>child.contains?.(target));},
    focus(){document.activeElement=this;},
    addEventListener(name,fn){listeners.set(name,fn);},emit(name,event){listeners.get(name)?.(event);}};
}
function $(id){if(!elements.has(id))elements.set(id,element(id));return elements.get(id);}
document={body:element('body'),activeElement:null,createElement:()=>element()};
$('inspector').append($('closeInspector'),$('depth'),$('detail'));
const cy=cytoscape({headless:true,elements:[
  {data:{id:'a',attributes:{graph_id:'a'}}},{data:{id:'b',attributes:{graph_id:'b',_aggregate:'kind'}}},
  {data:{id:'ab',source:'a',target:'b',attributes:{graph_id:'ab'}}}
]});
const state={view:'graph',selected:null,replay:null};
const context=vm.createContext({$,document,state,cy,
  window:{addEventListener:(name,fn)=>windowEvents.set(name,fn)},
  api:(_route,args)=>new Promise(resolve=>pending.push({args,resolve})),
  guarded:fn=>(...args)=>fn(...args)});
function load(start,end){vm.runInContext(source.slice(source.indexOf(start),source.indexOf(end,source.indexOf(start))),context);}
load('function text(', 'function setConnectionStatus(');
load('function attributes(', 'function openGroup(');
const keydownEnd=source.indexOf('\n});',source.indexOf("window.addEventListener('keydown'"))+4;
vm.runInContext(source.slice(source.indexOf('function openInspector('),keydownEnd),context);
load("cy.on('tap','node,edge'", "cy.on('dbltap'");
const run=code=>vm.runInContext(code,context);
const open=()=>$('inspector').classList.contains('inspector-open');
const expanded=()=>document.body.classList.contains('graph-expanded');
const settle=async(label='row')=>{
  const request=pending.shift();assert.ok(request);
  request.resolve({rows:[{title:label}],evidence:[]});await Promise.resolve();return request;
};
async function main() {
  // Ordinary inspection stays in the sidebar without stealing focus.
  $('expandGraph').focus();cy.$id('a').emit('tap');
  assert.equal(open(),false);assert.equal(document.activeElement,$('expandGraph'));
  await settle();
  run('setGraphExpanded(true)');assert.ok(expanded());assert.equal($('inspector').inert,true);
  cy.$id('a').emit('tap');assert.ok(open());assert.equal($('inspector').inert,false);
  assert.equal(document.activeElement,$('inspector'));
  assert.equal($('detail').children[0].textContent,'Loading selection…');
  assert.equal((await settle('node')).args.type,'nodes');
  $('depth').focus();
  const polling=run('inspect(state.selected)');
  assert.equal($('selectionActions').classList.contains('hidden'),false,'polling must keep focused actions visible');
  await settle('polled');await polling;assert.ok(open());
  // Moving among controls or interacting inside never dismisses the drawer.
  $('inspector').emit('focusout',{relatedTarget:$('depth')});assert.ok(open());
  windowEvents.get('pointerdown')({target:$('detail')});assert.ok(open());
  $('closeInspector').onclick();assert.equal(open(),false);assert.equal($('inspector').inert,true);
  assert.equal(document.activeElement,$('cy'));assert.ok(expanded());
  const refresh=run('inspect(state.selected)');await settle();await refresh;
  assert.equal(open(),false,'polling must not reopen a dismissed selection');
  // Another selected element opens the same panel, including relationship details.
  cy.$id('ab').emit('tap');assert.ok(open());assert.equal((await settle('edge')).args.type,'edges');
  $('inspector').emit('focusout',{relatedTarget:$('fit')});assert.equal(open(),false);
  cy.$id('b').emit('tap');assert.ok(open());assert.equal(pending.length,0);
  assert.equal($('openGroup').classList.contains('hidden'),false);
  windowEvents.get('pointerdown')({target:$('cy')});assert.equal(open(),false);
  state.replay={};cy.$id('a').emit('tap');assert.ok(open());assert.equal(pending.length,0);
  assert.match($('selectionHint').textContent,/Historical/);
  windowEvents.get('blur')();assert.equal(open(),false);state.replay=null;
  // Close while fetching: late details may finish, but cannot reopen the drawer.
  cy.$id('a').emit('tap');$('closeInspector').onclick();await settle();assert.equal(open(),false);
  // A slow old response must never replace a newer selection's evidence.
  cy.$id('a').emit('tap');cy.$id('ab').emit('tap');
  await settle('outdated');assert.equal($('detail').children[0].textContent,'Loading selection…');
  await settle('latest');assert.equal($('detail').children[0].children[1].textContent,'latest');
  const escape={key:'Escape',preventDefault(){this.prevented=true;}};
  windowEvents.get('keydown')(escape);assert.equal(open(),false);assert.ok(expanded());assert.ok(escape.prevented);
  windowEvents.get('keydown')(escape);assert.equal(expanded(),false);assert.equal($('inspector').inert,false);
  assert.equal(document.activeElement,$('expandGraph'));
  run('setGraphExpanded(true)');cy.$id('b').emit('tap');run('setGraphExpanded(false)');
  assert.equal(open(),false);assert.equal($('inspector').inert,false);
  state.view='tables';run('setGraphExpanded(true)');assert.equal(expanded(),false);
  cy.destroy();console.log('Expanded inspector selection, focus, dismissal and async regressions passed');
}
main().catch(error=>{cy.destroy();console.error(error);process.exitCode=1;});
