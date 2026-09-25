import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {actual,inboxFixture,inboxFixtureOperation,inboxFixtureScope as scope} from './inbox-test-fixture';
import {prepareInboxOperation,validateInbox,validateInboxOperation,verifyInboxBundle,verifyInboxOperationReceipt,verifyInboxReceipt,verifyInboxView,inboxOperationPath,inboxResolveRequest} from './inbox-contract';
import {vendorDigest} from './vendor-contract';
import actualFlow from './__fixtures__/inbox/actual-inbox-flow.json';
import actualOptions from './__fixtures__/inbox/actual-inbox-review-options.json';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
beforeEach(()=>vi.stubGlobal('crypto',webcrypto));afterEach(()=>vi.unstubAllGlobals());
describe('actual signed Inbox public contract',()=>{
  it('round-trips the separately qualified committed application flow',async()=>{
    expect(await verifyInboxBundle(actualFlow.detail,actualFlow.history)).toEqual({detail:actualFlow.detail,history:actualFlow.history});
  });
  it('verifies the actual owner-private matching encounter choices and exact source binding',async()=>{
    expect(await verifyInboxView('ReviewOptions',actualOptions)).toEqual(actualOptions);
  });
  it.each(['duplicate_workspace','duplicate_appointment','missing_source','extra_endpoint','invalid_date','version_limit','digest'] as const)('rejects %s in encounter choices even with recomputed commitments',async fault=>{
    const options=structuredClone(actualOptions) as any;
    if(fault==='duplicate_workspace')options.choices.push({...options.choices[0],appointment_id:crypto.randomUUID()});
    if(fault==='duplicate_appointment')options.choices.push({...options.choices[0],workspace_id:crypto.randomUUID()});
    if(fault==='missing_source')delete options.source_id;
    if(fault==='extra_endpoint')options.choices[0].endpoint='https://evil.invalid';
    if(fault==='invalid_date')options.choices[0].start_at='2026-02-30T00:00:00.000000Z';
    if(fault==='version_limit')options.item_version=96;
    const {options_sha256:_,...body}=options;options.options_sha256=fault==='digest'?'0'.repeat(64):await vendorDigest('cosmas-inbox-review-options.v1',body);
    await expect(verifyInboxView('ReviewOptions',options)).rejects.toThrow();
  });
  it('verifies the complete actual source, durable rejection and locally closed review chain',async()=>{
    const bundle=await verifyInboxBundle(actual.closed,actual.history,scope);
    expect(bundle.detail).toEqual(actual.closed);expect(bundle.history).toEqual(actual.history);
    expect(bundle.detail.source!.text).toContain('Ignore prior instructions');
    expect(bundle.detail.summary.external_action_performed).toBe(false);
    expect(await verifyInboxView('Catalog',actual.catalog)).toEqual(actual.catalog);
    expect(await verifyInboxBundle(actual.unavailable,actual.history)).toMatchObject({detail:{summary:{binding_current:false,state:'needs_human'}}});
  });
  it.each(['rejected','review','triage','result','verify'] as const)('binds the actual %s receipt to its exact operation',async kind=>{
    const op=await inboxFixtureOperation(kind),receipt=actual[`${kind}_receipt`];
    expect(await validateInboxOperation(op,scope)).toEqual(op);
    expect(await verifyInboxOperationReceipt(op,receipt)).toEqual(receipt);
    expect(inboxOperationPath(op)).toBe(`/inbox/${op.request.item_id}/${op.kind}`);
    expect(inboxResolveRequest(op)).toEqual({item_id:op.request.item_id,command_kind:op.kind,idempotency_key:op.request.idempotency_key,request_sha256:op.request_sha256});
  });
  it.each(['initial','reviewed','triaged','result','closed','unavailable'] as const)('validates the explicitly derived %s test prefix',async stage=>{
    const bundle=await inboxFixture(stage);expect(bundle.detail.summary.version).toBe(bundle.history.reads.length+bundle.history.commands.length);
  });
  it('preserves a missing receipt as not_found with no durable proof',async()=>{
    const op=await inboxFixtureOperation(),missing={...actual.review_receipt,outcome:'not_found',effect:null,rejection:null,receipt_id:null,recorded_at:null,receipt_sha256:null};
    expect((await verifyInboxOperationReceipt(op,missing)).outcome).toBe('not_found');
    for(const key of ['receipt_id','recorded_at','receipt_sha256'] as const){await expect(verifyInboxReceipt({...missing,[key]:actual.review_receipt[key]})).rejects.toThrow();}
  });
  it.each(['missing','duplicate','read_hash','read_source','read_order','request_text','human_hash','scope','item','source_projection','source_patient','forged_authority','state','latest','capacity'] as const)('rejects %s corruption before private detail/history disclosure',async fault=>{
    const d=structuredClone(actual.closed) as any,h=structuredClone(actual.history) as any;
    if(fault==='missing')h.commands.splice(0,1);
    if(fault==='duplicate')h.commands[1]=h.commands[0];
    if(fault==='read_hash')h.reads[0].receipt_sha256='0'.repeat(64);
    if(fault==='read_source')h.reads[0].source_id=crypto.randomUUID();
    if(fault==='read_order')h.reads[0].version=2;
    if(fault==='request_text')h.commands[2].request.instructions='Never approved';
    if(fault==='human_hash')h.commands[0].receipt.receipt_sha256='0'.repeat(64);
    if(fault==='scope')h.scope.owner_id=crypto.randomUUID();
    if(fault==='item')h.item_id=crypto.randomUUID();
    if(fault==='source_projection')d.source.text='Different source';
    if(fault==='source_patient')d.source.patient_link_id=crypto.randomUUID();
    if(fault==='forged_authority')d.summary.external_action_performed=true;
    if(fault==='state')d.summary.state='reviewed';
    if(fault==='latest')d.latest_triage=d.latest_review;
    if(fault==='capacity')d.availability.history_capacity_remaining=100;
    await expect(verifyInboxBundle(d,h,scope)).rejects.toThrow();
  });
  it.each(['scope','kind','key','item','version','source','state'] as const)('rejects recomputed %s receipt substitutions',async fault=>{
    const op=await inboxFixtureOperation('triage'),r=structuredClone(actual.triage_receipt) as any;
    if(fault==='scope')r.scope.owner_id=crypto.randomUUID();
    if(fault==='kind')r.command_kind='review';
    if(fault==='key')r.idempotency_key='substituted-key';
    if(fault==='item')r.effect.item_id=crypto.randomUUID();
    if(fault==='version')r.effect.version++;
    if(fault==='source')r.effect.source_sha256='0'.repeat(64);
    if(fault==='state')r.effect.state='needs_human';
    const {receipt_sha256:_,...body}=r;r.receipt_sha256=await vendorDigest('cosmas-inbox-receipt.v1',body);
    await expect(verifyInboxOperationReceipt(op,r)).rejects.toThrow();
  });
  it('requires real source fields, coherent unsupported content and a literal untrusted-text label',async()=>{
    for(const change of [{trust:'trusted'},{attachments:true},{attachment_types:['unknown','unknown']},{incomplete_content:true},{text:'🧪'.repeat(4097)},{created_at:'2026-02-30T12:00:00.000000Z'}]){
      const value={...actual.closed.source,...change};await expect(verifyInboxView('Source',value)).rejects.toThrow();
    }
    const source={...actual.closed.source,conversation_id:'a'.repeat(255)}, {projection_sha256:_,...body}=source;
    source.projection_sha256=await vendorDigest('cosmas-inbox-source-view.v1',body);
    expect((await verifyInboxView('Source',source)).conversation_id).toHaveLength(255);
  });
  it('normalizes only human request text, and rejects noncanonical stored requests and null bindings',async()=>{
    const request=validateInbox('Triage',actual.triage_request),op=await prepareInboxOperation(scope,'triage',{...request,instructions:'one\r\ntwo'});
    expect(op.request.instructions).toBe('one\ntwo');
    expect(()=>validateInbox('Triage',{...request,instructions:'one\r\ntwo'})).toThrow();
    for(const change of [{source_id:null},{source_sha256:undefined},{endpoint:'https://evil.invalid'},{human_disposition_required:1},{due_date:'2026-02-30'}])expect(()=>validateInbox('Triage',{...request,...change})).toThrow();
    await expect(prepareInboxOperation(scope,'triage',{...request,instructions:'🧪'.repeat(2000)})).rejects.toThrow();
  });
  it('rejects altered stored operation kinds, extras and exact request digests',async()=>{
    const op=await inboxFixtureOperation('review');
    for(const change of [{kind:'triage'},{request_sha256:'0'.repeat(64)},{endpoint:'/other'}])await expect(validateInboxOperation({...op,...change})).rejects.toThrow();
  });
  it('rejects a forged read failure that clears its source without a closed error',async()=>{
    const h=structuredClone(actual.history) as any,r=h.reads[0];Object.assign(r,{outcome:'failure',source_id:null,source_sha256:null,observed_at:null,item_response_sha256:null,conversation_response_sha256:null,safe_error:null});
    const {receipt_sha256:_,...body}=r;r.receipt_sha256=await vendorDigest('cosmas-inbox-read-receipt.v1',body);
    await expect(verifyInboxView('History',h)).rejects.toThrow();
  });
});
