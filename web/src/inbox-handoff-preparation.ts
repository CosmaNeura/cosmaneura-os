import {inboxApi} from './inbox-api';
import {verifyInboxBundle,verifyInboxView,type InboxBundle} from './inbox-contract';
import {InboxHandoffContractError} from './inbox-handoff-contract';
import type {InboxHandoffActor,InboxHandoffProposalBasis} from './inbox-handoff-recovery';
import type {WorkspaceIdentity,WorkPerson} from './workspace-api';
import {vendorCanonical,vendorObject,vendorUuid} from './vendor-contract';
export type InboxHandoffSource={bundle:InboxBundle};
export type InboxHandoffPreparation=InboxHandoffSource&{basis:InboxHandoffProposalBasis};
export async function readInboxHandoffSource(identity:WorkspaceIdentity,actor:InboxHandoffActor,itemId:string):Promise<InboxHandoffSource>{
  const scope={box_id:actor.box_id,owner_id:actor.actor_id},raw=await inboxApi.detail(identity,scope,itemId),bundle=await verifyInboxBundle(raw.detail,raw.history,scope),d=bundle.detail,s=d.summary,r=d.latest_review;
  if(s.item_id!==itemId||!s.binding_current||!s.workspace_current||s.incomplete_content||s.source_conflict||s.read_issue!==null||!s.source_id||!s.source_sha256||!s.workspace_id||!r?.receipt_id||!r.receipt_sha256||r.outcome!=='recorded')throw new InboxHandoffContractError();
  const reviewed=bundle.history.commands.find(x=>x.receipt.receipt_id===r.receipt_id);
  if(!reviewed||reviewed.receipt.command_kind!=='review'||vendorCanonical(reviewed.receipt)!==vendorCanonical(r))throw new InboxHandoffContractError();
  return {bundle};
}
export async function readInboxHandoffPreparation(identity:WorkspaceIdentity,actor:InboxHandoffActor,itemId:string):Promise<InboxHandoffPreparation>{
  const {bundle}=await readInboxHandoffSource(identity,actor,itemId),scope=bundle.detail.scope,s=bundle.detail.summary,r=bundle.detail.latest_review!;
  const options=await verifyInboxView('ReviewOptions',await inboxApi.reviewOptions(identity,scope,itemId));
  if(vendorCanonical(options.scope)!==vendorCanonical(scope)||options.item_id!==itemId||options.item_version!==s.version||options.source_id!==s.source_id||options.source_sha256!==s.source_sha256||options.patient_link_id!==s.patient_link_id)throw new InboxHandoffContractError();
  const choice=options.choices.find(x=>x.workspace_id===s.workspace_id);if(!choice)throw new InboxHandoffContractError();
  return {basis:{item_id:itemId,source_id:s.source_id!,source_sha256:s.source_sha256!,review_receipt_id:r.receipt_id!,review_receipt_sha256:r.receipt_sha256!,workspace_id:choice.workspace_id,expected_workspace_revision:choice.expected_workspace_revision,label:choice.label},bundle};
}
export function validateInboxHandoffPeople(value:unknown):WorkPerson[]{
  if(!Array.isArray(value)||value.length>500)throw new InboxHandoffContractError();
  const ids=new Set<string>();
  for(const p of value){if(!vendorObject(p)||Object.keys(p).sort().join(',')!=='available,id,name'||!vendorUuid(p.id)||typeof p.name!=='string'||p.name.trim()===''||Array.from(p.name).length>200||/[\x00-\x1f\x7f]/.test(p.name)||typeof p.available!=='boolean'||ids.has(p.id))throw new InboxHandoffContractError();ids.add(p.id);}
  vendorCanonical(value);return structuredClone(value) as WorkPerson[];
}
