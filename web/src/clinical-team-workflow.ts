import type {DraftHandoff,Workspace,WorkspaceEntry} from './workspace-api';

/** Follow only the saved review's exact revision link, never an unrelated newer role result. */
export function clinicalDraftLineage(workspace:Workspace,originId:string,role:'follow_up'|'research'):DraftHandoff[] {
  const handoffs=workspace.handoffs??[];
  const root=handoffs.find(h=>h.origin_entry_id===originId&&h.recipient_role===role&&!h.revision_request);
  if(!root)return [];
  const chain=[root],seen=new Set([root.id]);
  while(chain.length<=handoffs.length) {
    const parent=chain.at(-1)!,review=parent.review;
    if(parent.status!=='completed'||review?.decision!=='changes_requested'||!review.revision_handoff_id||
      review.attempt_id!==parent.attempt_id||review.result_entry_id!==parent.result_entry_id||review.result_sha256!==parent.result_sha256)break;
    const child=handoffs.find(h=>h.id===review.revision_handoff_id),link=child?.revision_request;
    if(!child||!link||seen.has(child.id)||child.recipient_role!==parent.recipient_role||
      child.recipient_agent_id!==parent.recipient_agent_id||child.recipient_key!==parent.recipient_key||
      link.parent_handoff_id!==parent.id||link.review_id!==review.id||link.attempt_id!==review.attempt_id||
      link.result_entry_id!==review.result_entry_id||link.result_sha256!==review.result_sha256||link.feedback!==review.feedback)break;
    seen.add(child.id);chain.push(child);
  }
  return chain;
}

export function clinicalDraftEntry(workspace:Workspace,handoff:DraftHandoff):WorkspaceEntry|undefined {
  if(handoff.status!=='completed'||handoff.task_brief_unavailable)return undefined;
  return workspace.entries.find(entry=>entry.id===handoff.result_entry_id&&entry.kind==='handoff_result'&&entry.reply&&
    (entry.reply.agent_id?entry.reply.agent_id===handoff.recipient_agent_id:entry.reply.role===handoff.recipient_role)&&
    ![entry.google_source_state,entry.calendar_source_state,entry.fax_source_state,entry.practice_fax_source_state,entry.ehr_source_state,entry.calendar_import_source_state].includes('unavailable'));
}

export function clinicalDraftAccepted(handoff:DraftHandoff):boolean {
  const review=handoff.review;
  return handoff.status==='completed'&&handoff.review_status==='current'&&review?.decision==='accepted'&&
    typeof handoff.result_entry_id==='string'&&typeof handoff.result_sha256==='string'&&/^[0-9a-f]{64}$/.test(handoff.result_sha256)&&
    review.attempt_id===handoff.attempt_id&&review.result_entry_id===handoff.result_entry_id&&review.result_sha256===handoff.result_sha256;
}

export function clinicalDraftRetryable(handoff:DraftHandoff):boolean {
  return !handoff.task_brief_unavailable&&['failed','interrupted'].includes(handoff.status)&&handoff.attempt_count<3&&
    ['team_work_limit','legacy_queued_unadmitted','legacy_running_unconfirmed','dispatch_interrupted','reservation_expired','model_unavailable','processing_interrupted'].includes(handoff.error_code??'');
}

export type ClinicalDraftSection={label:string;content:string};
// These are presentation labels for exact saved text, not a new generated-output contract.
function heading(line:string):string {
  return line.trim().replace(/^#{1,6}\s+/,'')
    .replace(/^\*\*(.*?)\*\*:?$/,'$1').replace(/^__(.*?)__:?$/,'$1').replace(/:$/,'').trim().toLowerCase();
}
export function clinicalDraftSections(role:'follow_up'|'research',content:string):ClinicalDraftSection[]|null {
  const lines=content.split('\n');
  const index=(names:string[])=>lines.flatMap((line,i)=>names.includes(heading(line))?[i]:[]);
  if(role==='follow_up') {
    const actions=index(['provider action items']);
    if(actions.length!==1||actions[0]===0)return null;
    const before=lines.slice(0,actions[0]).join('\n');
    const emailLines=lines.slice(0,actions[0]).map(line=>line.replace(/\*\*|__/g,''));
    if(!emailLines.some(line=>heading(line)==='subject'||/^\s*(?:#{1,6}\s*)?subject\s*:/i.test(line))||
      !emailLines.some(line=>heading(line)==='body'||/^\s*(?:#{1,6}\s*)?body\s*:/i.test(line)))return null;
    const after=lines.slice(actions[0]+1).join('\n');
    return after.trim()?[{label:'Patient email draft',content:before},{label:'Provider action items',content:after}]:null;
  }
  const labels=['Source-supported findings','Drug and treatment questions','Missing evidence / next checks'];
  const positions=labels.map(label=>index([label.toLowerCase()]));
  if(positions.some(p=>p.length!==1)||positions[0][0]>=positions[1][0]||positions[1][0]>=positions[2][0])return null;
  const sections=labels.map((label,i)=>({label,content:lines.slice(positions[i][0]+1,i<2?positions[i+1][0]:undefined).join('\n')}));
  return sections.every(s=>s.content.trim())?sections:null;
}
