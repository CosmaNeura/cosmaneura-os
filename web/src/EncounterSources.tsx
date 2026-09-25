import type { Workspace } from "./workspace-api";

const sourceRoutes = [
  { name: "Telehealth session", category: "Visit transcript", description: "Session transcript from Core.", status: "Awaiting connection", symbol: "▣" },
  { name: "Mobile Scribe", category: "Visit transcript", description: "Consented recording on your phone.", status: "Awaiting connection", symbol: "◉" },
  { name: "Patient chatbot", category: "Patient intake", description: "Responses supplied by the patient.", status: "Awaiting connection", symbol: "◇" },
  { name: "Clinician notebook", category: "Jotted notes", description: "Your working notes and saved references.", status: "Available here", symbol: "✎" },
  { name: "Session Prep", category: "Prep summary", description: "Prior visits summarized with source links.", status: "Awaiting connection", symbol: "≋" },
] as const;

export function EncounterSources({ workspace, selectedSource, locked, source, evidence, setSource, setEvidence, onSave, onNotebook }: {
  workspace: Workspace; selectedSource: string | null; locked: boolean;
  source: string; evidence: string; setSource: (value: string) => void; setEvidence: (value: string) => void;
  onSave: () => void; onNotebook: () => void;
}) {
  const entries = workspace.entries.filter(e => ["synthetic_source", "evidence", "scratchpad"].includes(e.kind));
  return <section aria-label="Scribe sources">
    <h2>Where Scribe gets context</h2>
    <p className="team-fine">Transcripts, patient intake, your jotted notes, and summaries of prior visits stay distinct.</p>
    <ul className="team-source-routes" aria-label="Scribe source connections">
      {sourceRoutes.map(route => <li key={route.name}>
        <span className="team-source-symbol" aria-hidden="true">{route.symbol}</span>
        <div><strong>{route.name}</strong><span className="team-source-category">{route.category}</span>
          <p>{route.description}</p>
          {route.name === "Clinician notebook" ? <button className="team-subtle" onClick={onNotebook}>Open notebook →</button> : <small>{route.status}</small>}
        </div>
      </li>)}
    </ul>
    <p className="team-fine">Scribe turns these materials into a visit note for your review. Recording begins only after consent and an explicit start.</p>
    <div className="team-source-saved-heading"><h3>Saved in this encounter</h3><span>{entries.length}</span></div>
    {entries.map(e => <article id={`source-${e.id}`} tabIndex={-1} className={`team-source ${selectedSource === e.id ? "selected" : ""}`} key={e.id}>
      <strong>{e.source_label ?? "Your jotted notes"}</strong>
      <small>{e.kind === "synthetic_source" ? "Prep example · invented fixture" : e.kind === "evidence" ? "Reference note · entered by you, unverified" : "Jotted notes · entered by you"} · revision {e.revision}</small>
      <p>{e.content}</p>
    </article>)}
    <details className="team-add-source"><summary>Add a reference note</summary>
      <p className="team-fine">Keep a jotted note about a source. This saves your text; it does not import a transcript or retrieve a prior visit.</p>
      <form onSubmit={event => { event.preventDefault(); onSave(); }}>
        <label>Reference label<input maxLength={160} value={source} disabled={locked} onChange={e => setSource(e.target.value)} /></label>
        <label>Reference note<textarea maxLength={20000} rows={4} value={evidence} disabled={locked} onChange={e => setEvidence(e.target.value)} /></label>
        <button disabled={locked || !evidence.trim() || !source.trim()}>Save reference note</button>
      </form>
    </details>
  </section>;
}
