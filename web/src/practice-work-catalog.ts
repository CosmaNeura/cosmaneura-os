import { validateVendor, vendorObject, vendorUuid, VendorContractError } from "./vendor-contract";
import type { PracticeWorkEntry, PracticeWorkItem, PracticeWorkPage, WorkspaceIdentity } from "./workspace-api";

const fail = (): never => { throw new VendorContractError(); };

/** Mixed work uses the existing catalog; vendor work retains its closed projection. */
export async function validatePracticeWorkPage(value: unknown, identity: WorkspaceIdentity): Promise<PracticeWorkPage> {
  if (!vendorObject(value) || Object.keys(value).sort().join(",") !== "items,next_cursor,people" ||
      !Array.isArray(value.items) || value.items.length > 50 || !Array.isArray(value.people) ||
      value.next_cursor !== null && !vendorUuid(value.next_cursor)) return fail();
  const people = value.people.map(person => validateVendor("Person", person));
  if (new Set(people.map(person => person.id)).size !== people.length) return fail();
  const ids = new Set<string>();
  let viewer = "mode" in identity ? undefined : identity.actorId;
  const items: PracticeWorkEntry[] = value.items.map(item => {
    if (!vendorObject(item)) return fail();
    let checked: PracticeWorkEntry;
    if (item.work_kind === "vendor_delivery") {
      checked = "handoffs" in item ? validateVendor("SharedVendorDetail", item) : validateVendor("SharedVendorWork", item);
    } else {
      if (item.work_kind !== undefined && !["follow_up", "visit_preparation"].includes(String(item.work_kind)) ||
          !vendorUuid(item.ticket_id) || !vendorUuid(item.revision_id) || !vendorUuid(item.viewer_id) ||
          typeof item.payload_hash !== "string" || !/^[a-f0-9]{64}$/.test(item.payload_hash) ||
          !Number.isSafeInteger(item.version) || Number(item.version) < 1 ||
          !Array.isArray(item.handoffs) || !Array.isArray(item.receipts) ||
          ["body", "due_date", "expected_outcome", "state"].some(key => typeof item[key] !== "string")) return fail();
      validateVendor("Person", item.originator); validateVendor("Person", item.responsible);
      checked = item as PracticeWorkItem;
    }
    if (ids.has(checked.ticket_id) || viewer !== undefined && checked.viewer_id !== viewer) return fail();
    ids.add(checked.ticket_id); viewer = checked.viewer_id;
    return checked;
  });
  return {items, people, next_cursor:value.next_cursor as string | null};
}
