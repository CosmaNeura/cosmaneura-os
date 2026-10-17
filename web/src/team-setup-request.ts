import {validPracticeProfile,normalizedProfile,practiceProfileContext} from './practice-profile';
import type {BotAddress, BotRole, BotSettings, BotSkill, TeamConfiguration, TeamSaveInput} from "./workspace-api";

export const TEAM_REQUEST_BYTES = 4 * 1048576, TEAM_RESPONSE_BYTES = 8 * 1048576;
export const PRESET_IDS = ["provider", "front_desk", "practice_manager"] as const;
export type PresetId = typeof PRESET_IDS[number];
export const BLOCKED_CAPABILITIES = ["model_answer", "private_draft_handoff", "practice_work_brief"] as const;
export type BlockedCapability = typeof BLOCKED_CAPABILITIES[number];
export const PRESET_SLOTS = {provider:["scribe","visit_prep","follow_up","chief"],
  front_desk:["inbox","scheduling","intake"],practice_manager:["operations","membership_billing","chief"]} as const;
export type SlotName = typeof PRESET_SLOTS[PresetId][number];
export type PresetBinding = {preset_id:PresetId;version:1|2;slots:Partial<Record<SlotName,BotAddress>>};
export type ModelWorkPolicy={version:1;max_attempts_per_24h:number};
export const RESOURCE_PURPOSES=["core_preparation","scheduling_context"] as const;
export type ResourcePurpose=typeof RESOURCE_PURPOSES[number];
export type BotResources={version:1;allowed:{purpose:ResourcePurpose;resource_ref:string}[]};
export type ResourceInventory={contract_version:1;resources:{purpose:ResourcePurpose;resource_ref:string;label:"Current reviewed preparation account"|"Current reviewed scheduling account"}[];inventory_sha256:string};
export type ModelUsage={contract_version:1;policy:ModelWorkPolicy|null;team_revision:number;as_of:string;window_start:string;admitted_units:number;occupied_units:number;remaining_units:number|null;pending_units:number;unknown_units:number;verified_input_tokens:number|null;verified_output_tokens:number|null;usage_complete:boolean;coverage:"new_admissions_and_retained_legacy_records"};
export type SetupReview = {catalog_version:1|2|3|4|5;configuration_sha256:string;prerequisites_sha256:string};
export type TeamRehearsalRequest = {expected_revision:number;configuration:TeamConfiguration;scenario_id:"preset_setup.v1"|"team_policy_setup.v1"};
export type PresetSlot = {slot:SlotName;role:BotRole;address:BotAddress|null;name:string;job_focus:string;working_preferences:string;
  enabled:boolean;response_style:"brief"|"detailed";include_notebook:boolean;include_evidence:boolean;skills:BotSkill[];blocked_capabilities:BlockedCapability[]};
export type PresetDescriptor = {preset_id:PresetId;version:1|2;label:string;purpose:string;slots:PresetSlot[];unavailable_capabilities:CapabilityId[]};
export type PresetCatalog = {contract:"private-team-presets.v1";version:1|2|3|4|5;presets:PresetDescriptor[]};
export const CAPABILITIES = ["saved_notebook","saved_evidence","work_status","model_answer","private_draft_handoff","practice_work_brief",
  "encounter_prep","consented_capture","clinical_note","transcript_correction","calendar_availability","staff_handoff","inbox_operations","membership_billing"] as const;
export type CapabilityId = typeof CAPABILITIES[number];
export const READINESS_STATES = ["ready_local","available_for_scoped_request","requires_encounter","connection_required","disabled_by_owner","paused","retired","unavailable_in_beta","resource_restricted","resource_unavailable","work_limit_reached"] as const;
export type ReadinessState = typeof READINESS_STATES[number];
export const ROUTINE_STATUSES = ["not_configured","paused","team_changed","bot_unavailable","skill_unavailable","restricted","waiting","missed","quiet_hours","already_run","run_limit","due"] as const;
export type SetupSource = {kind:"runtime";key:"model"|"capture"|"prep"|"notes"|"corrections"|"scheduling"|"routines"|"inbox"|"membership";enabled:boolean} |
  {kind:"account";key:"core"|"scheduling";state:"reviewed"|"missing"|"revoked"|"unverified"} |
  {kind:"scope";key:"encounter"|"work_item"|"recording_consent"|"provider_review"|"reviewed_inbox"|"reviewed_membership";required:true} |
  {kind:"routine";revision:number;status:typeof ROUTINE_STATUSES[number]} |
  {kind:"resource";purpose:ResourcePurpose;mode:"inherit"|"allow_list";selection:"inherited"|"current"|"unavailable"|"denied";inventory_sha256:string} |
  {kind:"model_work";limit:number|null;occupied_units:number;state:"unlimited"|"available"|"paused"|"exhausted";as_of:string};
export type CapabilityReadiness = {bot:BotAddress;capability:CapabilityId;selected:boolean;restricted:boolean;state:ReadinessState;explanation:string;sources:SetupSource[]};
export type SetupProjection = {contract_version:1|2|3|4|5;catalog_version:1|2|3|4|5;team_revision:number;configuration_sha256:string;prerequisites_sha256:string;capabilities:CapabilityReadiness[]};
export const REHEARSAL_CASES = ["private_sources","work_brief","scheduling","preparation","inbox","membership_billing","human_control"] as const;
export type TeamRehearsal = {scenario_id:"preset_setup.v1"|"team_policy_setup.v1";expected_revision:number;configuration:TeamConfiguration;setup:SetupProjection;setup_review:SetupReview;
  configuration_checks:"passed";cases:{case_id:typeof REHEARSAL_CASES[number]|"model_work_policy"|"resource_policy";bot:BotAddress|null;result:"demonstrated"|"withheld"|"prerequisite_required"|"unavailable";explanation:string}[]};

const ROLES = ["scribe","visit_prep","follow_up","chief","custom","research"], BASELINE = ROLES.slice(0,4);
const SKILLS = ["saved_context","work_status","encounter_prep","calendar_availability","inbox_review","membership_review"];
export const teamLiteral = <T extends string>(value:unknown,allowed:readonly T[]):value is T => typeof value==='string'&&allowed.includes(value as T);
export const teamNatural = (value:unknown):value is number => Number.isSafeInteger(value) && Number(value)>=0;
export const teamHash = (value:unknown):value is string => typeof value==="string" && /^[a-f0-9]{64}$/.test(value);
export const teamUuid = (value:unknown):value is string => typeof value==="string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(value);
export const teamAddress = (value:unknown):value is string => typeof value==="string" && (BASELINE.includes(value)||teamUuid(value));
export function teamClosed(value:unknown,required:string,optional=""):value is Record<string,unknown> {
  if (!value || typeof value!=="object" || Array.isArray(value)) return false;
  const keys=Object.keys(value), needed=required.split(",").filter(Boolean), allowed=[...needed,...optional.split(",")];
  return needed.every(key=>Object.hasOwn(value,key)) && keys.every(key=>allowed.includes(key));
}
// Python str.strip(), including NEL and the four information separators, but not BOM.
export const teamStrip = (value:string) => value.replace(/^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+|[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/g,"");
export function teamText(value:unknown,maximum:number,minimum=0):value is string {
  if (typeof value!=="string") return false;
  let count=0;
  for (const scalar of value) { const cp=scalar.codePointAt(0)!; if(cp>=0xd800&&cp<=0xdfff || ++count>maximum)return false; }
  return count>=minimum;
}
const text=(value:unknown,max:number,min=0) => typeof value==="string" && teamText(teamStrip(value),max,min);
const uniqueList=(value:unknown,allowed:readonly string[],maximum=allowed.length):value is string[] =>
  Array.isArray(value)&&value.length<=maximum&&value.every(v=>typeof v==="string"&&allowed.includes(v))&&new Set(value).size===value.length;
export const validModelPolicy=(v:unknown):v is ModelWorkPolicy=>teamClosed(v,"version,max_attempts_per_24h")&&v.version===1&&teamNatural(v.max_attempts_per_24h)&&v.max_attempts_per_24h<=1000;
export function validResources(v:unknown):v is BotResources {
  return teamClosed(v,"version,allowed")&&v.version===1&&Array.isArray(v.allowed)&&v.allowed.length<=2&&v.allowed.every(item=>
    teamClosed(item,"purpose,resource_ref")&&teamLiteral(item.purpose,RESOURCE_PURPOSES)&&teamHash(item.resource_ref))&&new Set(v.allowed.map(item=>item.purpose)).size===v.allowed.length;
}

/** Closed editable shape; temporary blank names/jobs stay recoverable. */
export function validTeamConfiguration(value:unknown,editing=false):value is TeamConfiguration {
  if(!teamClosed(value,"bots","practice_context,presets,model_work,practice_profile") || value.practice_profile!==undefined&&!validPracticeProfile(value.practice_profile)|| value.model_work!==undefined&&!validModelPolicy(value.model_work)||value.practice_context!==undefined&&!text(value.practice_context,1000) ||
    !Array.isArray(value.bots)||value.bots.length<4||value.bots.length>100)return false;
  if(!editing&&practiceProfileContext(value.practice_profile as import("./practice-profile").PracticeProfile|undefined,(value.practice_context as string|undefined)??"Direct Primary Care").length>1000)return false;
  const baseline=new Set<string>(), addresses=new Map<string,Record<string,unknown>>();let current=0;
  for(const bot of value.bots) {
    if(!teamClosed(bot,"role,name,enabled","response_style,include_notebook,include_evidence,instance_id,job_focus,working_preferences,retired,skills,blocked_capabilities,resources") ||
      bot.resources!==undefined&&!validResources(bot.resources)||
      !teamLiteral(bot.role,ROLES)||!text(bot.name,40,editing?0:1)||typeof bot.enabled!=="boolean" ||
      bot.response_style!==undefined&&!teamLiteral(bot.response_style,['brief','detailed']) ||
      ['include_notebook','include_evidence','retired'].some(k=>bot[k]!==undefined&&typeof bot[k]!=="boolean") ||
      bot.job_focus!==undefined&&!text(bot.job_focus,500) || bot.working_preferences!==undefined&&!text(bot.working_preferences,2000) ||
      bot.skills!==undefined&&!uniqueList(bot.skills,SKILLS) || bot.blocked_capabilities!==undefined&&!uniqueList(bot.blocked_capabilities,BLOCKED_CAPABILITIES))return false;
    const instance=bot.instance_id;
    if(instance!==undefined&&instance!==null&&(typeof instance!=="string"||!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(instance)))return false;
    if(bot.role==='custom'&&(!instance||!editing&&!text(bot.job_focus,500,1)) ||
      bot.role!=='custom'&&Array.isArray(bot.skills)&&bot.skills.length || bot.retired&&(!instance||bot.enabled))return false;
    const address=typeof instance==='string'?instance.toLowerCase():bot.role;
    if(addresses.has(address))return false;addresses.set(address,bot);
    if(!instance) {if(bot.role==='custom'||baseline.has(bot.role))return false;baseline.add(bot.role);}
    else if(bot.role==='chief')return false;
    if(!bot.retired)current++;
  }
  if(baseline.size!==4||!BASELINE.every(role=>baseline.has(role))||current>12)return false;
  if(value.presets===undefined)return true;
  if(!Array.isArray(value.presets)||value.presets.length>3)return false;
  const installed=new Set<string>(),bound=new Set<string>();
  for(const binding of value.presets) {
    if(!teamClosed(binding,"preset_id,version,slots")||!teamLiteral(binding.preset_id,PRESET_IDS)||(binding.version!==1&&!(['front_desk','practice_manager'].includes(binding.preset_id)&&binding.version===2))||installed.has(binding.preset_id))return false;
    const id=binding.preset_id;installed.add(id);
    if(!teamClosed(binding.slots,PRESET_SLOTS[id].join(',')))return false;
    for(const slot of PRESET_SLOTS[id]) {
      const address=binding.slots[slot];if(!teamAddress(address))return false;
      const bot=addresses.get(address);if(!bot)return false;
      if(id==='provider'||slot==='chief') {if(address!==slot)return false;}
      else if(bot.role!=='custom'||!bot.instance_id)return false;
      if(bound.has(address)&&address!=='chief')return false;bound.add(address);
    }
  }
  return installed.size===0||installed.has('provider');
}
export function normalizeTeamConfiguration(value:unknown):TeamConfiguration {
  if(!validTeamConfiguration(value))throw new Error('Invalid team configuration');
  const result:TeamConfiguration={practice_context:teamStrip(value.practice_context??'Direct Primary Care'),bots:value.bots.map(bot=>{
    const item:BotSettings={role:bot.role,name:teamStrip(bot.name),enabled:bot.enabled,response_style:bot.response_style??'brief',
      include_notebook:bot.include_notebook??bot.role!=="research",include_evidence:bot.include_evidence??bot.role!=="research"};
    if(bot.instance_id)item.instance_id=bot.instance_id.toLowerCase();
    if(bot.job_focus&&teamStrip(bot.job_focus))item.job_focus=teamStrip(bot.job_focus);
    if(bot.working_preferences&&teamStrip(bot.working_preferences))item.working_preferences=teamStrip(bot.working_preferences);
    if(bot.retired)item.retired=true;
    if(bot.skills?.length)item.skills=[...bot.skills];
    if(bot.blocked_capabilities?.length)item.blocked_capabilities=BLOCKED_CAPABILITIES.filter(cap=>bot.blocked_capabilities!.includes(cap));
    if(bot.resources!==undefined)item.resources={version:1,allowed:RESOURCE_PURPOSES.flatMap(p=>bot.resources!.allowed.filter(b=>b.purpose===p).map(b=>({...b})))};
    return item;
  })};
  const profile=normalizedProfile(value.practice_profile);if(profile)result.practice_profile=profile;
  if(value.presets?.length)result.presets=PRESET_IDS.flatMap(id=>value.presets!.filter(p=>p.preset_id===id).map(p=>structuredClone(p)));
  if(value.model_work!==undefined)result.model_work={...value.model_work};
  return result;
}
export function teamCanonical(value:unknown):string {
  if(Array.isArray(value))return '['+value.map(teamCanonical).join(',')+']';
  if(value&&typeof value==='object')return '{'+Object.keys(value).sort().map(key=>JSON.stringify(key)+':'+teamCanonical((value as Record<string,unknown>)[key])).join(',')+'}';
  return JSON.stringify(value);
}
export async function configurationHash(value:TeamConfiguration):Promise<string> {
  const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(teamCanonical(normalizeTeamConfiguration(value))));
  return [...new Uint8Array(bytes)].map(v=>v.toString(16).padStart(2,'0')).join('');
}
export const validSetupReview=(value:unknown):value is SetupReview => teamClosed(value,'catalog_version,configuration_sha256,prerequisites_sha256')&&
  (value.catalog_version===1||value.catalog_version===2||value.catalog_version===3||value.catalog_version===4||value.catalog_version===5)&&teamHash(value.configuration_sha256)&&teamHash(value.prerequisites_sha256);
export function validTeamSave(value:unknown):value is TeamSaveInput {
  return teamClosed(value,'expected_revision,idempotency_key,configuration','setup_review')&&teamNatural(value.expected_revision)&&
    typeof value.idempotency_key==='string'&&/^[A-Za-z0-9._:-]{8,255}$/.test(value.idempotency_key)&&validTeamConfiguration(value.configuration)&&
    (value.setup_review===undefined||validSetupReview(value.setup_review)&&(value.setup_review.catalog_version>=2||value.configuration.model_work===undefined&&value.configuration.bots.every(bot=>bot.resources===undefined)));
}
export function setupChange(current:TeamConfiguration,draft:TeamConfiguration):boolean {
  const selected=(config:TeamConfiguration)=>({presets:config.presets??[],policy:config.model_work??null,bots:config.bots.map(bot=>({address:bot.instance_id??bot.role,blocked:bot.blocked_capabilities??[],resources:bot.resources??null,inbox:bot.skills?.includes("inbox_review")??false,membership:bot.skills?.includes("membership_review")??false}))});
  const before=selected(current),after=selected(draft);
  // Adding an ordinary unrestricted coworker keeps the original editing path.
  return teamCanonical(before.policy)!==teamCanonical(after.policy)||teamCanonical(before.presets)!==teamCanonical(after.presets)||after.bots.some(bot=>
    teamCanonical(bot.blocked)!==teamCanonical(before.bots.find(b=>b.address===bot.address)?.blocked??[])||
    teamCanonical(bot.resources)!==teamCanonical(before.bots.find(b=>b.address===bot.address)?.resources??null)||bot.inbox!==(before.bots.find(b=>b.address===bot.address)?.inbox??false)||bot.membership!==(before.bots.find(b=>b.address===bot.address)?.membership??false));
}

export function applyPreset(draft:TeamConfiguration,catalog:PresetCatalog,id:PresetId,uuid:()=>string=()=>crypto.randomUUID()):TeamConfiguration {
  if(!validTeamConfiguration(draft,true))throw new Error('Review the team draft before adding coworkers.');
  if(draft.presets?.some(p=>p.preset_id===id))return draft;
  const preset=catalog.presets.find(p=>p.preset_id===id);if(!preset)throw new Error('This preset is unavailable.');
  const additions=preset.slots.filter(slot=>slot.address===null);
  if(draft.bots.length+additions.length>100||draft.bots.filter(b=>!b.retired).length+additions.length>12)throw new Error('The complete group will not fit. Review current coworkers and retained history before adding it.');
  const next=structuredClone(draft);next.presets??=[];
  if(!next.presets.some(p=>p.preset_id==='provider'))next.presets.push({preset_id:'provider',version:1,slots:{scribe:'scribe',visit_prep:'visit_prep',follow_up:'follow_up',chief:'chief'}});
  if(id==='provider')return next;
  const binding:PresetBinding={preset_id:id,version:preset.version,slots:{}};
  for(const slot of preset.slots) {
    if(slot.address!==null) {binding.slots[slot.slot]=slot.address;continue;}
    const instance_id=uuid();binding.slots[slot.slot]=instance_id;
    next.bots.push({role:slot.role,instance_id,name:slot.name,job_focus:slot.job_focus,working_preferences:slot.working_preferences,
      enabled:slot.enabled,response_style:slot.response_style,include_notebook:slot.include_notebook,include_evidence:slot.include_evidence,
      skills:[...slot.skills],...(slot.blocked_capabilities.length?{blocked_capabilities:[...slot.blocked_capabilities]}:{})});
  }
  next.presets.push(binding);if(!validTeamConfiguration(next,true))throw new Error('This preset could not be added.');return next;
}
export function replacePresetSlot(draft:TeamConfiguration,saved:TeamConfiguration,catalog:PresetCatalog,id:PresetId,slotName:SlotName,uuid:()=>string=()=>crypto.randomUUID()):TeamConfiguration {
  const binding=draft.presets?.find(p=>p.preset_id===id),old=binding?.slots[slotName];
  const previous=saved.presets?.find(p=>p.preset_id===id)?.slots[slotName];
  const retired=saved.bots.find(b=>b.instance_id===old),slot=catalog.presets.find(p=>p.preset_id===id)?.slots.find(s=>s.slot===slotName);
  if(!old||old!==previous||!retired?.retired||!slot||slot.address!==null||draft.bots.length>=100||draft.bots.filter(b=>!b.retired).length>=12)
    throw new Error('A replacement needs a saved retired coworker and room in the team history.');
  const next=structuredClone(draft),instance_id=uuid();next.presets!.find(p=>p.preset_id===id)!.slots[slotName]=instance_id;
  next.bots.push({role:'custom',instance_id,name:slot.name,job_focus:slot.job_focus,working_preferences:slot.working_preferences,enabled:slot.enabled,
    response_style:slot.response_style,include_notebook:slot.include_notebook,include_evidence:slot.include_evidence,skills:[...slot.skills],
    ...(slot.blocked_capabilities.length?{blocked_capabilities:[...slot.blocked_capabilities]}:{})});
  if(!validTeamConfiguration(next,true))throw new Error('This replacement could not be added.');return next;
}

/** Deliberate draft upgrade. Saved identities, context choices and owner limits survive. */
export function upgradeInboxPreset(draft:TeamConfiguration,catalog:PresetCatalog):TeamConfiguration {
  const preset=catalog.presets.find(p=>p.preset_id==='front_desk'),binding=draft.presets?.find(p=>p.preset_id==='front_desk');
  if(catalog.version<3||preset?.version!==2||binding?.version!==1)throw new Error('No Inbox upgrade is available.');
  const next=structuredClone(draft),target=next.bots.find(bot=>bot.instance_id===binding.slots.inbox);
  if(!target||target.retired)throw new Error('Replace the retired Inbox coworker before upgrading.');
  target.skills=[...new Set([...(target.skills??[]),'inbox_review' as const])];target.enabled=true;
  next.presets!.find(p=>p.preset_id==='front_desk')!.version=2;
  if(!validTeamConfiguration(next,true))throw new Error('The Inbox upgrade is invalid.');
  return next;
}

/** Deliberate upgrade preserves the saved coworker identity and owner restrictions. */
export function upgradeMembershipPreset(draft:TeamConfiguration,catalog:PresetCatalog):TeamConfiguration {
  const preset=catalog.presets.find(p=>p.preset_id==='practice_manager'),binding=draft.presets?.find(p=>p.preset_id==='practice_manager');
  if(catalog.version<4||preset?.version!==2||binding?.version!==1)throw new Error('No Membership/Billing upgrade is available.');
  const next=structuredClone(draft),target=next.bots.find(b=>b.instance_id===binding.slots.membership_billing);
  if(!target||target.retired)throw new Error('Replace the retired Membership/Billing coworker first.');
  target.skills=[...new Set([...(target.skills??[]),'membership_review' as const])];target.enabled=true;
  next.presets!.find(p=>p.preset_id==='practice_manager')!.version=2;
  if(!validTeamConfiguration(next,true))throw new Error('The Membership/Billing upgrade is invalid.');
  return next;
}
