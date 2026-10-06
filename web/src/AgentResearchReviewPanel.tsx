import {useEffect, useRef, useState} from 'react';
import type {AgentResearchReview} from '../../clients/capture/src/team/connector-tools';
import {agentResearchApi} from './connector-tools-api';
import {validateAgentResearchRecovery, type AgentResearchApproval, type AgentResearchRecoveryAccess} from './agent-research-recovery';
import {WorkspaceApiError, type AuthenticatedWorkspaceIdentity} from './workspace-api';

export function AgentResearchReviewPanel({identity, workspaceId, recovery, locked = false, onBusyChange, onReady, onAuthenticationLost}: {
  identity: AuthenticatedWorkspaceIdentity; workspaceId: string; recovery: AgentResearchRecoveryAccess;
  locked?: boolean; onBusyChange?: (busy: boolean) => void; onReady?: (proposal: AgentResearchReview) => void;
  onAuthenticationLost?: (cause: unknown) => void;
}) {
  const [proposals, setProposals] = useState<AgentResearchReview[]>([]), [pending, setPending] = useState<AgentResearchApproval | null>(null);
  const [checked, setChecked] = useState<string | null>(null), [busy, setBusy] = useState(false), [ready, setReady] = useState(false);
  const [error, setError] = useState(''), [message, setMessage] = useState('');
  const busyCallback = useRef(onBusyChange); busyCallback.current = onBusyChange;
  const live = useRef({identity, workspaceId, recovery, alive: true, generation: 0}), request = useRef<AbortController | null>(null);
  if (live.current.identity !== identity || live.current.workspaceId !== workspaceId || live.current.recovery !== recovery)
    live.current = {identity, workspaceId, recovery, alive: true, generation: live.current.generation + 1};
  const current = (generation: number) => live.current.alive && live.current.generation === generation &&
    live.current.identity === identity && live.current.workspaceId === workspaceId && live.current.recovery === recovery;
  useEffect(() => {live.current.alive = true; return () => {live.current.alive = false; request.current?.abort();};}, []);
  useEffect(() => {busyCallback.current?.(busy || !!pending);}, [busy, pending]);
  useEffect(() => {
    const generation = ++live.current.generation;
    setReady(false); setBusy(false); setPending(null); setProposals([]); setChecked(null); setError(''); setMessage('');
    void (async () => {await recovery.authorize(); if (!current(generation)) return;
      const saved = await recovery.load(); if (!current(generation)) return;
      setPending(saved ? validateAgentResearchRecovery(saved, workspaceId).pending : null); setReady(true);
    })().catch(() => {if (current(generation)) setError('Private query review could not be recovered. Reopen this visit before approving.');});
    return () => {live.current.generation++; request.current?.abort();};
  }, [identity, workspaceId, recovery]);
  const pendingMatch = (row: AgentResearchReview, value: AgentResearchApproval) => row.ticket_id === value.ticket_id &&
    row.revision_id === value.revision_id && row.payload_hash === value.payload_hash;
  function failure(cause: unknown) {
    setError('The query review could not be confirmed. Its exact request is retained; check saved reviews before another action.');
    if (cause instanceof WorkspaceApiError && [401, 403, 426].includes(cause.status)) {setProposals([]); setChecked(null); onAuthenticationLost?.(cause);}
  }
  async function load() {
    if (!ready || busy || locked) return;
    const generation = live.current.generation, controller = new AbortController(); request.current = controller;
    setBusy(true); setError(''); setChecked(null);
    try {
      await recovery.authorize(); if (!current(generation)) return;
      const result = await agentResearchApi.list(identity, workspaceId, controller.signal); if (!current(generation)) return;
      if (pending) {
        const exact = result.proposals.find(row => pendingMatch(row, pending));
        if (exact && ['approved', 'result_ready', 'expired', 'source_changed', 'team_changed'].includes(exact.state)) {
          await recovery.persist(null); if (!current(generation)) return; setPending(null);
        } else setMessage('The earlier review is still unresolved. No approval was repeated.');
      }
      setProposals(result.proposals);
    } catch (cause) {if (current(generation)) failure(cause);}
    finally {if (current(generation)) setBusy(false);}
  }
  async function approve(row: AgentResearchReview) {
    if (!ready || busy || locked || pending || checked !== row.revision_id || row.state !== 'pending_approval' ||
        Date.parse(row.expires_at) <= Date.now()) return;
    const generation = live.current.generation, controller = new AbortController(); request.current = controller;
    const exact: AgentResearchApproval = {ticket_id: row.ticket_id, revision_id: row.revision_id,
      payload_hash: row.payload_hash, public_query_confirmed: true};
    let transmitted = false;
    setBusy(true); setError(''); setMessage('');
    try {
      await recovery.authorize(); if (!current(generation)) return;
      await recovery.persist({contract: 'agent-research-review-recovery.v1', workspace_id: workspaceId, pending: exact});
      if (!current(generation)) return; setPending(exact);
      transmitted = true;
      const result = await agentResearchApi.approve(identity, workspaceId, exact, controller.signal); if (!current(generation)) return;
      await recovery.persist(null); if (!current(generation)) return;
      setPending(null); setChecked(null); setProposals(values => values.map(value => value.ticket_id === result.ticket_id ? result : value));
      setMessage('Query approved. Ask Research to run this reviewed query when you are ready.');
    } catch (cause) {if (current(generation)) {
      if (transmitted) failure(cause);
      else {setReady(false); setError('The approval was not sent. Reopen this visit to confirm private recovery storage before approving.');}
    }}
    finally {if (current(generation)) setBusy(false);}
  }
  return <section aria-label="Review bot-proposed public research">
    <h2>Review proposed research</h2>
    <p>Your bot can prepare a general public query. Review its wording and sources before allowing it to contact a public service.</p>
    <button disabled={!ready || busy || locked} onClick={() => void load()}>{pending ? 'Check saved query review' : 'Load proposed queries'}</button>
    {pending && <p role="status">The exact earlier review is retained until its saved state is confirmed.</p>}
    {proposals.map(row => <article key={row.ticket_id} aria-label="Proposed public query">
      <p>{row.query}</p><p>Sources: {row.sources.join(', ')} · {row.state.replaceAll('_', ' ')}</p>
      {row.state === 'pending_approval' && <><label><input type="checkbox" checked={checked === row.revision_id}
        disabled={!ready || busy || locked || !!pending || Date.parse(row.expires_at) <= Date.now()}
        onChange={event => setChecked(event.target.checked ? row.revision_id : null)}/>I reviewed this general query and confirmed it contains no patient identifiers.</label>
        <button disabled={!ready || busy || locked || !!pending || checked !== row.revision_id || Date.parse(row.expires_at) <= Date.now()}
          onClick={() => void approve(row)}>Approve public search</button></>}
      {row.state === 'approved' && <button disabled={!ready || busy || locked || !!pending || Date.parse(row.expires_at) <= Date.now()}
        onClick={() => {if (Date.parse(row.expires_at) > Date.now()) onReady?.(row);}}>Ask Research about this approved query</button>}
      {row.state === 'outcome_unconfirmed' && <p>The previous search outcome is uncertain. Read saved status before considering another query.</p>}
    </article>)}
    {message && <p role="status">{message}</p>}{error && <p role="alert">{error}</p>}
  </section>;
}
