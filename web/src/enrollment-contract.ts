export const ENROLLMENT_CONTRACT = 'enrollment.v1' as const;
/** Existing public company contact, verified against the marketing source. */
export const ENROLLMENT_CONTACT = 'mailto:john@cosmaneura.com?subject=CosmaBot%20practice%20setup';
export const BAA = {
  doc_id: 'CN-BAA-CUST-CW', version: '2.3',
  sha256: '9bdc110b6b2ffcc9f5e7aee653af499357d2f35dccf43c57d8bbcf70094ed34e',
  pdf_url: 'https://cosmaneura.com/baa-v2-3.pdf',
} as const;

export type EnrollmentConfig = {
  contract_version: typeof ENROLLMENT_CONTRACT; enabled: boolean;
  data_mode: 'disabled' | 'synthetic' | 'production'; auth_configured: boolean;
  clerk_publishable_key: string | null; auth_methods: ('google' | 'microsoft' | 'password')[];
  billing_configured: boolean; activation_available: boolean; production_qualified: boolean;
  blockers: string[]; allowed_workspace_origins: string[]; baa: typeof BAA;
  pricing: { currency: 'usd'; interval: 'month'; first_human_cents: 30000;
    additional_human_cents: 10000; max_self_serve_humans: 10; trial_days: 14; seat_policy: string };
};
export type EnrollmentProfile = { display_name: string; title: string; email: string };
export type EnrollmentPractice = {
  id: string; legal_name: string; display_name: string; address_line1: string; address_line2: string;
  city: string; region: string; postal_code: string; country: 'US'; administrative_email: string;
  human_seats: number; role: 'owner' | 'admin' | 'staff'; covered_entity:boolean; can_sign:boolean;
};
export type EnrollmentQuote = { currency: 'usd'; interval: 'month'; human_seats: number;
  monthly_total_cents: number | null; due_today_cents: 0; trial_days: 14; self_serve: boolean };
export type EnrollmentStage = 'account' | 'practice' | 'agreement' | 'activation_pending' | 'payment' |
  'finishing_setup' | 'ready' | 'negotiated' | 'payment_action_required' | 'canceled';
export type EnrollmentStatus = {
  contract_version: typeof ENROLLMENT_CONTRACT; revision: number; stage: EnrollmentStage;
  profile: EnrollmentProfile | null; practice: EnrollmentPractice | null;
  agreement: { accepted: boolean; doc_id: string; version: string; sha256: string; receipt_id: string | null } | null;
  quote: EnrollmentQuote | null;
  billing: { status: string; trial_ends_at: string | null; first_charge_at: string | null;
    cancel_at_period_end: boolean; payment_action_required: boolean };
  workspace: { status: 'pending' | 'provisioning' | 'ready' | 'failed'; url: string | null; organization_id: string | null; box_id: string | null };
  action_required: string | null;
};
export type EnrollmentDocument = { doc_id: string; version: string; sha256: string; html: string; pdf_url: string };
export type EnrollmentReceipt = { receipt: { id: string; practice_id: string; covered_entity_legal_name: string;
  accepted_by_subject: string; accepted_by_name: string; accepted_by_title: string; accepted_by_email: string;
  accepted_at: string; doc_id: string; version: string; sha256: string; authority_statement: string };
  document: EnrollmentDocument };
export type EnrollmentInvitation = { id: string; token: string; expires_at: string;
  role: 'admin' | 'staff'; can_sign: boolean; enrollment: EnrollmentStatus };
export type EnrollmentCheckout = { url: string | null; status: 'open' | 'complete' | 'pending' | 'expired'; enrollment: EnrollmentStatus };
export type EnrollmentPractices = {active_practice_id:string|null;practices:{id:string;legal_name:string;display_name:string;role:'owner'|'admin'|'staff';workspace_status:'pending'|'provisioning'|'ready'|'failed'}[]};
export type ProfileInput = { expected_revision: number; display_name: string; title: string };
export type PracticeInput = Omit<EnrollmentPractice, 'id' | 'role' | 'can_sign'> & { expected_revision: number; covered_entity: true };
export type AgreementInput = { expected_revision: number; doc_id: string; version: string; sha256: string;
  signature_name: string; signature_title: string; authority_confirmed: true; accepted: true };

export class EnrollmentError extends Error {
  constructor(public status: number, public code = 'enrollment_unavailable') { super('Enrollment could not be confirmed'); }
}
const invalid = (): never => { throw new EnrollmentError(502, 'invalid_enrollment_response'); };
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return invalid();
  return value as Record<string, unknown>;
}
function text(value: unknown, max = 255, empty = false): string {
  if (typeof value !== 'string' || value.length > max || !empty && !value.trim() || /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(value)) return invalid();
  return value;
}
function bool(value: unknown): boolean { return typeof value === 'boolean' ? value : invalid(); }
function integer(value: unknown, min = 0, max = Number.MAX_SAFE_INTEGER): number {
  return Number.isSafeInteger(value) && (value as number) >= min && (value as number) <= max ? value as number : invalid();
}
function nullableText(value: unknown, max = 255): string | null { return value === null ? null : text(value, max); }
function timestamp(value: unknown): string | null {
  const result = nullableText(value, 50);
  if (result !== null && !Number.isFinite(Date.parse(result))) return invalid();
  return result;
}
function documentIdentity(value: Record<string, unknown>) {
  if (value.doc_id !== BAA.doc_id || value.version !== BAA.version || value.sha256 !== BAA.sha256) return invalid();
}
export function validateEnrollmentConfig(value: unknown): EnrollmentConfig {
  const v = object(value), pricing = object(v.pricing), baa = object(v.baa);
  documentIdentity(baa);
  if (v.contract_version !== ENROLLMENT_CONTRACT || !['disabled','synthetic','production'].includes(String(v.data_mode)) ||
      baa.pdf_url !== BAA.pdf_url || pricing.currency !== 'usd' || pricing.interval !== 'month' ||
      pricing.first_human_cents !== 30000 || pricing.additional_human_cents !== 10000 ||
      pricing.max_self_serve_humans !== 10 || pricing.trial_days !== 14 ||
      !Array.isArray(v.auth_methods) || v.auth_methods.length !== 3 ||
      !['google','microsoft','password'].every(method => (v.auth_methods as unknown[]).includes(method)) ||
      !Array.isArray(v.blockers) || v.blockers.length > 30 || !Array.isArray(v.allowed_workspace_origins) || v.allowed_workspace_origins.length>20) return invalid();
  const config = { ...v, enabled: bool(v.enabled), auth_configured: bool(v.auth_configured),
    billing_configured: bool(v.billing_configured), activation_available: bool(v.activation_available),
    production_qualified: bool(v.production_qualified), clerk_publishable_key: nullableText(v.clerk_publishable_key, 1024),
    blockers: v.blockers.map(item => text(item)), allowed_workspace_origins:v.allowed_workspace_origins.map(item=>{
      const origin=text(item,2048);try{const url=new URL(origin);if(url.origin!==origin||url.protocol!=='https:')return invalid();}catch{return invalid();}return origin;
    }),pricing: { ...pricing, seat_policy: text(pricing.seat_policy, 1000) },
  } as EnrollmentConfig;
  if (config.auth_configured && !/^pk_(test|live)_[A-Za-z0-9_-]+$/.test(config.clerk_publishable_key ?? '') ||
      config.enabled && config.data_mode === 'disabled' ||
      config.enabled && config.data_mode === 'production' && (!config.production_qualified || !config.clerk_publishable_key?.startsWith('pk_live_'))) return invalid();
  return config;
}
export function validateEnrollmentQuote(value: unknown): EnrollmentQuote {
  const v = object(value), count = integer(v.human_seats, 1, 1000), self = bool(v.self_serve);
  if (v.currency !== 'usd' || v.interval !== 'month' || v.due_today_cents !== 0 || v.trial_days !== 14 ||
      self !== (count <= 10) || self && v.monthly_total_cents !== 30000 + (count - 1) * 10000 ||
      !self && v.monthly_total_cents !== null) return invalid();
  return { currency: 'usd', interval: 'month', human_seats: count,
    monthly_total_cents: self ? v.monthly_total_cents as number : null, due_today_cents: 0, trial_days: 14, self_serve: self };
}
export function validateEnrollmentDocument(value: unknown): EnrollmentDocument {
  const v = object(value); documentIdentity(v);
  if (v.pdf_url !== BAA.pdf_url) return invalid();
  return { ...BAA, html: text(v.html, 512000) };
}
export function validateEnrollmentStatus(value: unknown): EnrollmentStatus {
  const v = object(value), billing = object(v.billing), workspace = object(v.workspace);
  if (v.contract_version !== ENROLLMENT_CONTRACT || !['account','practice','agreement','activation_pending','payment',
      'finishing_setup','ready','negotiated','payment_action_required','canceled'].includes(String(v.stage)) ||
      !['pending','provisioning','ready','failed'].includes(String(workspace.status))) return invalid();
  const profile = v.profile === null ? null : object(v.profile);
  const practice = v.practice === null ? null : object(v.practice);
  const agreement = v.agreement === null ? null : object(v.agreement);
  if (agreement) documentIdentity(agreement);
  const status: EnrollmentStatus = {
    contract_version: ENROLLMENT_CONTRACT, revision: integer(v.revision), stage: v.stage as EnrollmentStage,
    profile: profile ? { display_name: text(profile.display_name, 160, v.stage==='account'), title: text(profile.title, 120, true), email: text(profile.email, 320) } : null,
    practice: practice ? { id: text(practice.id), legal_name: text(practice.legal_name, 160),
      display_name: text(practice.display_name, 160), address_line1: text(practice.address_line1, 200),
      address_line2: text(practice.address_line2, 200, true), city: text(practice.city, 100), region: text(practice.region, 80),
      postal_code: text(practice.postal_code, 20), country: 'US', administrative_email: text(practice.administrative_email,320),
      human_seats: integer(practice.human_seats, 1, 1000), role: practice.role as EnrollmentPractice['role'],covered_entity:bool(practice.covered_entity),can_sign:bool(practice.can_sign) } : null,
    agreement: agreement ? { accepted: bool(agreement.accepted), doc_id: BAA.doc_id, version: BAA.version,
      sha256: BAA.sha256, receipt_id: nullableText(agreement.receipt_id) } : null,
    quote: v.quote === null ? null : validateEnrollmentQuote(v.quote),
    billing: { status: text(billing.status, 50), trial_ends_at: timestamp(billing.trial_ends_at),
      first_charge_at: timestamp(billing.first_charge_at), cancel_at_period_end: bool(billing.cancel_at_period_end),
      payment_action_required: bool(billing.payment_action_required) },
    workspace: { status: workspace.status as EnrollmentStatus['workspace']['status'], url: nullableText(workspace.url, 2048),
      organization_id:nullableText(workspace.organization_id),box_id:nullableText(workspace.box_id) },
    action_required: nullableText(v.action_required, 1000),
  };
  if (practice && (practice.country !== 'US' || !['owner','admin','staff'].includes(String(practice.role))) ||
      status.quote && status.practice && status.quote.human_seats !== status.practice.human_seats ||
      status.agreement?.accepted && !status.agreement.receipt_id ||
      status.stage === 'ready' && (!status.profile || !status.practice || !status.agreement?.accepted ||
        status.workspace.status !== 'ready' || !status.workspace.url || !['trialing','active'].includes(status.billing.status) ||
        status.billing.payment_action_required || !/^org_[A-Za-z0-9_]{1,251}$/.test(status.workspace.organization_id??'') || !status.workspace.box_id)) return invalid();
  return status;
}
export function validateEnrollmentCheckout(value: unknown): EnrollmentCheckout {
  const v = object(value);
  if (!['open','complete','pending','expired'].includes(String(v.status))) return invalid();
  return { url: nullableText(v.url, 2048), status: v.status as EnrollmentCheckout['status'], enrollment: validateEnrollmentStatus(v.enrollment) };
}
export function validateEnrollmentInvitation(value: unknown): EnrollmentInvitation {
  const v = object(value);
  if (!['admin','staff'].includes(String(v.role))) return invalid();
  return { id: text(v.id), token: text(v.token, 1024), expires_at: timestamp(v.expires_at) ?? invalid(),
    role: v.role as EnrollmentInvitation['role'], can_sign: bool(v.can_sign), enrollment: validateEnrollmentStatus(v.enrollment) };
}
export function validateEnrollmentReceipt(value: unknown): EnrollmentReceipt {
  const v = object(value), r = object(v.receipt); documentIdentity(r);
  return { document: validateEnrollmentDocument(v.document), receipt: {
    id: text(r.id), practice_id: text(r.practice_id), covered_entity_legal_name: text(r.covered_entity_legal_name, 200),
    accepted_by_subject: text(r.accepted_by_subject), accepted_by_name: text(r.accepted_by_name, 160),
    accepted_by_title: text(r.accepted_by_title, 120), accepted_by_email: text(r.accepted_by_email,320),
    accepted_at: timestamp(r.accepted_at) ?? invalid(), doc_id: BAA.doc_id, version: BAA.version, sha256: BAA.sha256,
    authority_statement: text(r.authority_statement, 1000),
  } };
}
export function validateEnrollmentPractices(value:unknown):EnrollmentPractices {
  const v=object(value);if(!Array.isArray(v.practices)||v.practices.length>1000)return invalid();
  const practices=v.practices.map(item=>{const p=object(item);
    if(!['owner','admin','staff'].includes(String(p.role))||!['pending','provisioning','ready','failed'].includes(String(p.workspace_status)))return invalid();
    return {id:text(p.id),legal_name:text(p.legal_name,160),display_name:text(p.display_name,160),role:p.role as EnrollmentPractices['practices'][number]['role'],workspace_status:p.workspace_status as EnrollmentPractices['practices'][number]['workspace_status']};});
  const active=nullableText(v.active_practice_id);if(active&&!practices.some(item=>item.id===active))return invalid();
  return {active_practice_id:active,practices};
}
