import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,it,expect,vi} from 'vitest';
import actual from './__fixtures__/membership/actual-membership-cross-device-evidence.json';
import {MembershipWorkspaceMount} from './MembershipWorkMount';
import {EditorRecoveryContext,type EditorRecoveryAccess} from './editor-recovery';
import {DraftJournal} from './draft-journal';
import {memoryDraftStorage} from './draft-test-fixture';
import {membershipApi} from './membership-api';
import {membershipSavedDocument,verifyMembershipSavedFinance} from './membership-saved-evidence';
import {verifyMembershipBundle,type MembershipReviewBundle} from './membership-operation';
import {validateMembership} from './membership-contract';
import type {Workspace} from './workspace-api';
import type {PrivatePdfViewerProps} from './PrivatePdfViewer';
vi.mock('./PrivatePdfViewer',()=>({PrivatePdfViewer:({title}:PrivatePdfViewerProps)=><section aria-label={title}/> }));
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
let root:Root,node:HTMLDivElement,bundle:MembershipReviewBundle,journal:DraftJournal,context:EditorRecoveryAccess;
beforeEach(async()=>{
 Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.stubGlobal('crypto',webcrypto);bundle=await verifyMembershipBundle(actual.membership_detail,actual.membership_history);
 const scope=bundle.detail.scope,options=validateMembership('Options',{contract_version:1,scope,patient_link_id:bundle.detail.review.patient_link_id,expected_workspace_revision:bundle.detail.review.proposal.expected_workspace_revision,source:bundle.detail.review.proposal.source,enabled:true,installed_membership_service:'not_selected'});
 vi.spyOn(membershipApi,'bootstrap').mockResolvedValue(options);vi.spyOn(membershipApi,'options').mockResolvedValue(options);vi.spyOn(membershipApi,'catalog').mockResolvedValue({contract_version:1,scope,items:[bundle.detail.summary]});vi.spyOn(membershipApi,'detail').mockResolvedValue(bundle);
 vi.spyOn(membershipApi,'savedFinance').mockImplementation(async(_identity,s,b)=>verifyMembershipSavedFinance(actual.response,s,b));vi.spyOn(membershipApi,'execute');
 vi.spyOn(membershipSavedDocument,'preview').mockResolvedValue({document:bundle.detail.latest_result!.request.ledger!.document,bytes:Uint8Array.from(atob(actual.pdf_base64),c=>c.charCodeAt(0))});
 journal=new DraftJournal(await memoryDraftStorage()({scope:'c'.repeat(64)}));vi.spyOn(journal,'load');vi.spyOn(journal,'persist');
 context={journal,workspaceId:scope.workspace_id,authorize:vi.fn(async()=>({id:scope.workspace_id}) as Workspace),denied:vi.fn()};
 node=document.createElement('div');document.body.append(node);root=createRoot(node);
});
afterEach(async()=>{await act(async()=>root.unmount());journal.close();node.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});
const button=(label:string)=>Array.from(node.querySelectorAll('button')).find(b=>b.textContent===label);
async function wait(check:()=>void){for(let i=0;i<200;i++){let ok=false;await act(async()=>{await new Promise(r=>setTimeout(r,5));try{check();ok=true;}catch{}});if(ok)return;}check();}
async function mount(locked=false,missing=false){const s=bundle.detail.scope;await act(async()=>root.render(<EditorRecoveryContext.Provider value={missing?null:context}><MembershipWorkspaceMount identity={{boxId:s.box_id,actorId:s.owner_id}} workspaceId={s.workspace_id} enabled locked={locked}/></EditorRecoveryContext.Provider>));}
it('mounted fresh storage without prior membership/custody/finance records inspects the saved result without journal writes',async()=>{
 await mount();await wait(()=>expect(node.querySelector<HTMLButtonElement>('.membership-list button')?.disabled).toBe(false));await act(async()=>node.querySelector<HTMLButtonElement>('.membership-list button')!.click());
 await wait(()=>expect(button('Open saved ledger PDF')?.disabled).toBe(false));await act(async()=>button('Open saved ledger PDF')!.click());await wait(()=>expect(node.querySelector('[aria-label="Saved membership ledger evidence"]')).not.toBeNull());
 await act(async()=>button('Inspect saved finance evidence')!.click());await wait(()=>expect(node.textContent).toContain('Current verified finance evidence:'));
 expect(journal.persist).not.toHaveBeenCalled();expect(vi.mocked(journal.load).mock.calls.every(([address])=>address.endsWith(':membership-work'))).toBe(true);expect(membershipApi.execute).not.toHaveBeenCalled();
});
it('honors the parent workspace lock instead of bypassing global recovery failure',async()=>{
 await mount(true);await wait(()=>expect(node.querySelector('.membership-list button')).not.toBeNull());expect(node.querySelector<HTMLButtonElement>('.membership-list button')!.disabled).toBe(true);expect(button('Refresh membership work')!.disabled).toBe(true);expect(membershipApi.detail).not.toHaveBeenCalled();expect(journal.persist).not.toHaveBeenCalled();
});
it('missing parent recovery context does not mount an inspection bypass',async()=>{
 await mount(false,true);expect(node.textContent).toContain('Checking private encounter access and recovery');expect(membershipApi.bootstrap).not.toHaveBeenCalled();expect(node.querySelector('.membership-list')).toBeNull();expect(journal.persist).not.toHaveBeenCalled();
});
