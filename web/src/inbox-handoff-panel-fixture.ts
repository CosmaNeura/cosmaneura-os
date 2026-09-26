import {inboxFixture,actual,inboxFixtureScope} from './inbox-test-fixture';
import {validateInbox} from './inbox-contract';
import {vendorDigest} from './vendor-contract';
import {inboxHandoffFixture,inboxHandoffSelected,inboxHandoffStaffScope,inboxHandoffWorkspaceScope} from './inbox-handoff-test-fixture';
import {verifyInboxHandoffView} from './inbox-handoff-contract';
import type {Detail} from './inbox-handoff-schema';
export const panelActor={box_id:inboxFixtureScope.box_id,actor_id:inboxFixtureScope.owner_id};
export const panelIdentity={boxId:panelActor.box_id,actorId:panelActor.actor_id};
export const panelStaff=inboxHandoffStaffScope.actor_id;
export async function panelInbox(){
 const bundle=await inboxFixture('reviewed'),s=bundle.detail.summary;
 const b={contract_version:1,scope:inboxFixtureScope,item_id:s.item_id,item_version:s.version,source_id:s.source_id,source_sha256:s.source_sha256,patient_link_id:s.patient_link_id,choices:[{workspace_id:actual.review_request.workspace_id,expected_workspace_revision:actual.review_request.expected_workspace_revision,appointment_id:'70000000-0000-4000-8000-000000000001',label:'Invented reviewed encounter',start_at:actual.review_receipt.recorded_at}]};
 return {bundle,options:validateInbox('ReviewOptions',{...b,options_sha256:await vendorDigest('cosmas-inbox-review-options.v1',b)})};
}
/** Composed synthetic display fixture. The Inbox source prefix is validated from actual local
 * evidence; handoff identities are rebound solely for renderer tests, not an observed API result. */
export async function panelDetail(stage:Parameters<typeof inboxHandoffFixture>[0]='pending',viewer:'owner'|'staff'='owner',completeReview=true){
 const d=await inboxHandoffFixture(stage,viewer),{bundle}=await panelInbox(),s=bundle.detail.summary,r=bundle.detail.latest_review!;
 const replace=(id:string)=>id===inboxHandoffWorkspaceScope.owner_id?panelActor.actor_id:id;
 d.originator_id=panelActor.actor_id;d.responsible_id=replace(d.responsible_id);d.handoffs=d.handoffs.map(h=>({...h,from_id:replace(h.from_id),to_id:replace(h.to_id)}));
 if(d.private_source)d.private_source={item_id:s.item_id,source_id:s.source_id!,source_sha256:s.source_sha256!,review_receipt_id:r.receipt_id!,review_receipt_sha256:r.receipt_sha256!,unavailability:stage==='unavailable'?'source_changed':null};
 if(stage==='pending'&&completeReview){d.due_date=inboxHandoffSelected.due_date;d.expected_outcome=inboxHandoffSelected.expected_outcome;}
 return verifyInboxHandoffView('Detail',d,{...panelActor,actor_id:viewer==='owner'?panelActor.actor_id:panelStaff,owner_id:panelActor.actor_id,kind:'ticket',id:d.ticket_id});
}
export function panelCatalog(d:Detail){const {instructions:_,selected_context:__,due_date:___,expected_outcome:____,result:_____,handoffs:______,private_source:_______,...s}=d;return {contract_version:1 as const,items:[s]};}
