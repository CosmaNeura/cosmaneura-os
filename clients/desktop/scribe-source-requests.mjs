/** Closed source selections only; these values confer no identity or review authority. */
export const MAX_SCRIBE_SOURCE_REQUEST_BYTES = 2048;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const key = value => typeof value === 'string' && /^[A-Za-z0-9:_-]{8,100}$/.test(value);
const uuid = value => typeof value === 'string' && UUID.test(value);
const revision = value => Number.isSafeInteger(value) && value >= 1;
function exact(value, keys) {
  return value !== null && typeof value === 'object' && !Array.isArray(value) &&
    [Object.prototype, null].includes(Object.getPrototypeOf(value)) &&
    Object.keys(value).sort().join(',') === keys;
}

export function validScribeSourceRequest(action, body) {
  if (action === 'existing') return exact(body, 'idempotency_key') && key(body.idempotency_key);
  if (action !== 'source-packets' ||
      !exact(body, 'expected_revision,idempotency_key,reviewed,selection,share_with_team') ||
      !key(body.idempotency_key) || !revision(body.expected_revision) ||
      body.reviewed !== true || body.share_with_team !== true) return false;
  const selected = body.selection;
  return exact(selected, 'session_id,snapshot_sha256,source_transcript_version,version,working_transcript_id,working_transcript_version') &&
    selected.version === 1 && uuid(selected.session_id) && uuid(selected.working_transcript_id) &&
    revision(selected.source_transcript_version) && revision(selected.working_transcript_version) &&
    typeof selected.snapshot_sha256 === 'string' && /^[0-9a-f]{64}$/.test(selected.snapshot_sha256);
}
