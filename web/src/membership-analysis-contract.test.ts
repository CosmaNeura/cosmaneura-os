import {beforeEach,afterEach,it,expect,vi} from 'vitest';
import membership from './__fixtures__/membership-analysis-w88.json';
import payment from './__fixtures__/payment-analysis-w88.json';
import {membershipReviewSelection,MembershipSelectionTooLargeError,membershipSnapshot,paymentSnapshot} from './membership-analysis-contract';
import {modelRequestHash,validConversation,validModelWorkspace} from './model-work-request';
import {validProviderTeam,validPresetCatalog,validSetupProjection} from './team-setup-validators';
import {applyPreset,upgradeMembershipPreset,setupChange,type PresetCatalog} from './team-setup-request';
import {teamFixture,catalogFixture} from './team-setup-test-fixture';
import type {Detail} from './membership-schema';
import type {FinanceDetail} from './finance-schema';
import type {ConversationInput,TeamConfiguration} from './workspace-api';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
beforeEach(()=>vi.stubGlobal('crypto',webcrypto));afterEach(()=>vi.unstubAllGlobals());

for(const [kind,fixture] of [['membership',membership],['payment',payment]] as const)it(`${kind} selection matches actual application snapshots, hashes and saved recovery`,async()=>{
  const d=fixture.detail as Detail|FinanceDetail;
  expect(kind==='membership'?membershipSnapshot(d as Detail):paymentSnapshot(d as FinanceDetail)).toEqual(fixture.snapshot);
  const selected=await membershipReviewSelection(kind,d,fixture.workspace.id,fixture.request.expected_revision);
  expect({...selected.analysis,consented:true}).toEqual(fixture.request.membership_analysis);
  const body=fixture.request as ConversationInput;
  expect(validConversation(body)).toBe(true);expect(await validModelWorkspace(fixture.workspace,fixture.workspace.id)).toBe(true);
  const entry=fixture.workspace.entries.find(e=>'model_request' in e)!;
  expect(await modelRequestHash(body)).toBe((entry as {model_request:{request_sha256:string}}).model_request.request_sha256);
  expect(validProviderTeam(fixture.setup.team)).toBe(true);expect(validPresetCatalog(fixture.setup.catalog)).toBe(true);
  expect(validSetupProjection(fixture.setup.setup,fixture.setup.team.configuration as TeamConfiguration,fixture.setup.team.revision)).toBe(true);
  for(const patch of [{membership_analysis:null},{membership_analysis:{...body.membership_analysis,consented:false}},{inbox_analysis:null},{research_analysis:null}])expect(validConversation({...body,...patch})).toBe(false);
});

it('explicit Practice Manager upgrade preserves identities/preferences and needs review',()=>{
  const base=applyPreset(teamFixture().configuration,catalogFixture(),'practice_manager');
  const binding=base.presets!.find(p=>p.preset_id==='practice_manager')!,bot=base.bots.find(b=>b.instance_id===binding.slots.membership_billing)!;
  bot.name='My membership coworker';bot.working_preferences='Ask the manager about exceptions';bot.blocked_capabilities=['model_answer'];
  const upgraded=upgradeMembershipPreset(base,membership.setup.catalog as PresetCatalog),next=upgraded.bots.find(b=>b.instance_id===bot.instance_id)!;
  expect(next).toMatchObject({name:bot.name,working_preferences:bot.working_preferences,blocked_capabilities:bot.blocked_capabilities,skills:['membership_review'],enabled:true});
  expect(upgraded.presets!.find(p=>p.preset_id==='practice_manager')!.slots).toEqual(binding.slots);
  expect(setupChange(base,upgraded)).toBe(true);expect(base.presets!.find(p=>p.preset_id==='practice_manager')!.version).toBe(1);
  bot.retired=true;expect(()=>upgradeMembershipPreset(base,membership.setup.catalog as PresetCatalog)).toThrow('retired');
});

it('manual ledger projection excludes vendor/document references and keeps evidence limits',()=>{
  const d=structuredClone(membership.detail) as Detail;
  d.latest_result!.request.ledger={source_label:'PRIVATE LEDGER LABEL',system_kind:'practice_owned_ledger',record_reference:'PRIVATE_REFERENCE',observed_at:'2026-09-24T10:00:00Z',document:{artifact_id:crypto.randomUUID(),sha256:'a'.repeat(64),byte_length:10,media_type:'application/pdf'},observed_membership_state:'active',observed_billing_state:'current',reviewed_record_matches_patient:true,reviewed_document:true};
  const snapshot=membershipSnapshot(d),serialized=JSON.stringify(snapshot);
  expect(serialized).not.toContain('PRIVATE');expect(snapshot.data.ledger_observation?.authority).toBe('human_recorded_not_independent_service_verification');
  expect(snapshot.data.status.external_service_verified).toBe(false);
});

it('refuses oversized selected text without silently truncating the evidence',async()=>{
 const d=structuredClone(membership.detail) as Detail;d.review.proposal.instructions='x'.repeat(5001);
 await expect(membershipReviewSelection('membership',d,membership.workspace.id,3)).rejects.toBeInstanceOf(MembershipSelectionTooLargeError);
});
