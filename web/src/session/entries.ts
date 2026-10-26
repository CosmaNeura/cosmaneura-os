import {botAddress,type DraftHandoff,type ProviderTeam,type Workspace,type WorkspaceEntry} from '../workspace-api';
import {hasResearchPacketMarker,RESEARCH_PACKET_LABEL} from '../research-packet-marker';

export type ConversationAction={kind:'review_handoff'|'retry_handoff'|'review_note'|'review_work'|'check_request';id:string;label:string};
export type ConversationRow=
  {kind:'turn';id:string;entry:WorkspaceEntry;reviewLabel:string;actions:ConversationAction[]}|
  ({kind:'material';id:string;sourceId:string;label:string;createdAt:string}&({sourceKind:'ehr'|'outlook'|'gmail'|'calendar-import';state:'current'|'unavailable'}|{sourceKind:'research';state:'current'}))|
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
  // Keep older review cards at their saved position instead of appending them
  // after every new turn. This is display order, not an activity/read clock.
  const positions=new Map(turns.map(entry=>[entry.id,entry.revision]));
  if(bot?.role==='chief'){
    for(const source of workspace.entries){
      if(hasResearchPacketMarker(source)){
        const id=`source:${source.id}`;
        entries.push({kind:'material',sourceKind:'research',id,sourceId:source.id,createdAt:source.created_at,state:'current',label:RESEARCH_PACKET_LABEL});
        positions.set(id,source.revision);continue;
      }
      const sourceKind=source.kind==='ehr_read_source'?'ehr':source.kind==='microsoft_message'?'outlook':source.kind==='google_message'?'gmail':source.kind==='calendar_import_source'?'calendar-import':null;
      const custody=sourceKind==='ehr'?source.ehr_source_state:sourceKind==='outlook'?source.microsoft_source_state:sourceKind==='gmail'?source.google_source_state:sourceKind==='calendar-import'?source.calendar_import_source_state:undefined;
      if(!sourceKind||(custody!=='current'&&custody!=='unavailable'))continue;
      const state=custody,id=`source:${source.id}`,fallback=sourceKind==='ehr'?'Reviewed EHR source':sourceKind==='calendar-import'?'Imported calendar snapshot':sourceKind==='gmail'?'Reviewed Gmail email':'Reviewed Outlook email',unavailable=sourceKind==='ehr'?'Unavailable EHR source':sourceKind==='calendar-import'?'Unavailable calendar file summary':'Unavailable email source';
      // Material is metadata only. It is neither a reply nor an unread clock.
      entries.push({kind:'material',sourceKind,id,sourceId:source.id,createdAt:source.created_at,state,label:state==='current'?source.source_label??fallback:unavailable});
      positions.set(id,source.revision);
    }
    const origins=new Set(turns.map(entry=>entry.id)),handoffs=workspace.handoffs??[];
    const related=new Set(handoffs.filter(item=>origins.has(item.origin_entry_id)).map(item=>item.id));
    for(let pass=0;pass<handoffs.length;pass++){let added=false;for(const item of handoffs)if(item.revision_request&&related.has(item.revision_request.parent_handoff_id)&&!related.has(item.id)){related.add(item.id);added=true;}if(!added)break;}
    for(const handoff of workspace.handoffs??[]){
      // Revision children remain associated with the same Chief conversation.
      if(!related.has(handoff.id))continue;
      const result=workspace.entries.find(entry=>entry.id===handoff.result_entry_id);
      const withheld=!!result&&[result.google_source_state,result.microsoft_source_state,result.calendar_source_state,result.fax_source_state,result.practice_fax_source_state,result.ehr_source_state,result.calendar_import_source_state].includes('unavailable');
      const available=!!result?.reply&&!withheld&&result.kind==='handoff_result'&&result.reply.role===handoff.recipient_role&&result.reply.agent_name===handoff.recipient_name&&(!handoff.recipient_agent_id||result.reply.agent_id===handoff.recipient_agent_id)&&typeof handoff.result_sha256==='string'&&/^[a-f0-9]{64}$/.test(handoff.result_sha256);
      const label=handoffReviewLabel(handoff),reviewed=label==='Draft accepted'||label==='Changes requested'&&!!handoff.review?.revision_handoff_id&&handoffs.some(child=>child.id===handoff.review?.revision_handoff_id&&child.revision_request?.parent_handoff_id===handoff.id);
      const status=withheld?'Source access needs checking':handoff.status==='completed'?available?label:'Result needs checking':
        handoff.status==='queued'?'Queued':handoff.status==='running'?'Working':handoff.status==='failed'?'Could not finish':'Outcome needs checking';
      const actions:ConversationAction[]=available?[{kind:'review_handoff',id:handoff.id,label:'Review draft'}]:
        ['failed','interrupted'].includes(handoff.status)?[{kind:'retry_handoff',id:handoff.id,label:'Retry draft'}]:[];
      entries.push({kind:'review',id:`handoff:${handoff.id}`,author:handoff.recipient_name,title:`${handoff.recipient_name} draft`,status,needsReview:!reviewed,actions});
      positions.set(`handoff:${handoff.id}`,result?.revision??Math.max(handoff.context_revision,turns.find(entry=>entry.id===handoff.origin_entry_id)?.revision??0));
    }
  }
  if(['chief','scribe'].includes(bot?.role??'')&&workspace.note?.latest){
    const note=workspace.note.latest;
    entries.push({kind:'review',id:`note:${note.id}`,author:'Scribe',title:`Saved note · version ${note.version}`,
      status:note.sources_changed?'Sources changed':note.review?'Reviewed privately':'Needs your review',needsReview:note.sources_changed||!note.review,
      actions:[{kind:'review_note',id:note.id,label:'Review note'}]});
    positions.set(`note:${note.id}`,note.workspace_revision);
  }
  if(['chief','follow_up'].includes(bot?.role??''))for(const work of workspace.follow_ups??[]){
    if(['done','closed','rejected','completed','cancelled'].includes(work.state))continue;
    entries.push({kind:'review',id:`work:${work.ticket_id}`,author:'Follow-up',title:'Follow-up',status:work.source_changed?'Sources changed':work.state.replaceAll('_',' '),needsReview:true,
      actions:[{kind:'review_work',id:work.ticket_id,label:'Review follow-up'}]});
    const link=workspace.entries.find(entry=>entry.kind==='work_link'&&entry.ticket?.id===work.ticket_id);
    const sourceNote=workspace.note?.history.find(note=>note.version===work.note_version)??(workspace.note?.latest?.version===work.note_version?workspace.note.latest:null);
    positions.set(`work:${work.ticket_id}`,link?.revision??sourceNote?.workspace_revision??0);
  }
  entries.sort((left,right)=>(positions.get(left.id)??0)-(positions.get(right.id)??0));
  return {workspaceId:workspace.id,botAddress:selected,entries,turns};
}
