import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
import type {CaptureSource,CaptureSourceStartOptions} from '../../clients/capture/src/capture/source';
import {PrivateRecordingPanel,type PrivateRecordingPanelProps,type PrivateNotebookResult} from './PrivateRecordingPanel';
import {PrivateRecordingRuntime,openPrivateRecordingStore,listPrivateRecordings,type PrivateRecordingNativeReceipt} from './private-recording-runtime';
import {WorkspaceApiError} from './workspace-api';
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
  afterEach(async()=>{sources.forEach(s=>s.rejectStop=false);await act(async()=>root.unmount());for(const runtime of runtimes)await runtime.close().catch(()=>{});container.remove();vi.unstubAllGlobals();});
  async function wait(check:()=>boolean){for(let n=0;n<200&&!check();n++)await act(async()=>{await new Promise(resolve=>setTimeout(resolve,5));});expect(check()).toBe(true);}
  const status=()=>container.querySelector('.private-recording-status strong')?.textContent;
  async function render(){await act(async()=>root.render(<PrivateRecordingPanel {...props}/>));await wait(()=>['Ready for consent','Checking this device’s recording access','Saved on this device'].includes(container.querySelector('.private-recording-status strong')?.textContent??''));}
  function button(name:string){const value=[...container.querySelectorAll('button')].find(b=>b.textContent===name);expect(value,name).toBeTruthy();return value!;}
  async function click(name:string){await act(async()=>button(name).click());}
  async function consent(){
    const check=container.querySelector<HTMLInputElement>('input[type=checkbox]')!;await act(async()=>check.click());
  }
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
    await click('Stop and save recording');await wait(()=>status()==='Stopped · no audio captured');
    await act(async()=>finish());expect(status()).toBe('Stopped · no audio captured');
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
});
