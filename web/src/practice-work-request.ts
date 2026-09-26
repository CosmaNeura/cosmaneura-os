import type { FollowUpCompleteInput, WorkHandoffInput } from "./workspace-api";

export type PracticeWorkOperation = { ticketId: string; type: "handoff"; body: WorkHandoffInput } |
  { ticketId: string; type: "complete"; body: FollowUpCompleteInput };
const uuid = (value: unknown) => typeof value === "string" && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(value);
const keys = (value: object, expected: string) => Object.keys(value).sort().join(",") === expected.split(",").sort().join(",");
export function validPracticeOperation(value: unknown): value is PracticeWorkOperation {
  if (!value || typeof value !== "object" || Array.isArray(value) || !keys(value,"ticketId,type,body")) return false;
  const operation = value as Record<string,unknown>, body = operation.body as Record<string,unknown> | null;
  if (!uuid(operation.ticketId) || !body || typeof body !== "object" || Array.isArray(body) || !uuid(body.revision_id) ||
      typeof body.payload_hash !== "string" || !/^[a-f0-9]{64}$/.test(body.payload_hash) ||
      typeof body.idempotency_key !== "string" || !/^[A-Za-z0-9:_-]{8,100}$/.test(body.idempotency_key)) return false;
  if (operation.type === "complete") {
    const versioned = Object.hasOwn(body, "expected_version");
    return keys(body,"revision_id,payload_hash,idempotency_key,evidence" + (versioned ? ",expected_version" : "")) &&
      (!versioned || Number.isSafeInteger(body.expected_version) && (body.expected_version as number) >= 1) &&
      typeof body.evidence === "string" && !!body.evidence.trim() && body.evidence.length <= 2000;
  }
  if (operation.type !== "handoff" || !Number.isSafeInteger(body.expected_version) || (body.expected_version as number) < 1) return false;
  const fields="expected_version,revision_id,payload_hash,idempotency_key,kind";
  if (body.kind === "offer") return keys(body,fields+",recipient_id") && uuid(body.recipient_id);
  if (["accept","decline","recall"].includes(String(body.kind))) return keys(body,fields+",offer_id") && uuid(body.offer_id);
  return body.kind === "reclaim" && keys(body,fields);
}
