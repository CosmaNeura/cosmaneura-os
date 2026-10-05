import { BotAvatar } from "./BotAvatar";
import type { DraftHandoff } from "./workspace-api";
import {teamHash,teamUuid} from './team-setup-request';

const labels = { queued: "Queued", running: "Working on draft", completed: "Draft ready", failed: "Needs attention", interrupted: "Interrupted" };
const reasons:Record<string,string>={team_work_limit:"Not started: team work limit",legacy_queued_unadmitted:"Not started by this version; review before retry",
  legacy_running_unconfirmed:"Earlier draft outcome unconfirmed",dispatch_interrupted:"Draft outcome unconfirmed; the provider may have started work",
  reservation_expired:"The recorded draft request expired before starting",model_unavailable:"The draft could not be completed. Your brief is saved; retry when ready.",
  processing_interrupted:"The draft could not be completed. Your brief is saved; retry when ready.",
  source_changed:"The saved source versions changed. Ask Chief for a new assignment using the current sources.",
  authority_changed:"This teammate’s access changed. Review its source settings, then ask Chief for a new assignment."};

export function HandoffCard({ handoff, locked, onRetry, onShow, resultAvailable=true, maskedResultAvailable=false }: {
  handoff: DraftHandoff; locked: boolean; resultAvailable?:boolean; maskedResultAvailable?:boolean; onRetry: () => void; onShow: () => void;
}) {
  const recoverable = !handoff.task_brief_unavailable && !["source_changed","authority_changed"].includes(handoff.error_code??"") && Object.hasOwn(reasons,handoff.error_code??"")&&["failed","interrupted"].includes(handoff.status);
  const reviewRecovery=maskedResultAvailable&&handoff.status==='completed'&&handoff.review_status==='stale'&&handoff.task_brief_unavailable===true&&
    teamUuid(handoff.id)&&teamUuid(handoff.attempt_id)&&teamUuid(handoff.result_entry_id)&&teamHash(handoff.result_sha256);
  const task=handoff.task_brief,goal=task?.goal??handoff.brief,characters=[...goal],shortened=characters.length>160;
  const preview=shortened?characters.slice(0,159).join('')+'…':goal;
  return <article className="team-handoff" aria-label={`Draft assignment for ${handoff.recipient_name}`}>
    <header><BotAvatar role={handoff.recipient_role} active={handoff.status==='queued'||handoff.status==='running'} /><div><strong>{handoff.recipient_name}</strong>
      <small>{handoff.review_status==='stale'?'Review needs updating':handoff.review?.decision==='accepted'?'Draft accepted':
        handoff.review?.decision==='changes_requested'?'Changes requested':labels[handoff.status]}</small></div></header>
    <p className="team-task-goal">{preview}</p>
    {handoff.status === "completed" && handoff.result_entry_id && !handoff.task_brief_unavailable &&
      <button className="team-task-review" disabled={locked||!resultAvailable} onClick={onShow} aria-label={`Review ${handoff.recipient_name} result`}>{resultAvailable?'Review result':'Loading saved result…'}</button>}
    {reviewRecovery&&<button className="team-task-review" disabled={locked} onClick={onShow} aria-label={`Check saved ${handoff.recipient_name} review`}>Check saved review</button>}
    <p className="team-task-summary team-fine">{handoff.status==='completed'
      ? <>Private draft saved{handoff.completion_evidence?` · revision ${handoff.completion_evidence.revision} · ${handoff.completion_evidence.source_versions.length} sources cited`:''}</>
      : task ? <>{task.source_versions.length} saved {task.source_versions.length===1?'source':'sources'} · Independent draft</>
      : 'Saved assignment'}</p>
    {handoff.task_brief_unavailable&&<p className="team-handoff-error">The full task brief is unavailable. Ask Chief for a new assignment before continuing.</p>}
    <details className="team-task-details"><summary>{task?'Task brief and sources':'Assignment details'}</summary>
      {shortened&&<><h4>Full assignment</h4><p className="team-task-full-goal">{goal}</p></>}
      {task ? <>
        <p>Chief’s assignment saved · {task.source_versions.length} saved source {task.source_versions.length===1?'version':'versions'} · Can work independently</p>
        <h4>Result to prepare</h4><p className="team-task-output">{task.expected_output}</p>
        <h4>Missing or unconfirmed</h4>{task.missing_facts.length?<ul>{task.missing_facts.map((fact,i)=><li key={i}>{fact}</li>)}</ul>:<p>None identified by Chief. This does not establish that the record is complete.</p>}
        <h4>Check the draft for</h4><ul>{task.completion_criteria.map((item,i)=><li key={i}>{item}</li>)}</ul>
        <h4>Sources used for this assignment</h4><ul>{task.source_versions.map(source=><li key={source.entry_id}>{source.label} · revision {source.revision}<small>SHA-256 {source.sha256}</small></li>)}</ul>
        <p>Depends on Chief’s saved assignment, revision {task.depends_on.revision}. No sibling result is assumed.</p>
        <p>Allowed: prepare a private draft for your review. Public searches and external actions use their separate controls.</p>
      </> : <p>Detailed task requirements were not recorded.</p>}
      <p>Clinical care and external work are not marked complete.</p>
    </details>
    {handoff.error_code && <p className="team-handoff-error">{reasons[handoff.error_code] ??
      "The saved access or team context is no longer available. Resolve it and ask Chief for a new assignment."}</p>}
    {recoverable && handoff.attempt_count < 3 && <button disabled={locked} onClick={onRetry}>Retry {handoff.recipient_name} draft</button>}
    {recoverable && handoff.attempt_count >= 3 && <p className="team-fine">Three attempts recorded. Ask Chief for a new assignment when the service is available.</p>}
    {handoff.attempt_count > 1 && <details><summary>Attempt history</summary><ol>{handoff.attempts.map(attempt =>
      <li key={attempt.id}>Attempt {attempt.number} · {labels[attempt.status as keyof typeof labels]}</li>)}</ol></details>}
  </article>;
}
