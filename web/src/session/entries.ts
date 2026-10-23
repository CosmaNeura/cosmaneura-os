import {botAddress,type DraftHandoff,type ProviderTeam,type Workspace,type WorkspaceEntry} from '../workspace-api';

export type ConversationAction={kind:'review_handoff'|'retry_handoff'|'review_note'|'review_work'|'check_request';id:string;label:string};
export type ConversationRow=
  {kind:'turn';id:string;entry:WorkspaceEntry;reviewLabel:string;actions:ConversationAction[]}|
  {kind:'review';id:string;author:string;title:string;status:string;needsReview:boolean;actions:ConversationAction[]};
export type ConversationProjection={workspaceId:string|null;botAddress:string;entries:ConversationRow[];turns:WorkspaceEntry[]};

export function handoffReviewLabel(handoff:DraftHandoff,entryId=handoff.result_entry_id):string {
  const review=handoff.review;
  if(handoff.review_status==='stale')return 'Review needs updating';
  if(handoff.status!=='completed'||handoff.review_status!=='current'||!review||review.attempt_id!==handoff.attempt_id||
    review.result_entry_id!==entryId||review.result_sha256!==handoff.result_sha256)return 'Unreviewed draft';
  return review.decision==='accepted'?'Draft accepted':'Changes requested';
}
export function savedDraftReviewLabel(workspace:Workspace|null,entry:WorkspaceEntry):string {
  const matches=workspace?.handoffs?.filter(handoff=>handoff.result_entry_id===entry.id)??[];
  return matches.length===1?handoffReviewLabel(matches[0],entry.id):'Unreviewed draft';
}

/** A bot conversation plus attributed outcomes, without the internal delegation transcript. */
export function projectConversation(workspace:Workspace|null,team:ProviderTeam|null,selected:string):ConversationProjection {
  const bot=team?.configuration.bots.find(item=>botAddress(item)===selected),member=team?.members.find(item=>botAddress(item)===selected);
  const turns=workspace?.entries.filter(entry=>['conversation','handoff_result'].includes(entry.kind)&&
    (entry.model_request?entry.model_request.bot.address===selected:entry.reply&&(entry.reply.agent_id?entry.reply.agent_id===member?.agent_id:!bot?.instance_id&&entry.reply.role===bot?.role)))??[];
  const entries:ConversationRow[]=turns.map(entry=>({kind:'turn',id:entry.id,entry,reviewLabel:savedDraftReviewLabel(workspace,entry),
    actions:!entry.reply&&entry.model_request?.request.kind==='conversation'?[{kind:'check_request',id:entry.id,label:'Check saved result'}]:[]}));
  if(!workspace)return {workspaceId:null,botAddress:selected,entries,turns};
  if(bot?.role==='chief'){
    const origins=new Set(turns.map(entry=>entry.id));
    for(const handoff of workspace.handoffs??[]){
      // Revision children remain associated with the same Chief conversation.
      if(!origins.has(handoff.origin_entry_id)&&!handoff.revision_request)continue;
      const result=workspace.entries.find(entry=>entry.id===handoff.result_entry_id);
      const withheld=!!result&&[result.google_source_state,result.calendar_source_state,result.fax_source_state,result.practice_fax_source_state].includes('unavailable');
      const available=!!result?.reply&&!withheld;
      const label=handoffReviewLabel(handoff),reviewed=['Draft accepted','Changes requested'].includes(label);
      const status=withheld?'Source access needs checking':handoff.status==='completed'?available?label:'Result needs checking':
        handoff.status==='queued'?'Queued':handoff.status==='running'?'Working':handoff.status==='failed'?'Could not finish':'Outcome needs checking';
      const actions:ConversationAction[]=available?[{kind:'review_handoff',id:handoff.id,label:'Review draft'}]:
        ['failed','interrupted'].includes(handoff.status)?[{kind:'retry_handoff',id:handoff.id,label:'Retry draft'}]:[];
      entries.push({kind:'review',id:`handoff:${handoff.id}`,author:handoff.recipient_name,title:`${handoff.recipient_name} draft`,status,needsReview:!reviewed,actions});
    }
  }
  if(['chief','scribe'].includes(bot?.role??'')&&workspace.note?.latest){
    const note=workspace.note.latest;
    entries.push({kind:'review',id:`note:${note.id}`,author:'Scribe',title:`Saved note · version ${note.version}`,
      status:note.sources_changed?'Sources changed':note.review?'Reviewed privately':'Needs your review',needsReview:note.sources_changed||!note.review,
      actions:[{kind:'review_note',id:note.id,label:'Review note'}]});
  }
  if(['chief','follow_up'].includes(bot?.role??''))for(const work of workspace.follow_ups??[]){
    if(['done','closed','rejected','completed'].includes(work.state))continue;
    entries.push({kind:'review',id:`work:${work.ticket_id}`,author:'Follow-up',title:'Follow-up',status:work.source_changed?'Sources changed':work.state.replaceAll('_',' '),needsReview:true,
      actions:[{kind:'review_work',id:work.ticket_id,label:'Review follow-up'}]});
  }
  return {workspaceId:workspace.id,botAddress:selected,entries,turns};
}
