import type { Workspace } from "./workspace-api";

export function EncounterSources({ workspace, selectedSource, locked, source, evidence, setSource, setEvidence, onSave, onNotebook, briefViewedAt, onPrep }: {
  workspace: Workspace; selectedSource: string | null; locked: boolean;
  source: string; evidence: string; setSource: (value: string) => void; setEvidence: (value: string) => void;
  onSave: () => void; onNotebook: () => void; briefViewedAt?:string; onPrep?:()=>void;
}) {
  const reviewedThrough=workspace.note?.latest?.source_revision;
  const entries = [...workspace.entries].reverse().filter(e => ["synthetic_source", "evidence", "scratchpad", "google_message", "google_calendar", "efax_inbound_source"].includes(e.kind));
  return <section aria-label="Scribe sources">
    <div className="team-notebook-title"><h2>Saved visit sources</h2><span className="team-pill">{entries.length} saved</span></div>
    <p className="team-fine">Most recent first. Read changed material before reviewing the note.</p>
    {!entries.length&&<p>No notebook entries or reference notes have been saved for this visit.</p>}
    {entries.map(e => <article id={`source-${e.id}`} tabIndex={-1} className={`team-source ${selectedSource === e.id ? "selected" : ""}`} key={e.id}>
      <strong>{e.source_label ?? "Your jotted notes"}</strong>
      {!["google_message","google_calendar","efax_inbound_source"].includes(e.kind)&&reviewedThrough!==undefined&&e.revision>reviewedThrough&&<span className="team-pill">Newer than the note’s sources</span>}
      <small>{e.kind === "efax_inbound_source" ? "Reviewed fax passage · entered by you, separate from the clinical note" : e.kind === "google_calendar" ? "Reviewed calendar summary · separate from the clinical note" : e.kind === "google_message" ? "Reviewed email · separate from the clinical note" : e.kind === "synthetic_source" ? "Prep example · invented fixture" : e.kind === "evidence" ? "Reference note · entered by you, unverified" : "Jotted notes · entered by you"} · {new Date(e.created_at).toLocaleString()}</small>
      <p>{e.fax_source_state==="unavailable"?"This fax passage is unavailable. Check received-fax access and the selected visit before using it.":e.calendar_source_state==="unavailable"?"This calendar summary is unavailable. Review a fresh summary before using it.":e.google_source_state==="unavailable"?"This email source is unavailable. Check its account access and current message before using it.":e.content}</p>
    </article>)}
    <button className="team-subtle" onClick={onNotebook}>Open notebook</button>
    <section className="team-source-prep"><h3>Session Prep</h3>
      <p>{briefViewedAt?`Saved brief viewed for this visit · prepared ${new Date(briefViewedAt).toLocaleString()}.`:"Open Visit Prep to check for a saved brief."} Live refresh status is checked in Visit Prep.</p>
      {onPrep&&<button onClick={onPrep}>Open Session Prep</button>}
    </section>
    <details className="team-add-source"><summary>Add a reference note</summary>
      <p className="team-fine">Save your own text about a source. This does not import a transcript or retrieve a prior visit.</p>
      <form onSubmit={event => { event.preventDefault(); onSave(); }}>
        <label>Reference label<input maxLength={160} value={source} disabled={locked} onChange={e => setSource(e.target.value)} /></label>
        <label>Reference note<textarea maxLength={20000} rows={4} value={evidence} disabled={locked} onChange={e => setEvidence(e.target.value)} /></label>
        <button disabled={locked || !evidence.trim() || !source.trim()}>Save reference note</button>
      </form>
    </details>
    <details className="team-source-background"><summary>Other ways Scribe gets context</summary>
      <p>Telehealth and Mobile Scribe provide visit transcripts. Patient preparation, saved notebook entries and Session Prep provide additional context.</p>
      <p>Connection and recording status are not checked in this source list. Recording requires consent and an explicit start in the visit controls.</p>
    </details>
  </section>;
}
