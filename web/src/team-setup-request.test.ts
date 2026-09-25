import {afterEach,beforeEach,expect,it,vi} from "vitest";
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>("node:crypto");
import {applyPreset,configurationHash,normalizeTeamConfiguration,replacePresetSlot,setupChange,teamCanonical,validTeamConfiguration,validTeamSave} from "./team-setup-request";
import {validPresetCatalog,validProviderTeam,validSetupProjection,validTeamRehearsal} from "./team-setup-validators";
import {catalogFixture,teamFixture,teamUuid} from "./team-setup-test-fixture";
import actualSetup from "./__fixtures__/team-setup.json";
import actualRehearsal from "./__fixtures__/team-rehearsal.json";
import type {TeamConfiguration} from "./workspace-api";
import {DraftJournal,teamDraft,type TeamDraft} from "./draft-journal";
import {memoryDraftStorage} from "./draft-test-fixture";
beforeEach(()=>vi.stubGlobal('crypto',webcrypto));afterEach(()=>vi.unstubAllGlobals());
it('validates and hashes actual signed backend setup/rehearsal responses with nine stable bot identities',async()=>{
  // Copied from backend signed API qualification; invented data, no service acceptance.
  expect(validProviderTeam(actualSetup.team)).toBe(true);expect(validPresetCatalog(actualSetup.catalog)).toBe(true);
  expect(validSetupProjection(actualSetup.setup,actualSetup.team.configuration as TeamConfiguration,actualSetup.team.revision)).toBe(true);
  expect(validTeamRehearsal(actualRehearsal)).toBe(true);
  expect(await configurationHash(actualSetup.team.configuration as TeamConfiguration)).toBe(actualSetup.setup.configuration_sha256);
  expect(await configurationHash(actualRehearsal.configuration as TeamConfiguration)).toBe(actualRehearsal.setup_review.configuration_sha256);
});
it.each(['role','response_style'])('rejects array-coerced configuration %s before saving or replacing a recoverable journal',async field=>{
  const configuration=structuredClone(actualSetup.team.configuration) as any;
  configuration.bots[0][field]=[configuration.bots[0][field]];
  const pending={expected_revision:1,idempotency_key:'invalid-array-enum',configuration};
  expect(validTeamConfiguration(configuration,true)).toBe(false);expect(validTeamSave(pending)).toBe(false);
  const journal=new DraftJournal(await memoryDraftStorage()({scope:'a'.repeat(64)}));await journal.load('team');
  const retained={kind:'team' as const,baseRevision:1,configuration:teamFixture().configuration,pending:null};
  await journal.persist('team',retained);
  await expect(journal.persist('team',{kind:'team',baseRevision:1,configuration,pending})).rejects.toMatchObject({code:'integrity'});
  expect(await journal.load('team')).toEqual(retained);journal.close();
});
it.each(['response_style','skills','blocked_capabilities'])('rejects array-coerced catalog %s',field=>{
  const catalog=structuredClone(actualSetup.catalog) as any;
  const slot=catalog.presets[1].slots[field==='skills'?1:0];
  slot[field]=field==='response_style'?[slot[field]]:[[field==='skills'?'calendar_availability':'model_answer']];
  expect(validPresetCatalog(catalog)).toBe(false);
});
it.each(['role','capability-state'])('rejects array-coerced provider template %s',field=>{
  const team=structuredClone(actualSetup.team) as any;
  if(field==='role')team.templates[0].role=[team.templates[0].role];
  else team.members[0].capabilities[0].state=[team.members[0].capabilities[0].state];
  expect(validProviderTeam(team)).toBe(false);
});
it.each([['runtime','key'],['account','key'],['account','state'],['scope','key'],['routine','status']])('rejects array-coerced readiness source %s.%s',(kind,field)=>{
  const setup=structuredClone(actualSetup.setup) as any;
  const source=setup.capabilities.flatMap((c:any)=>c.sources).find((s:any)=>s.kind===kind);
  source[field]=[source[field]];
  expect(validSetupProjection(setup,actualSetup.team.configuration as TeamConfiguration,actualSetup.team.revision)).toBe(false);
});
it('rejects array-coerced rehearsal results',()=>{
  const rehearsal=structuredClone(actualRehearsal) as any;rehearsal.cases[0].result=[rehearsal.cases[0].result];
  expect(validTeamRehearsal(rehearsal)).toBe(false);
});
it('adds all three groups once, reuses the original four coworkers and preserves stable identities and edits',()=>{
  const initial=teamFixture().configuration,original=structuredClone(initial),catalog=catalogFixture(),uuid=vi.fn(()=>teamUuid(1+uuid.mock.calls.length));
  let draft=applyPreset(initial,catalog,'front_desk',uuid);draft=applyPreset(draft,catalog,'practice_manager',uuid);
  expect(draft.bots).toHaveLength(9);expect(draft.bots.slice(0,4)).toEqual(original.bots);expect(initial).toEqual(original);
  expect(uuid).toHaveBeenCalledTimes(5);expect(new Set(draft.bots.slice(4).map(b=>b.instance_id)).size).toBe(5);
  expect(draft.presets?.find(p=>p.preset_id==='practice_manager')?.slots.chief).toBe('chief');
  draft.bots[4].name='My inbox';draft.bots[4].working_preferences='Invented preferences';
  expect(applyPreset(draft,catalog,'front_desk',uuid)).toBe(draft);expect(applyPreset(draft,catalog,'provider',uuid)).toBe(draft);
  expect(uuid).toHaveBeenCalledTimes(5);
});
it('refuses an entire group before allocating UUIDs when current or retained capacity cannot fit it',()=>{
  for(const retained of [false,true]){
    const draft=teamFixture().configuration;
    for(let i=0;i<(retained?94:6);i++)draft.bots.push({role:'custom',instance_id:teamUuid(i+1),name:'Invented',job_focus:'Review saved work',response_style:'brief',include_notebook:false,include_evidence:false,enabled:!retained,...(retained?{retired:true}:{})});
    const before=structuredClone(draft),uuid=vi.fn(()=>teamUuid(100));
    expect(()=>applyPreset(draft,catalogFixture(),'front_desk',uuid)).toThrow();expect(uuid).not.toHaveBeenCalled();expect(draft).toEqual(before);
  }
});
it('replaces only a previously saved retired slot with a fresh identity while retaining history',()=>{
  let n=1;const saved=applyPreset(teamFixture().configuration,catalogFixture(),'front_desk',()=>teamUuid(n++));
  const draft=structuredClone(saved),old=draft.bots[4].instance_id;draft.bots[4].retired=true;draft.bots[4].enabled=false;
  expect(()=>replacePresetSlot(draft,saved,catalogFixture(),'front_desk','inbox')).toThrow();
  const retired=structuredClone(draft);const replaced=replacePresetSlot(draft,retired,catalogFixture(),'front_desk','inbox',()=>teamUuid(40));
  expect(replaced.bots.find(b=>b.instance_id===old)).toEqual(retired.bots[4]);expect(replaced.presets![1].slots.inbox).toBe(teamUuid(40));
  expect(replaced.bots).toHaveLength(8);expect(()=>replacePresetSlot(replaced,retired,catalogFixture(),'front_desk','inbox')).toThrow();
});
it('normalizes Python whitespace, defaults and sorted restrictions without adding new empty fields to legacy configurations',async()=>{
  const config=teamFixture().configuration;config.practice_context='\u0085Invented 😀\u001c';config.bots[0].name='\u001fScribe\u0085';
  config.bots[0].blocked_capabilities=['practice_work_brief','model_answer'];config.bots[1].blocked_capabilities=[];
  const normalized=normalizeTeamConfiguration(config);
  expect(normalized.practice_context).toBe('Invented 😀');expect(normalized.bots[0].name).toBe('Scribe');
  expect(normalized.bots[0].blocked_capabilities).toEqual(['model_answer','practice_work_brief']);expect(normalized.bots[1]).not.toHaveProperty('blocked_capabilities');expect(normalized).not.toHaveProperty('presets');
  expect(await configurationHash(config)).toBe(await configurationHash(normalized));
  config.bots[0].name='\ud800';expect(validTeamConfiguration(config)).toBe(false);
  config.bots[0].name='😀'.repeat(40);expect(validTeamConfiguration(config)).toBe(true);config.bots[0].name+='😀';expect(validTeamConfiguration(config)).toBe(false);
});
it.each(['unknown-version','unknown-slot','foreign-bot','unknown-deny','duplicate-deny','missing-provider','unknown-field'])('rejects closed malformed preset configuration: %s',kind=>{
  let n=1;const config=applyPreset(teamFixture().configuration,catalogFixture(),'front_desk',()=>teamUuid(n++)) as any;
  if(kind==='unknown-version')config.presets[1].version=999;if(kind==='unknown-slot')config.presets[1].slots.other='chief';
  if(kind==='foreign-bot')config.presets[1].slots.inbox=teamUuid(300);if(kind==='unknown-deny')config.bots[0].blocked_capabilities=['send_email'];
  if(kind==='duplicate-deny')config.bots[0].blocked_capabilities=['model_answer','model_answer'];if(kind==='missing-provider')config.presets.shift();
  if(kind==='unknown-field')config.bot_team_authority='external';expect(validTeamConfiguration(config,true)).toBe(false);
});
it.each(['enabled-runtime-lie','missing-account','private-source','unknown-state','false-deny','unknown-capability','duplicated-capability'])('withholds malformed or misleading readiness: %s',kind=>{
  const setup=structuredClone(actualSetup.setup) as any;const row=setup.capabilities.find((c:any)=>c.capability==='model_answer');
  if(kind==='enabled-runtime-lie')row.state='available_for_scoped_request';if(kind==='missing-account')setup.capabilities.find((c:any)=>c.capability==='encounter_prep').sources.splice(1,1);
  if(kind==='private-source')row.sources[0].account_id='private';if(kind==='unknown-state')row.state='connected';
  if(kind==='false-deny')row.restricted=true;if(kind==='unknown-capability')row.capability='send_email';if(kind==='duplicated-capability')setup.capabilities.push(row);
  expect(validSetupProjection(setup,actualSetup.team.configuration as TeamConfiguration,actualSetup.team.revision)).toBe(false);
});
it('keeps incomplete editable draft fields but requires strict submitted requests and preserves exact legacy bytes through journal reopening',async()=>{
  const factory=memoryDraftStorage(),options={scope:'a'.repeat(64)};let journal=new DraftJournal(await factory(options));await journal.load('team');
  const team=teamFixture(),config=structuredClone(team.configuration);config.bots[0].name='';
  expect(validTeamConfiguration(config,true)).toBe(true);expect(validTeamConfiguration(config)).toBe(false);
  await journal.persist('team',{kind:'team',baseRevision:1,configuration:config,pending:null});journal.close();journal=new DraftJournal(await factory(options));
  expect((await journal.load('team') as TeamDraft).configuration).toEqual(config);
  const legacy=teamFixture().configuration;legacy.bots[0].job_focus='';legacy.bots[0].instance_id=null;
  const pending={expected_revision:1,idempotency_key:'exact-old-pending-key',configuration:legacy};const serialized=JSON.stringify(pending);
  expect(validTeamSave(pending)).toBe(true);const record=teamDraft({...team,revision:3},legacy,{type:'team',body:pending})!;
  expect(record.baseRevision).toBe(1);await journal.persist('team',record);journal.close();journal=new DraftJournal(await factory(options));
  const recovered=await journal.load('team') as TeamDraft;expect(JSON.stringify(recovered.pending)).toBe(serialized);expect(recovered.pending).not.toHaveProperty('setup_review');
  await expect(journal.persist('team',{...recovered,pending:{...pending,configuration:config},configuration:config})).rejects.toMatchObject({code:'integrity'});
  expect(JSON.stringify((await journal.load('team') as TeamDraft).pending)).toBe(serialized);journal.close();
});
it('retains new exact reviewed pending bodies while omitting ephemeral review checkbox and rehearsal state',async()=>{
  const config=actualRehearsal.configuration as TeamConfiguration,pending={expected_revision:actualRehearsal.expected_revision,idempotency_key:'exact-new-pending',configuration:config,setup_review:actualRehearsal.setup_review};
  const factory=memoryDraftStorage(),journal=new DraftJournal(await factory({scope:'a'.repeat(64)}));await journal.load('team');
  await journal.persist('team',{kind:'team',baseRevision:pending.expected_revision,configuration:config,pending:pending as any});
  const saved=await journal.load('team') as TeamDraft;expect(teamCanonical(saved.pending)).toBe(teamCanonical(pending));expect(Object.keys(saved).sort()).toEqual(['baseRevision','configuration','kind','pending']);journal.close();
});
it('requires review for new presets, added or removed denials, while ordinary editable preferences keep their legacy path',()=>{
  const original=teamFixture().configuration,next=structuredClone(original);next.bots[0].name='Changed';expect(setupChange(original,next)).toBe(false);
  next.bots[0].blocked_capabilities=['model_answer'];expect(setupChange(original,next)).toBe(true);expect(setupChange(next,original)).toBe(true);
});
