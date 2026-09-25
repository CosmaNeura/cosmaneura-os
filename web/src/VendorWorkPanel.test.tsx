import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,describe,it,expect,vi} from 'vitest';
import {VendorWorkPanel,canPrepareAnotherDelivery,vendorProposalIssue,vendorVerificationIssue} from './VendorWorkPanel';
import {VendorSharedWorkCard} from './VendorSharedWorkCard';
import {vendorApi} from './vendor-api';
import {actual,shared,retirement,actualRetiredVerification,actualCompletedVerification,actualOptions,actualDetail,actualShared,actualProposal} from './vendor-test-fixture';
import {validateVendor,vendorDigest} from './vendor-contract';
import {emptyVendorRecovery,validateVendorRecovery,type VendorRecoveryAccess,type VendorRecoveryRecord} from './vendor-recovery';
import type {VendorOperation} from './vendor-operation';
import {WorkspaceApiError} from './workspace-api';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const identity={mode:'clerk_jwt' as const,getToken:async()=>'invented-test-token'};
function recovery(initial:VendorRecoveryRecord|null=null){let saved=initial;const access:VendorRecoveryAccess={load:vi.fn(async()=>saved),persist:vi.fn(async value=>{saved=structuredClone(value);}),authorize:vi.fn(async()=>{}),denied:vi.fn()};return {access,value:()=>saved};}
async function receipt(op:VendorOperation){
  const r=op.request;const effect={...actual.approval_receipt.effect,ticket_id:op.target_id??actual.approval_receipt.effect.ticket_id,operation_id:'operation_id'in r?r.operation_id:'proposed_operation_id'in r?r.proposed_operation_id:actualDetail().summary.operation_id,revision_id:'revision_id'in r?r.revision_id:actualDetail().summary.revision_id,payload_hash:'payload_hash'in r?r.payload_hash:actualDetail().summary.payload_hash};
  const v={...actual.approval_receipt,scope:op.scope,command_kind:op.kind,idempotency_key:op.request.idempotency_key,request_sha256:op.request_sha256,effect};const {receipt_sha256:_,...unsigned}=effect;
  effect.receipt_sha256=await vendorDigest('cosmas-vendor-public-receipt.v1',{scope:v.scope,command_kind:v.command_kind,idempotency_key:v.idempotency_key,request_sha256:v.request_sha256,effect:unsigned,summary:v.summary});return validateVendor('CommandResponse',v);
}
async function preparationProof(op:VendorOperation){
  const metadata={receipt_id:crypto.randomUUID(),retired_at:retirement.retired.observed_at};
  const binding={scope:op.scope,command_kind:op.kind,idempotency_key:op.request.idempotency_key,request_sha256:op.request_sha256};
  return validateVendor('PreparationCommandRetirementResponse',{contract_version:1,...binding,outcome:'retired',effect:null,summary:null,retirement:{...metadata,receipt_sha256:await vendorDigest('cosmas-vendor-public-preparation-retirement.v1',{...binding,retirement:metadata})},observed_at:metadata.retired_at});
}
describe('owner and staff delivery surfaces with actual HTTP fixtures',()=>{
  let root:Root,container:HTMLDivElement;
  beforeEach(()=>{Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.stubGlobal('crypto',webcrypto);container=document.createElement('div');document.body.append(container);root=createRoot(container);
    vi.spyOn(Date,'now').mockReturnValue(Date.parse('2026-09-22T00:00:00.000Z'));
    vi.spyOn(vendorApi,'options').mockResolvedValue(actualOptions());vi.spyOn(vendorApi,'catalog').mockResolvedValue(validateVendor('Catalog',actual.catalog));vi.spyOn(vendorApi,'detail').mockResolvedValue(actualDetail());vi.spyOn(vendorApi,'shared').mockResolvedValue(actualShared());vi.spyOn(vendorApi,'execute').mockImplementation(async(_identity,op)=>receipt(op));vi.spyOn(vendorApi,'recover').mockResolvedValue(validateVendor('CommandResponse',actual.proposal_receipt));vi.spyOn(vendorApi,'observations').mockResolvedValue(validateVendor('ObservationPage',actual.observations_empty));
  });
  afterEach(async()=>{await act(async()=>root.unmount());container.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});
  const button=(text:string)=>Array.from(container.querySelectorAll('button')).find(b=>b.textContent===text)!;
  const waitUi=async(check:()=>void)=>{for(let i=0;i<200;i++){let passed=false;await act(async()=>{await new Promise(r=>setTimeout(r,5));try{check();passed=true;}catch{/* Wait for observable UI state, never assume a fixed delay completes crypto or persistence. */}});if(passed)return;}check();};
  const idle=async()=>waitUi(()=>expect(container.querySelector('[aria-busy="true"]')).toBeNull());
  const click=async(text:string)=>{await waitUi(()=>{expect(button(text)).toBeTruthy();expect(button(text).matches(':disabled')).toBe(false);});await act(async()=>button(text).click());await idle();};
  const renderOwner=async(access:VendorRecoveryAccess|null)=>{await act(async()=>root.render(<VendorWorkPanel identity={identity} workspaceId={actualOptions().workspace_id} recovery={access}/>));if(access)await idle();};
  const renderStaff=async(access:VendorRecoveryAccess,item=actualShared())=>{await act(async()=>root.render(<VendorSharedWorkCard identity={identity} item={item} recovery={access}/>));if(access)await idle();};
  const notFound=(op:VendorOperation)=>validateVendor('CommandResponse',{contract_version:1,scope:op.scope,command_kind:op.kind,idempotency_key:op.request.idempotency_key,request_sha256:op.request_sha256,outcome:'not_found',effect:null,summary:null,observed_at:retirement.retired.observed_at});
  const renderRetirement=async(access:VendorRecoveryAccess)=>{const detail=validateVendor('Detail',retirement.manual_detail);vi.mocked(vendorApi.options).mockResolvedValue({...actualOptions(),workspace_id:detail.workspace_id});vi.mocked(vendorApi.catalog).mockResolvedValue({contract_version:1,workspace_id:detail.workspace_id,items:[detail.summary],next_cursor:null,observed_at:detail.observed_at});vi.mocked(vendorApi.detail).mockResolvedValue(detail);await act(async()=>root.render(<VendorWorkPanel identity={identity} workspaceId={detail.workspace_id} recovery={access}/>));await idle();};
  it('restores exact saved commands without automatically sending or reconciling',async()=>{
    const op=await actualProposal(),saved={...emptyVendorRecovery(op.scope),pending:op};const store=recovery(saved);await renderOwner(store.access);
    expect(button('Restore delivery draft')).toBeTruthy();expect(vendorApi.execute).not.toHaveBeenCalled();expect(vendorApi.recover).not.toHaveBeenCalled();
    await click('Restore delivery draft');expect(vendorApi.execute).not.toHaveBeenCalled();await click('Recover saved receipt');
    expect(vendorApi.recover).toHaveBeenCalledWith(identity,op);expect(vendorApi.execute).not.toHaveBeenCalled();expect(store.value()?.receipt?.outcome).toBe('recorded');
  });
  it('checks fresh access on restore and clears unsent sharing without rewriting an exact saved request',async()=>{
    const op=await actualProposal(),saved={...emptyVendorRecovery(op.scope),pending:op};saved.draft.share_to_practice=true;const store=recovery(saved);await renderOwner(store.access);const before=vi.mocked(store.access.authorize).mock.calls.length;
    await click('Restore delivery draft');expect(vi.mocked(store.access.authorize).mock.calls.length).toBe(before+1);expect(store.value()?.draft.share_to_practice).toBe(false);expect(store.value()?.pending).toEqual(op);expect(vendorApi.execute).not.toHaveBeenCalled();
  });
  it('refuses restoration when access was revoked after the offer was loaded',async()=>{
    const op=await actualProposal(),saved={...emptyVendorRecovery(op.scope),pending:op};saved.draft.message='Private retained text';const store=recovery(saved);await renderOwner(store.access);vi.mocked(store.access.authorize).mockRejectedValueOnce(new WorkspaceApiError(403));
    await click('Restore delivery draft');expect(container.textContent).toContain('Access to this private delivery work is unavailable');expect(container.textContent).not.toContain('Private retained text');expect(store.access.persist).not.toHaveBeenCalled();expect(vendorApi.execute).not.toHaveBeenCalled();
  });
  it('saves typing locally without repeated authorization HTTP reads',async()=>{
    const store=recovery();await renderOwner(store.access);const before=vi.mocked(store.access.authorize).mock.calls.length;const text=Array.from(container.querySelectorAll('label')).find(l=>l.textContent?.startsWith('Message to send'))!.querySelector('textarea')!;
    for(const value of ['H','He','Hello'])await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(text,value);text.dispatchEvent(new Event('input',{bubbles:true}));});
    expect(store.value()?.draft.message).toBe('Hello');expect(vi.mocked(store.access.authorize).mock.calls.length).toBe(before);expect(vendorApi.execute).not.toHaveBeenCalled();
  });
  it('binds approval to the exact review and does not automatically send',async()=>{
    const store=recovery();await renderOwner(store.access);const open=Array.from(container.querySelectorAll('button')).find(b=>b.textContent?.includes('Invented patient receives'))!;await act(async()=>open.click());
    expect(button('Approve reviewed delivery').disabled).toBe(true);const check=Array.from(container.querySelectorAll('label')).find(l=>l.textContent?.includes('I reviewed this destination'))!.querySelector('input')!;await act(async()=>check.click());
    await click('Approve reviewed delivery');expect(vendorApi.execute).toHaveBeenCalledTimes(1);const op=vi.mocked(vendorApi.execute).mock.calls[0][1];expect(op.kind).toBe('decide');expect(op.request).toMatchObject({review_sha256:actual.detail_pending.review_sha256,revision_id:actual.detail_pending.summary.revision_id,payload_hash:actual.detail_pending.summary.payload_hash,choice:'approve'});
    expect(store.value()?.pending).toEqual(op);expect(container.textContent).toContain('Vendor delivery: not observed');expect(container.textContent).toContain('Completion verification: pending');
  });
  it('explains a changed source and requires exact receipt recovery and retirement before a fresh review',async()=>{
    const store=recovery();await renderOwner(store.access);const open=Array.from(container.querySelectorAll('button')).find(b=>b.textContent?.includes('Invented patient receives'))!;await act(async()=>open.click());
    const check=Array.from(container.querySelectorAll('label')).find(l=>l.textContent?.includes('I reviewed this destination'))!.querySelector('input')!;await act(async()=>check.click());
    vi.mocked(vendorApi.execute).mockRejectedValueOnce(new WorkspaceApiError(409,'vendor_source_changed'));
    await click('Approve reviewed delivery');const op=store.value()!.pending!;
    expect(container.textContent).toContain('The reviewed note changed.');expect(op.kind).toBe('decide');expect(store.value()?.receipt).toBeNull();expect(button('Edit proposal').disabled).toBe(true);
    vi.mocked(vendorApi.recover).mockResolvedValueOnce(notFound(op));await click('Recover saved receipt');
    expect(button('Edit proposal').disabled).toBe(true);expect(vendorApi.execute).toHaveBeenCalledTimes(1);
    const original=retirement.retired.retirement,r=op.request;
    const metadata={...original,ticket_id:op.target_id!,operation_id:'operation_id'in r?r.operation_id:'',revision_id:'revision_id'in r?r.revision_id:'',payload_hash:'payload_hash'in r?r.payload_hash:''};
    const {receipt_sha256:_,...unsigned}=metadata;
    const proof=validateVendor('RetirementResponse',{...retirement.retired,scope:op.scope,command_kind:op.kind,idempotency_key:r.idempotency_key,request_sha256:op.request_sha256,retirement:{...unsigned,receipt_sha256:await vendorDigest('cosmas-vendor-public-retirement.v1',{scope:op.scope,command_kind:op.kind,idempotency_key:r.idempotency_key,request_sha256:op.request_sha256,retirement:unsigned})}});
    vi.spyOn(vendorApi,'retire').mockResolvedValueOnce(proof);
    await click('Retire this saved attempt');expect(vendorApi.retire).toHaveBeenCalledWith(identity,op);expect(store.value()?.pending).toEqual(op);expect(store.value()?.receipt).toEqual(proof);
    expect(button('Edit proposal').disabled).toBe(false);expect(vendorApi.execute).toHaveBeenCalledTimes(1);expect(container.textContent).toContain('This exact attempt is permanently retired');
  });
  it('offers all requested delivery lanes while explaining separate Spruce approval',async()=>{
    await renderOwner(recovery().access);expect(container.textContent).toContain('Spruce secure message');expect(container.textContent).toContain('Spruce document upload');expect(container.textContent).toContain('SRFax');expect(container.textContent).toContain('Documo fax');expect(container.textContent).toContain('This message or fax needs a separate review and approval.');expect(vendorApi.execute).not.toHaveBeenCalled();
  });
  it('explains missing required date without saving or describing a nonexistent operation as unconfirmed',async()=>{
    const op=await actualProposal(),o=actualOptions(),r=emptyVendorRecovery(op.scope);r.draft={...r.draft,connection_id:o.connections[0].id,correspondence_id:o.correspondences[0].id,source:o.source,message:'Invented message',expected_outcome:'Invented outcome'};const store=recovery(r);await renderOwner(store.access);await click('Restore delivery draft');
    expect(button('Propose for review').disabled).toBe(true);expect(container.textContent).toContain('To propose: Choose a due date.');expect(container.textContent).not.toContain('unconfirmed');expect(store.value()?.pending).toBeNull();expect(vendorApi.execute).not.toHaveBeenCalled();
  });
  it('validates the selected action before creating any command',()=>{
    const o=actualOptions(),d=emptyVendorRecovery({kind:'workspace',id:o.workspace_id}).draft;const ready={...d,connection_id:o.connections[0].id,correspondence_id:o.correspondences[0].id,source:o.source,message:'Invented message',due_date:'2026-10-01',expected_outcome:'Invented outcome'};expect(vendorProposalIssue(o,ready)).toBeNull();
    expect(vendorProposalIssue(o,{...ready,due_date:'2026-02-30'})).toBe('Choose a valid calendar date.');expect(vendorProposalIssue(o,{...ready,message:' '})).toBe('Write the message to send.');expect(vendorProposalIssue(o,{...ready,correspondence_id:''})).toBe('Choose a reviewed recipient.');expect(vendorProposalIssue(o,{...ready,expected_outcome:''})).toBe('Describe the expected outcome.');expect(vendorProposalIssue(o,{...ready,action:'spruce_media_upload'})).toBe('Prepare and select a verified private PDF.');
  });
  it('requires owner-verified vendor evidence when reported success lacks delivery confirmation',async()=>{
    const detail=actualDetail();detail.summary.state='approved';detail.summary.result='recorded_success';detail.summary.acceptance='accepted';detail.summary.transport='not_observed';detail.availability.verify={allowed:true,reason:'available'};
    detail.latest_result={receipt_id:crypto.randomUUID(),receipt_sha256:'a'.repeat(64),actor:{id:crypto.randomUUID(),name:'Invented staff member',available:true},disposition:'reported_success',evidence:'Invented staff report',recorded_at:detail.observed_at,observation_head:detail.summary.observation_head};vi.mocked(vendorApi.detail).mockResolvedValue(detail);
    const store=recovery();await renderOwner(store.access);const open=Array.from(container.querySelectorAll('button')).find(b=>b.textContent?.includes('Invented patient receives'))!;await act(async()=>open.click());await idle();await click('Review recorded delivery evidence');
    for(const label of ['I reviewed this human result','I reviewed all recorded vendor evidence','I confirm the expected outcome']){const input=Array.from(container.querySelectorAll('label')).find(l=>l.textContent?.includes(label))!.querySelector('input')!;await act(async()=>input.click());}
    expect(button('Verify completion').disabled).toBe(true);expect(container.textContent).toContain('A reported success alone cannot confirm completion');expect(store.value()?.pending).toBeNull();expect(vendorApi.execute).not.toHaveBeenCalled();
  });
  it('matches the delivery/manual-proof verification boundary without turning reports into proof',()=>{
    const detail=actualDetail();detail.latest_result={receipt_id:crypto.randomUUID(),receipt_sha256:'a'.repeat(64),actor:{id:crypto.randomUUID(),name:'Invented owner',available:true},disposition:'reported_success',evidence:'Invented report',recorded_at:detail.observed_at,observation_head:detail.summary.observation_head};
    expect(vendorVerificationIssue(detail)).toContain('has not confirmed delivery');detail.summary.acceptance='accepted';detail.summary.transport='delivered';expect(vendorVerificationIssue(detail)).toBeNull();detail.summary.conflicting_evidence=true;expect(vendorVerificationIssue(detail)).toContain('conflicting evidence');detail.latest_result.disposition='verified_in_vendor';expect(vendorVerificationIssue(detail)).toBeNull();detail.latest_result.disposition='unable_to_establish';expect(vendorVerificationIssue(detail)).toContain('Resolve the exception');
  });
  it('retires only on an explicit action, then retains exact request and proof when a manual result starts',async()=>{
    const op=await actualRetiredVerification(),proof=validateVendor('RetirementResponse',retirement.retired),store=recovery({...emptyVendorRecovery(op.scope),pending:op,receipt:notFound(op)});vi.spyOn(vendorApi,'retire').mockResolvedValue(proof);await renderRetirement(store.access);await click('Restore delivery draft');expect(vendorApi.retire).not.toHaveBeenCalled();expect(vendorApi.execute).not.toHaveBeenCalled();await click('Retire this verification attempt');expect(vendorApi.retire).toHaveBeenCalledWith(identity,op);expect(store.value()?.pending).toEqual(op);expect(store.value()?.receipt).toEqual(proof);expect(container.textContent).toContain('permanently retired');
    const disposition=Array.from(container.querySelectorAll('label')).find(l=>l.textContent==='ResultReported successReported exceptionI verified it in the vendor systemUnable to establish the outcome')?.querySelector('select')??Array.from(container.querySelectorAll('select')).find(s=>Array.from(s.options).some(o=>o.value==='verified_in_vendor'))!;
    const evidence=Array.from(container.querySelectorAll('label')).find(l=>l.textContent?.startsWith('Evidence'))!.querySelector('textarea')!;
    await act(async()=>{Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value')!.set!.call(disposition,'verified_in_vendor');disposition.dispatchEvent(new Event('change',{bubbles:true}));Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(evidence,'Invented owner verified the delivery directly in the local vendor fixture.');evidence.dispatchEvent(new Event('input',{bubbles:true}));});await click('Record result');
    expect(vi.mocked(vendorApi.execute).mock.calls.map(c=>c[1].kind)).toEqual(['result']);expect(vi.mocked(vendorApi.execute).mock.calls[0][1].request).toMatchObject({disposition:'verified_in_vendor'});expect(store.value()?.retired_commands).toEqual([{operation:op,receipt:proof}]);expect(store.value()?.receipts).toContainEqual(proof);
  });
  it('preserves the exact unresolved command if saving its retirement proof fails',async()=>{
    const op=await actualRetiredVerification(),old=notFound(op),store=recovery({...emptyVendorRecovery(op.scope),pending:op,receipt:old});vi.spyOn(vendorApi,'retire').mockResolvedValue(validateVendor('RetirementResponse',retirement.retired));await renderRetirement(store.access);await click('Restore delivery draft');vi.mocked(store.access.persist).mockRejectedValueOnce(new Error('CAS refused retirement proof'));await click('Retire this verification attempt');expect(store.value()?.pending).toEqual(op);expect(store.value()?.receipt).toEqual(old);expect(store.value()?.retired_commands).toEqual([]);expect(vendorApi.execute).not.toHaveBeenCalled();expect(container.textContent).toContain('Previous saved commands and receipts are retained');
  });
  it('shows recorded completion distinctly when original verification wins retirement',async()=>{
    const op=await actualCompletedVerification(),store=recovery({...emptyVendorRecovery(op.scope),pending:op,receipt:notFound(op)});vi.spyOn(vendorApi,'retire').mockResolvedValue(validateVendor('CommandResponse',retirement.completed));await renderRetirement(store.access);await click('Restore delivery draft');await click('Retire this verification attempt');expect(store.value()?.receipt?.outcome).toBe('recorded');expect(store.value()?.retired_commands).toEqual([]);expect(container.textContent).toContain('had already recorded this verification');expect(container.textContent).not.toContain('permanently retired');expect(vendorApi.execute).not.toHaveBeenCalled();
  });
  it('closes an unadmitted stale proposal explicitly, then saves a corrected proposal and reopens its retained history',async()=>{
    const op=await actualProposal(),request=op.request,initial=emptyVendorRecovery(op.scope);
    initial.draft={...initial.draft,action:request.action,connection_id:request.connection.id,correspondence_id:request.correspondence!.id,source:request.source,message:request.message!,due_date:request.due_date,expected_outcome:request.expected_outcome};
    const store=recovery({...initial,pending:op}),proof=await preparationProof(op);
    vi.spyOn(vendorApi,'retire').mockResolvedValue(proof);vi.mocked(vendorApi.recover).mockResolvedValue(notFound(op));
    await renderOwner(store.access);await click('Restore delivery draft');
    expect(button('Close this failed preparation')).toBeUndefined();expect(vendorApi.retire).not.toHaveBeenCalled();
    await click('Recover saved receipt');expect(button('Propose for review').matches(':disabled')).toBe(true);
    const fresh=actualOptions();fresh.entry_revision++;fresh.source={...fresh.source!,content_sha256:'f'.repeat(64),source_fingerprint:'e'.repeat(64)};
    vi.mocked(vendorApi.options).mockResolvedValue(fresh);
    await click('Close this failed preparation');
    expect(vendorApi.retire).toHaveBeenCalledWith(identity,op);expect(store.value()?.pending).toEqual(op);expect(store.value()?.receipt).toEqual(proof);
    expect(store.value()?.draft.message).toBe(request.message);expect(store.value()?.draft.source).toEqual(request.source);expect(button('Propose for review').matches(':disabled')).toBe(true);
    await click('Use current reviewed note');await click('Propose for review');
    const next=vi.mocked(vendorApi.execute).mock.calls[0][1];expect(next.request).toMatchObject({source:fresh.source,expected_workspace_revision:fresh.entry_revision});expect(next.request.idempotency_key).not.toBe(request.idempotency_key);
    expect(store.value()?.retired_commands).toEqual([{operation:op,receipt:proof}]);expect(store.value()?.receipts).toContainEqual(proof);
    await validateVendorRecovery(store.value(),op.scope);
    await act(async()=>root.unmount());root=createRoot(container);await renderOwner(store.access);await click('Restore delivery draft');
    expect(container.textContent).toContain('Saved action history (1)');expect(vendorApi.execute).toHaveBeenCalledTimes(1);
  });
  it('keeps the original proposal unresolved when its closure proof cannot be saved',async()=>{
    const op=await actualProposal(),original=notFound(op),store=recovery({...emptyVendorRecovery(op.scope),pending:op,receipt:original});
    vi.spyOn(vendorApi,'retire').mockResolvedValue(await preparationProof(op));await renderOwner(store.access);await click('Restore delivery draft');
    vi.mocked(store.access.persist).mockRejectedValueOnce(new Error('CAS refused preparation closure'));
    await click('Close this failed preparation');
    expect(store.value()?.pending).toEqual(op);expect(store.value()?.receipt).toEqual(original);expect(store.value()?.retired_commands).toEqual([]);
    expect(button('Close this failed preparation')).toBeTruthy();expect(vendorApi.execute).not.toHaveBeenCalled();expect(container.textContent).toContain('Previous saved commands and receipts are retained');
  });
  it('recovers a preparation already admitted instead of claiming it was closed or resubmitting it',async()=>{
    const op=await actualProposal(),saved=validateVendor('CommandResponse',actual.proposal_receipt),store=recovery({...emptyVendorRecovery(op.scope),pending:op,receipt:notFound(op)});
    vi.spyOn(vendorApi,'retire').mockResolvedValue(saved);await renderOwner(store.access);await click('Restore delivery draft');await click('Close this failed preparation');
    expect(store.value()?.receipt).toEqual(saved);expect(store.value()?.retired_commands).toEqual([]);expect(vendorApi.execute).not.toHaveBeenCalled();expect(container.textContent).toContain('already saved this preparation');
  });
  it('edits approved unsubmitted work with fresh source and exact revision binding, retaining the previous receipt',async()=>{
    const op=await actualProposal(),store=recovery({...emptyVendorRecovery(op.scope),pending:op,receipt:validateVendor('CommandResponse',actual.proposal_receipt)});vi.mocked(vendorApi.detail).mockResolvedValue(validateVendor('Detail',actual.detail_approved));
    await renderOwner(store.access);await click('Restore delivery draft');const open=Array.from(container.querySelectorAll('button')).find(b=>b.textContent?.includes('Invented patient receives'))!;await act(async()=>open.click());await click('Edit proposal');
    expect(store.value()?.draft.revises).toEqual({ticket_id:actual.detail_approved.summary.ticket_id,expected_version:actual.detail_approved.summary.version,revision_id:actual.detail_approved.summary.revision_id,payload_hash:actual.detail_approved.summary.payload_hash});expect(store.value()?.draft.source).toEqual(actualOptions().source);expect(store.value()?.draft.share_to_practice).toBe(false);expect(button('Send approved delivery').disabled).toBe(true);expect(vendorApi.execute).not.toHaveBeenCalled();
    await click('Save revised proposal');const revised=vi.mocked(vendorApi.execute).mock.calls[0][1];expect(revised.kind).toBe('propose');expect(revised.request).toMatchObject({revises:{ticket_id:actual.detail_approved.summary.ticket_id},source:actualOptions().source,share_to_practice:false});expect(store.value()?.receipts).toContainEqual(actual.proposal_receipt);expect(vendorApi.execute).toHaveBeenCalledTimes(1);
  });
  it('retains prior command, receipt and edited input when saving a revision fails',async()=>{
    const op=await actualProposal(),store=recovery({...emptyVendorRecovery(op.scope),pending:op,receipt:validateVendor('CommandResponse',actual.proposal_receipt)});await renderOwner(store.access);await click('Restore delivery draft');const open=Array.from(container.querySelectorAll('button')).find(b=>b.textContent?.includes('Invented patient receives'))!;await act(async()=>open.click());await click('Edit proposal');
    const text=Array.from(container.querySelectorAll('label')).find(l=>l.textContent?.startsWith('Message to send'))!.querySelector('textarea')!;await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(text,'Edited private message');text.dispatchEvent(new Event('input',{bubbles:true}));});
    await waitUi(()=>expect(store.value()?.draft.message).toBe('Edited private message'));vi.mocked(store.access.persist).mockRejectedValueOnce(new Error('local CAS conflict'));await click('Save revised proposal');expect(vendorApi.execute).not.toHaveBeenCalled();expect(store.value()?.pending).toEqual(op);expect(store.value()?.receipt).toEqual(actual.proposal_receipt);expect(text.value).toBe('Edited private message');expect(container.textContent).toContain('Previous saved commands and receipts are retained');
  });
  it('does not offer editing after a send was claimed',async()=>{
    const detail=actualDetail();detail.summary.submit_claimed=true;vi.mocked(vendorApi.detail).mockResolvedValue(detail);await renderOwner(recovery().access);const open=Array.from(container.querySelectorAll('button')).find(b=>b.textContent?.includes('Invented patient receives'))!;await act(async()=>open.click());expect(button('Edit proposal').disabled).toBe(true);expect(vendorApi.execute).not.toHaveBeenCalled();
  });
  it('prepares a distinct delivery after uncertainty only with explicit duplicate-risk acknowledgment and fresh approval',async()=>{
    const old=actualDetail();old.summary.submit_claimed=true;old.summary.acceptance='unconfirmed';old.summary.dispatch='unconfirmed';old.summary.state='approved';vi.mocked(vendorApi.detail).mockResolvedValue(old);
    const op=await actualProposal(),store=recovery({...emptyVendorRecovery(op.scope),pending:op,receipt:validateVendor('CommandResponse',actual.proposal_receipt)});await renderOwner(store.access);await click('Restore delivery draft');const open=Array.from(container.querySelectorAll('button')).find(b=>b.textContent?.includes('Invented patient receives'))!;await act(async()=>open.click());await click('Prepare another delivery');
    expect(vendorApi.execute).not.toHaveBeenCalled();expect(store.value()?.draft.supersedes?.operation_id).toBe(old.summary.operation_id);expect(store.value()?.draft.revises).toBeNull();expect(button('Propose another delivery').disabled).toBe(true);
    const acknowledgment=Array.from(container.querySelectorAll('label')).find(l=>l.textContent?.includes('another delivery could be a duplicate'))!.querySelector('input')!;await act(async()=>acknowledgment.click());await click('Propose another delivery');
    const sent=vi.mocked(vendorApi.execute).mock.calls[0][1];expect(sent.kind).toBe('propose');expect(sent.request).toMatchObject({supersedes_operation_id:old.summary.operation_id,acknowledge_prior_uncertainty:true,share_to_practice:false});expect('revises'in sent.request).toBe(false);expect('proposed_operation_id'in sent.request&&sent.request.proposed_operation_id).not.toBe(old.summary.operation_id);expect(store.value()?.receipts).toContainEqual(actual.proposal_receipt);expect(vendorApi.execute).toHaveBeenCalledTimes(1);
  });
  it('restores preparation context without restoring duplicate-risk acknowledgment',async()=>{
    const old=actualDetail();old.summary.submit_claimed=true;old.summary.acceptance='unconfirmed';old.summary.dispatch='unconfirmed';const o=actualOptions(),r=emptyVendorRecovery({kind:'workspace',id:o.workspace_id});r.draft={...r.draft,connection_id:o.connections[0].id,source:o.source,supersedes:old.summary};
    await renderOwner(recovery(r).access);await click('Restore delivery draft');const acknowledgment=Array.from(container.querySelectorAll('label')).find(l=>l.textContent?.includes('another delivery could be a duplicate'))!.querySelector('input')!;expect(acknowledgment.checked).toBe(false);expect(button('Propose another delivery').disabled).toBe(true);expect(vendorApi.execute).not.toHaveBeenCalled();
  });
  it('limits another-delivery preparation to claimed uncertain, rejected or failed outcomes',()=>{
    const base=actualDetail().summary;expect(canPrepareAnotherDelivery(base)).toBe(false);expect(canPrepareAnotherDelivery({...base,submit_claimed:true,acceptance:'rejected'})).toBe(true);expect(canPrepareAnotherDelivery({...base,submit_claimed:true,acceptance:'accepted',transport:'failed'})).toBe(true);
    expect(canPrepareAnotherDelivery({...base,submit_claimed:true,acceptance:'accepted',transport:'pending'})).toBe(false);expect(canPrepareAnotherDelivery({...base,submit_claimed:true,transport:'delivered'})).toBe(false);expect(canPrepareAnotherDelivery({...base,submit_claimed:true,verification:'verified'})).toBe(false);
  });
  it('does not permit actions when private encrypted recovery is unavailable',async()=>{
    await renderOwner(null);expect(button('Propose for review').closest('fieldset')!.disabled).toBe(true);expect(vendorApi.execute).not.toHaveBeenCalled();
  });
  it.each([401,403,404])('hides all owner content and notifies scope recovery after %s',async status=>{
    vi.mocked(vendorApi.options).mockRejectedValueOnce(new WorkspaceApiError(status));const store=recovery();await renderOwner(store.access);expect(container.textContent).toContain('Access to this private delivery work is unavailable');expect(container.textContent).not.toContain(actual.detail_pending.review.expected_outcome);expect(container.querySelector('textarea')).toBeNull();expect(store.access.denied).toHaveBeenCalled();
  });
  it.each([401,403,404])('hides stale staff item after denied detail %s',async status=>{
    vi.mocked(vendorApi.shared).mockRejectedValueOnce(new WorkspaceApiError(status));const store=recovery();await renderStaff(store.access);expect(container.textContent).not.toContain(actualShared().body);expect(container.textContent).toContain('Access to this published work is unavailable');expect(store.access.denied).toHaveBeenCalled();
  });
  it('exposes only current published responsibilities and reports to staff, with no send or legacy completion',async()=>{
    await renderStaff(recovery().access);expect(button('Accept responsibility')).toBeTruthy();expect(button('Approve reviewed delivery')).toBeUndefined();expect(button('Send approved delivery')).toBeUndefined();expect(button('Verify completion')).toBeUndefined();expect(button('Complete')).toBeUndefined();expect(container.textContent).not.toContain(actual.detail_pending.review.message);expect(container.textContent).not.toContain(actual.detail_pending.review.source.note_id);
    expect(container.querySelector('input[type=file]')).toBeNull();expect(container.textContent).toContain('The owner reviews private delivery content');
  });
  it('fences delayed private detail after workspace scope changes',async()=>{
    let release!:(v:ReturnType<typeof actualDetail>)=>void;vi.mocked(vendorApi.detail).mockImplementationOnce(()=>new Promise(r=>{release=r;}));const store=recovery();await renderOwner(store.access);
    const open=Array.from(container.querySelectorAll('button')).find(b=>b.textContent?.includes('Invented patient receives'))!;await act(async()=>open.click());
    const other='11111111-1111-4111-8111-111111111111';await act(async()=>root.render(<VendorWorkPanel identity={identity} workspaceId={other} recovery={recovery().access}/>));await act(async()=>release(actualDetail()));expect(container.textContent).not.toContain(actual.detail_pending.review.message);
  });
  it('shows recorded staff human reports without marking completion verified',async()=>{
    const detail=validateVendor('SharedVendorDetail',shared.shared_result_detail);vi.mocked(vendorApi.shared).mockResolvedValue(detail);await renderStaff(recovery().access,detail);expect(container.textContent).toContain(detail.latest_result!.evidence);expect(container.textContent).toContain('Completion verification: exception unresolved');
  });
});
