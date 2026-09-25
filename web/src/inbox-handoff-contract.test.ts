import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {inboxHandoffReceipts,actualInboxHandoff,inboxHandoffFixtureOperation,inboxHandoffSyntheticProposal,inboxHandoffMissing,inboxHandoffSyntheticOwnerReview,inboxHandoffFixture,inboxHandoffFixtureCatalog,inboxHandoffTicketScope as scope,inboxHandoffStaffScope as staffScope,inboxHandoffWorkspaceScope as workspace} from './inbox-handoff-test-fixture';
import {validateInboxHandoff,normalizeInboxHandoff,prepareInboxHandoffOperation,validateInboxHandoffOperation,verifyInboxHandoffReceipt,verifyInboxHandoffOperationReceipt,verifyInboxHandoffView,inboxHandoffOperationPath,inboxHandoffResolvePath,inboxHandoffResolveRequest,inboxHandoffPayloadHash,validateInboxHandoffActor} from './inbox-handoff-contract';
import {vendorDigest} from './vendor-contract';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
beforeEach(()=>vi.stubGlobal('crypto',webcrypto));afterEach(()=>vi.unstubAllGlobals());
async function rehash(value:any){const {receipt_sha256:_,...body}=value;return {...body,receipt_sha256:await vendorDigest('cosmas-inbox-handoff-receipt.v1',body)};}
describe('frozen signed backend handoff contract',()=>{
  it('checks all six actual authenticated backend receipt digests',async()=>{
    expect(actualInboxHandoff.publication_operations).toBe(1);expect(actualInboxHandoff.handoffs).toBe(2);
    for(const receipt of inboxHandoffReceipts)expect(await verifyInboxHandoffReceipt(receipt)).toEqual(receipt);
  });
  it.each(['decide','handoff','accept','result','verify'] as const)('reconstructs the exact signed %s request digest',async kind=>{
    const op=await inboxHandoffFixtureOperation(kind),receipt=inboxHandoffReceipts[{decide:1,handoff:2,accept:3,result:4,verify:5}[kind]];
    expect(op.request_sha256).toBe(receipt.request_sha256);expect(await verifyInboxHandoffOperationReceipt(op,receipt)).toEqual(receipt);
    expect(await validateInboxHandoffOperation(op,op.scope)).toEqual(op);expect(inboxHandoffOperationPath(op)).toBe(`/inbox-handoffs/${scope.id}/${op.kind}`);
    expect(inboxHandoffResolvePath(op)).toBe(`/inbox-handoffs/${scope.id}/resolve`);expect(inboxHandoffResolveRequest(op)).toEqual({command_kind:op.kind,idempotency_key:op.request.idempotency_key,request_sha256:op.request_sha256});
  });
  it('uses a workspace route for a distinctly labeled synthetic proposal',async()=>{
    const {operation,receipt}=await inboxHandoffSyntheticProposal();expect(await verifyInboxHandoffOperationReceipt(operation,receipt)).toEqual(receipt);
    expect(inboxHandoffOperationPath(operation)).toBe(`/workspaces/${workspace.id}/inbox-handoffs/propose`);expect(inboxHandoffResolvePath(operation)).toBe(`/workspaces/${workspace.id}/inbox-handoffs/resolve`);
  });
  it.each(['pending','published','offered','accepted','result','closed','unavailable'] as const)('checks the derived %s owner display state',async stage=>{
    const detail=await inboxHandoffFixture(stage);expect(detail.external_action_performed).toBe(false);expect(detail.verified_current).toBe(stage==='closed');
    if(stage==='unavailable')expect(detail).toMatchObject({publication_active:false,due_date:null,expected_outcome:null,result:null,requires_owner_attention:true});
  });
  it.each(['offered','accepted','result','closed','unavailable'] as const)('withholds private source from derived staff %s state',async stage=>{
    const detail=await inboxHandoffFixture(stage,'staff');expect(Object.hasOwn(detail,'private_source')).toBe(false);
    if(stage==='unavailable')expect(detail).toMatchObject({instructions:null,selected_context:null,result:null,due_date:null,expected_outcome:null,verified_current:false});
  });
  it('accepts the separately labeled R10 owner review projection only with a matching full payload',async()=>{
    const pending=await inboxHandoffSyntheticOwnerReview();expect(pending).toMatchObject({state:'pending_approval',publication_active:false,due_date:'2026-10-02',result:null});
    const unavailable=await inboxHandoffSyntheticOwnerReview('unavailable');expect(unavailable).toMatchObject({state:'source_unavailable',requires_owner_attention:true,publication_active:false,result:null});
    for(const patch of [{due_date:null},{expected_outcome:null},{due_date:'2026-10-03'},{expected_outcome:'Changed work'},{instructions:'Changed instructions'},{result:(await inboxHandoffFixture()).result}])await expect(verifyInboxHandoffView('Detail',{...pending,...patch},scope)).rejects.toThrow();
  });
  it('retains not_found as a nonreceipt, never as proof of a recorded rejection',async()=>{
    const op=await inboxHandoffFixtureOperation(),missing=inboxHandoffMissing(op);expect(await verifyInboxHandoffOperationReceipt(op,missing)).toEqual(missing);
    for(const extra of [{scope:op.scope},{receipt_id:inboxHandoffReceipts[1].receipt_id},{receipt_sha256:'a'.repeat(64)},{rejection:null},{effect:inboxHandoffReceipts[1].effect}])await expect(verifyInboxHandoffReceipt({...missing,...extra})).rejects.toThrow();
  });
  it('binds a synthetic durable rejection to its unchanged exact request',async()=>{
    const op=await inboxHandoffFixtureOperation(),r=await rehash({...inboxHandoffReceipts[1],outcome:'rejected',effect:null,rejection:'work_changed'});
    expect(await verifyInboxHandoffOperationReceipt(op,r)).toEqual(r);expect(r.receipt_id).toBeTruthy();
    await expect(verifyInboxHandoffOperationReceipt(op,{...r,rejection:null})).rejects.toThrow();
  });
  it.each(['scope','actor','owner','kind','key','ticket','version','revision','payload','state','timestamp','extra'] as const)('rejects recomputed %s receipt substitution',async fault=>{
    const op=await inboxHandoffFixtureOperation(),r:any=structuredClone(inboxHandoffReceipts[1]);
    if(fault==='scope')r.scope.kind='workspace';if(fault==='actor')r.scope.actor_id=staffScope.actor_id;if(fault==='owner')r.scope.owner_id=staffScope.actor_id;
    if(fault==='kind')r.command_kind='handoff';if(fault==='key')r.idempotency_key='different-key';if(fault==='ticket')r.effect.ticket_id=crypto.randomUUID();
    if(fault==='version')r.effect.version++;if(fault==='revision')r.effect.revision_id=crypto.randomUUID();if(fault==='payload')r.effect.payload_hash='c'.repeat(64);
    if(fault==='state')r.effect.state='rejected';if(fault==='timestamp')r.recorded_at='2026-02-30T00:00:00.000000Z';if(fault==='extra')r.endpoint='https://example.invalid';
    await expect(verifyInboxHandoffOperationReceipt(op,await rehash(r))).rejects.toThrow();
  });
  it('rejects substituted proposal payloads and native ticket identity',async()=>{
    const {operation,receipt}=await inboxHandoffSyntheticProposal();await expect(verifyInboxHandoffOperationReceipt(operation,await rehash({...receipt,effect:{...receipt.effect,payload_hash:'c'.repeat(64)}}))).rejects.toThrow();
    await expect(prepareInboxHandoffOperation(scope,'propose',operation.request)).rejects.toThrow();
    const decision=await inboxHandoffFixtureOperation();if(decision.kind!=='decide')throw new Error('fixture');
    await expect(prepareInboxHandoffOperation(workspace,'decide',decision.request)).rejects.toThrow();
    await expect(prepareInboxHandoffOperation(scope,'decide',{...decision.request,ticket_id:crypto.randomUUID()})).rejects.toThrow();
  });
  it.each(['propose','decide','verify'] as const)('keeps %s owner authority distinct from staff participation',async kind=>{
    const op=kind==='propose'?(await inboxHandoffSyntheticProposal()).operation:await inboxHandoffFixtureOperation(kind);
    await expect(prepareInboxHandoffOperation({...op.scope,actor_id:staffScope.actor_id},op.kind,op.request)).rejects.toThrow();
  });
  it.each([{kind:'offer'},{kind:'offer',recipient_id:scope.owner_id,offer_id:scope.id},{kind:'accept'},{kind:'accept',offer_id:scope.id,recipient_id:scope.owner_id},{kind:'reclaim',offer_id:scope.id},{kind:'recall',offer_id:null}])('rejects malformed responsibility request %j',async patch=>{
    const op=await inboxHandoffFixtureOperation('handoff'),request:any={...op.request};delete request.recipient_id;Object.assign(request,patch);expect(()=>validateInboxHandoff('Handoff',request)).toThrow();
  });
  it('normalizes only fresh human text; durable exact requests reject normalization',async()=>{
    const {operation}=await inboxHandoffSyntheticProposal();const request={...operation.request,instructions:'First\r\nSecond'};
    expect(normalizeInboxHandoff('Propose',request).instructions).toBe('First\nSecond');expect(()=>validateInboxHandoff('Propose',request)).toThrow();
    for(const patch of [{selected_context:null},{reviewed_minimum_context:1},{due_date:'2026-02-30'},{instructions:'\u00a0\u2000'},{instructions:'x\u000b'},{instructions:'\ud800'},{source_id:operation.request.source_id.toUpperCase()+'x'},{endpoint:'https://example.invalid'}])expect(()=>validateInboxHandoff('Propose',{...operation.request,...patch})).toThrow();
    await expect(prepareInboxHandoffOperation(workspace,'propose',{...operation.request,instructions:'🧪'.repeat(2200)})).rejects.toThrow();
  });
  it('matches Python ASCII payload hashing for Unicode selected context',async()=>{
    expect(await inboxHandoffPayloadHash({instructions:'Review 🧪\nCafé',selected_context:'患者',due_date:'2026-10-02',expected_outcome:'Done'})).toBe('747fd16004101620437c5340e18fc6b9bc2a1f5963d07bca04891ed3d6c6d840');
  });
  it.each(['private_source','raw_source','state','publication','verified','attention','originator','responsible','handoff_order','handoff_duplicate','handoff_target','result_actor','body','version'] as const)('refuses corrupted %s detail',async fault=>{
    const d:any=await inboxHandoffFixture('closed','staff');
    if(fault==='private_source')d.private_source=(await inboxHandoffFixture()).private_source;if(fault==='raw_source')d.raw_message='private source';
    if(fault==='state')d.state='pending_approval';if(fault==='publication')d.publication_active=false;if(fault==='verified')d.verified_current=false;if(fault==='attention')d.requires_owner_attention=true;
    if(fault==='originator')d.originator_id=crypto.randomUUID();if(fault==='responsible')d.responsible_id=scope.owner_id;
    if(fault==='handoff_order')d.handoffs.reverse();if(fault==='handoff_duplicate')d.handoffs.push(d.handoffs[1]);if(fault==='handoff_target')d.handoffs[1].to_id=crypto.randomUUID();
    if(fault==='result_actor')d.result.actor_id=crypto.randomUUID();if(fault==='body')d.instructions='Altered approved instructions';if(fault==='version')d.version=0;
    await expect(verifyInboxHandoffView('Detail',d,staffScope)).rejects.toThrow();
  });
  it('requires the owner private source binding and withholds unavailable shared content',async()=>{
    const owner:any=await inboxHandoffFixture();delete owner.private_source;await expect(verifyInboxHandoffView('Detail',owner,scope)).rejects.toThrow();
    const staff=await inboxHandoffFixture('unavailable','staff');for(const patch of [{instructions:'still visible'},{selected_context:'retained source'},{due_date:'2026-10-02'},{expected_outcome:'Done'},{result:(await inboxHandoffFixture()).result},{private_source:null},{verified_current:true}])await expect(verifyInboxHandoffView('Detail',{...staff,...patch},staffScope)).rejects.toThrow();
  });
  it('does not grant detail visibility to an unrelated participant',async()=>{
    const detail=await inboxHandoffFixture('closed','staff');await expect(verifyInboxHandoffView('Detail',detail,{...staffScope,actor_id:crypto.randomUUID()})).rejects.toThrow();
  });
  it('checks catalog uniqueness, exact actor context and closed bounds',async()=>{
    const catalog=await inboxHandoffFixtureCatalog();expect(await verifyInboxHandoffView('Catalog',catalog)).toEqual(catalog);
    await expect(verifyInboxHandoffView('Catalog',{...catalog,items:[...catalog.items,...catalog.items]})).rejects.toThrow();
    await expect(verifyInboxHandoffView('Catalog',{...catalog,items:Array.from({length:101},()=>catalog.items[0])})).rejects.toThrow();
    expect(()=>validateInboxHandoffActor({box_id:scope.box_id,actor_id:scope.actor_id,owner_id:scope.owner_id})).toThrow();
  });
  it('rejects altered journal operations before transport',async()=>{
    const op=await inboxHandoffFixtureOperation();for(const patch of [{version:2},{request_sha256:'a'.repeat(64)},{endpoint:'/send'},{kind:'publish'}])await expect(validateInboxHandoffOperation({...op,...patch})).rejects.toThrow();
  });
});
