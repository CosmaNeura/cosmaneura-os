import {afterEach, expect, it, vi} from 'vitest';
import {parseWorkBrief} from './routine-api';
import {parseIncomingBrief} from './routine-inbox-contract';
import pending from './__fixtures__/routine-inbox/actual-chief-pending.json';
import offered from './__fixtures__/routine-inbox/actual-chief-offered.json';
import accepted from './__fixtures__/routine-inbox/actual-chief-accepted.json';
import result from './__fixtures__/routine-inbox/actual-chief-result.json';
import verified from './__fixtures__/routine-inbox/actual-chief-verified.json';
import changed from './__fixtures__/routine-inbox/actual-chief-changed.json';
import unavailable from './__fixtures__/routine-inbox/actual-chief-unavailable.json';
import fair from './__fixtures__/routine-inbox/actual-chief-fair.json';
import generic from './__fixtures__/routine-lanes/actual-routine-lanes.json';
import legacy from './__fixtures__/routine-lanes/actual-legacy-routine.json';

// Positive vectors are byte-identical copies of actual signed PostgreSQL API
// evidence. Mutations below are deliberately invalid inputs, never substitute
// successful response fixtures.
const stages = {pending, offered, accepted, result, verified};
const copy = (value: unknown): any => structuredClone(value);
const reject = (value: any, id = value.id) => {
  expect(() => parseWorkBrief(value, id)).toThrow();
};
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.clearAllMocks(); });

for (const [stage, vectors] of Object.entries(stages)) {
  for (const role of ['owner', 'staff'] as const) {
    it(`accepts the exact signed ${stage} ${role} report and preserves its projection`, () => {
      const raw = vectors[role], before = JSON.stringify(raw);
      const parsed = parseWorkBrief(raw, raw.id);
      expect(parsed).toEqual({id: raw.id, scheduled_at: raw.scheduled_at, completed_at: raw.completed_at,
        local_date: raw.local_date, kind: raw.kind, ...raw.generic, model_used: false,
        contract_version: 2, snapshot_version: 2, incoming: raw.incoming});
      expect(JSON.stringify(raw)).toBe(before);
    });
  }
}

for (const [name, vectors] of Object.entries({changed, unavailable, fair})) {
  it(`accepts the exact signed ${name} owner report without replacing its observations`, () => {
    const raw = vectors.owner, before = JSON.stringify(raw), parsed = parseWorkBrief(raw, raw.id);
    expect(parsed.incoming).toEqual(raw.incoming);
    expect(parsed.items).toEqual(raw.generic.items);
    expect(parsed.counts).toEqual(raw.generic.counts);
    expect(parsed.matching_items).toBe(raw.generic.matching_items);
    expect(JSON.stringify(raw)).toBe(before);
  });
}

it('keeps actual changed work and unavailable source signals distinct without historical context', () => {
  const work = parseWorkBrief(changed.owner, changed.owner.id).incoming!;
  const source = parseWorkBrief(unavailable.owner, unavailable.owner.id).incoming!;
  expect(work).toMatchObject({coverage: 'partial', reason: 'work_changed', counts: {work_changed: 1, source_unavailable: 0}});
  expect(source).toMatchObject({coverage: 'partial', reason: 'source_unavailable', counts: {work_changed: 0, source_unavailable: 1}});
  expect(work.items[0].requires_owner_attention).toBe(false);
  expect(source.items[0].requires_owner_attention).toBe(true);
  for (const section of [work, source]) expect(section.items[0]).toMatchObject({body: null, due_date: null,
    pending_offer: false, ready_for_review: false, verified_current: false, publication_receipt_id: null,
    result_receipt_id: null, verification_receipt_id: null, changed_since_report: true});
});

it('preserves the actual five-per-section allocation and full bounded counts', () => {
  const raw = fair.owner, parsed = parseWorkBrief(raw, raw.id);
  expect(parsed.items).toHaveLength(5); expect(parsed.incoming!.items).toHaveLength(5);
  expect(parsed.matching_items).toBe(7); expect(parsed.incoming!.matching_items).toBe(7);
  expect(parsed.counts.open).toBe(7); expect(parsed.incoming!.counts!.pending_approval).toBe(7);
});

it.each(['changed_body', 'changed_verified', 'unavailable_body', 'unavailable_verified', 'false_hidden_count'])
('rejects corrupted actual changed, unavailable or fair evidence: %s', fault => {
  const raw = copy(fault.startsWith('changed') ? changed.owner : fault.startsWith('unavailable') ? unavailable.owner : fair.owner);
  if (fault.endsWith('_body')) raw.incoming.items[0].body = accepted.owner.incoming.items[0].body;
  if (fault.endsWith('_verified')) raw.incoming.items[0].verified_current = true;
  if (fault === 'false_hidden_count') raw.incoming.counts.pending_approval = 4;
  reject(raw);
});

it('keeps unavailable staff coverage distinct from zero and preserves exact human verification', () => {
  expect(parseWorkBrief(pending.staff, pending.staff.id).incoming).toEqual({coverage: 'unavailable',
    reason: 'source_unavailable', items: [], matching_items: 0, counts: null, withheld_sources: true});
  for (const raw of [pending.owner, offered.owner, accepted.owner, result.owner]) {
    const incoming = parseWorkBrief(raw, raw.id).incoming!;
    expect(incoming.counts!.verified_complete).toBe(0);
    expect(incoming.items[0].verified_current).toBe(false);
  }
  const incoming = parseWorkBrief(verified.owner, verified.owner.id).incoming!;
  expect(incoming.counts!.verified_complete).toBe(1);
  expect(incoming.items[0]).toMatchObject({state: 'closed', verified_current: true,
    publication_receipt_id: verified.owner.incoming.items[0].publication_receipt_id,
    result_receipt_id: verified.owner.incoming.items[0].result_receipt_id,
    verification_receipt_id: verified.owner.incoming.items[0].verification_receipt_id});
});

it('continues to accept the exact legacy signed report without adding incoming observations', () => {
  expect(parseWorkBrief(legacy.report, legacy.report.id)).toEqual(legacy.report);
  expect(parseWorkBrief(legacy.report, legacy.report.id).incoming).toBeUndefined();
});

it.each(['root', 'generic', 'incoming', 'counts', 'item', 'responsible'])('rejects extra private fields at %s', level => {
  const raw = copy(verified.owner);
  const target = ({root: raw, generic: raw.generic, incoming: raw.incoming, counts: raw.incoming.counts,
    item: raw.incoming.items[0], responsible: raw.incoming.items[0].responsible} as Record<string, any>)[level];
  target.private_source_body = 'PRIVATE source content';
  reject(raw);
});

it.each(['root_body', 'section_body', 'items', 'counts', 'matching', 'withheld', 'legacy_reason'])
('rejects unavailable source disclosure or contradictory metadata: %s', fault => {
  const raw = copy(pending.staff), section = raw.incoming;
  if (fault === 'root_body') raw.body = 'PRIVATE';
  if (fault === 'section_body') section.body = 'PRIVATE';
  if (fault === 'items') { section.items = copy(pending.owner.incoming.items); section.matching_items = 1; }
  if (fault === 'counts') section.counts = copy(pending.owner.incoming.counts);
  if (fault === 'matching') section.matching_items = 1;
  if (fault === 'withheld') section.withheld_sources = false;
  if (fault === 'legacy_reason') section.reason = 'legacy_report';
  reject(raw);
});

it.each(['body', 'due_date', 'pending_offer', 'ready_for_review', 'verified_current',
  'publication_receipt_id', 'result_receipt_id', 'verification_receipt_id', 'owner_attention', 'complete_coverage'])
('rejects unavailable row context or false readiness: %s', fault => {
  const raw = copy(verified.owner), section = raw.incoming, row = section.items[0];
  const old = copy(row);
  Object.assign(row, {state: 'source_unavailable', body: null, due_date: null, requires_owner_attention: true,
    pending_offer: false, ready_for_review: false, verified_current: false, publication_receipt_id: null,
    result_receipt_id: null, verification_receipt_id: null, changed_since_report: true});
  Object.assign(section, {coverage: 'partial', reason: 'source_unavailable', withheld_sources: true});
  for (const key of Object.keys(section.counts)) section.counts[key] = key === 'source_unavailable' ? 1 : 0;
  if (['body', 'due_date', 'publication_receipt_id', 'result_receipt_id', 'verification_receipt_id'].includes(fault)) row[fault] = old[fault];
  if (['pending_offer', 'ready_for_review', 'verified_current'].includes(fault)) row[fault] = true;
  if (fault === 'owner_attention') row.requires_owner_attention = false;
  if (fault === 'complete_coverage') Object.assign(section, {coverage: 'complete', reason: null, withheld_sources: false});
  reject(raw);
});

it.each(['approved_verified', 'pending_verified', 'missing_publication', 'missing_result', 'missing_verification',
  'terminal_offer', 'terminal_ready', 'offered_and_ready', 'ready_without_result', 'false_complete_count'])
('rejects a false human completion or readiness claim: %s', fault => {
  const raw = copy(fault === 'offered_and_ready' ? offered.owner : fault === 'ready_without_result' ? result.owner : verified.owner);
  const row = raw.incoming.items[0];
  if (fault === 'approved_verified') row.state = 'approved';
  if (fault === 'pending_verified') row.state = 'pending_approval';
  if (fault === 'missing_publication') row.publication_receipt_id = null;
  if (fault === 'missing_result') row.result_receipt_id = null;
  if (fault === 'missing_verification') row.verification_receipt_id = null;
  if (fault === 'terminal_offer') row.pending_offer = true;
  if (fault === 'terminal_ready') row.ready_for_review = true;
  if (fault === 'offered_and_ready') { row.ready_for_review = true; row.result_receipt_id = result.owner.incoming.items[0].result_receipt_id; }
  if (fault === 'ready_without_result') row.result_receipt_id = null;
  if (fault === 'false_complete_count') { row.verified_current = false; raw.incoming.counts.verified_complete = 1; }
  reject(raw);
});

it.each([0, 1, 3, '2', true, null])('rejects non-negotiated contract version %s', version => {
  const raw = copy(accepted.owner); raw.contract_version = version; reject(raw);
});

it.each([0, 3, '2', true, null])('rejects invalid immutable snapshot version %s', version => {
  const raw = copy(accepted.owner); raw.snapshot_version = version; reject(raw);
});

it.each(['absent_contract', 'header_as_body', 'model_used', 'legacy_with_incoming', 'v2_not_included', 'legacy_withheld'])
('rejects envelope or generation semantic confusion: %s', fault => {
  const raw = copy(accepted.owner);
  if (fault === 'absent_contract') delete raw.contract_version;
  if (fault === 'header_as_body') raw['X-Cosmas-Routine-Contract'] = '2';
  if (fault === 'model_used') raw.model_used = true;
  if (fault === 'legacy_with_incoming') raw.snapshot_version = 1;
  if (fault === 'v2_not_included' || fault === 'legacy_withheld') {
    raw.incoming = {coverage: 'not_included', reason: 'legacy_report', items: [], matching_items: 0,
      counts: null, withheld_sources: fault === 'legacy_withheld'};
    if (fault === 'legacy_withheld') raw.snapshot_version = 1;
  }
  reject(raw);
});

it.each([-1, 1.5, true, '1', 101])('rejects invalid incoming matching count %s', value => {
  const raw = copy(pending.owner); raw.incoming.matching_items = value; reject(raw);
});

it.each(['pending_approval', 'open', 'overdue', 'awaiting_acceptance', 'responsible_unavailable',
  'awaiting_review', 'verified_complete', 'source_unavailable', 'work_changed'])('rejects an impossible visible %s count', key => {
  const raw = copy(accepted.owner); raw.incoming.counts[key] = key === 'open' ? 0 : 1; reject(raw);
});

it('rejects duplicate incoming ticket identities even with matching aggregate counts', () => {
  const raw = copy(accepted.owner);
  raw.incoming.items.push(copy(raw.incoming.items[0])); raw.incoming.matching_items = 2; raw.incoming.counts.open = 2;
  reject(raw);
});

it('rejects a ticket appearing in both incoming and generic sections', () => {
  const raw = copy(accepted.owner), row = copy(generic.report.items.find(item => item.state === 'approved'));
  row.ticket_id = raw.incoming.items[0].ticket_id;
  raw.generic = {items: [row], matching_items: 1, counts: {open: 1, overdue: row.due_date < raw.local_date ? 1 : 0,
    awaiting_acceptance: Number(row.pending_offer), responsible_unavailable: Number(!row.responsible.available),
    verified_complete: 0}, withheld_sources: false, truncated: false};
  reject(raw);
});

it('requires every available incoming slot when the generic section is empty', () => {
  const raw = copy(accepted.owner);
  raw.incoming.matching_items = 10; raw.incoming.counts.open = 10;
  reject(raw);
});

it('rejects a ten-item report that lets generic work take the fifth incoming slot', () => {
  // This malicious envelope combines signed rows to isolate section fairness:
  // four incoming observations are structurally valid with one hidden row,
  // but six generic rows displace its reserved fifth slot.
  const raw = copy(accepted.owner);
  raw.generic = {items: copy(generic.report.items.slice(0, 6)), matching_items: generic.report.matching_items,
    counts: copy(generic.report.counts), withheld_sources: generic.report.withheld_sources,
    truncated: generic.report.truncated};
  raw.incoming.items = [pending, offered, accepted, result].map(value => copy(value.owner.incoming.items[0]));
  raw.incoming.matching_items = 5;
  raw.incoming.counts = {pending_approval: 1, open: 3, overdue: 0, awaiting_acceptance: 1,
    responsible_unavailable: 0, awaiting_review: 1, verified_complete: 1, source_unavailable: 0, work_changed: 0};
  expect(() => parseIncomingBrief(raw.incoming, raw.local_date, 2)).not.toThrow();
  expect(raw.generic.items.length + raw.incoming.items.length).toBe(10);
  reject(raw);
});

it('rejects malformed row identifiers, scalar bounds and nonboolean authority facts', () => {
  for (const [key, value] of [['ticket_id', 'not-a-uuid'], ['revision_id', 'private'], ['originator_id', 'private'],
    ['payload_hash', 'a'.repeat(63)], ['version', 0], ['version', Number.MAX_SAFE_INTEGER], ['body', 'x'.repeat(181)],
    ['due_date', '2026-02-30'], ['requires_owner_attention', 'true'], ['changed_since_report', 1],
    ['verified_current', 'false'], ['publication_receipt_id', 'private']]) {
    const raw = copy(accepted.owner); raw.incoming.items[0][key as string] = value; reject(raw);
  }
});

it('binds the parsed report to the requested immutable run id', () => {
  reject(accepted.owner, verified.owner.id);
});

it('places the generation-2 negotiation in the actual Headers object for saved-run reads', async () => {
  for (const flag of ['VITE_WORKSPACE_ENABLED', 'VITE_WORKSPACE_AUTHENTICATED_ENABLED', 'VITE_WORKSPACE_ROUTINES_ENABLED']) vi.stubEnv(flag, 'true');
  vi.stubEnv('VITE_COSMAS_ENV', 'synth_os'); vi.stubEnv('VITE_API_BASE', 'http://127.0.0.1:8000'); vi.resetModules();
  const fetch = vi.fn(async () => Response.json(accepted.owner, {headers: {'Cache-Control': 'no-store'}}));
  vi.stubGlobal('fetch', fetch);
  const {routineApi} = await import('./routine-api');
  const parsed = await routineApi.run({mode: 'clerk_jwt', getToken: async () => 'invented.routine.token'}, 'chief', accepted.owner.id);
  expect(parsed.incoming).toEqual(accepted.owner.incoming);
  expect(fetch).toHaveBeenCalledOnce();
  const [url, options] = fetch.mock.calls[0] as unknown as [string, RequestInit];
  expect(url).toBe('http://127.0.0.1:8000/provider-team/routines/chief/runs/' + accepted.owner.id);
  expect(options).toMatchObject({method: 'GET', credentials: 'omit', cache: 'no-store', redirect: 'error', referrerPolicy: 'no-referrer'});
  expect(new Headers(options.headers).get('X-Cosmas-Routine-Contract')).toBe('2');
});
