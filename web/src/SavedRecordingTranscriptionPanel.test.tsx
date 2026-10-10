import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {SavedRecordingTranscriptionPanel} from './SavedRecordingTranscriptionPanel';
import {prepareCapture} from './capture-api';
import {BffResponseError} from '../../clients/capture/src/bff/http-client';
import type {ProviderTeam,Workspace} from './workspace-api';
const mocks=vi.hoisted(()=>({read:vi.fn(),write:vi.fn(),close:vi.fn(),ledger:vi.fn(),runtimeClose:vi.fn(),open:vi.fn()}));
vi.mock('./private-recording-runtime',()=>({openPrivateRecordingStore:async()=>({read:mocks.read,write:mocks.write,close:mocks.close}),PrivateRecordingRuntime:{open:mocks.open}}));
vi.mock('./private-recording-ledger',()=>({PrivateRecordingLedgerController:class{readCurrent=mocks.ledger;}}));
vi.mock('./private-recording-api',()=>({parsePrivateRecordingReceipt:async()=>{},parseRecordingVisitBinding:async()=>{},privateRecordingApi:{read:async()=>receipt}}));
vi.mock('./capture-api',()=>({prepareCapture:vi.fn()}));
const id=(n:number)=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const identity={mode:'clerk_jwt' as const,getToken:async()=>null};
const workspace:Workspace={id:id(1),appointment_id:id(2),label:'Invented visit',revision:1,entries:[],work_candidates:[],private_draft:{title:'Visit',state:'linked',link_receipt_id:id(9),linked_at:'2026-10-09T12:00:00Z'}};
const receipt={local_recording_id:id(3),recording_id:id(4),workspace_id:id(1),state:'linked_metadata',link:{receipt_id:id(5),source_sha256:'a'.repeat(64),workspace_link_receipt_id:id(9)},finish:{manifest_sha256:'b'.repeat(64),chunks:1,frames:1}};
const admission={key:id(6),language:'en-US',attestation:{modality:'in_person',participant_regions:[],method:'verbal_attestation',all_parties_consented:true,granted_at:'2026-10-09T12:00:00Z'},source:{recording_id:id(4),link_receipt_id:id(5),source_sha256:'a'.repeat(64),manifest_sha256:'b'.repeat(64),chunks:1,frames:1}};
let root:Root,host:HTMLDivElement,stored:unknown;
const back=vi.fn(),navigation=vi.fn();
beforeEach(()=>{
  Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.clearAllMocks();
  HTMLElement.prototype.scrollIntoView=vi.fn();
  stored={contract:'cosmas.saved-transfer.v1',recording_id:id(3),workspace_id:id(1),scope:'c'.repeat(64),link_request:null,receipt,admission:structuredClone(admission),admitted:null};
  mocks.read.mockImplementation(async()=>structuredClone(stored));
  mocks.write.mockImplementation(async(_key,_before,next)=>{stored=structuredClone(next);});
  mocks.ledger.mockResolvedValue({state:'finished',attach:{},receipt,finish:{}});
  mocks.open.mockResolvedValue({snapshot:{workspaceId:id(1),phase:'sealed',recordedChunks:1,elapsedSeconds:19},close:mocks.runtimeClose,
    snapshotForLedger:async()=>({phase:'sealed',manifestSHA256:'b'.repeat(64),chunks:1,frames:1}),
    savedChunks:async function*(){const wavBytes=new Uint8Array(46);wavBytes[44]=1;yield{wavBytes};}});
  host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();});
const button=(name:string)=>[...host.querySelectorAll('button')].find(b=>b.textContent===name);
async function mount(){await act(async()=>root.render(<SavedRecordingTranscriptionPanel entry={{recordingId:id(3),scope:'c'.repeat(64),platform:'desktop'}} identity={identity} workspace={workspace} team={{revision:1} as ProviderTeam}
  isCurrent={()=>true} locked={false} notesEnabled={false} onDraftLock={()=>{}} onReviewDraft={()=>{}} onCurrentDraft={()=>{}} notebookDirty={false} onNotebook={()=>{}}
  onRecordings={back} onNavigationLock={navigation} taskBot={{selection:{address:'scribe',team_revision:1},name:'Scribe',enabled:true,includeNotebook:false}}/>));
  await vi.waitFor(()=>expect(button('Continue transcription')?.disabled).toBe(false));}
it.each(['capture_request_conflict','capture_consent_required','capture_consent_unavailable'])('retains exact intent and offers recordings rather than futile retry for %s',async code=>{
  const original=structuredClone(stored);
  vi.mocked(prepareCapture).mockRejectedValue(new BffResponseError(409,code,null));
  await mount();await act(async()=>button('Continue transcription')!.click());
  expect(host.querySelector('[role="alert"]')?.textContent).toContain('Your audio is saved');
  expect(button('Continue transcription')).toBeUndefined();expect(host.textContent).toContain(code);
  expect(stored).toEqual(original);expect(prepareCapture).toHaveBeenCalledOnce();
  await act(async()=>button('Return to recordings')!.click());expect(back).toHaveBeenCalledOnce();
  expect(navigation.mock.calls.some(call=>call[0]===true)).toBe(true);expect(navigation.mock.calls.at(-1)).toEqual([false]);
});
it('keeps the exact retry for an uncertain response without exposing private error text',async()=>{
  vi.mocked(prepareCapture).mockRejectedValue(new BffResponseError(503,'private-response-must-not-appear',null));
  await mount();await act(async()=>button('Continue transcription')!.click());
  expect(button('Continue transcription')?.disabled).toBe(false);expect(host.textContent).not.toContain('private-response-must-not-appear');
  await act(async()=>button('Continue transcription')!.click());
  expect(vi.mocked(prepareCapture).mock.calls[0]).toEqual(vi.mocked(prepareCapture).mock.calls[1]);
});

it('requires fresh explicit consent only after a definite no-admission result and retains earlier intent across reopen',async()=>{
  const original=structuredClone(admission);
  vi.mocked(prepareCapture).mockRejectedValueOnce(new BffResponseError(409,'capture_recording_consent_required',null)).mockRejectedValue(new BffResponseError(503,'unconfirmed',null));
  await mount();await act(async()=>button('Continue transcription')!.click());
  const send=button('Send recording with confirmed consent');expect(send?.disabled).toBe(true);
  expect(host.textContent).toContain('expired before Scribe accepted');
  await act(async()=>(host.querySelector('input[type="checkbox"]') as HTMLInputElement).click());
  expect(send?.disabled).toBe(false);await act(async()=>send!.click());
  const retained=stored as {contract:string;admission:typeof admission;prior_admissions:typeof admission[];renew_saved_consent:boolean};
  expect(retained.contract).toBe('cosmas.saved-transfer.v3');expect(retained.prior_admissions).toEqual([original]);
  expect(retained.admission.source).toEqual(original.source);expect(retained.admission.key).not.toBe(original.key);
  expect(retained.renew_saved_consent).toBe(true);expect(vi.mocked(prepareCapture).mock.calls[1][8]).toBe(true);
  await act(async()=>root.unmount());root=createRoot(host);await mount();
  await act(async()=>button('Continue transcription')!.click());
  expect(vi.mocked(prepareCapture).mock.calls[2]).toEqual(vi.mocked(prepareCapture).mock.calls[1]);
  expect((stored as typeof retained).prior_admissions).toEqual([original]);
});
