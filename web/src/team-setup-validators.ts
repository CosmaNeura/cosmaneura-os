import type {BotTemplate, ProviderTeam, TeamConfiguration} from "./workspace-api";
import {BLOCKED_CAPABILITIES, CAPABILITIES, PRESET_IDS, PRESET_SLOTS, READINESS_STATES, REHEARSAL_CASES, ROUTINE_STATUSES, RESOURCE_PURPOSES, validModelPolicy,
  normalizeTeamConfiguration, teamAddress, teamCanonical, teamClosed as closed, teamHash, teamLiteral, teamNatural, teamText, teamUuid,
  validSetupReview, validTeamConfiguration, type ModelUsage, type ResourceInventory, type PresetCatalog, type PresetId, type SetupProjection, type TeamRehearsal} from "./team-setup-request";
import {modelTime} from "./model-work-request";

const roles=['scribe','visit_prep','follow_up','chief','custom','research'],skills=['saved_context','work_status','encounter_prep','calendar_availability','inbox_review','membership_review'];
const list=(v:unknown,allowed:readonly string[])=>Array.isArray(v)&&v.length<=allowed.length&&v.every(x=>teamLiteral(x,allowed))&&new Set(v).size===v.length;
const address=(v:{role:string;instance_id?:string|null})=>v.instance_id??v.role;
function capability(v:unknown):boolean {
  return closed(v,'key,label,state,connector,contract')&&teamText(v.key,100,1)&&teamText(v.label,200,1)&&
    teamLiteral(v.state,['local','enabled','awaiting_connection'])&&teamText(v.connector,200)&&
    (v.contract===null||teamText(v.contract,200,1));
}
function template(v:unknown):v is BotTemplate {
  return closed(v,'role,agent_id,name,initials,description,prompt,capabilities','instance_id')&&teamLiteral(v.role,roles)&&
    (v.agent_id===null||teamUuid(v.agent_id))&&(v.instance_id===undefined||v.instance_id===null||teamUuid(v.instance_id))&&
    teamText(v.name,80,1)&&teamText(v.initials,20,1)&&teamText(v.description,2000)&&teamText(v.prompt,4000)&&
    Array.isArray(v.capabilities)&&v.capabilities.length<=30&&v.capabilities.every(capability)&&new Set(v.capabilities.map(c=>(c as {key:string}).key)).size===v.capabilities.length;
}
export function validProviderTeam(v:unknown):v is ProviderTeam {
  if(!closed(v,'revision,template_version,configuration,members,llm','recovery_scope,templates,custom_skills,scheduling,capture')||
    !teamNatural(v.revision)||!teamText(v.template_version,100,1)||!validTeamConfiguration(v.configuration)||
    !Array.isArray(v.members)||v.members.length!==v.configuration.bots.length||!v.members.every(template)||
    !closed(v.llm,'enabled,model')||typeof v.llm.enabled!=='boolean'||!teamText(v.llm.model,100,1)||
    v.recovery_scope!==undefined&&!teamHash(v.recovery_scope))return false;
  const configuration=v.configuration;
  if(v.members.some((member,i)=>address(member)!==address(configuration.bots[i])||member.role!==configuration.bots[i].role))return false;
  if(v.templates!==undefined&&(!Array.isArray(v.templates)||v.templates.length>5||!v.templates.every(template)||new Set(v.templates.map(t=>t.role)).size!==v.templates.length))return false;
  if(v.custom_skills!==undefined&&(!Array.isArray(v.custom_skills)||v.custom_skills.length>6||!v.custom_skills.every(s=>capability(s)&&teamLiteral(s.key,skills))||new Set(v.custom_skills.map(s=>s.key)).size!==v.custom_skills.length))return false;
  if(v.scheduling!==undefined&&(!closed(v.scheduling,'enabled')||typeof v.scheduling.enabled!=='boolean'))return false;
  return v.capture===undefined||closed(v.capture,'enabled','notes_enabled,corrections_enabled,prep_enabled,prep_work_enabled')&&Object.values(v.capture).every(value=>typeof value==='boolean');
}
export function validPresetCatalog(v:unknown):v is PresetCatalog {
  if(!closed(v,'contract,version,presets')||v.contract!=='private-team-presets.v1'||(v.version!==1&&v.version!==2&&v.version!==3&&v.version!==4)||!Array.isArray(v.presets)||v.presets.length!==3)return false;
  for(const [index,preset] of v.presets.entries()) {
    if(!closed(preset,'preset_id,version,label,purpose,slots,unavailable_capabilities')||preset.preset_id!==PRESET_IDS[index]||preset.version!==((v.version>=3&&preset.preset_id==='front_desk'||v.version>=4&&preset.preset_id==='practice_manager')?2:1)||
      !teamText(preset.label,80,1)||!teamText(preset.purpose,500,1)||!Array.isArray(preset.slots))return false;
    const id=preset.preset_id as PresetId,inventory=PRESET_SLOTS[id];
    const unavailable=id==='front_desk'&&v.version<3?['inbox_operations']:id==='practice_manager'&&v.version<4?['membership_billing']:[];
    if(preset.slots.length!==inventory.length||teamCanonical(preset.unavailable_capabilities)!==teamCanonical(unavailable))return false;
    for(const [i,slot] of preset.slots.entries()) {
      if(!closed(slot,'slot,role,address,name,job_focus,working_preferences,enabled,response_style,include_notebook,include_evidence,skills,blocked_capabilities')||
        slot.slot!==inventory[i]||!teamText(slot.name,40,1)||!teamText(slot.job_focus,500)||!teamText(slot.working_preferences,2000)||
        !teamLiteral(slot.response_style,['brief','detailed'])||[slot.enabled,slot.include_notebook,slot.include_evidence].some(b=>typeof b!=='boolean')||
        !list(slot.skills,skills)||!list(slot.blocked_capabilities,BLOCKED_CAPABILITIES))return false;
      if(id==='provider'||slot.slot==='chief') {if(slot.address!==slot.slot||slot.role!==slot.slot)return false;}
      else if(slot.address!==null||slot.role!=='custom'||!slot.job_focus)return false;
      if((slot.slot==='inbox'&&v.version<3||slot.slot==='membership_billing'&&v.version<4)&&(slot.enabled||slot.include_notebook||slot.include_evidence||(slot.skills as unknown[]).length))return false;
      if(slot.slot==='inbox'&&v.version>=3&&(!slot.enabled||slot.include_notebook||slot.include_evidence||teamCanonical(slot.skills)!=='["inbox_review"]'))return false;
      if(slot.slot==='membership_billing'&&v.version>=4&&(!slot.enabled||slot.include_notebook||slot.include_evidence||teamCanonical(slot.skills)!=='["membership_review"]'))return false;
    }
  }
  return true;
}
function source(v:unknown):boolean {
  if(!v||typeof v!=='object'||!('kind' in v))return false;
  const value=v as Record<string,unknown>;
  switch(value.kind) {
    case 'runtime':return closed(value,'kind,key,enabled')&&teamLiteral(value.key,['model','capture','prep','notes','corrections','scheduling','routines','inbox','membership'])&&typeof value.enabled==='boolean';
    case 'account':return closed(value,'kind,key,state')&&teamLiteral(value.key,['core','scheduling'])&&teamLiteral(value.state,['reviewed','missing','revoked','unverified']);
    case 'scope':return closed(value,'kind,key,required')&&teamLiteral(value.key,['encounter','work_item','recording_consent','provider_review','reviewed_inbox','reviewed_membership'])&&value.required===true;
    case 'routine':return closed(value,'kind,revision,status')&&teamNatural(value.revision)&&teamLiteral(value.status,ROUTINE_STATUSES);
    case 'resource':return closed(value,'kind,purpose,mode,selection,inventory_sha256')&&teamLiteral(value.purpose,RESOURCE_PURPOSES)&&teamLiteral(value.mode,['inherit','allow_list'])&&
      teamLiteral(value.selection,['inherited','current','unavailable','denied'])&&teamHash(value.inventory_sha256)&&((value.mode==='inherit')===(value.selection==='inherited'));
    case 'model_work':return closed(value,'kind,limit,occupied_units,state,as_of')&&(value.limit===null||teamNatural(value.limit)&&value.limit<=1000)&&teamNatural(value.occupied_units)&&modelTime(value.as_of)&&
      value.state===(value.limit===null?'unlimited':value.limit===0?'paused':value.occupied_units>=value.limit?'exhausted':'available');
    default:return false;
  }
}
export function validSetupProjection(v:unknown,configuration:TeamConfiguration,revision:number):v is SetupProjection {
  if(!closed(v,'contract_version,catalog_version,team_revision,configuration_sha256,prerequisites_sha256,capabilities')||(v.contract_version!==1&&v.contract_version!==2&&v.contract_version!==3&&v.contract_version!==4)||v.catalog_version!==v.contract_version||
    v.team_revision!==revision||!teamHash(v.configuration_sha256)||!teamHash(v.prerequisites_sha256)||!Array.isArray(v.capabilities)||v.capabilities.length>1400)return false;
  if(v.contract_version===1&&(configuration.model_work!==undefined||configuration.bots.some(bot=>bot.resources!==undefined)))return false;
  const seen=new Set<string>(),bots=new Map(configuration.bots.map(b=>[address(b),b]));
  for(const item of v.capabilities) {
    if(!closed(item,'bot,capability,selected,restricted,state,explanation,sources')||!teamAddress(item.bot)||!bots.has(item.bot)||
      !teamLiteral(item.capability,CAPABILITIES)||typeof item.selected!=='boolean'||typeof item.restricted!=='boolean'||
      !teamLiteral(item.state,READINESS_STATES)||!teamText(item.explanation,v.contract_version>=2?1000:240,1)||
      !Array.isArray(item.sources)||item.sources.length>6||!item.sources.every(source))return false;
    const key=item.bot+':'+item.capability;if(seen.has(key))return false;seen.add(key);
    const bot=bots.get(item.bot)!;
    const cap=item.capability,has=(skill:string)=>bot.role==='custom'?(bot.skills??[]).includes(skill as never):
      skill==='saved_context'||skill==='work_status'||skill==='encounter_prep'&&['scribe','visit_prep'].includes(bot.role)||skill==='calendar_availability'&&bot.role==='follow_up';
    const inbox=cap==='inbox_operations'&&v.contract_version>=3&&has('inbox_review');
    const membership=cap==='membership_billing'&&v.contract_version>=4&&has('membership_review');
    const unavailable=cap==='membership_billing'&&!membership||cap==='inbox_operations'&&!inbox;
    const selected=unavailable?false:cap==='saved_notebook'||cap==='saved_evidence'?has('saved_context'):
      ['work_status','private_draft_handoff','practice_work_brief','staff_handoff'].includes(cap)?has('work_status'):
      cap==='encounter_prep'?has('encounter_prep'):cap==='calendar_availability'?has('calendar_availability'):true;
    const restricted=inbox||membership?bot.blocked_capabilities?.includes('model_answer')??false:cap==='saved_notebook'?!bot.include_notebook:['saved_evidence','encounter_prep','calendar_availability'].includes(cap)?!bot.include_evidence:
      cap==='private_draft_handoff'?bot.blocked_capabilities?.some(c=>c==='model_answer'||c==='private_draft_handoff')??false:
      ['model_answer','practice_work_brief'].includes(cap)?bot.blocked_capabilities?.includes(cap as never)??false:false;
    if(item.selected!==selected||item.restricted!==restricted)return false;
    const sourceKeys:Record<string,string[]>={model_answer:['runtime:model'],private_draft_handoff:['runtime:model'],practice_work_brief:['runtime:routines','routine:'],
      encounter_prep:['runtime:prep','account:core','scope:encounter'],consented_capture:['runtime:capture','account:core','scope:recording_consent'],
      clinical_note:['runtime:notes','account:core','scope:provider_review'],transcript_correction:['runtime:corrections','account:core','scope:encounter'],
      calendar_availability:['runtime:scheduling','account:scheduling','scope:encounter'],staff_handoff:['scope:work_item']};
    const sources=item.sources as Record<string,unknown>[];
    const expectedKeys=[...(inbox?['runtime:inbox','scope:reviewed_inbox']:membership?['runtime:membership','scope:reviewed_membership']:(sourceKeys[cap]??[]))];
    if(inbox||membership)expectedKeys.push('model_work:');
    if(v.contract_version>=2&&['model_answer','private_draft_handoff'].includes(cap))expectedKeys.push('model_work:');
    if(v.contract_version>=2&&['encounter_prep','calendar_availability'].includes(cap))expectedKeys.push('resource:');
    if(teamCanonical(sources.map(s=>s.kind+':'+(s.key??'')))!==teamCanonical(expectedKeys))return false;
    const resource=sources.find(s=>s.kind==='resource'),work=sources.find(s=>s.kind==='model_work');
    if(work&&work.limit!==(configuration.model_work?.max_attempts_per_24h??null))return false;
    if(resource) {
      const purpose=cap==='encounter_prep'?'core_preparation':'scheduling_context',binding=bot.resources?.allowed.find(b=>b.purpose===purpose);
      if(resource.purpose!==purpose||resource.mode!==(bot.resources?'allow_list':'inherit')||
        (!bot.resources?resource.selection!=='inherited':!binding?resource.selection!=='denied':!teamLiteral(resource.selection,['current','unavailable'])))return false;
    }
    const expected=unavailable?'unavailable_in_beta':bot.retired?'retired':!bot.enabled?'paused':!selected||restricted?'disabled_by_owner':
      resource?.selection==='denied'?'resource_restricted':resource?.selection==='unavailable'?'resource_unavailable':
      work&&(work.state==='paused'||work.state==='exhausted')?'work_limit_reached':
      sources.some(s=>s.kind==='runtime'&&!s.enabled||s.kind==='account'&&s.state!=='reviewed')?'connection_required':
      sources.some(s=>s.kind==='scope'&&s.key!=='work_item'&&s.key!=='reviewed_inbox'&&s.key!=='reviewed_membership')?'requires_encounter':
      (inbox||membership||['model_answer','private_draft_handoff','staff_handoff'].includes(cap))?'available_for_scoped_request':'ready_local';
    if(item.state!==expected)return false;
  }
  return true;
}
export function validTeamRehearsal(v:unknown):v is TeamRehearsal {
  if(!closed(v,'scenario_id,expected_revision,configuration,setup,setup_review,configuration_checks,cases')||!teamLiteral(v.scenario_id,['preset_setup.v1','team_policy_setup.v1'])||
    !teamNatural(v.expected_revision)||!validTeamConfiguration(v.configuration)||!validSetupReview(v.setup_review)||v.configuration_checks!=='passed'||
    !validSetupProjection(v.setup,v.configuration,v.expected_revision)||!Array.isArray(v.cases)||
    teamCanonical(v.configuration)!==teamCanonical(normalizeTeamConfiguration(v.configuration))||
    v.setup.configuration_sha256!==v.setup_review.configuration_sha256||v.setup.prerequisites_sha256!==v.setup_review.prerequisites_sha256||
    v.setup.catalog_version!==v.setup_review.catalog_version||(v.scenario_id==='team_policy_setup.v1'?v.setup.contract_version<2:v.setup.contract_version!==1))return false;
  const expected:{case_id:string;bot?:string|null}[]=REHEARSAL_CASES.map(case_id=>({case_id}));
  if(v.scenario_id==='team_policy_setup.v1')expected.push({case_id:'model_work_policy',bot:null},...v.configuration.bots.map(bot=>({case_id:'resource_policy',bot:address(bot)})));
  if(v.cases.length!==expected.length)return false;
  const addresses=new Set(v.configuration.bots.map(address));
  const setup=v.setup;
  return v.cases.every((item,i)=>closed(item,'case_id,bot,result,explanation')&&item.case_id===expected[i].case_id&&(!Object.hasOwn(expected[i],'bot')||item.bot===expected[i].bot)&&
    (item.bot===null||teamAddress(item.bot)&&addresses.has(item.bot))&&teamLiteral(item.result,['demonstrated','withheld','prerequisite_required','unavailable'])&&
    teamText(item.explanation,v.scenario_id==='team_policy_setup.v1'?1000:400,1)&&((item.case_id!=='membership_billing'||setup.contract_version>=4)&&(item.case_id!=='inbox'||setup.contract_version>=3)||item.result==='unavailable'));
}

export function validResourceInventory(v:unknown):v is ResourceInventory {
  if(!closed(v,'contract_version,resources,inventory_sha256')||v.contract_version!==1||!teamHash(v.inventory_sha256)||!Array.isArray(v.resources)||v.resources.length>2)return false;
  const seen=new Set<string>();
  return v.resources.every(item=>{if(!closed(item,'purpose,resource_ref,label')||!teamLiteral(item.purpose,RESOURCE_PURPOSES)||!teamHash(item.resource_ref)||seen.has(item.purpose)||
    item.label!==(item.purpose==='core_preparation'?'Current reviewed preparation account':'Current reviewed scheduling account'))return false;seen.add(item.purpose);return true;});
}
export function validModelUsage(v:unknown):v is ModelUsage {
  if(!closed(v,'contract_version,policy,team_revision,as_of,window_start,admitted_units,occupied_units,remaining_units,pending_units,unknown_units,verified_input_tokens,verified_output_tokens,usage_complete,coverage')||
    v.contract_version!==1||v.policy!==null&&!validModelPolicy(v.policy)||!teamNatural(v.team_revision)||!modelTime(v.as_of)||!modelTime(v.window_start)||Date.parse(v.window_start)>Date.parse(v.as_of)||
    !['admitted_units','occupied_units','pending_units','unknown_units'].every(k=>teamNatural(v[k]))||typeof v.usage_complete!=='boolean'||v.coverage!=='new_admissions_and_retained_legacy_records')return false;
  const value=v as unknown as ModelUsage;
  if(value.admitted_units>value.occupied_units||value.pending_units>value.occupied_units||value.unknown_units>value.occupied_units||value.occupied_units>value.admitted_units+value.pending_units)return false;
  if(value.remaining_units!==(value.policy===null?null:Math.max(0,value.policy.max_attempts_per_24h-value.occupied_units)))return false;
  return (value.verified_input_tokens===null&&value.verified_output_tokens===null&&!value.usage_complete)||teamNatural(value.verified_input_tokens)&&teamNatural(value.verified_output_tokens);
}
