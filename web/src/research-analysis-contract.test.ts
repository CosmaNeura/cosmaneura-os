import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {validResearchAnalysis,validResearchAnchor,researchPacketSize,selectedResearchPacket} from './research-analysis-contract';
import {analysisAnchor,analysisBody,analysisProjection,analysisSelection,analysisWorkspace} from './research-analysis-test-fixture';
import {conversationFromEntry,exactModelObservation,modelRequestHash,validConversation,validModelWorkspace} from './model-work-request';
import {modelReceipt,modelUuid} from './model-work-test-fixture';
import {validateResearchDraft} from './research-contract';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
beforeEach(()=>vi.stubGlobal('crypto',webcrypto));afterEach(()=>vi.unstubAllGlobals());
it('closes consent and anchor contracts without widening old absent selections',()=>{
 expect(validResearchAnalysis(analysisSelection)).toBe(true);expect(validConversation(analysisBody)).toBe(true);
 for(const selection of [null,undefined,{...analysisSelection,consented:1},{...analysisSelection,version:true},{...analysisSelection,extra:true},{...analysisSelection,entries:[]},{...analysisSelection,entries:[analysisAnchor,analysisAnchor]},{...analysisSelection,entries:[{...analysisAnchor,entry_revision:501}]},{...analysisSelection,entries:[{...analysisAnchor,entry_revision:'3'}]}])expect(validConversation({...analysisBody,research_analysis:selection}),JSON.stringify(selection)).toBe(false);
 for(const anchor of [{...analysisAnchor,extra:1},{...analysisAnchor,run_id:'wrong'},{...analysisAnchor,entry_revision:0},{...analysisAnchor,save_request_sha256:'b'.repeat(63)}])expect(validResearchAnchor(anchor)).toBe(false);
 const {research_analysis:_,...legacy}=analysisBody;expect(validConversation(legacy)).toBe(true);expect(JSON.stringify(legacy)).not.toContain('research_analysis');
});
it('binds immutable ordered selections to model receipts and refuses omitted or changed anchors',async()=>{
 const receipt=await modelReceipt(analysisBody),operation={type:'ask' as const,body:analysisBody};expect(await exactModelObservation(receipt,modelUuid(71),operation)).toBe(true);
 const {research_analysis:_,...without}=analysisBody;
 for(const body of [without,{...analysisBody,research_analysis:{...analysisSelection,entries:[{...analysisAnchor,save_request_sha256:'b'.repeat(64)}]}}])expect(await exactModelObservation(receipt,modelUuid(71),{...operation,body})).toBe(false);
 const next={...analysisAnchor,entry_id:modelUuid(76)},one={...analysisBody,research_analysis:{...analysisSelection,entries:[analysisAnchor,next]}},two={...one,research_analysis:{...analysisSelection,entries:[next,analysisAnchor]}};
 expect(await modelRequestHash(one)).not.toBe(await modelRequestHash(two));
});
it('reconstructs the exact second-device selection and rejects altered or omitted projection metadata',async()=>{
 const workspace=await analysisProjection();expect(await validModelWorkspace(workspace,workspace.id)).toBe(true);expect(conversationFromEntry(workspace.entries[0])).toEqual(analysisBody);
 const altered=structuredClone(workspace),request=altered.entries[0].model_request!.request;if(request.kind!=='conversation')throw new Error();delete request.research_analysis;expect(await validModelWorkspace(altered,altered.id)).toBe(false);
 const changed=structuredClone(workspace);changed.entries[0].model_request!.bot.role='scribe';expect(await validModelWorkspace(changed,changed.id)).toBe(false);
});
it('counts Unicode scalar characters and UTF8 bytes without silently shortening packets',()=>{
 expect(researchPacketSize([{content:'😀'.repeat(5000)}])).toBe('ready');expect(researchPacketSize([{content:'a'.repeat(5001)}])).toBe('too_large');
 expect(researchPacketSize([{content:'😀'.repeat(5000)},{content:'😀'.repeat(5000)}])).toBe('too_large');expect(researchPacketSize([{content:'a'.repeat(5000)},{content:'b'.repeat(5000)},{content:'c'.repeat(5000)}])).toBe('ready');expect(researchPacketSize([])).toBe('unavailable');
 const workspace=analysisWorkspace();expect(selectedResearchPacket(workspace,analysisAnchor)?.content).toBe(workspace.entries[0].content);expect(selectedResearchPacket(workspace,{...analysisAnchor,entry_revision:2})).toBeNull();expect(selectedResearchPacket({...workspace,entries:[workspace.entries[0],workspace.entries[0]]},analysisAnchor)).toBeNull();
});
it('retains the current saved anchor and unsent reviewed choice without granting consent',()=>{
 const draft={version:1,bot:modelUuid(72),topic:'literature',query:'',sources:[],pending:null,saved_packet:analysisAnchor,analysis_draft:{question:'Question retained',selected:true}};
 expect(validateResearchDraft(draft,modelUuid(72))).toEqual(draft);expect(()=>validateResearchDraft({...draft,saved_packet:{...analysisAnchor,save_request_sha256:'wrong'}},modelUuid(72))).toThrow();expect(()=>validateResearchDraft({...draft,analysis_draft:{...draft.analysis_draft,consented:true}},modelUuid(72))).toThrow();
});
import backendSamples from './__fixtures__/research-analysis-normalization.json';
it.each(backendSamples.cases)('matches actual backend selection validation and immutable digest: $case',async sample=>{
 expect(validConversation(sample.request)).toBe(sample.accepted);if(!sample.accepted)return;
 if(!validConversation(sample.request))throw new Error('Expected accepted backend fixture');expect(await modelRequestHash(sample.request)).toBe(sample.request_sha256);
});
