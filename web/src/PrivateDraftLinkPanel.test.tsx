import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {PrivateDraftLinkPanel} from './PrivateDraftLinkPanel';
import {DraftJournal,editorAddress} from './draft-journal';
import {memoryDraftStorage} from './draft-test-fixture';
import type {EditorRecoveryAccess} from './editor-recovery';
import {validatePrivateDraftLinkRecovery} from './private-draft-recovery';
import {workspaceApi,WorkspaceApiError,type AuthenticatedWorkspaceIdentity,type Workspace} from './workspace-api';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const id=(n:number)=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const draft:Workspace={id:id(1),appointment_id:null,label:'Private note',revision:1,entries:[],work_candidates:[],private_draft:{title:'Private note',state:'unlinked',link_receipt_id:null,linked_at:null}};
const linked:Workspace={...draft,appointment_id:id(2),revision:2,private_draft:{title:'Private note',state:'linked',link_receipt_id:id(3),linked_at:'2026-10-07T14:00:00Z'}};
const identity:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:vi.fn()};
let host:HTMLDivElement,root:Root,recovery:EditorRecoveryAccess;
const saved=vi.fn(),denied=vi.fn();
beforeEach(async()=>{vi.clearAllMocks();vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);
 recovery={workspaceId:draft.id,journal:new DraftJournal(await memoryDraftStorage()({scope:'a'.repeat(64)})),authorize:vi.fn().mockResolvedValue(draft),denied};
 vi.spyOn(workspaceApi,'catalog').mockResolvedValue([{appointment_id:id(2),workspace_id:null,label:'Invented confirmed visit'}]);
 vi.spyOn(workspaceApi,'linkAppointment').mockRejectedValue(new WorkspaceApiError(503));
 vi.spyOn(workspaceApi,'resolveAppointmentLink').mockResolvedValue({contract_version:1,outcome:'not_found',link_receipt_id:null,workspace:null});
 host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());recovery.journal.close();host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});
async function mount(account=identity){await act(async()=>root.render(<PrivateDraftLinkPanel identity={account} workspace={draft} recovery={recovery} locked={false} onSaved={saved} onAccessLost={denied}/>));}
async function click(label:string){const button=[...host.querySelectorAll('button')].find(b=>b.textContent===label)!;expect(button,label).toBeTruthy();expect(button.disabled).toBe(false);await act(async()=>button.click());}
async function choose(){await click('Load available visits');await act(async()=>{const select=host.querySelector('select')!;Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value')!.set!.call(select,id(2));select.dispatchEvent(new Event('change',{bubbles:true}));});
 expect([...host.querySelectorAll('button')].find(b=>b.textContent==='Link this visit')!.disabled).toBe(true);await act(async()=>host.querySelector<HTMLInputElement>('input[type=checkbox]')!.click());}
it('retains an uncertain reviewed link across remount, then retries only the original key after explicit lookup',async()=>{
 await mount();expect(workspaceApi.catalog).not.toHaveBeenCalled();await choose();await click('Link this visit');
 const body=vi.mocked(workspaceApi.linkAppointment).mock.calls[0][2];expect(body).toMatchObject({expected_revision:1,appointment_id:id(2),appointment_link_confirmed:true});
 const prior=await recovery.journal.load(editorAddress(draft.id,'private-draft-link'));expect(prior?.pending).toBe(body.idempotency_key);
 await act(async()=>root.unmount());root=createRoot(host);await mount();expect(workspaceApi.linkAppointment).toHaveBeenCalledOnce();
 await click('Check saved visit link');expect(workspaceApi.resolveAppointmentLink).toHaveBeenCalledExactlyOnceWith(identity,draft.id,body);
 expect(await recovery.journal.load(editorAddress(draft.id,'private-draft-link'))).toEqual(prior);expect(saved).not.toHaveBeenCalled();
 vi.mocked(workspaceApi.linkAppointment).mockResolvedValue({entry_revision:2,link_receipt_id:id(3),workspace:linked});await click('Retry same visit link');
 expect(workspaceApi.linkAppointment).toHaveBeenLastCalledWith(identity,draft.id,body);expect(workspaceApi.linkAppointment).toHaveBeenCalledTimes(2);
 expect(saved).toHaveBeenCalledExactlyOnceWith(linked);expect(await recovery.journal.load(editorAddress(draft.id,'private-draft-link'))).toBeNull();
});
it('withholds an old account’s late link result while preserving its exact pending request',async()=>{
 let finish!:(value:Awaited<ReturnType<typeof workspaceApi.linkAppointment>>)=>void;
 vi.mocked(workspaceApi.linkAppointment).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));await mount();await choose();await click('Link this visit');
 await mount({mode:'clerk_jwt',getToken:vi.fn()});await act(async()=>finish({entry_revision:2,link_receipt_id:id(3),workspace:linked}));
 expect(saved).not.toHaveBeenCalled();expect((await recovery.journal.load(editorAddress(draft.id,'private-draft-link')))?.pending).toBeTruthy();
});
it('rejects extra consent fields, non-UUID visits and invalid expected revisions in saved link requests',()=>{
 const data={contract:'private-draft-link-recovery.v1',workspace_id:draft.id,pending:{expected_revision:1,idempotency_key:id(4),appointment_id:id(2),appointment_link_confirmed:true}};
 expect(()=>validatePrivateDraftLinkRecovery({...data,pending:{...data.pending,send_confirmed:true}},draft.id)).toThrow();
 expect(()=>validatePrivateDraftLinkRecovery({...data,pending:{...data.pending,appointment_id:'unconfirmed label'}},draft.id)).toThrow();
 expect(()=>validatePrivateDraftLinkRecovery({...data,pending:{...data.pending,expected_revision:0}},draft.id)).toThrow();
});
