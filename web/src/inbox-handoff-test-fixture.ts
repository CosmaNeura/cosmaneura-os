import signed from './__fixtures__/inbox-handoff/actual-signed-process.json';
import {validateInboxHandoff,prepareInboxHandoffOperation,verifyInboxHandoffView,inboxHandoffPayloadHash,type InboxHandoffKind,type InboxHandoffRequests} from './inbox-handoff-contract';
import {INBOX_HANDOFF_SCHEMAS,type Detail,type Scope,type NotFound} from './inbox-handoff-schema';
import {vendorDigest} from './vendor-contract';
export const actualInboxHandoff=signed;
export const inboxHandoffReceipts=signed.vectors.map(v=>validateInboxHandoff('Response',v));
export const inboxHandoffWorkspaceScope=inboxHandoffReceipts[0].scope;
export const inboxHandoffTicketScope=inboxHandoffReceipts[1].scope;
export const inboxHandoffStaffScope=inboxHandoffReceipts[3].scope;
export const inboxHandoffIdentity={boxId:inboxHandoffWorkspaceScope.box_id,actorId:inboxHandoffWorkspaceScope.actor_id};
export const inboxHandoffActor={box_id:inboxHandoffWorkspaceScope.box_id,actor_id:inboxHandoffWorkspaceScope.actor_id};
export const inboxHandoffSelected={instructions:'Please review the appointment question.',selected_context:"The patient asked about next week's appointment.",due_date:'2026-10-02',expected_outcome:'Record the local administrative review outcome.'};
/** Requests below are reconstructed from the frozen signed test's literal inputs and receipts.
 * Their hashes must equal the observed backend hashes. No new service action occurs here. */
export async function inboxHandoffFixtureOperation(kind:Exclude<InboxHandoffKind,'propose'>|'accept'='decide'){
  const index={decide:1,handoff:2,accept:3,result:4,verify:5}[kind],receipt=inboxHandoffReceipts[index],effect=receipt.effect!;
  const base={idempotency_key:receipt.idempotency_key,ticket_id:effect.ticket_id,expected_version:effect.version-1,revision_id:effect.revision_id,payload_hash:effect.payload_hash};
  if(kind==='decide')return prepareInboxHandoffOperation(receipt.scope,'decide',{...base,choice:'approve',publish_selected_context:true});
  if(kind==='handoff')return prepareInboxHandoffOperation(receipt.scope,'handoff',{...base,kind:'offer',recipient_id:inboxHandoffStaffScope.actor_id});
  if(kind==='accept')return prepareInboxHandoffOperation(receipt.scope,'handoff',{...base,kind:'accept',offer_id:inboxHandoffReceipts[2].effect!.effect_id});
  if(kind==='result')return prepareInboxHandoffOperation(receipt.scope,'result',{...base,evidence:'Accountable local review finished.',no_external_action_claimed:true});
  return prepareInboxHandoffOperation(receipt.scope,'verify',{...base,result_receipt_id:inboxHandoffReceipts[4].effect!.effect_id,result_request_sha256:inboxHandoffReceipts[4].request_sha256,reviewed_current_source:true,reviewed_result:true,local_handoff_only:true});
}
/** Synthetic proposal uses invented source IDs because the archived signed run retained receipts,
 * not the private proposal request. Do not describe this generated vector as an observed request. */
export async function inboxHandoffSyntheticProposal(){
  const request:InboxHandoffRequests['propose']={...inboxHandoffSelected,idempotency_key:'synthetic-handoff-proposal',item_id:'10000000-0000-4000-8000-000000000001',source_id:'10000000-0000-4000-8000-000000000002',source_sha256:'a'.repeat(64),review_receipt_id:'10000000-0000-4000-8000-000000000003',review_receipt_sha256:'b'.repeat(64),expected_workspace_revision:3,reviewed_minimum_context:true};
  const operation=await prepareInboxHandoffOperation(inboxHandoffWorkspaceScope,'propose',request);
  const body={...inboxHandoffReceipts[0],idempotency_key:request.idempotency_key,request_sha256:operation.request_sha256,effect:{...inboxHandoffReceipts[0].effect!,payload_hash:await inboxHandoffPayloadHash(request)}};
  const {receipt_sha256:_,...unsigned}=body;
  return {operation,receipt:{...unsigned,receipt_sha256:await vendorDigest('cosmas-inbox-handoff-receipt.v1',unsigned)}};
}
export const inboxHandoffMissing=(operation:{kind:InboxHandoffKind;request:{idempotency_key:string};request_sha256:string}):NotFound=>({contract_version:1,outcome:'not_found',effect:null,scope:null,command_kind:operation.kind,idempotency_key:operation.request.idempotency_key,request_sha256:operation.request_sha256});
/** Derived display states, built from observed signed receipts and explicitly invented private
 * source IDs. They qualify client invariants; they are not additional backend observations. */
export async function inboxHandoffFixture(stage:'pending'|'published'|'offered'|'accepted'|'result'|'closed'|'unavailable'='closed',viewer:'owner'|'staff'='owner'){
  const n={pending:0,published:1,offered:2,accepted:3,result:4,closed:5,unavailable:5}[stage];
  const r=inboxHandoffReceipts[n],e=r.effect!,scope:Scope=viewer==='owner'?inboxHandoffTicketScope:inboxHandoffStaffScope;
  const active=stage!=='pending'&&stage!=='unavailable',owner=viewer==='owner';
  const d:Detail={contract_version:1,work_kind:'incoming_message',ticket_id:e.ticket_id,version:e.version,revision_id:e.revision_id,payload_hash:e.payload_hash,state:stage==='unavailable'?'source_unavailable':e.state,publication_active:active,requires_owner_attention:stage==='unavailable',originator_id:scope.owner_id,originator_available:true,responsible_id:n<3?scope.owner_id:inboxHandoffStaffScope.actor_id,publication_receipt_id:n===0?null:inboxHandoffReceipts[1].effect!.effect_id,verified_current:stage==='closed',external_action_performed:false,instructions:active||owner?inboxHandoffSelected.instructions:null,selected_context:active||owner?inboxHandoffSelected.selected_context:null,due_date:active?inboxHandoffSelected.due_date:null,expected_outcome:active?inboxHandoffSelected.expected_outcome:null,result:active&&n>=4?{receipt_id:inboxHandoffReceipts[4].effect!.effect_id,request_sha256:inboxHandoffReceipts[4].request_sha256,actor_id:inboxHandoffStaffScope.actor_id,evidence:'Accountable local review finished.'}:null,handoffs:[]};
  if(n>=2)d.handoffs.push({id:inboxHandoffReceipts[2].effect!.effect_id,kind:'offer',from_id:scope.owner_id,to_id:inboxHandoffStaffScope.actor_id,offer_id:null});
  if(n>=3)d.handoffs.push({id:inboxHandoffReceipts[3].effect!.effect_id,kind:'accept',from_id:scope.owner_id,to_id:inboxHandoffStaffScope.actor_id,offer_id:inboxHandoffReceipts[2].effect!.effect_id});
  if(owner)d.private_source={item_id:'10000000-0000-4000-8000-000000000001',source_id:'10000000-0000-4000-8000-000000000002',source_sha256:'a'.repeat(64),review_receipt_id:'10000000-0000-4000-8000-000000000003',review_receipt_sha256:'b'.repeat(64),unavailability:stage==='unavailable'?'source_changed':null};
  return verifyInboxHandoffView('Detail',d,scope);
}
export async function inboxHandoffFixtureCatalog(){
  const detail=await inboxHandoffFixture(),summary=Object.fromEntries(Object.keys(INBOX_HANDOFF_SCHEMAS.Summary.properties).map(k=>[k,detail[k as keyof Detail]]));
  return verifyInboxHandoffView('Catalog',{contract_version:1,items:[summary]});
}

/** Synthetic R10-compatible owner review projection. No observed R10 claim. */
export async function inboxHandoffSyntheticOwnerReview(stage:'pending'|'unavailable'='pending'){
  const d=await inboxHandoffFixture(stage);
  return verifyInboxHandoffView('Detail',{...d,due_date:inboxHandoffSelected.due_date,expected_outcome:inboxHandoffSelected.expected_outcome},inboxHandoffTicketScope);
}
