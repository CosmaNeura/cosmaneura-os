import type {BotRole,ProviderTeam,TeamConfiguration} from "./workspace-api";
import {configurationHash,normalizeTeamConfiguration,PRESET_IDS,PRESET_SLOTS,REHEARSAL_CASES,type PresetCatalog,type PresetId,type PresetSlot,type SetupProjection,type TeamRehearsal} from "./team-setup-request";
export const teamUuid=(n:number)=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
export function teamFixture(configuration?:TeamConfiguration,revision=1):ProviderTeam {
  const roles:BotRole[]=['scribe','visit_prep','follow_up','chief'];
  const config:TeamConfiguration=configuration??{practice_context:'Invented practice',bots:roles.map(role=>({role,name:role==='scribe'?'Scribe':role.replaceAll('_',' '),enabled:true,response_style:'brief' as const,include_notebook:true,include_evidence:true}))};
  return {revision,configuration:structuredClone(config),template_version:'provider-team-v3',recovery_scope:'a'.repeat(64),llm:{enabled:true,model:'gpt-4.1'},
    capture:{enabled:true,notes_enabled:true,corrections_enabled:true,prep_enabled:true,prep_work_enabled:true},scheduling:{enabled:true},
    members:config.bots.map(bot=>({role:bot.role,name:bot.name,instance_id:bot.instance_id??null,agent_id:teamUuid(100+config.bots.indexOf(bot)),initials:'BT',description:'Invented coworker',prompt:'Use permitted saved sources.',capabilities:[]})),
    templates:roles.filter(role=>role!=='chief').map(role=>({role,name:role,agent_id:null,initials:'BT',description:'Invented coworker',prompt:'Use permitted saved sources.',capabilities:[]})),
    custom_skills:[{key:'work_status',label:'Work status',state:'local',connector:'Workspace',contract:null},{key:'saved_context',label:'Saved context',state:'local',connector:'Workspace',contract:null},
      {key:'encounter_prep',label:'Saved intake preparation',state:'enabled',connector:'Core',contract:'core.encounter-context.v1'},{key:'calendar_availability',label:'Calendar availability',state:'enabled',connector:'Scheduling',contract:null}]};
}
const names:Record<string,string>={provider:'Provider',front_desk:'Front desk',practice_manager:'Practice manager',scribe:'Scribe',visit_prep:'Visit Prep',follow_up:'Follow-up',chief:'Chief',inbox:'Inbox',scheduling:'Scheduling',intake:'Intake',operations:'Operations',membership_billing:'Membership / Billing'};
export function catalogFixture():PresetCatalog {
  const slot=(id:PresetId,slot:PresetSlot['slot']):PresetSlot=>{const baseline=id==='provider'||slot==='chief',paused=['inbox','membership_billing'].includes(slot);
    return {slot,role:baseline?slot as BotRole:'custom',address:baseline?slot:null,name:names[slot],job_focus:baseline?'':`Invented ${slot} preparation job`,working_preferences:'',enabled:!paused,response_style:'brief',include_notebook:baseline,include_evidence:baseline||['scheduling','intake'].includes(slot),
      skills:baseline||paused?[]:slot==='scheduling'?['work_status','calendar_availability']:slot==='intake'?['work_status','encounter_prep']:['work_status'],blocked_capabilities:[]};};
  return {contract:'private-team-presets.v1',version:1,presets:PRESET_IDS.map(id=>({preset_id:id,version:1,label:names[id],purpose:`Invented ${names[id]} coworkers.`,slots:PRESET_SLOTS[id].map(s=>slot(id,s)),unavailable_capabilities:id==='front_desk'?['inbox_operations']:id==='practice_manager'?['membership_billing']:[]}))};
}
export async function projectionFixture(config:TeamConfiguration,revision=1):Promise<SetupProjection> {
  return {contract_version:1,catalog_version:1,team_revision:revision,configuration_sha256:await configurationHash(config),prerequisites_sha256:'b'.repeat(64),capabilities:config.bots.map(bot=>({bot:bot.instance_id??bot.role,capability:'model_answer',selected:true,restricted:bot.blocked_capabilities?.includes('model_answer')??false,
    state:bot.retired?'retired':!bot.enabled?'paused':bot.blocked_capabilities?.includes('model_answer')?'disabled_by_owner':'available_for_scoped_request',explanation:'Invented runtime prerequisites. Every request retains its authority checks.',sources:[{kind:'runtime',key:'model',enabled:true}]}))};
}
export async function rehearsalFixture(config:TeamConfiguration,revision=1):Promise<TeamRehearsal>{
  const configuration=normalizeTeamConfiguration(config),setup=await projectionFixture(configuration,revision);
  return {scenario_id:'preset_setup.v1',expected_revision:revision,configuration,setup,setup_review:{catalog_version:1,configuration_sha256:setup.configuration_sha256,prerequisites_sha256:setup.prerequisites_sha256},configuration_checks:'passed',
    cases:REHEARSAL_CASES.map(id=>({case_id:id,bot:null,result:id==='inbox'||id==='membership_billing'?'unavailable':'demonstrated',explanation:`Invented ${id} example; no external action.`}))};
}
