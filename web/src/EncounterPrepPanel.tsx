import { useEffect, useRef, useState } from "react";
import { readEncounterPrep, type EncounterPrep } from "./encounter-prep-api";
import {PREP_WORK_BUILD} from "./prep-work-api";
import {PreparationWorkPanel} from "./PreparationWorkPanel";
import {BffResponseError} from "../../clients/capture/src/bff/http-client";
import {WorkspaceApiError} from "./workspace-api";
import type { AuthenticatedWorkspaceIdentity, CaptureBotSelection } from "./workspace-api";

export function EncounterPrepPanel({workspaceId, identity, bot, name, enabled, locked, entryRevision=0, workEnabled=false, onChanged, onAccessLost}: {
  workspaceId: string; identity: AuthenticatedWorkspaceIdentity; bot: CaptureBotSelection;
  name: string; enabled: boolean; locked: boolean; entryRevision?:number; workEnabled?:boolean;
  onChanged?:(revision:number)=>void;onAccessLost?:(cause:WorkspaceApiError)=>void;
}) {
  const [value, setValue] = useState<EncounterPrep | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [checked, setChecked] = useState("");
  const active = useRef<AbortController | null>(null);
  useEffect(() => { setValue(null); setError(""); setChecked(""); setBusy(false);
    return () => active.current?.abort(); }, [workspaceId, identity, bot.address, bot.team_revision]);
  async function read() {
    if (!enabled || locked || busy) return;
    const controller = new AbortController(); active.current?.abort(); active.current = controller;
    setBusy(true); setError(""); setValue(null); setChecked("");
    try {
      const result = await readEncounterPrep(workspaceId, identity, bot, controller.signal);
      if (!controller.signal.aborted) { setValue(result); setChecked(new Date().toLocaleTimeString()); }
    } catch (cause) {
      if (!controller.signal.aborted && cause instanceof BffResponseError && [401,403,404].includes(cause.status)) onAccessLost?.(new WorkspaceApiError(cause.status));
      if (!controller.signal.aborted) setError("Visit context could not be confirmed. Refresh the encounter and check the bot's saved-source settings before trying again.");
    } finally { if (!controller.signal.aborted) setBusy(false); }
  }
  return <section className="team-prep" aria-label="Visit preparation">
    <div className="capture-actions"><button disabled={!enabled || locked || busy} onClick={() => void read()}>
      {busy ? "Checking visit context…" : value ? "Refresh visit context" : "Review visit context"}</button>
      <small>{name} · saved intake and prior visit drafts</small></div>
    {error && <p role="alert">{error}</p>}
    {value && <>
      <p className="team-fine">Checked at {checked}. Prior Core drafts are generated text; clinical review and signature have not been verified. These sources remain separate from this visit's transcript and scratch notes.</p>
      {!value.sources.length && <p>No saved intake summary or recent prior draft is available for this encounter.</p>}
      {value.sources.map(source => <details key={source.source_id}>
        <summary>{source.label} · visit {new Date(source.source_at).toLocaleDateString()}</summary>
        <p className="team-prep-content">{source.content}</p>
        {source.content_redacted && <p className="team-fine">Private access identifiers were removed from this display.</p>}
        {source.truncated && <p className="team-fine">Showing an excerpt. Open Core to inspect the full source.</p>}
      </details>)}
      {value.additional_notes_available && <p className="team-fine">More saved records are available in Core.</p>}
    </>}
    {PREP_WORK_BUILD&&workEnabled&&<PreparationWorkPanel workspaceId={workspaceId} identity={identity} bot={bot} entryRevision={entryRevision}
      receipt={value} enabled={enabled} locked={locked||busy} onChanged={onChanged} onAccessLost={onAccessLost}/>}
  </section>;
}
