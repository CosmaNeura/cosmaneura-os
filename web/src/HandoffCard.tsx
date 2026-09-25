import { BotAvatar } from "./BotAvatar";
import type { DraftHandoff } from "./workspace-api";

const labels = { queued: "Queued", running: "Working on draft", completed: "Draft ready", failed: "Needs attention", interrupted: "Interrupted" };
const reasons:Record<string,string>={team_work_limit:"Not started: team work limit",legacy_queued_unadmitted:"Not started by this version; review before retry",
  legacy_running_unconfirmed:"Earlier draft outcome unconfirmed",dispatch_interrupted:"Draft outcome unconfirmed; the provider may have started work",
  reservation_expired:"The recorded draft request expired before starting",model_unavailable:"The draft could not be completed. Your brief is saved; retry when ready.",
  processing_interrupted:"The draft could not be completed. Your brief is saved; retry when ready."};

export function HandoffCard({ handoff, locked, onRetry, onShow }: {
  handoff: DraftHandoff; locked: boolean; onRetry: () => void; onShow: () => void;
}) {
  const recoverable = Object.hasOwn(reasons,handoff.error_code??"")&&["failed","interrupted"].includes(handoff.status);
  return <article className="team-handoff" aria-label={`Draft assignment for ${handoff.recipient_name}`}>
    <header><BotAvatar role={handoff.recipient_role} active={handoff.status==='queued'||handoff.status==='running'} /><div><strong>Chief → {handoff.recipient_name}</strong>
      <small>{labels[handoff.status]}</small></div></header>
    <p>{handoff.brief}</p>
    <small className="team-fine">Private draft · context through revision {handoff.context_revision}</small>
    {handoff.error_code && <p className="team-handoff-error">{reasons[handoff.error_code] ??
      "The saved access or team context is no longer available. Resolve it and ask Chief for a new assignment."}</p>}
    {handoff.status === "completed" && <button onClick={onShow}>View {handoff.recipient_name} draft</button>}
    {recoverable && handoff.attempt_count < 3 && <button disabled={locked} onClick={onRetry}>Retry {handoff.recipient_name} draft</button>}
    {recoverable && handoff.attempt_count >= 3 && <p className="team-fine">Three attempts recorded. Ask Chief for a new assignment when the service is available.</p>}
    {handoff.attempt_count > 1 && <details><summary>Attempt history</summary><ol>{handoff.attempts.map(attempt =>
      <li key={attempt.id}>Attempt {attempt.number} · {labels[attempt.status as keyof typeof labels]}</li>)}</ol></details>}
  </article>;
}
