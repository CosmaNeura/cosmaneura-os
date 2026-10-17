import {requestTeamPayload, requireRecoveryScope, WorkspaceApiError, type ProviderTeam, type WorkspaceIdentity} from "./workspace-api";
import {configurationHash, normalizeTeamConfiguration, teamCanonical, teamClosed, teamNatural, validTeamConfiguration,
  type PresetCatalog, type SetupProjection, type TeamRehearsal, type TeamRehearsalRequest} from "./team-setup-request";
import {validModelUsage, validResourceInventory, validPresetCatalog, validProviderTeam, validSetupProjection, validTeamRehearsal} from "./team-setup-validators";
export type TeamSetup = {team:ProviderTeam;catalog:PresetCatalog;setup:SetupProjection};
export const teamSetupApi={
  async read(identity:WorkspaceIdentity,signal?:AbortSignal):Promise<TeamSetup> {
    return requestTeamPayload(identity,"/provider-team/setup",undefined,signal,async value => {
    if(!teamClosed(value,"team,catalog,setup")||!validProviderTeam(value.team)||!validPresetCatalog(value.catalog)||
      !validSetupProjection(value.setup,value.team.configuration,value.team.revision)||value.catalog.version!==5||value.setup.contract_version!==5)throw new WorkspaceApiError(503);
    if("mode" in identity)requireRecoveryScope(value.team);
    if(value.setup.configuration_sha256!==await configurationHash(value.team.configuration))throw new WorkspaceApiError(503);
    return value as TeamSetup;
    });
  },
  async rehearse(identity:WorkspaceIdentity,body:TeamRehearsalRequest,signal?:AbortSignal):Promise<TeamRehearsal> {
    if(!teamClosed(body,"expected_revision,configuration,scenario_id")||!teamNatural(body.expected_revision)||body.scenario_id!=="team_policy_setup.v1"||
      !validTeamConfiguration(body.configuration))throw new WorkspaceApiError(422,"invalid_team_configuration");
    return requestTeamPayload(identity,"/provider-team/rehearsal",body,signal,async value => {
    if(!validTeamRehearsal(value)||value.setup.contract_version!==5||value.scenario_id!==body.scenario_id||value.expected_revision!==body.expected_revision||
      teamCanonical(value.configuration)!==teamCanonical(normalizeTeamConfiguration(body.configuration))||
      value.setup.configuration_sha256!==await configurationHash(body.configuration))throw new WorkspaceApiError(503);
    return value;
    });
  },
  resources:(identity:WorkspaceIdentity,signal?:AbortSignal)=>requestTeamPayload(identity,"/provider-team/resources",undefined,signal,value=>{
    if(!validResourceInventory(value))throw new WorkspaceApiError(503);return value;
  }),
  usage:(identity:WorkspaceIdentity,signal?:AbortSignal)=>requestTeamPayload(identity,"/provider-team/usage",undefined,signal,value=>{
    if(!validModelUsage(value))throw new WorkspaceApiError(503);return value;
  }),
};
