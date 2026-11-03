'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../scripts/viewer/app.js'),'utf8');
const defaults={gpu:false,worker:false,elementScale:100,experimentalPromptSeen:false};
const plain=value=>JSON.parse(JSON.stringify(value));
const tick=()=>new Promise(resolve=>setImmediate(resolve));

function harness(saved=defaults,{gpu=true,worker=true,readyState='complete'}={}) {
  const elements=new Map(),events=new Map(),requests=[],refreshes=[];
  const timers=new Map(),eventOptions=new Map();
  let now=0,timerId=0,finishGraph,graphRunning=false;
  function advance(milliseconds) {
    const target=now+milliseconds;
    while(true) {
      const next=[...timers].filter(([,timer])=>timer.at<=target).sort((a,b)=>a[1].at-b[1].at)[0];
      if(!next)break;
      now=next[1].at;timers.delete(next[0]);next[1].fn();
    }
    now=target;
  }
  let storage=plain(saved),readError=null,writeError=null,hold=false;
  const pending=[];
  function $(id) {
    if(!elements.has(id))elements.set(id,{disabled:false,hidden:false,checked:false,value:'',textContent:'',
      open:false,opens:0,showModal(){this.open=true;this.opens++;},close(){this.open=false;},
      addEventListener(name,fn){this[name]=fn;}});
    return elements.get(id);
  }
  const state={acceleration:false,workerLayoutEnabled:false,elementScale:1,activeWork:null};
  const document={readyState,createElement:()=>({getContext:()=>gpu?{getExtension:()=>null}:null})};
  const context=vm.createContext({$,state,console,AbortController,
    setTimeout(fn,delay){const id=++timerId;timers.set(id,{fn,at:now+delay,delay});return id;},
    clearTimeout:id=>timers.delete(id),
    token:'synthetic-token',elementScales:[30,40,50,65,80,100,125,150,200,250,300,400],
    liveLayout:{},backgroundLayout:{cancel(){}},cancelReplayLayout(){},setLayoutStatus(){},setNotice(){},
    document,
    cy:{elements:()=>({updateStyle(){}}),renderer:()=>({webgl:false})},replaceRenderer(){},
    requestedLayout:async()=>{},graphControl:fn=>(...args)=>fn(...args),showError(error){throw error;},
    window:{addEventListener(name,fn,options){events.set(name,fn);eventOptions.set(name,options);}},
    refresh(){refreshes.push(plain(state));graphRunning=true;return new Promise(resolve=>{
      finishGraph=()=>{graphRunning=false;resolve();};
    });},setInterval(){},
    fetch:async(url,options)=>{
      assert.equal(url,'/api/preferences');assert.equal(options.keepalive,true);
      assert.equal(options.headers['X-Viewer-Token'],'synthetic-token');
      const body=JSON.parse(options.body);requests.push(body);
      if(hold)await new Promise(resolve=>pending.push(resolve));
      const error=body.updates?writeError:readError;
      if(!error && body.updates)storage={...storage,...body.updates};
      return {ok:!error,json:async()=>error?{error}:plain(storage)};
    }});
  if(worker)context.Worker=function(){};
  function load(start,end) {
    const first=source.indexOf(start),last=source.indexOf(end,first);
    assert.ok(first>=0 && last>first,'shipped code extraction: '+start);
    vm.runInContext(source.slice(first,last),context);
  }
  load("const graphCancelled=",'function interruptGraphWork(');
  load('async function api(', '// A timer fallback');
  load('function saveVisualPreferences(', "$('cy').addEventListener('webglcontextlost'");
  const startup=source.slice(source.indexOf('async function loadVisualPreferences('));
  assert.ok(startup.trimEnd().endsWith('initializeViewer();'));
  vm.runInContext(startup.replace(/initializeViewer\(\);\s*$/,''),context);
  return {$,state,events,requests,refreshes,run:code=>vm.runInContext(code,context),
    advance,timers,eventOptions,graphRunning:()=>graphRunning,finishGraph:()=>finishGraph(),
    browserLoad(){document.readyState='complete';const callback=events.get('load');
      if(eventOptions.get('load')?.once)events.delete('load');callback?.();},
    saved:()=>storage,setReadError:value=>readError=value,setWriteError:value=>writeError=value,
    hold(value){hold=value;},release(){assert.ok(pending.length);pending.shift()();}};
}

async function main() {
  // The actual startup waits for saved rendering choices before graph refresh.
  const startup=harness({...defaults,gpu:true,worker:true,elementScale:150,experimentalPromptSeen:true});
  startup.hold(true);const initializing=startup.run('initializeViewer()');await tick();
  assert.equal(startup.refreshes.length,0);startup.release();await initializing;
  assert.equal(startup.refreshes.length,1);assert.equal(startup.refreshes[0].acceleration,true);
  assert.equal(startup.refreshes[0].workerLayoutEnabled,true);assert.equal(startup.refreshes[0].elementScale,1.5);
  assert.equal(startup.$('experimentalWelcome').opens,0);

  // The three seconds begin at browser load while initial graph work is pending.
  const loading=harness(defaults,{readyState:'loading'});await loading.run('initializeViewer()');
  assert.equal(loading.eventOptions.get('load').once,true);
  assert.equal(loading.$('experimentalWelcome').opens,0);loading.advance(10000);
  assert.equal(loading.$('experimentalWelcome').opens,0,'no timer before browser load');
  loading.browserLoad();assert.equal(loading.events.has('load'),false);
  assert.equal(loading.$('experimentalWelcome').open,false);loading.advance(2999);
  assert.equal(loading.$('experimentalWelcome').open,false);loading.advance(1);
  assert.equal(loading.$('experimentalWelcome').open,true);
  assert.equal(loading.graphRunning(),true,'prompt does not await initial graph rendering');
  loading.finishGraph();assert.equal(loading.graphRunning(),false);

  // Settings arriving after the deadline still gate the offer on persisted choice.
  for(const seen of [true,false]) {
    const late=harness({...defaults,experimentalPromptSeen:seen},{readyState:'loading'});
    late.hold(true);const starting=late.run('initializeViewer()');await tick();
    late.browserLoad();late.advance(3000);assert.equal(late.$('experimentalWelcome').opens,0);
    late.release();await starting;
    assert.equal(late.$('experimentalWelcome').opens,seen?0:1);
  }

  for(const enabled of [true,false]) {
    const app=harness();await app.run('initializeViewer()');
    assert.equal(app.$('experimentalWelcome').open,false);
    app.advance(2999);assert.equal(app.$('experimentalWelcome').open,false);
    app.advance(1);
    assert.equal(app.$('experimentalWelcome').open,true);
    await app.$(enabled?'tryExperimental':'skipExperimental').onclick();
    assert.equal(app.$('experimentalWelcome').open,false);
    assert.deepEqual(app.saved(),{...defaults,gpu:enabled,worker:enabled,experimentalPromptSeen:true});
    const restart=harness(app.saved());await restart.run('initializeViewer()');restart.advance(3000);
    assert.equal(restart.$('experimentalWelcome').opens,0);
  }
  const escape=harness();await escape.run('initializeViewer()');escape.advance(3000);
  let prevented=false;escape.$('experimentalWelcome').cancel({preventDefault(){prevented=true;}});
  await escape.state.preferenceSave;assert.ok(prevented);
  assert.deepEqual(escape.saved(),{...defaults,experimentalPromptSeen:true});

  for(const gpu of [true,false])for(const worker of [true,false]) {
    const app=harness({...defaults,gpu,worker,elementScale:65,experimentalPromptSeen:true});
    await app.run('loadVisualPreferences()');
    assert.equal(app.state.acceleration,gpu);assert.equal(app.state.workerLayoutEnabled,worker);
    assert.equal(app.state.elementScale,.65);assert.equal(app.$('elementScale').value,'65');
    app.run('setAcceleration(!state.acceleration);setWorkerLayout(!state.workerLayoutEnabled);setElementScale(250)');
    await app.state.preferenceSave;
    assert.deepEqual(app.saved(),{gpu:!gpu,worker:!worker,elementScale:250,experimentalPromptSeen:true});
  }

  const ordered=harness({...defaults,experimentalPromptSeen:true});await ordered.run('loadVisualPreferences()');
  ordered.hold(true);ordered.run('setAcceleration(true);setAcceleration(false);setWorkerLayout(true);setWorkerLayout(false)');
  await tick();assert.equal(ordered.requests.length,2,'only first write starts while blocked');
  ordered.release();await tick();assert.equal(ordered.state.preferencesUnsaved,true,'old save cannot mark newer toggle saved');
  ordered.release();await tick();ordered.release();await tick();ordered.release();await ordered.state.preferenceSave;
  assert.deepEqual(ordered.requests.slice(1).map(row=>[row.updates.gpu,row.updates.worker]),
    [[true,false],[false,false],[false,true],[false,false]]);
  assert.equal(ordered.state.preferencesUnsaved,false);

  const failed=harness({...defaults,experimentalPromptSeen:true});await failed.run('loadVisualPreferences()');
  failed.setWriteError('disk full');failed.run('setAcceleration(true)');await failed.state.preferenceSave;
  assert.equal(failed.state.preferencesUnsaved,true);assert.equal(failed.$('retryPreferences').hidden,false);
  assert.match(failed.$('preferencesStatus').textContent,/could not be saved.*disk full/);
  const unload={preventDefault(){this.prevented=true;}};failed.events.get('beforeunload')(unload);
  assert.equal(unload.prevented,true);
  failed.setWriteError(null);await failed.$('retryPreferences').onclick();
  assert.equal(failed.state.preferencesUnsaved,false);assert.equal(failed.saved().gpu,true);

  const corrupt=harness();corrupt.setReadError('Invalid viewer settings file');await corrupt.run('initializeViewer()');
  assert.equal(corrupt.requests.length,1);assert.equal(corrupt.state.preferencesReady,undefined);
  for(const id of ['experimentalAcceleration','experimentalWorker','elementScale'])assert.equal(corrupt.$(id).disabled,true);
  assert.equal(corrupt.$('experimentalWelcome').opens,0);assert.equal(corrupt.$('retryPreferences').hidden,false);
  await corrupt.run('saveVisualPreferences()');assert.equal(corrupt.requests.length,1,'failed reads never overwrite existing settings');
  corrupt.advance(1000);const timer=[...corrupt.timers.keys()];
  corrupt.setReadError(null);await corrupt.$('retryPreferences').onclick();
  assert.equal(corrupt.state.preferencesReady,true);assert.equal(corrupt.$('elementScale').disabled,false);
  assert.deepEqual([...corrupt.timers.keys()],timer,'retry preserves the original single offer timer');
  corrupt.advance(1999);assert.equal(corrupt.$('experimentalWelcome').opens,0);
  corrupt.advance(1);assert.equal(corrupt.$('experimentalWelcome').opens,1);
  await corrupt.$('retryPreferences').onclick();corrupt.advance(3000);
  assert.equal(corrupt.$('experimentalWelcome').opens,1,'retry cannot duplicate the offer');

  const unavailable=harness({...defaults,gpu:true,worker:true,experimentalPromptSeen:true},{gpu:false,worker:false});
  await unavailable.run('loadVisualPreferences()');
  assert.deepEqual(unavailable.saved(),{...defaults,experimentalPromptSeen:true});
  assert.match(unavailable.$('accelerationStatus').textContent,/unavailable/);

  // Preferences use the shipped API with null graph work, even while cancelled.
  const cancelled=harness({...defaults,experimentalPromptSeen:true});await cancelled.run('loadVisualPreferences()');
  cancelled.state.activeWork={cancelled:true,requests:new Set()};
  cancelled.run('setAcceleration(true)');await cancelled.state.preferenceSave;
  assert.equal(cancelled.saved().gpu,true);assert.equal(cancelled.state.activeWork.requests.size,0);
  assert.equal(cancelled.state.preferencesUnsaved,false);
  console.log('Viewer preferences startup, prompt, persistence, failure and cancellation regressions passed');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
