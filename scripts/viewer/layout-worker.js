/* Same-origin classic worker; uses the same pinned layout engine as the UI. */
'use strict';
importScripts('cytoscape.min.js','graph-layout.js');
self.onmessage=event=>{
  const {id,elements,options}=event.data;
  let graph;
  try {
    const styles=new Map(elements.filter(e=>e.group==='nodes').map(e=>[e.data.id,e.style]));
    const keys=Object.keys(styles.values().next().value || {});
    graph=cytoscape({headless:true,styleEnabled:true,
      elements:elements.map(({style,...element})=>element),layout:{name:'preset'},
      style:[{selector:'node',style:Object.fromEntries(keys.map(key=>[key,node=>styles.get(node.id())[key]]))}]});
    MemoryGraphLayout.arrange(graph,{...options,animate:false,fit:false});
    const positions=graph.nodes().map(n=>[n.id(),{...n.position()}]);
    if(positions.some(([,p])=>!Number.isFinite(p.x) || !Number.isFinite(p.y)))
      throw new Error('Background layout returned invalid coordinates');
    self.postMessage({id,positions,
      layout:graph.scratch('memory-layout')});
  } catch(error) {self.postMessage({id,error:error.message || String(error)});}
  finally {if(graph)graph.destroy();}
};
