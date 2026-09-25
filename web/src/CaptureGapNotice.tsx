import { gapReasons, type CaptureGapReview } from "./capture-gap-review";

export function CaptureGapNotice({ review }: { review: CaptureGapReview }) {
  return <aside className="team-note-notice" aria-label="Capture interruptions">
    <strong>Recording has {review.observations.length} {review.observations.length === 1 ? "interruption" : "interruptions"}</strong>
    <p>Some conversation may be missing. Check the note for missing context before reviewing it.</p>
    <details><summary>Review capture interruptions</summary>
      <p className="team-fine">These times show when an interruption was noticed and acknowledged. They do not establish how much audio is missing.</p>
      <ol className="capture-gap-observations">{review.observations.map(gap => <li key={gap.gap_id}>
        <strong>{gapReasons[gap.reason_code]}</strong>
        <p>Noticed {new Date(gap.observed_at).toLocaleString()} · Acknowledged {new Date(gap.acknowledged_at).toLocaleString()}</p>
        <p>{gap.decision === "resume_capture" ? "Continuation was requested; recording required a separate Start." : "The recording was finished with this interruption retained."}</p>
      </li>)}</ol>
    </details>
  </aside>;
}
