import actual from './__fixtures__/inbox/actual-inbox-process.json';
import {validateInbox,verifyInboxBundle,prepareInboxOperation,type InboxKind} from './inbox-contract';
export {actual};
export const inboxFixtureScope=validateInbox('Scope',actual.initial.scope);
export const inboxFixtureIdentity={boxId:inboxFixtureScope.box_id,actorId:inboxFixtureScope.owner_id};
export const inboxFixtureItem=actual.initial.summary.item_id;
export async function inboxFixtureOperation(kind:InboxKind|'rejected'='review'){
  const command=kind==='rejected'?'triage':kind;
  return prepareInboxOperation(inboxFixtureScope,command,validateInbox(({review:'Review',triage:'Triage',result:'Result',verify:'Verify'} as const)[command],actual[`${kind}_request`]));
}
/** Derived prefixes are test states, not additional observed backend snapshots. */
export async function inboxFixture(stage:'initial'|'reviewed'|'triaged'|'result'|'closed'|'unavailable'='closed'){
  if(stage==='closed'||stage==='unavailable')return verifyInboxBundle(actual[stage==='closed'?'closed':'unavailable'],actual.history);
  const d=validateInbox('Detail',actual.initial),h=validateInbox('History',actual.history),count={initial:0,reviewed:2,triaged:3,result:4}[stage];
  h.commands=h.commands.slice(0,count);d.summary.version=1+count;d.availability.history_capacity_remaining=100-d.summary.version;
  for(const item of h.commands){
    if(item.receipt.outcome!=='recorded')continue;
    const kind=item.receipt.command_kind;
    if(kind==='review'){d.latest_review=item.receipt;d.summary.workspace_id=actual.review_request.workspace_id;d.summary.workspace_current=true;}
    if(kind==='triage'){d.latest_triage=item.receipt;d.summary.classification='administrative_review';d.availability.result=true;}
    if(kind==='result'){d.latest_result=item.receipt;d.availability.verify=true;}
    d.summary.state=item.receipt.effect!.state;
  }
  return verifyInboxBundle(d,h);
}
