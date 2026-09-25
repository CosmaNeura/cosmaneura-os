import http from './__fixtures__/membership/actual-membership-http.json';
import process from './__fixtures__/membership/actual-membership-process.json';
import manual from './__fixtures__/membership/actual-membership-manual-evidence.json';
import type {Detail,History,Options,Result} from './membership-schema';
import {validateMembership,membershipClassification} from './membership-contract';
import {prepareMembershipOperation,verifyMembershipBundle} from './membership-operation';
export {http,process,manual};
export const membershipFixtureScope=validateMembership('Scope',process.detail.scope);
export const membershipFixtureIdentity={boxId:membershipFixtureScope.box_id,actorId:membershipFixtureScope.owner_id};
/** UI states are derived from actual immutable command prefixes; not extra observed server snapshots. */
export async function membershipFixture(stage:1|2|3|4=3,ledger=false){
 const actual=ledger?manual:process,d=validateMembership('Detail',actual.detail),h=validateMembership('History',actual.history);h.items=h.items.slice(0,stage);
 const e=h.items.at(-1)!.receipt.effect!,r=[...h.items].reverse().find(i=>i.receipt.command_kind==='result');
 d.summary={...d.summary,version:stage,state:e.state,result:r?(r.request as Result).disposition:'none',evidence_classification:membershipClassification(r?.request as Result|undefined),evidence_current:r&&(r.request as Result).ledger?'available':'none',verification:stage===4?'review_verified':'pending',can_verify:stage===3};
 d.latest_result=r?{receipt_id:r.receipt.effect!.receipt_id,receipt_sha256:r.receipt.receipt_sha256!,request:r.request as Result}:null;
 return verifyMembershipBundle(d,h);
}
export function membershipFixtureOptions(d:Detail):Options{return validateMembership('Options',{contract_version:1,scope:d.scope,patient_link_id:d.review.patient_link_id,expected_workspace_revision:d.review.proposal.expected_workspace_revision,source:d.review.proposal.source,enabled:true,installed_membership_service:'not_selected'});}
export async function membershipHistoryOperations(h:History){return Promise.all(h.items.map(i=>prepareMembershipOperation(h.scope,i.receipt.command_kind,i.request)));}
