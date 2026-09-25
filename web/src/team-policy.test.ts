import {beforeEach,afterEach,expect,it,vi} from 'vitest';
import {configurationHash,normalizeTeamConfiguration,setupChange,validTeamConfiguration,validTeamSave} from './team-setup-request';
import {validModelUsage,validResourceInventory,validSetupProjection,validTeamRehearsal} from './team-setup-validators';
import {policyRehearsalFixture,policySetupFixture,resourcesFixture,usageFixture} from './team-policy-test-fixture';
import {teamFixture} from './team-setup-test-fixture';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
beforeEach(()=>vi.stubGlobal('crypto',webcrypto));afterEach(()=>vi.unstubAllGlobals());
it('preserves absent legacy fields and distinguishes zero, empty deny list and explicit removal in hashes and review',async()=>{
 const original=teamFixture().configuration,restricted=structuredClone(original);restricted.model_work={version:1,max_attempts_per_24h:0};restricted.bots[0].resources={version:1,allowed:[]};
 const normalized=normalizeTeamConfiguration(restricted);expect(normalized.model_work?.max_attempts_per_24h).toBe(0);expect(normalized.bots[0].resources?.allowed).toEqual([]);
 expect(normalizeTeamConfiguration(original)).not.toHaveProperty('model_work');expect(normalizeTeamConfiguration(original).bots[0]).not.toHaveProperty('resources');
 expect(await configurationHash(original)).not.toBe(await configurationHash(restricted));expect(setupChange(original,restricted)).toBe(true);expect(setupChange(restricted,original)).toBe(true);
 const ordinary=structuredClone(restricted);ordinary.bots[0].name='Renamed';expect(setupChange(restricted,ordinary)).toBe(false);
});
it.each([null,{version:1,max_attempts_per_24h:-1},{version:1,max_attempts_per_24h:1001},{version:1,max_attempts_per_24h:1.5},{version:1,max_attempts_per_24h:'0'},{version:1,max_attempts_per_24h:0,grant:true}])('rejects malformed attempt policy %j',model_work=>{
 expect(validTeamConfiguration({...teamFixture().configuration,model_work})).toBe(false);
});
it.each([null,{version:1,allowed:[{purpose:['core_preparation'],resource_ref:'d'.repeat(64)}]},{version:1,allowed:[{purpose:'core_preparation',resource_ref:'d'.repeat(64),account:'private'}]},{version:1,allowed:[{purpose:'capture',resource_ref:'d'.repeat(64)}]},{version:1,allowed:[{purpose:'core_preparation',resource_ref:'d'.repeat(64)},{purpose:'core_preparation',resource_ref:'e'.repeat(64)}]}])('rejects malformed or broadened source policy %j',resources=>{
 const c=teamFixture().configuration;(c.bots[0] as any).resources=resources;expect(validTeamConfiguration(c)).toBe(false);
});
it('normalizes binding order but retains an unavailable exact saved opaque binding',()=>{
 const c=teamFixture().configuration;c.bots[0].resources={version:1,allowed:[{purpose:'scheduling_context',resource_ref:'f'.repeat(64)},{purpose:'core_preparation',resource_ref:'d'.repeat(64)}]};
 expect(normalizeTeamConfiguration(c).bots[0].resources?.allowed.map(b=>b.purpose)).toEqual(['core_preparation','scheduling_context']);expect(normalizeTeamConfiguration(c).bots[0].resources?.allowed[1].resource_ref).toBe('f'.repeat(64));
});
it('requires v2 for new policy review and projection while old exact save requests remain valid',async()=>{
 const config=teamFixture().configuration,setup=await policySetupFixture(config),body={expected_revision:1,idempotency_key:'legacy-request-key',configuration:config,setup_review:{catalog_version:1 as const,configuration_sha256:setup.setup.configuration_sha256,prerequisites_sha256:setup.setup.prerequisites_sha256}};
 expect(validTeamSave(body)).toBe(true);config.model_work={version:1,max_attempts_per_24h:0};expect(validTeamSave(body)).toBe(false);expect(validTeamSave({...body,setup_review:{...body.setup_review,catalog_version:2}})).toBe(true);
 expect(validSetupProjection({...setup.setup,contract_version:1,catalog_version:1},config,1)).toBe(false);
});
it('keeps policy readiness separate from direct denials and enforces precedence, source order and all rehearsal cases',async()=>{
 const c=teamFixture().configuration;c.model_work={version:1,max_attempts_per_24h:0};c.bots[0].resources={version:1,allowed:[]};
 const rehearsal=await policyRehearsalFixture(c);rehearsal.setup.capabilities.push({bot:'scribe',capability:'encounter_prep',selected:true,restricted:false,state:'resource_restricted',explanation:'Invented denied source.',sources:[{kind:'runtime',key:'prep',enabled:true},{kind:'account',key:'core',state:'reviewed'},{kind:'scope',key:'encounter',required:true},{kind:'resource',purpose:'core_preparation',mode:'allow_list',selection:'denied',inventory_sha256:resourcesFixture.inventory_sha256}]});expect(validTeamRehearsal(rehearsal)).toBe(true);expect(rehearsal.cases).toHaveLength(12);
 const model=rehearsal.setup.capabilities.find(r=>r.bot==='scribe'&&r.capability==='model_answer')!;expect(model).toMatchObject({restricted:false,state:'work_limit_reached'});
 const prep=rehearsal.setup.capabilities.find(r=>r.bot==='scribe'&&r.capability==='encounter_prep')!;expect(prep).toMatchObject({restricted:false,state:'resource_restricted'});
 const denied=structuredClone(rehearsal);denied.setup.capabilities.find(r=>r.bot==='scribe'&&r.capability==='encounter_prep')!.restricted=true;expect(validTeamRehearsal(denied)).toBe(false);
 const reordered=structuredClone(rehearsal);reordered.setup.capabilities.find(r=>r.bot==='scribe'&&r.capability==='encounter_prep')!.sources.reverse();expect(validTeamRehearsal(reordered)).toBe(false);
 const omitted=structuredClone(rehearsal);omitted.cases.pop();expect(validTeamRehearsal(omitted)).toBe(false);
 const wrongBot=structuredClone(rehearsal);wrongBot.cases.at(-1)!.bot='scribe';expect(validTeamRehearsal(wrongBot)).toBe(false);
});
it('rejects private inventory fields and wrong labels or repeated purposes',()=>{
 expect(validResourceInventory(resourcesFixture)).toBe(true);expect(validResourceInventory({...resourcesFixture,resources:[]})).toBe(true);
 for(const resources of [[{...resourcesFixture.resources[0],patient_id:'private'}],[{...resourcesFixture.resources[0],label:'Actual account'}],[resourcesFixture.resources[0],resourcesFixture.resources[0]]])expect(validResourceInventory({...resourcesFixture,resources})).toBe(false);
});
it('counts the occupied union once, preserves unknown usage and refuses contradictory allowance observations',()=>{
 const partial={...usageFixture,policy:{version:1 as const,max_attempts_per_24h:5},admitted_units:3,pending_units:2,occupied_units:4,remaining_units:1,unknown_units:1,usage_complete:false,verified_input_tokens:null,verified_output_tokens:null};
 expect(validModelUsage(partial)).toBe(true);expect(validModelUsage({...partial,occupied_units:6,remaining_units:0})).toBe(false);expect(validModelUsage({...partial,remaining_units:2})).toBe(false);
 expect(validModelUsage({...partial,usage_complete:true})).toBe(false);expect(validModelUsage({...partial,verified_input_tokens:0})).toBe(false);expect(validModelUsage({...partial,as_of:'2026-02-30T00:00:00Z'})).toBe(false);
});
