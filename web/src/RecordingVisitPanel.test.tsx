import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {RecordingVisitPanel} from './RecordingVisitPanel';
import {privateRecordingApi,type RecordingVisitRequest,type RecordingVisitBinding} from './private-recording-api';
import {workspaceApi,type Workspace,type ProviderTeam} from './workspace-api';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
const mocks=vi.hoisted(()=>({read:vi.fn(),write:vi.fn(),close:vi.fn(),ledger:vi.fn()}));
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
vi.mock('./private-recording-runtime',()=>({openPrivateRecordingStore:async()=>({read:mocks.read,write:mocks.write,close:mocks.close})}));
vi.mock('./private-recording-ledger',()=>({PrivateRecordingLedgerController:class{readCurrent=mocks.ledger;}}));
const id=(n:number)=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const identity={mode:'clerk_jwt' as const,getToken:async()=> 'invented'},team={revision:1} as ProviderTeam;
const origin:Workspace={id:id(1),appointment_id:null,label:'Original private notebook',revision:1,entries:[],work_candidates:[]};
const target:Workspace={id:id(2),appointment_id:id(3),label:'Invented patient · existing visit',revision:7,entries:[],work_candidates:[]};
let root:Root,container:HTMLDivElement,pending:unknown,binding:RecordingVisitBinding|null;
const selected=vi.fn(async()=>{});
beforeEach(()=>{
  Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});pending=null;binding=null;
  vi.clearAllMocks();mocks.read.mockImplementation(async()=>pending);mocks.write.mockImplementation(async(_key,_before,next)=>{pending=next;});
  mocks.ledger.mockResolvedValue({state:'finished',attach:{workspace_id:origin.id},receipt:{recording_id:id(5)}});
  vi.spyOn(privateRecordingApi,'read').mockResolvedValue({recording_id:id(5)} as never);
  vi.spyOn(privateRecordingApi,'readVisitBinding').mockImplementation(async()=>binding);
  vi.spyOn(privateRecordingApi,'bindVisit').mockImplementation(async(_i,_a,_t,_r,command)=>{binding={contract:'cosmas.private-recording.visit-binding.v1',receipt_id:id(6),recording_id:id(5),origin_workspace_id:origin.id,target_workspace_id:target.id,appointment_id:id(3),request:command,request_sha256:'a'.repeat(64),appointment_sha256:'b'.repeat(64),source_sha256:'c'.repeat(64)};return binding;});
  vi.spyOn(workspaceApi,'catalog').mockResolvedValue([{workspace_id:target.id,appointment_id:id(3),label:target.label}]);
  vi.spyOn(workspaceApi,'open').mockResolvedValue({identity,team,workspace:target});
  vi.spyOn(workspaceApi,'openExisting').mockResolvedValue({identity,team,workspace:target});
  container=document.createElement('div');document.body.append(container);root=createRoot(container);
});
afterEach(async()=>{await act(async()=>root.unmount());container.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});
async function render(){await act(async()=>root.render(<RecordingVisitPanel entry={{recordingId:id(4),scope:'a'.repeat(64),platform:'desktop'}} identity={identity} origin={origin} team={team} locked={false} isCurrent={()=>true} onSelected={selected}/>));}
const button=()=>container.querySelector<HTMLButtonElement>('button')!;
async function choose(){await vi.waitFor(()=>expect(container.querySelector('select')).toBeTruthy());
  const select=container.querySelector('select')!;await act(async()=>{select.value=id(3);select.dispatchEvent(new Event('change',{bubbles:true}));});
  expect(button().disabled).toBe(true);await act(async()=>container.querySelector<HTMLInputElement>('input')!.click());}
it('allows an existing notebook, requires visit confirmation and retains the exact selection before dispatch',async()=>{
  await render();await choose();expect(container.querySelector('option[value="'+id(3)+'"]')?.hasAttribute('disabled')).toBe(false);
  await act(async()=>button().click());await vi.waitFor(()=>expect(selected).toHaveBeenCalledWith(target,binding));
  expect(pending).toMatchObject({target_workspace_id:target.id,expected_target_revision:7,visit_confirmed:true});
  expect(mocks.write.mock.invocationCallOrder[0]).toBeLessThan(vi.mocked(privateRecordingApi.bindVisit).mock.invocationCallOrder[0]);
  expect(origin.appointment_id).toBe(null);
});
it('reopens a saved binding without another catalog or connection mutation',async()=>{
  binding={contract:'cosmas.private-recording.visit-binding.v1',receipt_id:id(6),recording_id:id(5),origin_workspace_id:origin.id,target_workspace_id:target.id,appointment_id:id(3),request:{idempotency_key:id(7),target_workspace_id:target.id,appointment_id:id(3),expected_target_revision:7,visit_confirmed:true},request_sha256:'a'.repeat(64),appointment_sha256:'b'.repeat(64),source_sha256:'c'.repeat(64)};
  await render();await vi.waitFor(()=>expect(selected).toHaveBeenCalledWith(target,binding));
  expect(workspaceApi.catalog).not.toHaveBeenCalled();expect(privateRecordingApi.bindVisit).not.toHaveBeenCalled();
});
it('a lost reply retains the original visit and retries exactly it',async()=>{
  vi.mocked(privateRecordingApi.bindVisit).mockRejectedValueOnce(Error('lost reply'));
  await render();await choose();await act(async()=>button().click());await vi.waitFor(()=>expect(container.textContent).toContain('Continue with saved visit'));
  const original=structuredClone(pending) as RecordingVisitRequest;
  await act(async()=>button().click());await vi.waitFor(()=>expect(selected).toHaveBeenCalled());
  expect(vi.mocked(privateRecordingApi.bindVisit).mock.calls.map(c=>c[4])).toEqual([original,original]);
  expect(workspaceApi.open).toHaveBeenCalledTimes(1);
});
it('withholds a late catalog after the provider leaves the screen',async()=>{
  let release!:(value:Awaited<ReturnType<typeof workspaceApi.catalog>>)=>void;
  vi.mocked(workspaceApi.catalog).mockImplementation(()=>new Promise(resolve=>{release=resolve;}));
  await render();await vi.waitFor(()=>expect(release).toBeTypeOf('function'));
  await act(async()=>root.unmount());await act(async()=>release([{workspace_id:target.id,appointment_id:id(3),label:target.label}]));
  expect(selected).not.toHaveBeenCalled();expect(mocks.close).toHaveBeenCalled();
});
it('stores visit choices in the actual encrypted store and refuses foreign key families',async()=>{
  const runtime=await vi.importActual<typeof import('./private-recording-runtime')>('./private-recording-runtime');
  const store=await runtime.openPrivateRecordingStore('a'.repeat(64),'desktop',{indexedDB:new IDBFactory(),crypto:webcrypto});
  const key='visit-binding:'+id(4),command={idempotency_key:id(7),target_workspace_id:target.id,appointment_id:id(3),expected_target_revision:7,visit_confirmed:true};
  vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);
  try{await store.write(key,null,command);expect(await store.read(key)).toEqual(command);
    await expect(store.write('unbounded:'+id(4),null,command)).rejects.toThrow();
    await expect(store.write(key,null,{...command,target_workspace_id:id(99)})).rejects.toThrow();
  }finally{store.close();}
});
