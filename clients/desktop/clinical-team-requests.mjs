const ID = /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/;
const DIGEST = /^[a-f0-9]{64}$/;
export const MAX_CLINICAL_TEAM_REQUEST_BYTES = 4096;
export function validClinicalTeamRequest(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value) &&
    Object.keys(value).sort().join(',') === 'content_hash,expected_revision,idempotency_key,note_id,note_version,share_with_team,source_fingerprint' &&
    Number.isSafeInteger(value.expected_revision) && value.expected_revision >= 1 &&
    typeof value.idempotency_key === 'string' && /^[A-Za-z0-9:_-]{8,100}$/.test(value.idempotency_key) &&
    typeof value.note_id === 'string' && ID.test(value.note_id) &&
    Number.isSafeInteger(value.note_version) && value.note_version >= 1 && value.note_version <= 50 &&
    typeof value.content_hash === 'string' && DIGEST.test(value.content_hash) &&
    typeof value.source_fingerprint === 'string' && DIGEST.test(value.source_fingerprint) &&
    value.share_with_team === true;
}
