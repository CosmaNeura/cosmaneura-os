/** Browser and native callers supply their existing signed-session transport. */
export type ConnectorTransport = (path: string, init: {
  method: 'GET' | 'POST'; contractHeader: string; body?: unknown; signal?: AbortSignal;
}) => Promise<unknown>;
export type ConnectorTool = {id: string; name: string; title: string; plugin: string;
  enabled: boolean; agentCallable: boolean; readOnly: boolean; description: string};
export class ConnectorToolsError extends Error {
  constructor(readonly code: 'invalid_connector_catalog' | 'invalid_connector_request' | 'connector_unavailable') {
    super(code);
  }
}
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const text = (v: unknown, maximum: number): v is string => typeof v === 'string' && v.length > 0 &&
  Array.from(v).length <= maximum && !/[\u0000-\u001f\u007f]|[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/.test(v);
const fail = (): never => {throw new ConnectorToolsError('invalid_connector_catalog');};

/** Catalog metadata can describe capabilities but never supplies executable URLs. */
export function parseConnectorCatalog(value: unknown): ConnectorTool[] {
  if (!record(value) || Object.keys(value).sort().join(',') !== '_meta,tools' ||
      !record(value._meta) || value._meta['ai.cosmas/contract'] !== 'cosmas.plugins.v1' ||
      !Array.isArray(value.tools) || value.tools.length > 256) return fail();
  const ids = new Set<string>();
  return value.tools.map(row => {
    if (!record(row) || !record(row._meta) || !record(row.annotations)) return fail();
    const meta = row._meta['ai.cosmas/operation'];
    if (!record(meta) || !text(meta.id, 100) || !/^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$/.test(meta.id) ||
        ids.has(meta.id) || !text(meta.plugin, 40) || !text(row.name, 100) ||
        row.name !== meta.id.replace('.', '_') || !text(row.title, 300) ||
        !text(row.description, 4000) || typeof meta.feature_enabled !== 'boolean' ||
        typeof meta.agent_callable !== 'boolean' || meta.external_send !== false ||
        meta.implementation !== 'first_party_http' || meta.account_status !== 'not_checked' ||
        meta.operation_health !== 'not_checked' || typeof row.annotations.readOnlyHint !== 'boolean') return fail();
    ids.add(meta.id);
    return {id: meta.id, name: row.name, title: row.title, plugin: meta.plugin,
      description: row.description, enabled: meta.feature_enabled,
      agentCallable: meta.agent_callable, readOnly: row.annotations.readOnlyHint};
  });
}

// Only local account/setup observations and retained work are dispatched here.
// Provider-content requests belong to their independently reviewed intent flow.
export const CONNECTOR_STATUS = {
  'google.connection_status': {path: '/connections/google/session', header: 'X-Cosmas-Google-Connection',
    label: 'Google account', body: {action: 'status', include_capabilities: true}},
  'google.message_status': {path: '/connections/google/messages', header: 'X-Cosmas-Google-Messages',
    label: 'Google message access', body: {action: 'status'}},
  'google.calendar_status': {path: '/connections/google/calendar-summaries', header: 'X-Cosmas-Google-Calendar',
    label: 'Google calendar access', body: {action: 'status'}},
  'microsoft.connection_status': {path: '/connections/microsoft/session', header: 'X-Cosmas-Microsoft-Connection',
    label: 'Microsoft account', body: {action: 'status'}},
  'fax_inbound.status': {path: '/fax-inbound', header: 'X-Cosmas-Fax-Inbound', label: 'Practice fax receiving'},
  'efax_inbound.status': {path: '/efax-inbound', header: 'X-Cosmas-EFax-Inbound', label: 'eFax receiving'},
  'portal.setup_status': {path: '/portal-setup', header: 'X-Cosmas-Portal-Contract', label: 'Portal accounts'},
  'stripe.setup_status': {path: '/finance-setup', header: 'X-Cosmas-Finance-Setup-Contract', label: 'Payment account'},
} as const;
export type ConnectorStatusId = keyof typeof CONNECTOR_STATUS;
export type ConnectorStatusObservation = {state: string | null; account: {label: string; email: string} | null; raw: unknown};
export const connectorStatusId = (v: unknown): v is ConnectorStatusId => typeof v === 'string' && Object.hasOwn(CONNECTOR_STATUS, v);
export const availableConnectorStatuses = (tools: ConnectorTool[]) => tools.filter(tool =>
  connectorStatusId(tool.id) && tool.enabled && tool.agentCallable && tool.readOnly);
export function connectorStatusObservation(value: unknown): ConnectorStatusObservation {
  if (!record(value)) throw new ConnectorToolsError('invalid_connector_request');
  const account = record(value.account) && text(value.account.label, 256) && text(value.account.email, 320)
    ? {label: value.account.label, email: value.account.email} : null;
  return {state: typeof value.state === 'string' ? value.state : null, account, raw: value};
}

export class ConnectorTools {
  constructor(private readonly transport: ConnectorTransport) {}
  async catalog(signal?: AbortSignal) {
    return parseConnectorCatalog(await this.transport('/connections/plugins', {
      method: 'GET', contractHeader: 'X-Cosmas-Connection-Contract', signal,
    }));
  }
  async status(id: ConnectorStatusId, signal?: AbortSignal): Promise<ConnectorStatusObservation> {
    if (!connectorStatusId(id)) throw new ConnectorToolsError('invalid_connector_request');
    // Recheck signed feature availability on every deliberate operation.
    const catalog = await this.catalog(signal);
    if (!availableConnectorStatuses(catalog).some(tool => tool.id === id)) throw new ConnectorToolsError('connector_unavailable');
    signal?.throwIfAborted();
    const operation = CONNECTOR_STATUS[id];
    return connectorStatusObservation(await this.transport(operation.path, {method: 'body' in operation ? 'POST' : 'GET',
      contractHeader: operation.header, ...('body' in operation ? {body: {...operation.body}} : {}), signal}));
  }
}

export type AgentResearchHandle = {ticket_id: string; revision_id: string; payload_hash: string};
export type AgentResearchReview = AgentResearchHandle & {contract: 'agent-research.review.v1'; workspace_id: string;
  state: 'pending_approval' | 'approved' | 'expired' | 'result_ready' | 'outcome_unconfirmed' | 'source_changed' | 'team_changed';
  query: string; topic: string; sources: string[]; expires_at: string; bot: string; team_revision: number;
  run_id: string | null; next_step: 'review_query' | 'ask_research_to_execute' | 'read_saved_result' | 'wait_for_result' | 'start_new_query'};
export type AgentResearchHistory = {contract: 'agent-research.history.v1'; workspace_id: string; proposals: AgentResearchReview[]};
const uuid = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/.test(v);
const hash = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
const keys = (v: unknown, names: string): v is Record<string, unknown> => record(v) &&
  Object.keys(v).sort().join(',') === names.split(',').sort().join(',');
export function validAgentResearchHandle(value: unknown): value is AgentResearchHandle {
  return keys(value, 'ticket_id,revision_id,payload_hash') && uuid(value.ticket_id) && uuid(value.revision_id) && hash(value.payload_hash);
}
export function parseAgentResearchReview(value: unknown, workspaceId: string): AgentResearchReview {
  if (!keys(value, 'contract,workspace_id,ticket_id,revision_id,payload_hash,state,query,topic,sources,expires_at,bot,team_revision,run_id,next_step') ||
      value.contract !== 'agent-research.review.v1' || value.workspace_id !== workspaceId || !uuid(workspaceId) ||
      !uuid(value.ticket_id) || !uuid(value.revision_id) || !hash(value.payload_hash) ||
      !['pending_approval', 'approved', 'expired', 'result_ready', 'outcome_unconfirmed', 'source_changed', 'team_changed'].includes(String(value.state)) ||
      !text(value.query, 500) || !['literature', 'drug_safety', 'trials', 'coverage', 'provider_data'].includes(String(value.topic)) ||
      !Array.isArray(value.sources) || value.sources.length < 1 || value.sources.length > 3 ||
      new Set(value.sources).size !== value.sources.length || value.sources.some(v => !['pubmed', 'clinical_trials', 'dailymed', 'rxnorm', 'openfda',
        'cms_coverage', 'cms_open_data', 'medicare_care_compare', 'npi_registry'].includes(String(v))) ||
      !text(value.expires_at, 40) || !/(?:Z|[+-]\d\d:\d\d)$/.test(value.expires_at) || !Number.isFinite(Date.parse(value.expires_at)) ||
      !uuid(value.bot) || !Number.isSafeInteger(value.team_revision) || (value.team_revision as number) < 1 ||
      value.run_id !== null && !uuid(value.run_id) || value.next_step !== (value.state === 'pending_approval' ? 'review_query' :
        value.state === 'approved' ? 'ask_research_to_execute' : value.state === 'result_ready' ? 'read_saved_result' :
          value.state === 'outcome_unconfirmed' ? 'wait_for_result' : 'start_new_query')) throw new ConnectorToolsError('invalid_connector_request');
  return value as AgentResearchReview;
}
export function parseAgentResearchHistory(value: unknown, workspaceId: string): AgentResearchHistory {
  if (!keys(value, 'contract,workspace_id,proposals') || value.contract !== 'agent-research.history.v1' ||
      value.workspace_id !== workspaceId || !Array.isArray(value.proposals) || value.proposals.length > 10) throw new ConnectorToolsError('invalid_connector_request');
  const proposals = value.proposals.map(row => parseAgentResearchReview(row, workspaceId));
  if (new Set(proposals.map(row => row.ticket_id)).size !== proposals.length) throw new ConnectorToolsError('invalid_connector_request');
  return {contract: 'agent-research.history.v1', workspace_id: workspaceId, proposals};
}
