import {beforeEach,afterEach,it,expect,vi} from 'vitest';
import actual from './__fixtures__/inbox-analysis-w87.json';
import {inboxFixture} from './inbox-test-fixture';
import {inboxDraftSelection,validInboxAnalysis} from './inbox-analysis-contract';
import {validConversation,conversationFromEntry,validModelWorkspace,modelRequestHash} from './model-work-request';
import {validPresetCatalog,validProviderTeam,validSetupProjection} from './team-setup-validators';
import {applyPreset,upgradeInboxPreset,setupChange} from './team-setup-request';
import type {ConversationInput,Workspace,ProviderTeam} from './workspace-api';
import type {PresetCatalog} from './team-setup-request';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
beforeEach(()=>vi.stubGlobal('crypto',webcrypto));afterEach(()=>vi.unstubAllGlobals());
it('accepts actual local API responses and reconstructs the exact saved Inbox request',async()=>{
  expect(validPresetCatalog(actual.setup.catalog)).toBe(true);expect(validProviderTeam(actual.setup.team)).toBe(true);
  expect(validSetupProjection(actual.setup.setup,actual.setup.team.configuration as ProviderTeam['configuration'],actual.setup.team.revision)).toBe(true);
  expect(validConversation(actual.request)).toBe(true);expect(await validModelWorkspace(actual.workspace,actual.workspace.id)).toBe(true);
  const entry=(actual.workspace as Workspace).entries.find(e=>e.model_request)!;
  expect(conversationFromEntry(entry)).toEqual(actual.request);
  expect(await modelRequestHash(actual.request as ConversationInput)).toBe(entry.model_request!.request_sha256);
});
it('selects only a current administrative message and keeps consent separate',async()=>{
  const bundle=await inboxFixture('triaged');const selected=inboxDraftSelection(bundle);expect(selected).not.toBeNull();
  expect('consented' in selected!.analysis).toBe(false);expect(validInboxAnalysis({...selected!.analysis,consented:true})).toBe(true);
  for(const stage of ['initial','reviewed','result','closed','unavailable'] as const)expect(inboxDraftSelection(await inboxFixture(stage))).toBeNull();
  const changed=structuredClone(bundle);changed.detail.summary.classification='urgent_human_review';expect(inboxDraftSelection(changed)).toBeNull();
  changed.detail.summary.classification='administrative_review';changed.detail.summary.workspace_current=false;expect(inboxDraftSelection(changed)).toBeNull();
});
it('keeps null, foreign fields, double-source and changed retry selections out of the model contract',async()=>{
  const body=actual.request as ConversationInput;expect(validConversation({...body,inbox_analysis:null})).toBe(false);
  expect(validConversation({...body,inbox_analysis:{...body.inbox_analysis,consented:false}})).toBe(false);
  expect(validConversation({...body,research_analysis:null})).toBe(false);
  expect(validConversation({...body,inbox_analysis:{...body.inbox_analysis,source_text:'injected'}})).toBe(false);
  expect(await modelRequestHash({...body,inbox_analysis:{...body.inbox_analysis!,item_version:body.inbox_analysis!.item_version+1}})).not.toBe(await modelRequestHash(body));
});
it('upgrades Front Desk deliberately while retaining existing identity, owner settings and restrictions',()=>{
  const catalog=actual.setup.catalog as PresetCatalog;
  const base=structuredClone(actual.setup.team.configuration) as ProviderTeam['configuration'];
  base.bots=base.bots.filter(b=>!b.instance_id);delete base.model_work;
  const installed=applyPreset(base,catalog,'front_desk');const binding=installed.presets!.find(p=>p.preset_id==='front_desk')!;
  const bot=installed.bots.find(b=>b.instance_id===binding.slots.inbox)!;
  expect(binding.version).toBe(2);expect(bot.skills).toEqual(['inbox_review']);expect(bot.include_notebook).toBe(false);
  binding.version=1;bot.skills=[];bot.enabled=false;bot.name='My named Inbox';bot.blocked_capabilities=['model_answer'];bot.working_preferences='Keep my preferences';
  const before=structuredClone(installed),upgraded=upgradeInboxPreset(installed,catalog),current=upgraded.bots.find(b=>b.instance_id===bot.instance_id)!;
  expect(installed).toEqual(before);expect(current).toEqual({...bot,enabled:true,skills:['inbox_review']});expect(setupChange(before,upgraded)).toBe(true);
  expect(upgraded.bots.map(b=>b.instance_id??b.role)).toEqual(before.bots.map(b=>b.instance_id??b.role));
});
