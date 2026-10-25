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
  large.add(Array.from({length:1101},(_,i)=>({data:{id:'large'+i,label:'Large graph node '+i}})));
  graphLayout.arrange(large,{width:1200,height:500,fit:false});
  assert.equal(large.scratch('memory-layout'),'grid-large');
  assert.equal(new Set(large.nodes().map(n=>n.position('x')+','+n.position('y'))).size,1101);
  assertSeparated(large);
} finally {large.destroy();}

console.log('Graph layout regressions passed: live growth, label separation, manual positions, landscape and portrait orientation.');
