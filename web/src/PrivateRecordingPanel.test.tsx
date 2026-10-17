import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
import type {CaptureSource,CaptureSourceStartOptions} from '../../clients/capture/src/capture/source';
import {PrivateRecordingPanel,type PrivateRecordingPanelProps,type PrivateNotebookResult} from './PrivateRecordingPanel';
import {PrivateRecordingRuntime,openPrivateRecordingStore,listPrivateRecordings,type PrivateRecordingNativeReceipt} from './private-recording-runtime';
import {workspaceApi,WorkspaceApiError} from './workspace-api';
import {privateRecordingApi,type PrivateRecordingReceipt,type PrivateRecordingIntent} from './private-recording-api';
import {vendorCanonical,vendorSha256} from './vendor-contract';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const {Blob:NodeBlob}=await vi.importActual<{Blob:typeof Blob}>('node:buffer');
const scope='b'.repeat(64),id='00000000-0000-4000-8000-000000000001';
const identity={mode:'clerk_jwt' as const,getToken:vi.fn()};
const notebook:PrivateNotebookResult={identity,workspace:{id,appointment_id:null,label:'Private recording',revision:0,entries:[],work_candidates:[],private_draft:{title:'Private recording',state:'unlinked',link_receipt_id:null,linked_at:null}},team:{revision:1,recovery_scope:scope,template_version:'provider-team-v1',llm:{enabled:false,model:'gpt-4.1'},configuration:{practice_context:'',bots:[]},members:[]}};
function wav(sample:number){
  const bytes=new Uint8Array(76),d=new DataView(bytes.buffer),text=(at:number,value:string)=>[...value].forEach((c,i)=>bytes[at+i]=c.charCodeAt(0));
  text(0,'RIFF');d.setUint32(4,68,true);text(8,'WAVE');text(12,'fmt ');d.setUint32(16,16,true);d.setUint16(20,1,true);d.setUint16(22,1,true);d.setUint32(24,16000,true);d.setUint32(28,32000,true);d.setUint16(32,2,true);d.setUint16(34,16,true);text(36,'data');d.setUint32(40,32,true);for(let n=0;n<16;n++)d.setInt16(44+n*2,sample,true);return bytes;
}
/** Generated PCM stands in for a physical microphone; storage/runtime/WAV verification are real. */
class PcmSource implements CaptureSource {
  readonly kind='microphone' as const;options:CaptureSourceStartOptions|null=null;starts=0;stops=0;rejectStop=false;
  async start(options:CaptureSourceStartOptions){this.options=options;this.starts++;}
  async stop(){this.stops++;if(this.rejectStop)throw new Error('Synthetic lost stop');}
  async chunk(sample=42){expect(this.options).not.toBeNull();const bytes=wav(sample);await this.options!.onChunk({sequenceNumber:0,durationMs:1,wavBytes:bytes});expect([...bytes]).toEqual(Array(bytes.length).fill(0));}
  async confirmRecoveryClosed(){return true;}
}
describe('Private Scribe recording controls with encrypted local PCM',()=>{
  let root:Root,container:HTMLDivElement,factory:IDBFactory,sources:PcmSource[],runtimes:PrivateRecordingRuntime[],props:PrivateRecordingPanelProps;
  const close=vi.fn(),opened=vi.fn(),accessLost=vi.fn(),fetch=vi.fn(),createUrl=vi.fn((_blob:Blob|MediaSource)=> 'blob:private-test'),revokeUrl=vi.fn();
  beforeEach(()=>{
    Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.clearAllMocks();
    vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);vi.stubGlobal('Blob',NodeBlob);vi.stubGlobal('fetch',fetch);
    vi.stubGlobal('URL',Object.assign(URL,{createObjectURL:createUrl,revokeObjectURL:revokeUrl}));localStorage.clear();
    factory=new IDBFactory();sources=[];runtimes=[];
    props={identity,scope,platform:'desktop',isCurrent:()=>true,onClose:close,onNotebook:opened,onAccessLost:accessLost,
      prepareStore:()=>openPrivateRecordingStore(scope,'desktop',{indexedDB:factory,crypto:webcrypto}),
      runtimeFactory:async(options,input)=>{const runtime=await PrivateRecordingRuntime.open({...options,createSource:async()=>{const source=new PcmSource();sources.push(source);return source;},acquireLock:async()=>async()=>{}},input);runtimes.push(runtime);return runtime;}};
    container=document.createElement('div');document.body.append(container);root=createRoot(container);
  });
  afterEach(async()=>{sources.forEach(s=>s.rejectStop=false);await act(async()=>root.unmount());for(const runtime of runtimes)await runtime.close().catch(()=>{});container.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});
  async function wait(check:()=>boolean,timeout=1000){const end=performance.now()+timeout;while(!check()&&performance.now()<end)await act(async()=>{await new Promise(resolve=>setTimeout(resolve,5));});expect(check()).toBe(true);}
  const status=()=>container.querySelector('.private-recording-status strong')?.textContent;
  async function render(){await act(async()=>root.render(<PrivateRecordingPanel {...props}/>));await wait(()=>['Ready for consent','Checking this device’s recording access','Saved on this device'].includes(container.querySelector('.private-recording-status strong')?.textContent??''));}
  function button(name:string){const value=[...container.querySelectorAll('button')].find(b=>b.textContent===name);expect(value,name).toBeTruthy();return value!;}
  async function click(name:string){await act(async()=>button(name).click());}
  async function consent(){
    const check=container.querySelector<HTMLInputElement>('input[type=checkbox]')!;await act(async()=>check.click());
  }
  it('shows saved-recording recovery without new-recording consent while access is pending',async()=>{
    let release!:()=>void;props={...props,recordingId:id,authorize:()=>new Promise<void>(resolve=>release=resolve)};
    await act(async()=>root.render(<PrivateRecordingPanel {...props}/>));
    expect(status()).toBe('Opening saved recording…');expect(container.querySelector('h1')?.textContent).toBe('Private recording');
    expect(container.querySelector('input[type=checkbox]')).toBeNull();expect(container.textContent).not.toContain('Start recording');
    expect(container.textContent).toContain('Play your saved recording');expect(sources).toHaveLength(0);expect(fetch).not.toHaveBeenCalled();
    await click('Close recording');expect(close).toHaveBeenCalledOnce();
    await act(async()=>root.unmount());root=createRoot(container);await act(async()=>release());
  });
  it('shows microphone state before the first saved chunk and reports exact-zero saved audio',async()=>{
    await render();await consent();await click('Start recording');await wait(()=>status()==='Recording');
    expect(container.textContent).toContain('Microphone on');expect(container.textContent).toContain('0:00 saved');expect(sources[0].stops).toBe(0);
    await act(async()=>sources[0].chunk(0));await click('Stop and save recording');await wait(()=>status()==='Saved on this device');
    expect(container.textContent).not.toContain('Microphone on');await click('Play saved recording');
    await wait(()=>container.textContent?.includes('contains no microphone signal')===true);
    expect(container.querySelector('audio')).not.toBeNull();expect(fetch).not.toHaveBeenCalled();
  });
  it('explains an inactive-app pause and requires consent before Resume',async()=>{
    await render();await consent();await click('Start recording');await wait(()=>sources.length===1);
    await act(async()=>sources[0].options!.onInterruption!('capture_backgrounded'));await wait(()=>status()==='Paused');
    expect(container.textContent).toContain('Recording paused when the app became inactive.');
    expect(button('Resume recording').disabled).toBe(true);expect(sources[0].stops).toBe(1);
  });
  it('uses the current private iPhone signal meter and discards late replies after Stop',async()=>{
    const revision='00000000-0000-4000-8000-000000000010';
    props={...props,platform:'ios',identity:{mode:'clerk_jwt',getToken:vi.fn(),nativeSession:{revision,isCurrent:()=>true}},
      prepareNative:async()=>({receiptId:id,revision,expiresAt:new Date(Date.now()+60000).toISOString()}),
      consumeNative:async()=>({receiptId:id,revision})};
    let reply!:(v:unknown)=>void;
    const read=vi.fn(()=>new Promise<unknown>(resolve=>reply=resolve));props.readInputSignal=read;
    await render();await wait(()=>button('Start recording').disabled===true&&status()==='Ready for consent');
    await consent();await click('Start recording');await wait(()=>status()==='Recording'&&read.mock.calls.length===1&&!!container.querySelector('meter'),3000);
    expect(container.querySelector('meter')?.value).toBe(0);
    await click('Stop and save recording');await wait(()=>status()==='Stopped · no audio captured');
    await act(async()=>reply({version:2,signal:{inputBuffers:2,convertedBuffers:2,inputEverNonzero:true,convertedEverNonzero:true,inputLevel:.1,convertedLevel:.1,inputAgeMs:0,convertedAgeMs:0,zeroInputMs:0,inputMuted:false,route:'built_in'}}));
    expect(container.querySelector('meter')).toBeNull();expect(read).toHaveBeenCalledOnce();expect(fetch).not.toHaveBeenCalled();
  });
  it('prewarms without microphone or HTTP and starts before a held notebook response, then saves/reopens verified PCM',async()=>{
    let release!:(value:PrivateNotebookResult)=>void;props.prepareNotebook=vi.fn(()=>new Promise<PrivateNotebookResult>(resolve=>release=resolve));
    await render();expect(sources).toHaveLength(0);expect(runtimes).toHaveLength(0);expect(fetch).not.toHaveBeenCalled();expect(button('Start recording').disabled).toBe(true);
    expect(container.textContent).not.toContain('Where everyone is located');
    await consent();await click('Start recording');await wait(()=>status()==='Recording');
    expect(sources[0].starts).toBe(1);expect(opened).not.toHaveBeenCalled();expect(button('Close recording').disabled).toBe(true);
    await act(async()=>sources[0].chunk());await act(async()=>release(notebook));await wait(()=>runtimes[0].snapshot.workspaceId===id);
    expect(container.textContent).not.toContain('Open private notebook');await click('Pause recording');await wait(()=>container.textContent?.includes('Paused')===true);
    expect(container.querySelector<HTMLInputElement>('input[type=checkbox]')!.checked).toBe(false);expect(button('Resume recording').disabled).toBe(true);
    await consent();await click('Resume recording');await wait(()=>sources.length===2&&sources[1].starts===1);await act(async()=>sources[1].chunk(84));
    await click('Stop and save recording');await wait(()=>status()==='Saved on this device');
    expect(runtimes[0].snapshot.recordedChunks).toBe(2);await click('Play saved recording');await wait(()=>createUrl.mock.calls.length===1);
    const blob=createUrl.mock.calls[0][0] as Blob;const bytes=new Uint8Array(await blob.arrayBuffer());expect(bytes.length).toBe(108);expect(new DataView(bytes.buffer).getInt16(44,true)).toBe(42);expect(new DataView(bytes.buffer).getInt16(76,true)).toBe(84);
    const recordingId=runtimes[0].snapshot.recordingId;await click('Close recording');expect(revokeUrl).toHaveBeenCalledWith('blob:private-test');
    await act(async()=>root.unmount());root=createRoot(container);props={...props,recordingId,prepareNotebook:async()=>notebook};await render();
    expect(sources).toHaveLength(2);expect(container.textContent).toContain('2 saved audio chunks');await click('Open private notebook');expect(opened).toHaveBeenCalledExactlyOnceWith(notebook);
    expect(fetch).not.toHaveBeenCalled();const rows=await listPrivateRecordings(scope,'desktop',()=>openPrivateRecordingStore(scope,'desktop',{indexedDB:factory,crypto:webcrypto}));expect(rows[0]).toMatchObject({recordingId,phase:'sealed',recordedChunks:2,workspaceId:id});
  });
  it('retains a lost notebook result without retry and permits a locally saved recording',async()=>{
    props.prepareNotebook=vi.fn().mockRejectedValue(new WorkspaceApiError(503));await render();await consent();await click('Start recording');await wait(()=>sources.length===1);await act(async()=>sources[0].chunk());await click('Stop and save recording');
    await wait(()=>status()==='Saved on this device');expect(props.prepareNotebook).toHaveBeenCalledOnce();expect(container.textContent).toContain('exact request is retained');expect(container.textContent).not.toContain('Open private notebook');expect(fetch).not.toHaveBeenCalled();
  });
  it('shows a pending microphone stage without claiming recording or polling idle notebook metadata',async()=>{
    const timers=vi.spyOn(globalThis,'setTimeout');
    let finish!:()=>void;const pending=new Promise<void>(resolve=>finish=resolve);
    props.prepareNotebook=async()=>notebook;
    props.runtimeFactory=async(options,input)=>{
      const source=new PcmSource();sources.push(source);
      source.start=async value=>{source.options=value;source.starts++;value.onStartupStage?.('microphone_permission');await pending;};
      const runtime=await PrivateRecordingRuntime.open({...options,createSource:async()=>source,acquireLock:async()=>async()=>{}},input);runtimes.push(runtime);return runtime;
    };
    await render();await consent();await click('Start recording');await wait(()=>status()==='Requesting microphone access');
    expect(button('Stop and save recording').disabled).toBe(false);
    await wait(()=>container.textContent?.includes('Waiting for recording to start')===true);
    expect(container.textContent).not.toContain('Checking notebook recording status');expect(status()).toBe('Requesting microphone access');
    const help=timers.mock.calls.find(call=>call[1]===15000)?.[0];expect(typeof help).toBe('function');
    await act(async()=>{if(typeof help==='function')help();});expect(container.textContent).toContain('Still waiting?');
    await click('Stop and save recording');await wait(()=>status()==='Stopped · no audio captured');
    await act(async()=>finish());expect(status()).toBe('Stopped · no audio captured');
  });

  it('uses the recording option title for both stored audio and notebook preparation',async()=>{
    props.prepareNotebook=vi.fn(async()=>notebook);await render();expect(props.prepareNotebook).not.toHaveBeenCalled();
    const field=container.querySelector<HTMLInputElement>('.private-recording-consent input[maxlength="160"]')!;
    await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(field,'Synthetic follow-up visit');field.dispatchEvent(new Event('input',{bubbles:true}));});
    await consent();await click('Start recording');await wait(()=>status()==='Recording');
    expect(props.prepareNotebook).toHaveBeenCalledExactlyOnceWith('Synthetic follow-up visit');expect(runtimes[0].snapshot.title).toBe('Synthetic follow-up visit');
    await act(async()=>sources[0].chunk());await click('Stop and save recording');await wait(()=>status()==='Saved on this device');
    expect(runtimes[0].snapshot.title).toBe('Synthetic follow-up visit');
  });
  it('withholds former-account audio and stops the producer before reporting changed access',async()=>{
    await render();await consent();await click('Start recording');await wait(()=>sources.length===1);await act(async()=>sources[0].chunk());
    props={...props,isCurrent:()=>false};await act(async()=>root.render(<PrivateRecordingPanel {...props}/>));await wait(()=>accessLost.mock.calls.length===1);
    expect(sources[0].stops).toBe(1);expect(runtimes[0].snapshot.phase).toBe('paused');expect(container.textContent).toContain('Private recording details are hidden');expect(container.textContent).not.toContain('saved audio chunks');expect(container.textContent).not.toContain('Play saved recording');expect(container.querySelector('audio')).toBeNull();
  });
  it('keeps stop uncertainty visible and prevents close, playback and another start until exact stop succeeds',async()=>{
    await render();await consent();await click('Start recording');await wait(()=>sources.length===1);sources[0].rejectStop=true;await click('Stop and save recording');
    await wait(()=>container.textContent?.includes('Microphone stop unconfirmed')===true);expect(button('Close recording').disabled).toBe(true);expect(container.querySelector('audio')).toBeNull();expect(container.textContent).not.toContain('Start recording');
    sources[0].rejectStop=false;await click('Stop and save recording');await wait(()=>status()==='Stopped · no audio captured');expect(sources[0].starts).toBe(1);
  });
  it('prepares current entry authority once in parallel with storage and never starts before it passes',async()=>{
    let allow!:()=>void;props.authorize=vi.fn(()=>new Promise<void>(resolve=>allow=resolve));
    const prepare=props.prepareStore!;props.prepareStore=vi.fn(prepare);
    await act(async()=>root.render(<PrivateRecordingPanel {...props}/>));expect(props.authorize).toHaveBeenCalledOnce();expect(props.prepareStore).toHaveBeenCalledOnce();
    await consent();expect(button('Start recording').disabled).toBe(true);expect(sources).toHaveLength(0);
    await act(async()=>allow());await wait(()=>button('Start recording').disabled===false);await click('Start recording');await wait(()=>sources.length===1);
    expect(props.authorize).toHaveBeenCalledOnce();expect(fetch).not.toHaveBeenCalled();
  });
  it('refuses denied entry authority before creating a recording or invoking the microphone',async()=>{
    props.authorize=vi.fn().mockRejectedValue(new WorkspaceApiError(403));await act(async()=>root.render(<PrivateRecordingPanel {...props}/>));
    await wait(()=>accessLost.mock.calls.length===1);expect(button('Start recording').disabled).toBe(true);expect(runtimes).toHaveLength(0);expect(sources).toHaveLength(0);
    expect(await listPrivateRecordings(scope,'desktop',()=>openPrivateRecordingStore(scope,'desktop',{indexedDB:factory,crypto:webcrypto}))).toEqual([]);
  });
  it('does not retain consent after a failed Start',async()=>{
    props.runtimeFactory=vi.fn().mockRejectedValue(new Error('Synthetic unavailable source'));await render();await consent();await click('Start recording');
    await wait(()=>container.querySelector('[role=alert]')!==null);expect(container.querySelector<HTMLInputElement>('input[type=checkbox]')!.checked).toBe(false);expect(button('Start recording').disabled).toBe(true);expect(sources).toHaveLength(0);
  });
  it('reports a confirmed late notebook only with the original saved recording ID after close',async()=>{
    let finish!:(value:PrivateNotebookResult)=>void;const finalize=vi.fn();props={...props,onNotebookPrepared:finalize,prepareNotebook:()=>new Promise<PrivateNotebookResult>(resolve=>finish=resolve)};
    await render();await consent();await click('Start recording');await wait(()=>status()==='Recording');await act(async()=>sources[0].chunk());
    await click('Stop and save recording');await wait(()=>status()==='Saved on this device');const recordingId=runtimes[0].snapshot.recordingId;
    await click('Close recording');await act(async()=>root.unmount());root=createRoot(container);await act(async()=>finish(notebook));
    expect(finalize).toHaveBeenCalledExactlyOnceWith(notebook,recordingId);expect(opened).not.toHaveBeenCalled();expect(sources).toHaveLength(1);
  });
  it('prewarms and consumes separate native receipts before Start and Resume, with no network on either click',async()=>{
    const revision='00000000-0000-4000-8000-000000000010',nativeIdentity={mode:'clerk_jwt' as const,getToken:vi.fn(),nativeSession:{revision,isCurrent:()=>true}};
    let finish!:(value:PrivateRecordingNativeReceipt)=>void;const native=vi.fn(()=>new Promise<PrivateRecordingNativeReceipt>(resolve=>finish=resolve)),receipts:{receiptId:string;revision:string}[]=[];
    const consume=vi.fn(async(receipt:PrivateRecordingNativeReceipt)=>({receiptId:receipt.receiptId,revision:receipt.revision}));
    props={...props,identity:nativeIdentity,platform:'ios',prepareNative:native,consumeNative:consume};
    // Exercise the real portable runtime; the generated PCM source consumes the exact native receipt.
    props.runtimeFactory=async(options,input)=>{const runtime=await PrivateRecordingRuntime.open({...options,platform:'desktop',createSource:async()=>{const received=options.nativePreparation?.();expect(received).toBeTruthy();receipts.push(received!);const source=new PcmSource();sources.push(source);return source;},acquireLock:async()=>async()=>{}},input);runtimes.push(runtime);return runtime;};
    await render();await consent();expect(button('Start recording').disabled).toBe(true);expect(sources).toHaveLength(0);expect(native).toHaveBeenCalledExactlyOnceWith({scope,revision});
    const receiptId='00000000-0000-4000-8000-000000000011';await act(async()=>finish({receiptId,revision,expiresAt:new Date(Date.now()+60000).toISOString()}));await click('Start recording');await wait(()=>status()==='Recording');
    expect(receipts).toEqual([{receiptId,revision}]);expect(native).toHaveBeenCalledOnce();await click('Pause recording');await wait(()=>native.mock.calls.length===2);expect(button('Resume recording').disabled).toBe(true);
    await consent();const secondId='00000000-0000-4000-8000-000000000012';await act(async()=>finish({receiptId:secondId,revision,expiresAt:new Date(Date.now()+60000).toISOString()}));await click('Resume recording');await wait(()=>status()==='Recording');expect(receipts).toEqual([{receiptId,revision},{receiptId:secondId,revision}]);expect(native).toHaveBeenCalledTimes(2);expect(consume).toHaveBeenCalledTimes(2);expect(fetch).not.toHaveBeenCalled();
  });
  it('shows failed device preparation and retries without location input or starting a microphone',async()=>{
    const revision='00000000-0000-4000-8000-000000000010';
    const native=vi.fn().mockRejectedValueOnce(new Error('Device setup unavailable')).mockResolvedValue({receiptId:'00000000-0000-4000-8000-000000000011',revision,expiresAt:new Date(Date.now()+60000).toISOString()});
    props={...props,identity:{mode:'clerk_jwt',getToken:vi.fn(),nativeSession:{revision,isCurrent:()=>true}},platform:'ios',prepareNative:native};
    await act(async()=>root.render(<PrivateRecordingPanel {...props}/>));await wait(()=>status()==='Recording not ready');
    expect(container.textContent).toContain('this device’s recording access could not be checked');expect(button('Start recording').disabled).toBe(true);expect(sources).toHaveLength(0);
    await click('Try preparing recording again');await wait(()=>status()==='Ready for consent');
    expect(container.textContent).not.toContain('Where everyone is located');await consent();expect(button('Start recording').disabled).toBe(false);expect(sources).toHaveLength(0);
  });
  it('offers a fresh access check after expiry without starting the microphone',async()=>{
    vi.useFakeTimers();
    try{
      const revision='00000000-0000-4000-8000-000000000010';
      const native=vi.fn(async()=>({receiptId:'00000000-0000-4000-8000-000000000011',revision,expiresAt:new Date(Date.now()+60000).toISOString()}));
      props={...props,identity:{mode:'clerk_jwt',getToken:vi.fn(),nativeSession:{revision,isCurrent:()=>true}},platform:'ios',prepareNative:native};
      await act(async()=>root.render(<PrivateRecordingPanel {...props}/>));
      for(let n=0;n<100&&status()!=='Ready for consent';n++)await act(async()=>vi.advanceTimersByTimeAsync(5));
      expect(status()).toBe('Ready for consent');
      await act(async()=>vi.advanceTimersByTimeAsync(60000));
      expect(status()).toBe('Recording not ready');expect(button('Start recording').disabled).toBe(true);
      await click('Try preparing recording again');expect(status()).toBe('Ready for consent');expect(native).toHaveBeenCalledTimes(2);expect(sources).toHaveLength(0);
    }finally{vi.useRealTimers();}
  });
  it('retries recovery of the exact saved recording and retains its verified audio',async()=>{
    await render();await consent();await click('Start recording');await wait(()=>status()==='Recording');await act(async()=>sources[0].chunk(84));
    await click('Stop and save recording');await wait(()=>status()==='Saved on this device');const recordingId=runtimes[0].snapshot.recordingId;
    await act(async()=>root.unmount());root=createRoot(container);
    const original=props.runtimeFactory!,recovery=vi.fn().mockRejectedValueOnce(new Error('Recovery temporarily unavailable')).mockImplementation(original);
    props={...props,recordingId,runtimeFactory:recovery};
    await act(async()=>root.render(<PrivateRecordingPanel {...props}/>));await wait(()=>status()==='Recording not ready');
    await click('Try preparing recording again');await wait(()=>status()==='Saved on this device');
    expect(recovery.mock.calls.map(([,input])=>input.recordingId)).toEqual([recordingId,recordingId]);expect(runtimes.at(-1)!.snapshot).toMatchObject({recordingId,recordedChunks:1,phase:'sealed'});expect(sources).toHaveLength(1);
    await click('Play saved recording');await wait(()=>createUrl.mock.calls.length===1);
    expect(new DataView(await (createUrl.mock.calls[0][0] as Blob).arrayBuffer()).getInt16(44,true)).toBe(84);
  });
  it('keeps one recording controller when minimized and stops with the persistent controls',async()=>{
    await render();await consent();await click('Start recording');await wait(()=>status()==='Recording');
    await act(async()=>sources[0].options!.onInputLevel?.(.42));expect(container.querySelector<HTMLMeterElement>('meter')!.value).toBe(.42);
    props={...props,minimized:true,onExpand:vi.fn()};await act(async()=>root.render(<PrivateRecordingPanel {...props}/>));
    expect(container.querySelector('.private-recording-panel')!.hasAttribute('hidden')).toBe(true);expect(sources).toHaveLength(1);expect(sources[0].stops).toBe(0);
    await act(async()=>sources[0].chunk(84));await click('Pause');await wait(()=>status()==='Paused');expect(button('Stop and save').disabled).toBe(false);await click('Stop and save');await wait(()=>status()==='Saved on this device');
    expect(sources[0].stops).toBe(1);expect(runtimes[0].snapshot.recordedChunks).toBe(1);
    await click('Return to recording');expect(props.onExpand).toHaveBeenCalledOnce();
  });
  it('renames device display metadata without changing the original audio or manifest proof',async()=>{
    await render();await consent();await click('Start recording');await wait(()=>status()==='Recording');await act(async()=>sources[0].chunk(84));await click('Stop and save recording');await wait(()=>status()==='Saved on this device');
    const before=await runtimes[0].snapshotForLedger(),recordingId=runtimes[0].snapshot.recordingId;
    await act(async()=>runtimes[0].rename('Yesterday’s invented recording'));
    const after=await runtimes[0].snapshotForLedger();expect(after.manifestSHA256).toBe(before.manifestSHA256);expect(after.frames).toBe(before.frames);
    await act(async()=>root.unmount());root=createRoot(container);props={...props,recordingId};await render();
    expect(runtimes.at(-1)!.snapshot.title).toBe('Yesterday’s invented recording');await click('Play saved recording');await wait(()=>createUrl.mock.calls.length===1);
    expect(new DataView(await (createUrl.mock.calls[0][0] as Blob).arrayBuffer()).getInt16(44,true)).toBe(84);
  });
  it('connects an unlinked saved clip by explicit selection and saves metadata without rerecording or automatic POST on reopen',async()=>{
    await render();await consent();await click('Start recording');await wait(()=>status()==='Recording');await act(async()=>sources[0].chunk(84));
    await click('Stop and save recording');await wait(()=>status()==='Saved on this device');const recordingId=runtimes[0].snapshot.recordingId;
    await act(async()=>root.unmount());root=createRoot(container);props={...props,recordingId};
    const uuid=(n:number)=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
    const serverScope=await vendorSha256(new TextEncoder().encode(vendorCanonical({contract:'cosmas-private-drafts-v1',box_id:uuid(10),owner_id:uuid(11)})));
    const linked={...notebook,workspace:{...notebook.workspace,revision:1},team:{...notebook.team,recovery_scope:serverScope,
      configuration:{practice_context:'',bots:[{role:'scribe' as const,name:'Scribe',enabled:true,response_style:'brief' as const,include_notebook:true,include_evidence:true}]},
      members:[{role:'scribe' as const,agent_id:uuid(12),name:'Scribe',initials:'S',description:'',prompt:'',capabilities:[]}]}};
    const catalog=vi.spyOn(workspaceApi,'privateDraftSummaries').mockResolvedValue({contract_version:2,has_more:false,drafts:[{workspace_id:id,title:'Synthetic test notebook',revision:1,created_at:new Date().toISOString(),updated_at:new Date().toISOString(),title_revision:0,patient_label:null,visit_at:null,note_state:'draft',duration_seconds:null,recording_state:'none',link_state:'unlinked',appointment_id:null}]});
    const open=vi.spyOn(workspaceApi,'openPrivateDraft').mockResolvedValue(linked);
    let receipt!:PrivateRecordingReceipt;
    const attach=vi.spyOn(privateRecordingApi,'attach').mockImplementation(async(_identity,v:PrivateRecordingIntent)=>receipt={contract:'cosmas.private-recording.v1',custody:'local_device_metadata',recording_id:uuid(3),local_recording_id:recordingId,workspace_id:id,workspace_revision:1,owner_id:uuid(11),box_id:uuid(10),agent_id:uuid(12),team_revision_id:uuid(13),recovery_scope:serverScope,attach_sha256:v.request_sha256,started_at:v.request.started_at,created_at:new Date().toISOString(),state:'unfinished',finish:null,link:null,upstream_capture_admitted:false,audio_uploaded:false,transcription_started:false});
    const finish=vi.spyOn(privateRecordingApi,'finish').mockImplementation(async(_identity,_v,_team,_id,f)=>receipt={...receipt,state:'finished',finish:{receipt_id:uuid(4),request_sha256:f.request_sha256,manifest_sha256:f.request.manifest_sha256,chunks:f.request.chunks,frames:f.request.frames,ended_at:f.request.ended_at}});
    await render();expect(catalog).not.toHaveBeenCalled();expect(attach).not.toHaveBeenCalled();
    await click('Choose private notebook');await wait(()=>container.textContent?.includes('Use notebook: Synthetic test notebook')===true);
    expect(open).not.toHaveBeenCalled();await click('Use notebook: Synthetic test notebook');await wait(()=>container.textContent?.includes('Save recording details to notebook')===true);
    expect(open).toHaveBeenCalledExactlyOnceWith(identity,id);expect(runtimes.at(-1)!.snapshot.workspaceId).toBe(id);expect(attach).not.toHaveBeenCalled();await wait(()=>!button('Save recording details to notebook').disabled);
    await click('Save recording details to notebook');await wait(()=>container.textContent?.includes('Recording details saved to your private notebook')===true);
    expect(attach).toHaveBeenCalledOnce();expect(finish).toHaveBeenCalledOnce();expect(sources).toHaveLength(1);
    await click('Play saved recording');await wait(()=>createUrl.mock.calls.length===1);expect(new DataView(await (createUrl.mock.calls[0][0] as Blob).arrayBuffer()).getInt16(44,true)).toBe(84);
    await act(async()=>root.unmount());root=createRoot(container);props={...props,prepareNotebook:async()=>linked};await render();
    await wait(()=>container.textContent?.includes('Recording details saved to your private notebook')===true);expect(attach).toHaveBeenCalledOnce();expect(finish).toHaveBeenCalledOnce();expect(sources).toHaveLength(1);
  });
  it('withholds a saved-notebook selection result after account access changes',async()=>{
    await render();await consent();await click('Start recording');await wait(()=>status()==='Recording');await act(async()=>sources[0].chunk());await click('Stop and save recording');await wait(()=>status()==='Saved on this device');
    let finish!:(value:PrivateNotebookResult)=>void;
    vi.spyOn(workspaceApi,'privateDraftSummaries').mockResolvedValue({contract_version:2,has_more:false,drafts:[{workspace_id:id,title:'Synthetic test notebook',revision:1,created_at:new Date().toISOString(),updated_at:new Date().toISOString(),title_revision:0,patient_label:null,visit_at:null,note_state:'draft',duration_seconds:null,recording_state:'none',link_state:'unlinked',appointment_id:null}]});
    vi.spyOn(workspaceApi,'openPrivateDraft').mockImplementation(()=>new Promise(resolve=>finish=resolve));
    await click('Choose private notebook');await wait(()=>container.textContent?.includes('Use notebook: Synthetic test notebook')===true);await click('Use notebook: Synthetic test notebook');
    props={...props,isCurrent:()=>false};await act(async()=>root.render(<PrivateRecordingPanel {...props}/>));await act(async()=>finish(notebook));
    expect(runtimes[0].snapshot.workspaceId).toBeNull();expect(container.textContent).not.toContain('Open private notebook');expect(sources).toHaveLength(1);expect(opened).not.toHaveBeenCalled();
  });
  it('keeps playback and Close available during a held notebook catalog and discards its late result',async()=>{
    const busy=vi.fn();props.onBusyChange=busy;
    await render();await consent();await click('Start recording');await wait(()=>status()==='Recording');
    await act(async()=>sources[0].chunk(84));await click('Stop and save recording');await wait(()=>status()==='Saved on this device');
    const recordingId=runtimes[0].snapshot.recordingId;
    let resolve!:(value:Awaited<ReturnType<typeof workspaceApi.privateDraftSummaries>>)=>void;
    vi.spyOn(workspaceApi,'privateDraftSummaries').mockImplementation(()=>new Promise(done=>resolve=done));
    await click('Choose private notebook');expect(button('Choose private notebook').disabled).toBe(true);
    expect(button('Close recording').disabled).toBe(false);expect(button('Play saved recording').disabled).toBe(false);expect(busy.mock.calls.at(-1)).toEqual([false]);
    await click('Play saved recording');await wait(()=>createUrl.mock.calls.length===1);
    expect(new DataView(await (createUrl.mock.calls[0][0] as Blob).arrayBuffer()).getInt16(44,true)).toBe(84);
    await click('Close recording');expect(close).toHaveBeenCalledOnce();
    // Deliberately leave React mounted: completion must be invalidated by Close itself.
    await act(async()=>resolve({contract_version:2,has_more:false,drafts:[{workspace_id:id,title:'Late notebook',revision:1,created_at:new Date().toISOString(),updated_at:new Date().toISOString(),title_revision:0,patient_label:null,visit_at:null,note_state:'draft',duration_seconds:null,recording_state:'none',link_state:'unlinked',appointment_id:null}]}));
    expect(container.textContent).not.toContain('Use notebook: Late notebook');expect(opened).not.toHaveBeenCalled();expect(fetch).not.toHaveBeenCalled();
    await act(async()=>root.unmount());root=createRoot(container);props={...props,recordingId};await render();
    await click('Play saved recording');await wait(()=>createUrl.mock.calls.length===2);
    expect(new DataView(await (createUrl.mock.calls[1][0] as Blob).arrayBuffer()).getInt16(44,true)).toBe(84);expect(sources).toHaveLength(1);
  });
  it('closes while a notebook selection is held without mapping its late response or changing saved audio',async()=>{
    await render();await consent();await click('Start recording');await wait(()=>status()==='Recording');
    await act(async()=>sources[0].chunk(84));await click('Stop and save recording');await wait(()=>status()==='Saved on this device');
    const recordingId=runtimes[0].snapshot.recordingId;
    vi.spyOn(workspaceApi,'privateDraftSummaries').mockResolvedValue({contract_version:2,has_more:false,drafts:[{workspace_id:id,title:'Synthetic test notebook',revision:1,created_at:new Date().toISOString(),updated_at:new Date().toISOString(),title_revision:0,patient_label:null,visit_at:null,note_state:'draft',duration_seconds:null,recording_state:'none',link_state:'unlinked',appointment_id:null}]});
    let resolve!:(value:PrivateNotebookResult)=>void;vi.spyOn(workspaceApi,'openPrivateDraft').mockImplementation(()=>new Promise(done=>resolve=done));
    const attach=vi.spyOn(privateRecordingApi,'attach'),finish=vi.spyOn(privateRecordingApi,'finish');
    await click('Choose private notebook');await click('Use notebook: Synthetic test notebook');
    expect(button('Close recording').disabled).toBe(false);await click('Close recording');expect(close).toHaveBeenCalledOnce();
    await act(async()=>resolve(notebook));
    expect(runtimes[0].snapshot.workspaceId).toBeNull();expect(opened).not.toHaveBeenCalled();expect(attach).not.toHaveBeenCalled();expect(finish).not.toHaveBeenCalled();
    const rows=await listPrivateRecordings(scope,'desktop',()=>openPrivateRecordingStore(scope,'desktop',{indexedDB:factory,crypto:webcrypto}));
    expect(rows[0]).toMatchObject({recordingId,workspaceId:null,phase:'sealed',recordedChunks:1});expect(sources).toHaveLength(1);
  });
  async function reopenMappedClip(){
    await render();await consent();await click('Start recording');await wait(()=>status()==='Recording');
    await act(async()=>{await sources[0].chunk(84);await runtimes[0].attachWorkspace(id,true);});
    await click('Stop and save recording');await wait(()=>status()==='Saved on this device');
    const recordingId=runtimes[0].snapshot.recordingId;
    await act(async()=>root.unmount());root=createRoot(container);
    props={...props,recordingId,prepareNotebook:vi.fn().mockRejectedValue(new WorkspaceApiError(503))};
    await render();await wait(()=>container.textContent?.includes('Retry opening private notebook')===true);
    return recordingId;
  }
  it('recovers the same mapped notebook after a failed read without changing audio or dispatching metadata',async()=>{
    const recordingId=await reopenMappedClip();
    const open=vi.spyOn(workspaceApi,'openPrivateDraft').mockRejectedValueOnce(new WorkspaceApiError(503))
      .mockResolvedValueOnce({...notebook,workspace:{...notebook.workspace,id:'00000000-0000-4000-8000-000000000002'}}).mockResolvedValueOnce(notebook);
    const attach=vi.spyOn(privateRecordingApi,'attach'),finish=vi.spyOn(privateRecordingApi,'finish');
    expect(container.textContent).not.toContain('Choose private notebook');
    await click('Retry opening private notebook');await wait(()=>container.textContent?.includes('its notebook link are retained')===true);
    expect(runtimes.at(-1)!.snapshot.workspaceId).toBe(id);expect(button('Close recording').disabled).toBe(false);
    await click('Play saved recording');await wait(()=>createUrl.mock.calls.length===1);
    expect(new DataView(await (createUrl.mock.calls[0][0] as Blob).arrayBuffer()).getInt16(44,true)).toBe(84);
    await click('Retry opening private notebook');await wait(()=>container.textContent?.includes('its notebook link are retained')===true);
    expect(container.textContent).not.toContain('Open private notebook');expect(runtimes.at(-1)!.snapshot.workspaceId).toBe(id);
    await click('Retry opening private notebook');await wait(()=>container.textContent?.includes('Open private notebook')===true);
    expect(open.mock.calls).toEqual([[identity,id],[identity,id],[identity,id]]);expect(props.prepareNotebook).toHaveBeenCalledOnce();
    expect(runtimes.at(-1)!.snapshot).toMatchObject({recordingId,workspaceId:id,recordedChunks:1,phase:'sealed'});
    expect(attach).not.toHaveBeenCalled();expect(finish).not.toHaveBeenCalled();expect(fetch).not.toHaveBeenCalled();expect(sources).toHaveLength(1);
    await click('Open private notebook');expect(opened).toHaveBeenCalledExactlyOnceWith(notebook);
  });
  it('withholds a late mapped-notebook recovery after account access changes',async()=>{
    await reopenMappedClip();let resolve!:(value:PrivateNotebookResult)=>void;
    vi.spyOn(workspaceApi,'openPrivateDraft').mockImplementation(()=>new Promise(done=>resolve=done));
    await click('Retry opening private notebook');
    props={...props,isCurrent:()=>false};await act(async()=>root.render(<PrivateRecordingPanel {...props}/>));
    await act(async()=>resolve(notebook));
    expect(container.textContent).toContain('Recording access changed');expect(container.textContent).not.toContain('Open private notebook');
    expect(runtimes.at(-1)!.snapshot.workspaceId).toBe(id);expect(sources).toHaveLength(1);expect(opened).not.toHaveBeenCalled();expect(fetch).not.toHaveBeenCalled();
  });
  it('closes and plays saved audio during a held mapped-notebook retry without opening its late result',async()=>{
    const recordingId=await reopenMappedClip();let resolve!:(value:PrivateNotebookResult)=>void;
    vi.spyOn(workspaceApi,'openPrivateDraft').mockImplementation(()=>new Promise(done=>resolve=done));
    const attach=vi.spyOn(privateRecordingApi,'attach'),finish=vi.spyOn(privateRecordingApi,'finish');
    await click('Retry opening private notebook');expect(button('Retry opening private notebook').disabled).toBe(true);
    expect(button('Close recording').disabled).toBe(false);expect(button('Play saved recording').disabled).toBe(false);
    await click('Play saved recording');await wait(()=>createUrl.mock.calls.length===1);
    await click('Close recording');expect(close).toHaveBeenCalledOnce();await act(async()=>resolve(notebook));
    expect(opened).not.toHaveBeenCalled();expect(attach).not.toHaveBeenCalled();expect(finish).not.toHaveBeenCalled();expect(fetch).not.toHaveBeenCalled();
    expect(runtimes.at(-1)!.snapshot).toMatchObject({recordingId,workspaceId:id,recordedChunks:1,phase:'sealed'});expect(sources).toHaveLength(1);
  });
});
