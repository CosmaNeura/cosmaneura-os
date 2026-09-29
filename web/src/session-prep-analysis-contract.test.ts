import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import actual from './__fixtures__/session-prep-chat.json';
import {sessionPrepAnalysis,validSessionPrepAnalysis} from './session-prep-analysis-contract';
import {conversationFromEntry,modelCanonical,modelRequestHash,validConversation,validModelWorkspace} from './model-work-request';
import {sessionPrepFixture} from './test-fixtures/session-prep';
import type {Workspace,ConversationInput} from './workspace-api';
const {webcrypto,createHash}=await vi.importActual<{webcrypto:Crypto;createHash:(algorithm:string)=>{update:(value:string)=>{digest:(format:string)=>string}}}>('node:crypto');
beforeEach(()=>vi.stubGlobal('crypto',webcrypto));afterEach(()=>vi.unstubAllGlobals());

it('accepts actual signed API output and recovers the exact selected request',async()=>{
  expect(validConversation(actual.request)).toBe(true);
  expect(await modelRequestHash(actual.request as ConversationInput)).toBe(actual.observation.request_sha256);
  expect(await validModelWorkspace(actual.workspace,actual.workspace.id)).toBe(true);
  expect(conversationFromEntry((actual.workspace as Workspace).entries.at(-1)!)).toEqual(actual.request);
  const omitted=structuredClone(actual.workspace);
  delete (omitted.entries.at(-1)!.model_request!.request as Partial<typeof actual.request>).session_prep_analysis;
  expect(await validModelWorkspace(omitted,omitted.id)).toBe(false);
});

it('fingerprints the exact Unicode display, including freshness and source provenance',async()=>{
  const value=sessionPrepFixture();value.prepared_brief!.recap.text='Invented café 🩺';
  const selection=await sessionPrepAnalysis(value);
  expect(selection.snapshot_sha256).toBe(createHash('sha256').update(modelCanonical(value)).digest('hex'));
  expect(JSON.stringify(selection)).not.toContain('Invented');
  const changed=structuredClone(value);changed.completeness='partial';
  expect(await sessionPrepAnalysis(changed)).not.toEqual(selection);
});

it('rejects implicit consent, null, mixed selections and client clinical text',()=>{
  const selected=actual.request.session_prep_analysis;
  for(const patch of [{consented:false},{consented:1},{version:true},{brief_version:'1'},{brief_version:2147483648},{clinical_text:'forged'}])
    expect(validSessionPrepAnalysis({...selected,...patch})).toBe(false);
  for(const patch of [{session_prep_analysis:null},{inbox_analysis:null},{research_analysis:null},{membership_analysis:null}])
    expect(validConversation({...actual.request,...patch})).toBe(false);
});
