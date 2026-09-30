import {useEffect, useId, useMemo, useRef, useState} from "react";
import {BffResponseError} from "../../clients/capture/src/bff/http-client";
import {readSessionPrep, type CitedText, type SessionPrep} from "./session-prep-api";
import {sessionPrepAnalysis, type SessionPrepAnalysis} from "./session-prep-analysis-contract";
import {WorkspaceApiError, type AuthenticatedWorkspaceIdentity, type CaptureBotSelection} from "./workspace-api";

export function SessionPrepPanel({workspaceId, identity, bot, enabled, locked, onAccessLost, onSelect, selected=false, onBriefViewed}: {
  workspaceId: string; identity: AuthenticatedWorkspaceIdentity; bot: CaptureBotSelection;
  enabled: boolean; locked: boolean; onAccessLost?: (cause: WorkspaceApiError) => void;
  onSelect?: (selection:SessionPrepAnalysis|null)=>void; selected?:boolean; onBriefViewed?:(at:string|null)=>void;
}) {
  const scope = useMemo(() => Symbol(), [workspaceId, identity, bot.address, bot.team_revision, enabled]);
  const currentScope = useRef(scope); currentScope.current = scope;
  const blocked = useRef(locked); blocked.current = locked;
  const active = useRef<AbortController | null>(null);
  const [expanded,setExpanded]=useState(false);
  const [state, setState] = useState<{scope: symbol; busy: boolean; value?: SessionPrep; error?: string}>({scope, busy: false});
  const current = state.scope === scope ? state : {busy: false, value: undefined, error: undefined};
  const sourceId = useId();
  useEffect(() => () => active.current?.abort(), [scope]);
  async function open() {
    if (!enabled || locked || current.busy) return;
    const controller = new AbortController(); active.current?.abort(); active.current = controller;
    onSelect?.(null); onBriefViewed?.(null);
    setState({scope, busy: true});
    try {
      const value = await readSessionPrep(workspaceId, identity, bot, controller.signal);
      if (!controller.signal.aborted && currentScope.current === scope) {setState({scope, busy: false, value});setExpanded(true);onBriefViewed?.(value.prepared_brief?value.generated_at:null);}
    } catch (error) {
      if (controller.signal.aborted || currentScope.current !== scope) return;
      setState({scope, busy: false, error: "Session Prep could not be confirmed. Refresh the encounter and check your connection before trying again."});
      if (error instanceof BffResponseError && [401, 403, 404].includes(error.status)) onAccessLost?.(new WorkspaceApiError(error.status));
    }
  }
  const value = current.value;
  const brief = value?.prepared_brief;
  async function include() {
    if(!value?.prepared_brief||!enabled||locked||current.busy||!onSelect)return;
    if(selected){onSelect(null);return;}
    const sourceRequest=active.current;
    try {
      const chosen=await sessionPrepAnalysis(value);
      if(currentScope.current===scope&&!blocked.current&&active.current===sourceRequest&&!sourceRequest?.signal.aborted) {onSelect(chosen);setExpanded(false);}
    } catch {
      if(currentScope.current===scope&&active.current===sourceRequest&&!sourceRequest?.signal.aborted)
        setState({scope,busy:false,value,error:"This brief could not be included. Refresh Session Prep and try again."});
    }
  }
  const sources = value?.sources.filter(source => source.included) ?? [];
  function showSource(ref: string) {
    const target = document.getElementById(`${sourceId}-${ref}`);
    const detail=target?.querySelector("details"); if(detail)detail.open=true;
    // Native requests are bound to the exact document URL, including its fragment.
    target?.scrollIntoView({block: "nearest"});
    target?.focus({preventScroll: true});
  }
  const citations = (refs: string[]) => <sup className="session-prep-citations" aria-label={`Sources ${refs.map(ref => sources.findIndex(s => s.source_id === ref) + 1).join(", ")}`}>
    {refs.map(ref => <button key={ref} type="button" aria-label={`Show source ${sources.findIndex(s => s.source_id === ref) + 1}`}
      aria-controls={`${sourceId}-${ref}`} onClick={() => showSource(ref)}>[{sources.findIndex(s => s.source_id === ref) + 1}]</button>)}</sup>;
  const items = (title: string, entries: CitedText[]) => entries.length > 0 && <section><h4>{title}</h4><ul>{entries.map((item, i) =>
    <li key={i}>{item.text} {citations(item.source_refs)}</li>)}</ul></section>;
  return <section className="team-prep session-prep" aria-label="Session Prep brief" aria-busy={current.busy}>
    <h3>Session Prep</h3>
    <p>A visit brief from your finalized notes and available patient-reported preparation.</p>
    <div className="capture-actions"><button className={value?"team-subtle":"team-primary"} disabled={!enabled || locked || current.busy} onClick={() => void open()}>
      {current.busy ? "Opening Session Prep…" : value?.state === "pending" ? "Check for completed brief" : value ? "Refresh Session Prep" : "Open Session Prep"}</button></div>
    {current.error && <p role="alert">{current.error}</p>}
    {value?.state === "pending" && <p role="status">Your brief is being prepared in Cosmaneura. Check again shortly; you can continue working in the meantime.</p>}
    {value?.state === "unavailable" && <p role="status">{value.reason_code === "no_eligible_sources" ?
      "No finalized notes or patient-reported preparation are available for this visit yet." : "Session Prep is temporarily unavailable. Try again shortly."}</p>}
    {brief && value && <>
      <p className="team-fine">AI-prepared brief · review against the cited sources. Prepared {new Date(value.generated_at!).toLocaleString()}.</p>
      {onSelect&&!selected&&<button className="team-subtle" disabled={!enabled||locked||current.busy} onClick={()=>void include()}>Include in chat</button>}
      {value.state === "refreshing" && <p role="status">An updated brief is being prepared. This is the previous version, using sources through {new Date(value.current_through!).toLocaleString()}.</p>}
      {value.completeness === "partial" && <p role="status">Some records are not included. Review the source list before using this brief.</p>}
      <details className="session-prep-detail" open={expanded} onToggle={event=>setExpanded(event.currentTarget.open)}><summary>Review brief · version {value.brief_version}</summary>
      <section><h4>Recap</h4><p className="team-prep-content">{brief.recap.text} {citations(brief.recap.source_refs)}</p></section>
      {items("Talking points", brief.talking_points)}
      {items("Changes since prior visits", brief.trajectory_and_material_changes)}
      {items("Open threads", brief.open_threads)}
      {items("Cautions", brief.cautions)}
      {items("Suggested visit outline", brief.suggested_outline)}
      {brief.patient_reported && <section><h4>Patient-reported preparation</h4><p>{brief.patient_reported.summary} {citations(brief.patient_reported.source_refs)}</p></section>}
      <section className="session-prep-sources"><h4>Sources</h4><ol>{sources.map(source => <li key={source.source_id} id={`${sourceId}-${source.source_id}`} tabIndex={-1}>
        <strong>{source.source_class === "clinician_finalized_note" ? "Finalized clinician note" : "Patient-reported Visit Prep"}</strong> · {new Date(source.source_at!).toLocaleDateString()} · version {source.source_version}
        <details><summary>Original text unavailable here</summary><p>This brief includes the source’s date and version, but the original text is not available in this view. Open the matching {source.source_class === "clinician_finalized_note" ? "finalized note" : "patient preparation"} in your clinical record to check the statement.</p></details>
        </li>)}</ol>
        {value.sources.some(s => !s.included && s.reason_code === "selection_limit") && <p className="team-fine">Additional records fall outside this brief's source limit.</p>}
        {value.sources.some(s => !s.included && s.reason_code === "source_temporarily_unavailable") && <p className="team-fine">A source was temporarily unavailable.</p>}
      </section>
      </details>
    </>}
  </section>;
}
