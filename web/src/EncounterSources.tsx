import type { Workspace } from "./workspace-api";
import {currentSharedNote,parseSharedClinicalNote} from './clinical-team-contract';
import {hasResearchPacketMarker,RESEARCH_PACKET_LABEL} from './research-packet-marker';

export function EncounterSources({ workspace, selectedSource, locked, source, evidence, setSource, setEvidence, onSave, onNotebook, briefViewedAt, onPrep, onReviewAppointment, onImportCalendar, onReviewOutlook, appointmentReviewLocked }: {
  workspace: Workspace; selectedSource: string | null; locked: boolean;
  source: string; evidence: string; setSource: (value: string) => void; setEvidence: (value: string) => void;
  onSave: () => void; onNotebook: () => void; briefViewedAt?:string; onPrep?:()=>void; onReviewAppointment?:()=>void; onImportCalendar?:()=>void; onReviewOutlook?:()=>void; appointmentReviewLocked?:boolean;
}) {
  const reviewedThrough=workspace.note?.latest?.source_revision;
  const entries = [...workspace.entries].reverse().filter(e => ["synthetic_source", "evidence", "scratchpad", "google_message", "microsoft_message", "google_calendar", "efax_inbound_source", "fax_inbound_source", "ehr_read_source", "calendar_import_source"].includes(e.kind)||parseSharedClinicalNote(e));
  const current=currentSharedNote(workspace);
  return <section aria-label="Saved sources">
    <div className="team-notebook-title"><h2>Saved visit sources</h2><span className="team-pill">{entries.length} saved</span></div>
    {onReviewOutlook&&<section className="outlook-source-action" aria-label="Outlook email source"><button disabled={locked||appointmentReviewLocked} onClick={onReviewOutlook}>Review Outlook email</button><p>Choose an email and check that it belongs to this visit before saving a source.</p></section>}
    {onReviewAppointment&&<section className="ehr-source-action" aria-label="Appointment source"><button disabled={locked||appointmentReviewLocked} onClick={onReviewAppointment}>Review EHR records</button><p>Choose the patient and appointment, then review the available records before saving a source. Your conversation draft stays in place.</p></section>}
    {onImportCalendar&&<section className="calendar-import-action" aria-label="Import calendar source"><button disabled={locked||appointmentReviewLocked} onClick={onImportCalendar}>Import calendar file</button><p>Review an event from an exported file before adding its summary to this visit.</p></section>}
    <p className="team-fine">Most recent first. Read changed material before reviewing the note.</p>
    {!entries.length&&<p>No notebook entries or reference notes have been saved for this visit.</p>}
    {entries.map(e => {const shared=parseSharedClinicalNote(e),research=hasResearchPacketMarker(e);return <article id={`source-${e.id}`} tabIndex={-1} className={`team-source ${selectedSource === e.id ? "selected" : ""}`} key={e.id}>
      <strong>{research?RESEARCH_PACKET_LABEL:e.source_label ?? "Your jotted notes"}</strong>
      {!shared&&!["google_message", "microsoft_message","google_calendar","efax_inbound_source","fax_inbound_source", "ehr_read_source", "calendar_import_source"].includes(e.kind)&&reviewedThrough!==undefined&&e.revision>reviewedThrough&&<span className="team-pill">Newer than the note’s sources</span>}
      <small>{shared?`Saved note version ${shared.note.version} · shared by you with your private team`:research?"Saved public Research snapshot · source claims require review":(e.kind === "efax_inbound_source" || e.kind === "fax_inbound_source") ? "Reviewed fax passage · entered by you, separate from the clinical note" : e.kind === "calendar_import_source" ? "Imported calendar summary · file snapshot only" : e.kind === "ehr_read_source" ? "Reviewed EHR source · frozen reviewed snapshot" : e.kind === "google_calendar" ? "Reviewed calendar summary · separate from the clinical note" : (e.kind === "google_message" || e.kind === "microsoft_message") ? "Reviewed email · separate from the clinical note" : e.kind === "synthetic_source" ? "Prep example · invented fixture" : e.kind === "evidence" ? "Reference note · entered by you, unverified" : "Jotted notes · entered by you"} · {new Date(e.created_at).toLocaleString()}</small>
      {shared&&<><p className="team-fine">{current?.entry.id===e.id?'Current shared saved-note snapshot.':'Historical saved-note snapshot; reconcile and share the latest note before new team work.'} This is a private draft, not clinical sign-off or a current chart read.</p><small>Content SHA-256: {shared.note.content_hash}</small></>}
      <p style={shared?{whiteSpace:'pre-wrap'}:undefined}>{shared?shared.note.content:e.calendar_import_source_state==="unavailable"?"This imported calendar summary is unavailable. Review a new import before using it.":e.ehr_source_state==="unavailable"?"This EHR source is unavailable. Check practice access before using it.":(e.fax_source_state==="unavailable"||e.practice_fax_source_state==="unavailable")?"This fax passage is unavailable. Check received-fax access and the selected visit before using it.":e.calendar_source_state==="unavailable"?"This calendar summary is unavailable. Review a fresh summary before using it.":(e.google_source_state==="unavailable"||e.microsoft_source_state==="unavailable")?"This email source is unavailable. Check its account access and current message before using it.":e.content}</p>
    </article>;})}
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
