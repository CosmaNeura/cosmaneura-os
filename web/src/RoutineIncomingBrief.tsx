import type {IncomingBriefItem,IncomingBriefSection} from './routine-inbox-contract';

const status=(v:IncomingBriefItem)=>v.state==='work_changed'?'Work changed since this brief · open current follow-up':v.state==='source_unavailable'?v.changed_since_report?'Changed since this brief · current review required':'Source unavailable · owner attention required':
  v.state==='pending_approval'?'Needs owner approval':v.state==='rejected'?'Proposal rejected':
  v.verified_current?'Local handoff verified':v.state==='closed'?'Closed · current completion unverified':
  v.ready_for_review?'Human result awaiting owner review':v.pending_offer?'Responsibility offered · acceptance pending':'Active internal follow-up';

export function RoutineIncomingBrief({section,onOpen,blocked=false}:{section?:IncomingBriefSection;onOpen?:(id:string)=>void;blocked?:boolean}){
  if(!section||section.coverage==='not_included')return <section aria-label="Incoming work coverage"><h4>Incoming handoffs</h4><p>This earlier brief did not include incoming handoffs.</p></section>;
  const shortCounts=section.counts?([
    [section.counts.overdue,'overdue'],[section.counts.awaiting_review,'awaiting review'],
    [section.counts.pending_approval,'awaiting approval'],[section.counts.awaiting_acceptance,'awaiting acceptance'],
    [section.counts.responsible_unavailable,'with an unavailable assignee'],[section.counts.source_unavailable,'with unavailable sources'],
    [section.counts.work_changed,'changed since this brief'],[section.counts.open,'active'],
    [section.counts.verified_complete,'locally verified'],
  ] as const).filter(([count])=>count>0).slice(0,3).map(([count,label])=>`${count} ${label}`).join(' · '):'';
  return <section aria-label="Incoming work coverage"><h4>Incoming handoffs</h4>
    <p>Coverage: {section.coverage==='complete'?'reviewed sources available to this account':section.coverage==='partial'?'partial · some sources need current review':'unavailable · work counts are unknown'}{section.reason==='collection_limit'?' (catalog limit reached)':''}.</p>
    {shortCounts&&<p aria-label="Incoming work summary">{shortCounts}.</p>}
    <ul>{section.items.map(item=><li key={item.ticket_id}><strong>{item.body??'Incoming follow-up requires current review'}</strong><br/>
      {item.responsible.name}{!item.responsible.available?' · unavailable':''}{item.due_date?` · Due ${item.due_date}`:''}<br/>
      <span>{status(item)}</span>{onOpen&&<div><button disabled={blocked} onClick={()=>onOpen(item.ticket_id)}>Open current incoming follow-up</button></div>}</li>)}</ul>
    {section.matching_items>section.items.length&&<p>Showing {section.items.length} of {section.matching_items} available incoming observations.</p>}
    {section.coverage==='complete'&&section.matching_items===0&&<p>No incoming handoffs were observed in these reviewed sources.</p>}
    <details><summary>Counts and coverage details</summary>
      {section.counts&&<dl>{([
        ['Needs approval',section.counts.pending_approval],['Active',section.counts.open],['Overdue',section.counts.overdue],
        ['Awaiting acceptance',section.counts.awaiting_acceptance],['Responsible person unavailable',section.counts.responsible_unavailable],
        ['Result awaiting review',section.counts.awaiting_review],['Locally verified',section.counts.verified_complete],
        ['Source unavailable',section.counts.source_unavailable],['Changed since brief',section.counts.work_changed],
      ] as const).map(([label,count])=><div key={label}><dt>{label}</dt><dd>{count}</dd></div>)}</dl>}
      {section.reason==='collection_limit'&&<p>The incoming catalog exceeded its 100-item limit. Work counts are unknown.</p>}
      {section.withheld_sources&&<p>Unavailable context and old completion claims are withheld. Authorized responsibility signals remain visible.</p>}
      <p className="team-fine">A dated administrative handoff report does not establish a patient reply or clinical outcome.</p>
    </details>
  </section>;
}
