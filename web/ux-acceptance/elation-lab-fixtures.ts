/** Invented, inert provider data for the existing EHR rehearsal ledger.
 * URLs are recorded strings only; this module performs no network requests. */
export type ElationLabFixture = {
  coverage: 'returned_page_only' | 'more_rows_available' | 'continuation_unknown';
  returned_report_count: number;
  other_report_count: number;
  reported_total: string | null;
  reports: {
    metadata_json: string;
    report_json: string;
    changed_since_selection: boolean;
  }[];
};

type Original = string | number | bigint | boolean | null | Original[] | {[key: string]: Original};
const quote = (value: string) => JSON.stringify(value).replace(/[\u007f-\uffff]/g,
  char => '\\u' + char.charCodeAt(0).toString(16).padStart(4, '0'));
// Match the Python provider's canonical JSON, including exact int64 tokens and
// escaped Unicode. Never pass original identifiers through a JavaScript Number.
const canonical = (value: Original): string => {
  if (typeof value === 'string') return quote(value);
  if (typeof value === 'bigint') return value.toString();
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value !== null && typeof value === 'object') {
    return '{' + Object.keys(value).sort().map(key => quote(key) + ':' + canonical(value[key])).join(',') + '}';
  }
  return JSON.stringify(value);
};

const metadataKeys = ['chart_date', 'document_date', 'report_type', 'created_date',
  'custom_title', 'deleted_date', 'is_urgent', 'order_status', 'reported_date',
  'requisition_number', 'signed_date'] as const;

/** Scenario suffixes leave the surrounding UI/router naming independent. The
 * ledger owns opaque handles, parent proof, hashes, lost responses and recovery. */
export function elationLabFixture(scenario: string | null = null): ElationLabFixture {
  const is = (suffix: string) => scenario === suffix || scenario?.endsWith('-' + suffix) === true;
  const changed = is('changed');
  const result: {[key: string]: Original} = {
    test: {code: 'INVENTED', loinc: null, name: 'Invented analyte'},
    test_category: {description: 'Invented panel', value: 'SYNTH'},
    value: changed ? '<0.1000' : '001.2300',
    units: 'µg/L', value_type: 'Numeric',
    reference_min: '< 0.10', reference_max: '≤ 3.00',
    abnormal_flag: 'Alert high', is_abnormal: false, status: 'CORRECTED',
    note: 'Première ligne\r\n\tOriginal second line', text: null,
  };
  const report: {[key: string]: Original} = {
    id: 9223372036854775807n, patient: 930, practice: 910, physician: 920,
    report_type: 'Lab', chart_date: '2026-10-25T12:00:00Z',
    document_date: '2026-10-24T09:00:00-04:00', reported_date: null,
    custom_title: 'Invented corrected panel', created_date: '2026-10-25T12:00:00.120000Z',
    signed_date: null, deleted_date: null, is_urgent: false, order_status: 'COMPLETED',
    requisition_number: '',
    grids: [{
      accession_number: 'Invented A', collected_date: '2026-10-24T08:00:00',
      resulted_date: '2026-10-25T11:00:00Z', status: 'AMENDED',
      note: 'Original grid note\r\n\tSecond recorded line', results: is('empty-results') ? [] : [result],
    }],
    files: [{id: 7, document: 'https://invented.invalid/original.pdf', content_type: 'application/pdf'}],
    images: [], printable_view: 'https://invented.invalid/printable', tags: [8], vendor: null,
  };
  if (is('absent-grid')) delete report.grids;
  if (is('empty-grid')) report.grids = [];
  const selectedMetadata: {[key: string]: Original} = {};
  for (const key of metadataKeys) if (Object.hasOwn(report, key)) selectedMetadata[key] = report[key];
  if (changed) selectedMetadata.custom_title = 'Invented panel before update';

  if (is('empty-page')) return {
    coverage: 'returned_page_only', returned_report_count: 0, other_report_count: 0,
    reported_total: '0', reports: [],
  };
  const unknown = is('unknown') || is('unknown-continuation');
  const partial = is('partial');
  return {
    coverage: unknown ? 'continuation_unknown' : partial ? 'more_rows_available' : 'returned_page_only',
    returned_report_count: 2, other_report_count: 1,
    reported_total: unknown ? null : partial ? '3' : '2',
    reports: [{
      metadata_json: canonical(selectedMetadata), report_json: canonical(report),
      changed_since_selection: changed,
    }],
  };
}
