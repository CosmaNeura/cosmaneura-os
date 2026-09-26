import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,describe,it,expect,vi} from 'vitest';
import actual from './__fixtures__/membership/actual-membership-cross-device-evidence.json';
import {MembershipWorkPanel} from './MembershipWorkPanel';
import {membershipApi} from './membership-api';
import {membershipSavedDocument,verifyMembershipSavedFinance} from './membership-saved-evidence';
import {verifyMembershipBundle,type MembershipReviewBundle} from './membership-operation';
import {validateMembership} from './membership-contract';
import {type MembershipEvidenceAccess} from './membership-evidence';
import {emptyMembershipRecovery,type MembershipRecoveryRecord} from './membership-recovery';


import {WorkspaceApiError} from './workspace-api';
import type {PrivatePdfViewerProps} from './PrivatePdfViewer';
// These tests validate inspection wiring. Actual parser/canvas qualification is
// retained with the shared viewer; fixture callbacks confer no approval here.
vi.mock('./PrivatePdfViewer',()=>({PrivatePdfViewer:({title,onReviewReady}:PrivatePdfViewerProps)=><section aria-label={title}><button onClick={()=>onReviewReady?.(true)}>Fixture inspected pages</button></section>}));
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
describe('read-only saved membership evidence after closure',()=>{
 let root:Root,node:HTMLDivElement,current:MembershipReviewBundle,evidence:MembershipEvidenceAccess,saved:MembershipRecoveryRecord|null,persistCount:number;
 beforeEach(async()=>{
  Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.stubGlobal('crypto',webcrypto);current=await verifyMembershipBundle(actual.membership_detail,actual.membership_history);
  const scope=current.detail.scope;
  const bytes=Uint8Array.from(atob(actual.pdf_base64),c=>c.charCodeAt(0));
  evidence={load:vi.fn(async()=>({scope,documents:[],finance:[]})),preview:vi.fn(async()=>{throw new Error('No local artifact journal');}),financeDetail:vi.fn(async()=>{throw new Error('No original finance journal');})};
  vi.spyOn(membershipSavedDocument,'preview').mockResolvedValue({bytes,document:current.detail.latest_result!.request.ledger!.document});
  vi.spyOn(membershipApi,'savedFinance').mockImplementation(async(_identity,scope,bundle)=>verifyMembershipSavedFinance(actual.response,scope,bundle));
  vi.spyOn(membershipApi,'options').mockResolvedValue(validateMembership('Options',{contract_version:1,scope,patient_link_id:current.detail.review.patient_link_id,expected_workspace_revision:current.detail.review.proposal.expected_workspace_revision,source:current.detail.review.proposal.source,enabled:true,installed_membership_service:'not_selected'}));
  vi.spyOn(membershipApi,'catalog').mockImplementation(async()=>({contract_version:1,scope,items:[current.detail.summary]}));vi.spyOn(membershipApi,'detail').mockImplementation(async()=>structuredClone(current));vi.spyOn(membershipApi,'execute');vi.spyOn(membershipApi,'recover');vi.spyOn(membershipApi,'retire');
  node=document.createElement('div');document.body.append(node);root=createRoot(node);saved=null;persistCount=0;
 });
 afterEach(async()=>{await act(async()=>root.unmount());node.remove();vi.restoreAllMocks();vi.unstubAllGlobals();vi.useRealTimers();});
 const button=(label:string)=>Array.from(node.querySelectorAll('button')).find(b=>b.textContent===label);
 const wait=async(check:()=>void)=>{for(let i=0;i<200;i++){let done=false;await act(async()=>{await new Promise(r=>setTimeout(r,5));try{check();done=true;}catch{}});if(done)return;}check();};
 const click=async(label:string)=>{await wait(()=>expect(button(label)?.matches(':disabled')).toBe(false));await act(async()=>button(label)!.click());};
 const checks=()=>Array.from(node.querySelectorAll<HTMLInputElement>('input[type=checkbox]'));
 const render=async(adapter:MembershipEvidenceAccess|null=evidence,initial:MembershipRecoveryRecord|null=null,withoutJournal=false)=>{
  saved=initial;const access={load:async()=>saved,persist:async(value:MembershipRecoveryRecord|null)=>{persistCount++;saved=structuredClone(value);},authorize:async()=>{},denied:vi.fn()};
  await act(async()=>root.render(<MembershipWorkPanel identity={{boxId:current.detail.scope.box_id,actorId:current.detail.scope.owner_id}} scope={current.detail.scope} recovery={withoutJournal?null:access} evidence={adapter??undefined} enabled/>));
  if(initial)await click('Restore membership draft');await wait(()=>expect(node.querySelector('.membership-list button')).not.toBeNull());await act(async()=>node.querySelector<HTMLButtonElement>('.membership-list button')!.click());await wait(()=>expect(button('Open saved ledger PDF')).toBeDefined());return access;
 };
 const noActions=()=>{expect(membershipApi.execute).not.toHaveBeenCalled();expect(membershipApi.recover).not.toHaveBeenCalled();expect(membershipApi.retire).not.toHaveBeenCalled();expect(saved?.pending??null).toBeNull();expect(checks().every(c=>!c.checked)).toBe(true);};
 it('opens the actual closed result PDF using only its server binding, outside the disabled editor',async()=>{
  const local=emptyMembershipRecovery(current.detail.scope);local.draft.artifact_id=crypto.randomUUID();await render(evidence,local);expect(current.detail.summary.state).toBe('closed');expect(button('Record membership result')?.matches(':disabled')).toBe(true);expect(button('Open saved ledger PDF')?.matches(':disabled')).toBe(false);
  await click('Open saved ledger PDF');await wait(()=>expect(node.querySelector('[aria-label="Saved membership ledger evidence"]')).not.toBeNull());expect(membershipSavedDocument.preview).toHaveBeenCalledWith(expect.anything(),current.detail.scope,current,expect.any(AbortSignal));
  await click('Fixture inspected pages');noActions();expect(saved?.draft.artifact_id).toBe(local.draft.artifact_id);await click('Close saved evidence');expect(node.querySelector('[aria-label="Saved membership ledger evidence"]')).toBeNull();
 });
 it('inspects the exact actual finance verification and fresh recorded detail without changing any choice',async()=>{
  await render();await click('Inspect saved finance evidence');await wait(()=>expect(node.textContent).toContain('Current verified finance evidence: '+actual.response.detail.summary.payment_state));
  expect(membershipApi.savedFinance).toHaveBeenCalledWith(expect.anything(),current.detail.scope,current,expect.any(AbortSignal));expect(evidence.preview).not.toHaveBeenCalled();expect(node.textContent).toContain('$125.00');expect(node.textContent).toContain(actual.response.detail.review.customer.label);noActions();
 });
 it('reads server evidence on another device with no custody or finance journal',async()=>{
  await render(null);await click('Open saved ledger PDF');await wait(()=>expect(node.querySelector('[aria-label="Saved membership ledger evidence"]')).not.toBeNull());
  await click('Inspect saved finance evidence');await wait(()=>expect(node.textContent).toContain('Current verified finance evidence:'));expect(evidence.load).not.toHaveBeenCalled();expect(evidence.financeDetail).not.toHaveBeenCalled();expect(evidence.preview).not.toHaveBeenCalled();noActions();
 });
 it('withholds a later contradictory finance detail and retains the saved source text',async()=>{
  const changed=structuredClone(actual.response.detail);changed.summary.conflicting_evidence=true;vi.mocked(membershipApi.savedFinance).mockImplementation(async(_identity,scope,bundle)=>verifyMembershipSavedFinance({...actual.response,detail:changed},scope,bundle));await render();await click('Inspect saved finance evidence');await wait(()=>expect(node.querySelector('[role="alert"]')).not.toBeNull());expect(node.textContent).not.toContain('Current verified finance evidence:');expect(node.textContent).toContain(current.detail.latest_result!.request.evidence);noActions();
 });
 it('rechecks the saved result after reading bytes and withholds evidence that changed during the read',async()=>{
  await render();const before=structuredClone(current);vi.mocked(membershipApi.detail).mockResolvedValueOnce(before).mockImplementationOnce(async()=>{current.detail.summary.evidence_current='changed';return verifyMembershipBundle(current.detail,current.history);});await click('Open saved ledger PDF');await wait(()=>expect(node.textContent).toContain('The exact saved evidence is unavailable or changed'));expect(membershipSavedDocument.preview).toHaveBeenCalledOnce();expect(node.querySelector('[aria-label="Saved membership ledger evidence"]')).toBeNull();noActions();
 });
 it.each([401,403,404])('clears all saved private content on access denial %s',async status=>{
  await render();await click('Open saved ledger PDF');await wait(()=>expect(node.querySelector('[aria-label="Saved membership ledger evidence"]')).not.toBeNull());vi.mocked(membershipApi.detail).mockRejectedValueOnce(new WorkspaceApiError(status));await click('Inspect saved finance evidence');await wait(()=>expect(node.textContent).toContain('Private membership work is unavailable'));expect(node.textContent).not.toContain(current.detail.latest_result!.request.evidence);expect(node.querySelector('[aria-label="Saved membership ledger evidence"]')).toBeNull();noActions();
 });
 it('clears open evidence when a fresh current result becomes stale',async()=>{
  await render();await click('Open saved ledger PDF');await wait(()=>expect(node.querySelector('[aria-label="Saved membership ledger evidence"]')).not.toBeNull());current.detail.summary.evidence_current='changed';await click('Refresh membership work');await wait(()=>expect(node.querySelector('[aria-label="Saved membership ledger evidence"]')).toBeNull());noActions();
 });
 it('can select and inspect saved work with no membership journal access and makes zero journal writes',async()=>{
  await render(null,null,true);await click('Open saved ledger PDF');await wait(()=>expect(node.querySelector('[aria-label="Saved membership ledger evidence"]')).not.toBeNull());
  await click('Inspect saved finance evidence');await wait(()=>expect(node.textContent).toContain('Current verified finance evidence:'));expect(persistCount).toBe(0);expect(saved).toBeNull();expect(button('Record membership result')?.matches(':disabled')).toBe(true);noActions();
 });
 it('permits historical saved source inspection without enabling new approval',async()=>{
  current.detail.summary.source_current=false;await render(null);await click('Open saved ledger PDF');await wait(()=>expect(node.querySelector('[aria-label="Saved membership ledger evidence"]')).not.toBeNull());expect(button('Approve private review')?.matches(':disabled')).toBe(true);noActions();
 });
 it('aborts an in-flight saved preview on unmount and never publishes late bytes',async()=>{
  let release!:(v:{bytes:Uint8Array;document:import('./membership-schema').Document})=>void;
  vi.mocked(membershipSavedDocument.preview).mockImplementation(()=>new Promise(resolve=>{release=resolve;}));await render(null);await click('Open saved ledger PDF');await wait(()=>expect(membershipSavedDocument.preview).toHaveBeenCalledOnce());
  const signal=vi.mocked(membershipSavedDocument.preview).mock.calls[0][3]!;await act(async()=>root.unmount());root=createRoot(node);expect(signal.aborted).toBe(true);
  await act(async()=>{release({bytes:Uint8Array.from(atob(actual.pdf_base64),c=>c.charCodeAt(0)),document:current.detail.latest_result!.request.ledger!.document});});expect(node.textContent).toBe('');noActions();
 });
 it('ends the entire inspection at60s and cannot publish late private bytes',async()=>{
  let release!:(value:{bytes:Uint8Array;document:import('./membership-schema').Document})=>void;vi.mocked(membershipSavedDocument.preview).mockImplementation(()=>new Promise(resolve=>{release=resolve;}));await render();await wait(()=>expect(button('Open saved ledger PDF')?.matches(':disabled')).toBe(false));
  vi.useFakeTimers();await act(async()=>button('Open saved ledger PDF')!.click());await act(async()=>{await vi.advanceTimersByTimeAsync(1);});expect(membershipSavedDocument.preview).toHaveBeenCalledOnce();
  const signal=vi.mocked(membershipSavedDocument.preview).mock.calls[0][3]!;await act(async()=>{await vi.advanceTimersByTimeAsync(60001);});expect(signal.aborted).toBe(true);expect(node.querySelector('[aria-label="Saved membership ledger evidence"]')).toBeNull();
  vi.useRealTimers();await act(async()=>{release({bytes:Uint8Array.from(atob(actual.pdf_base64),c=>c.charCodeAt(0)),document:current.detail.latest_result!.request.ledger!.document});await new Promise(resolve=>setTimeout(resolve,30));});expect(node.querySelector('[aria-label="Saved membership ledger evidence"]')).toBeNull();noActions();
 });
});
