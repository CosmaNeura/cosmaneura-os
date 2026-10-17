import currentWorkContract from './__fixtures__/membership-analysis-w88.json';
import type {TeamSetup} from './team-setup-api';
import type {ModelUsage,ResourceInventory,SetupProjection,TeamRehearsal} from './team-setup-request';
import type {TeamConfiguration} from './workspace-api';
import {catalogFixture,projectionFixture,rehearsalFixture,teamFixture} from './team-setup-test-fixture';
export const policyTime='2026-09-21T22:00:00Z';
export const resourcesFixture:ResourceInventory={contract_version:1,inventory_sha256:'c'.repeat(64),resources:[
  {purpose:'core_preparation',resource_ref:'d'.repeat(64),label:'Current reviewed preparation account'},
  {purpose:'scheduling_context',resource_ref:'e'.repeat(64),label:'Current reviewed scheduling account'}]};
export const usageFixture:ModelUsage={contract_version:1,policy:null,team_revision:1,as_of:policyTime,window_start:'2026-09-20T22:00:00Z',admitted_units:0,occupied_units:0,remaining_units:null,pending_units:0,unknown_units:0,verified_input_tokens:0,verified_output_tokens:0,usage_complete:true,coverage:'new_admissions_and_retained_legacy_records'};
/** Invented v2 projection for component/transport tests, not a server qualification. */
export function policyProjection(configuration:TeamConfiguration,previous:SetupProjection):SetupProjection {
  const result=structuredClone(previous);result.contract_version=2;result.catalog_version=2;
  for(const row of result.capabilities){const bot=configuration.bots.find(b=>(b.instance_id??b.role)===row.bot)!;
    if(row.capability==='model_answer'||row.capability==='private_draft_handoff'){
      const limit=configuration.model_work?.max_attempts_per_24h??null;row.sources.push({kind:'model_work',limit,occupied_units:0,state:limit===null?'unlimited':limit===0?'paused':'available',as_of:policyTime});
      if(limit===0&&!bot.retired&&bot.enabled&&row.selected&&!row.restricted)row.state='work_limit_reached';
    }
    if(row.capability==='encounter_prep'||row.capability==='calendar_availability'){
      const purpose=row.capability==='encounter_prep'?'core_preparation':'scheduling_context',binding=bot.resources?.allowed.find(b=>b.purpose===purpose);
      const selection=!bot.resources?'inherited':!binding?'denied':resourcesFixture.resources.some(r=>r.purpose===purpose&&r.resource_ref===binding.resource_ref)?'current':'unavailable';
      row.sources.push({kind:'resource',purpose,mode:bot.resources?'allow_list':'inherit',selection,inventory_sha256:resourcesFixture.inventory_sha256});
      if(!bot.retired&&bot.enabled&&row.selected&&!row.restricted){if(selection==='denied')row.state='resource_restricted';if(selection==='unavailable')row.state='resource_unavailable';}
    }
  }
  return result;
}
export function upgradeSetupFixture(value:TeamSetup):TeamSetup{return {...structuredClone(value),catalog:{...structuredClone(currentWorkContract.setup.catalog),version:5} as TeamSetup['catalog'],setup:{...policyProjection(value.team.configuration,value.setup),contract_version:5,catalog_version:5}};}
export function upgradeRehearsalFixture(value:TeamRehearsal):TeamRehearsal{return {...structuredClone(value),scenario_id:'team_policy_setup.v1',setup:{...policyProjection(value.configuration,value.setup),contract_version:5,catalog_version:5},setup_review:{...value.setup_review,catalog_version:5},cases:[...value.cases,
  {case_id:'model_work_policy',bot:null,result:'demonstrated',explanation:'Invented policy only; no provider call.'},...value.configuration.bots.map(bot=>({case_id:'resource_policy' as const,bot:bot.instance_id??bot.role,result:'demonstrated' as const,explanation:'Invented source policy only; no grant or service call.'}))]};}
export async function policySetupFixture(configuration:TeamConfiguration=teamFixture().configuration,revision=1):Promise<TeamSetup>{return upgradeSetupFixture({team:teamFixture(configuration,revision),catalog:catalogFixture(),setup:await projectionFixture(configuration,revision)});}
export async function policyRehearsalFixture(configuration:TeamConfiguration,revision=1){return upgradeRehearsalFixture(await rehearsalFixture(configuration,revision));}
