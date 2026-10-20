import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {RecordingVisitPanel} from './RecordingVisitPanel';
import {parseVisitTranscriptionIntent,visitTranscriptionIntentHash,type RecordingTranscriptionGesture} from './SavedRecordingTranscriptionPanel';
import {privateRecordingApi,type RecordingVisitRequest,type RecordingVisitBinding} from './private-recording-api';
import {workspaceApi,type Workspace,type ProviderTeam} from './workspace-api';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
const mocks=vi.hoisted(()=>({read:vi.fn(),write:vi.fn(),close:vi.fn(),ledger:vi.fn(),open:vi.fn()}));
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
vi.mock('./private-recording-runtime',()=>({openPrivateRecordingStore:async()=>({read:mocks.read,write:mocks.write,close:mocks.close}),PrivateRecordingRuntime:{open:mocks.open}}));
vi.mock('./private-recording-ledger',()=>({PrivateRecordingLedgerController:class{readCurrent=mocks.ledger;}}));
const id=(n:number)=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const identity={mode:'clerk_jwt' as const,getToken:async()=> 'invented'},team={revision:1,recovery_scope:'e'.repeat(64),configuration:{practice_context:'Invented',bots:[{role:'scribe',name:'Scribe',enabled:true,response_style:'brief',include_notebook:false,include_evidence:false}]}} as ProviderTeam;
const origin:Workspace={id:id(1),appointment_id:null,label:'Original private notebook',revision:1,entries:[],work_candidates:[]};
const target:Workspace={id:id(2),appointment_id:id(3),label:'Invented patient · existing visit',revision:7,entries:[],work_candidates:[]};
const taskBot={selection:{address:'scribe',team_revision:1},name:'Scribe',enabled:true,includeNotebook:false};
const receipt={recording_id:id(5),local_recording_id:id(4),workspace_id:origin.id,owner_id:id(11),box_id:id(10),recovery_scope:team.recovery_scope,
  finish:{request_sha256:'d'.repeat(64),manifest_sha256:'b'.repeat(64),chunks:1,frames:16}};
const consent={modality:'in_person',participant_regions:[],method:'verbal_attestation',all_parties_consented:true,granted_at:'2026-10-20T12:00:00.000Z',language:'en-US'};
let root:Root,container:HTMLDivElement,pending:unknown,binding:RecordingVisitBinding|null,access:boolean;
const selected=vi.fn(async(_workspace:Workspace,_binding:RecordingVisitBinding|null,_gesture?:RecordingTranscriptionGesture)=>{});
async function bound(command:RecordingVisitRequest){return {contract:'cosmas.private-recording.visit-binding.v1' as const,receipt_id:id(6),recording_id:id(5),origin_workspace_id:origin.id,target_workspace_id:target.id,appointment_id:id(3),request:command,
  request_sha256:await visitTranscriptionIntentHash({contract:'cosmas.private-recording.visit-binding.v1',request:command}),appointment_sha256:'a'.repeat(64),source_sha256:'c'.repeat(64)};}
const command=()=>({idempotency_key:id(7),target_workspace_id:target.id,appointment_id:id(3),expected_target_revision:7,visit_confirmed:true as const});
beforeEach(()=>{
  Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});pending=null;binding=null;access=true;
  vi.clearAllMocks();vi.stubGlobal('crypto',webcrypto);mocks.read.mockImplementation(async()=>pending);mocks.write.mockImplementation(async(_key,_before,next)=>{pending=structuredClone(next);});
  mocks.ledger.mockResolvedValue({state:'finished',attach:{workspace_id:origin.id},receipt});
  mocks.open.mockResolvedValue({snapshot:{workspaceId:origin.id,phase:'sealed',title:'Invented consent check clip',elapsedSeconds:23},snapshotForLedger:async()=>({recordingId:id(4),phase:'sealed',manifestSHA256:'b'.repeat(64),chunks:1,frames:16,consent,startedAt:'2026-10-20T12:00:00Z'}),close:async()=>{}});
  vi.spyOn(privateRecordingApi,'read').mockResolvedValue(receipt as never);
  vi.spyOn(privateRecordingApi,'readVisitBinding').mockImplementation(async()=>binding);
  vi.spyOn(privateRecordingApi,'bindVisit').mockImplementation(async(_i,_a,_t,_r,request)=>binding=await bound(request));
  vi.spyOn(workspaceApi,'catalog').mockResolvedValue([{workspace_id:target.id,appointment_id:id(3),label:target.label}]);
  vi.spyOn(workspaceApi,'open').mockResolvedValue({identity,team,workspace:target});
  vi.spyOn(workspaceApi,'openExisting').mockResolvedValue({identity,team,workspace:target});
  container=document.createElement('div');document.body.append(container);root=createRoot(container);
});
afterEach(async()=>{await act(async()=>root.unmount());container.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});
async function render(selectedOrigin=origin){await act(async()=>root.render(<RecordingVisitPanel entry={{recordingId:id(4),scope:'a'.repeat(64),platform:'desktop'}} identity={identity} origin={selectedOrigin} team={team} locked={false} isCurrent={()=>access} taskBot={taskBot} onSelected={selected}/>));}
async function waitFor(assert:()=>unknown){const deadline=performance.now()+1500;let failure:unknown;while(performance.now()<deadline){await act(async()=>{await new Promise(resolve=>setTimeout(resolve,5));});try{assert();return;}catch(error){failure=error;}}throw failure;}
const button=()=>[...container.querySelectorAll('button')].find(b=>b.textContent==='Confirm visit and transcribe')!;
async function choose(){await waitFor(()=>expect(container.querySelector('select')).toBeTruthy());
  const select=container.querySelector('select')!;await act(async()=>{select.value=id(3);select.dispatchEvent(new Event('change',{bubbles:true}));});
  expect(button().disabled).toBe(true);await act(async()=>container.querySelector<HTMLInputElement>('input')!.click());}
async function submit(){await act(async()=>button().click());}
it('journals combined consent and the exact source before binding, then hands off one claimable gesture',async()=>{
  await render();await choose();expect(container.textContent).toContain('Invented consent check clip');expect(container.textContent).toContain('0:23 saved recording');expect(container.querySelector('time')?.dateTime).toBe('2026-10-20T12:00:00Z');expect(container.textContent).toContain('everyone agreed to send it to Scribe for transcription');
  await submit();await waitFor(()=>expect(selected).toHaveBeenCalled());
  const intent=await parseVisitTranscriptionIntent(pending);
  expect(intent.request).toMatchObject({target_workspace_id:target.id,expected_target_revision:7,visit_confirmed:true});
  expect(intent).toMatchObject({owner_id:receipt.owner_id,box_id:receipt.box_id,recording_id:receipt.recording_id,local_recording_id:id(4),manifest_sha256:'b'.repeat(64),finish_request_sha256:'d'.repeat(64)});
  expect(mocks.write.mock.invocationCallOrder[0]).toBeLessThan(vi.mocked(privateRecordingApi.bindVisit).mock.invocationCallOrder[0]);
  const gesture=selected.mock.calls[0][2]!;expect(gesture.intent_sha256).toBe(await visitTranscriptionIntentHash(intent));expect(gesture.claim()).toBe(true);expect(gesture.claim()).toBe(false);
  expect(origin.appointment_id).toBe(null);
});
it('changing the selected visit invalidates the unchecked combined consent',async()=>{
  await render();await choose();const select=container.querySelector('select')!;
  await act(async()=>{select.value='';select.dispatchEvent(new Event('change',{bubbles:true}));});
  expect(container.querySelector<HTMLInputElement>('input')!.checked).toBe(false);expect(button().disabled).toBe(true);expect(privateRecordingApi.bindVisit).not.toHaveBeenCalled();
});
it('reopens a saved binding without catalog, mutation or an upload gesture',async()=>{
  binding=await bound(command());await render();await waitFor(()=>expect(selected).toHaveBeenCalledWith(target,binding,undefined));
  expect(workspaceApi.catalog).not.toHaveBeenCalled();expect(privateRecordingApi.bindVisit).not.toHaveBeenCalled();
});
it('requires fresh explicit combined consent to continue a legacy saved request',async()=>{
  pending=command();await render();await waitFor(()=>expect(container.textContent).toContain(target.label));
  expect(button().disabled).toBe(true);expect(privateRecordingApi.bindVisit).not.toHaveBeenCalled();
  await act(async()=>container.querySelector<HTMLInputElement>('input')!.click());await submit();await waitFor(()=>expect(selected).toHaveBeenCalled());
  expect((await parseVisitTranscriptionIntent(pending)).request).toEqual(command());expect(selected.mock.calls[0][2]).toBeDefined();
});
it('resolves a lost successful binding response inside the same action without resending',async()=>{
  vi.mocked(privateRecordingApi.bindVisit).mockImplementationOnce(async(_i,_a,_t,_r,request)=>{binding=await bound(request);throw new Error('Synthetic lost reply');});
  await render();await choose();await submit();await waitFor(()=>expect(selected).toHaveBeenCalled());
  expect(privateRecordingApi.bindVisit).toHaveBeenCalledOnce();expect(privateRecordingApi.readVisitBinding).toHaveBeenCalledTimes(3);
});
it('a definite missing lost binding retries only the retained exact request after an explicit gesture',async()=>{
  vi.mocked(privateRecordingApi.bindVisit).mockRejectedValueOnce(new Error('Synthetic lost reply'));
  await render();await choose();await submit();await waitFor(()=>expect(container.querySelector('[role=alert]')).toBeTruthy());
  const original=structuredClone(pending);expect(selected).not.toHaveBeenCalled();await submit();await waitFor(()=>expect(selected).toHaveBeenCalled());
  expect(vi.mocked(privateRecordingApi.bindVisit).mock.calls.map(c=>c[4])).toEqual([(original as {request:unknown}).request,(original as {request:unknown}).request]);
  expect(pending).toEqual(original);expect(workspaceApi.open).toHaveBeenCalledOnce();
});
it('an unconfirmed binding read cannot authorize a POST or replace the durable intent',async()=>{
  await render();await choose();vi.mocked(privateRecordingApi.readVisitBinding).mockRejectedValueOnce(new Error('Synthetic read lost'));await submit();
  await waitFor(()=>expect(container.querySelector('[role=alert]')).toBeTruthy());const retained=structuredClone(pending);
  expect(privateRecordingApi.bindVisit).not.toHaveBeenCalled();expect(selected).not.toHaveBeenCalled();
  await submit();await waitFor(()=>expect(selected).toHaveBeenCalled());expect(pending).toEqual(retained);
});
it.each(['source','visit','identity'] as const)('rejects changed %s before binding or handing off',async change=>{
  await render();await choose();
  if(change==='source')mocks.open.mockResolvedValue({snapshot:{workspaceId:origin.id,phase:'sealed'},snapshotForLedger:async()=>({recordingId:id(4),phase:'sealed',manifestSHA256:'f'.repeat(64),chunks:1,frames:16,consent}),close:async()=>{}});
  if(change==='visit')vi.mocked(workspaceApi.open).mockResolvedValue({identity,team,workspace:{...target,appointment_id:id(99)}});
  if(change==='identity')vi.mocked(workspaceApi.open).mockResolvedValue({identity:{...identity},team,workspace:target});
  await submit();await waitFor(()=>expect(container.querySelector('[role=alert]')).toBeTruthy());
  expect(privateRecordingApi.bindVisit).not.toHaveBeenCalled();expect(selected).not.toHaveBeenCalled();expect(pending).toBeNull();
});
it('withholds a binding reply after owner authority is lost',async()=>{
  let release!:(value:RecordingVisitBinding)=>void;vi.mocked(privateRecordingApi.bindVisit).mockImplementation(()=>new Promise(resolve=>release=resolve));
  await render();await choose();await submit();await waitFor(()=>expect(release).toBeTypeOf('function'));
  const intent=await parseVisitTranscriptionIntent(pending);access=false;await act(async()=>release(await bound(intent.request)));
  expect(selected).not.toHaveBeenCalled();
});
it('ordinary reopening of combined recovery never claims its persisted consent',async()=>{
  await render();await choose();vi.mocked(privateRecordingApi.bindVisit).mockRejectedValueOnce(new Error('Synthetic lost reply'));await submit();await waitFor(()=>expect(pending).not.toBeNull());
  const intent=await parseVisitTranscriptionIntent(pending);binding=await bound(intent.request);await act(async()=>root.unmount());root=createRoot(container);await render();
  await waitFor(()=>expect(selected).toHaveBeenCalledWith(target,binding,undefined));expect(privateRecordingApi.bindVisit).toHaveBeenCalledOnce();
});
it('withholds a late catalog after leaving the screen',async()=>{
  let release!:(value:Awaited<ReturnType<typeof workspaceApi.catalog>>)=>void;
  vi.mocked(workspaceApi.catalog).mockImplementation(()=>new Promise(resolve=>release=resolve));
  await render();await waitFor(()=>expect(release).toBeTypeOf('function'));await act(async()=>root.unmount());
  await act(async()=>release([{workspace_id:target.id,appointment_id:id(3),label:target.label}]));expect(selected).not.toHaveBeenCalled();expect(mocks.close).toHaveBeenCalled();
});
it('upgrades a legacy exact visit request to combined consent in the real encrypted store and refuses foreign key families',async()=>{
  await render();await choose();await submit();await waitFor(()=>expect(selected).toHaveBeenCalled());const intent=await parseVisitTranscriptionIntent(pending);
  const runtime=await vi.importActual<typeof import('./private-recording-runtime')>('./private-recording-runtime');
  const store=await runtime.openPrivateRecordingStore('a'.repeat(64),'desktop',{indexedDB:new IDBFactory(),crypto:webcrypto});
  const key='visit-binding:'+id(4),request=intent.request;vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);
  try{await store.write(key,null,request);expect(await store.read(key)).toEqual(request);await store.write(key,request,intent);expect(await store.read(key)).toEqual(intent);
    await expect(store.write('unbounded:'+id(4),null,request)).rejects.toThrow();await expect(store.write(key,null,{...request,target_workspace_id:id(99)})).rejects.toThrow();
  }finally{store.close();}
});

it.each(['revision','scope','scribe'] as const)('rejects a freshly opened target with altered %s authority before binding',async change=>{
  await render();await choose();const changed=structuredClone(team);
  if(change==='revision')changed.revision++;
  if(change==='scope')changed.recovery_scope='f'.repeat(64);
  if(change==='scribe')changed.configuration.bots[0].enabled=false;
  vi.mocked(workspaceApi.open).mockResolvedValue({identity,team:changed,workspace:target});await submit();
  await waitFor(()=>expect(container.querySelector('[role=alert]')).toBeTruthy());expect(pending).toBeNull();expect(privateRecordingApi.bindVisit).not.toHaveBeenCalled();expect(selected).not.toHaveBeenCalled();
});
it('withholds an armed handoff if the target authority changes during the post-binding read',async()=>{
  await render();await choose();vi.mocked(workspaceApi.openExisting).mockResolvedValue({identity,team:{...team,recovery_scope:'f'.repeat(64)},workspace:target});await submit();
  await waitFor(()=>expect(container.querySelector('[role=alert]')).toBeTruthy());expect(privateRecordingApi.bindVisit).toHaveBeenCalledOnce();expect(selected).not.toHaveBeenCalled();expect(pending).not.toBeNull();
});

it('a held binding reply cannot hand off after recording-origin replacement returns to the original notebook',async()=>{
  let release!:(value:RecordingVisitBinding)=>void,held!:Promise<RecordingVisitBinding>;
  vi.mocked(privateRecordingApi.bindVisit).mockImplementation(()=>held=new Promise(resolve=>release=resolve));
  await render();await choose();await submit();await waitFor(()=>expect(release).toBeTypeOf('function'));const intent=await parseVisitTranscriptionIntent(pending);
  await render({...origin,id:id(99)});await render();await waitFor(()=>expect(container.textContent).toContain(target.label));
  await act(async()=>{release(await bound(intent.request));await held;});expect(selected).not.toHaveBeenCalled();expect(privateRecordingApi.bindVisit).toHaveBeenCalledOnce();expect(pending).toEqual(intent);
});
