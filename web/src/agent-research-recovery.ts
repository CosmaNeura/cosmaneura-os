import {validAgentResearchHandle, type AgentResearchHandle} from '../../clients/capture/src/team/connector-tools';

export type AgentResearchApproval = AgentResearchHandle & {public_query_confirmed: true};
export type AgentResearchRecovery = {contract: 'agent-research-review-recovery.v1'; workspace_id: string;
  pending: AgentResearchApproval | null};
export type AgentResearchRecoveryAccess = {authorize(): Promise<void>;
  load(): Promise<AgentResearchRecovery | null>; persist(value: AgentResearchRecovery | null): Promise<void>};
export function validAgentResearchApproval(value: unknown): value is AgentResearchApproval {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const row = value as Record<string, unknown>;
  return Object.keys(row).sort().join(',') === 'payload_hash,public_query_confirmed,revision_id,ticket_id' &&
    row.public_query_confirmed === true && validAgentResearchHandle({ticket_id: row.ticket_id,
      revision_id: row.revision_id, payload_hash: row.payload_hash});
}
export function validateAgentResearchRecovery(value: unknown, workspaceId: string): AgentResearchRecovery {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid private query review');
  const row = value as Record<string, unknown>;
  if (Object.keys(row).sort().join(',') !== 'contract,pending,workspace_id' ||
      !/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/.test(workspaceId) ||
      row.contract !== 'agent-research-review-recovery.v1' || row.workspace_id !== workspaceId ||
      row.pending !== null && !validAgentResearchApproval(row.pending)) throw new Error('Invalid private query review');
  return value as AgentResearchRecovery;
}
