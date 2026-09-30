import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {validResearchAnalysis,validResearchAnchor,researchPacketSize,selectedResearchPacket,researchSavedText,researchAnalysisText,researchAnalysisPreview} from './research-analysis-contract';
import {analysisAnchor,analysisBody,analysisProjection,analysisSelection,analysisWorkspace,analysisProofFixture} from './research-analysis-test-fixture';
import {conversationFromEntry,exactModelObservation,modelRequestHash,validConversation,validModelWorkspace} from './model-work-request';
import {modelReceipt,modelUuid} from './model-work-test-fixture';
import {researchDigest,validateResearchDraft} from './research-contract';
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
import previewSamples from './__fixtures__/research-analysis-preview.json';
import type {ResearchResult} from './research-contract';
it.each(backendSamples.cases)('matches actual backend selection validation and immutable digest: $case',async sample=>{
 expect(validConversation(sample.request)).toBe(sample.accepted);if(!sample.accepted)return;
 if(!validConversation(sample.request))throw new Error('Expected accepted backend fixture');expect(await modelRequestHash(sample.request)).toBe(sample.request_sha256);
});
it.each(previewSamples.cases)('matches backend saved text, complete model text and bounds: $name',async sample=>{
 const records=sample.records as ResearchResult[],proof=await analysisProofFixture(records);
 expect(researchSavedText(records)).toBe(sample.saved_text);expect(researchAnalysisText(records)).toBe(sample.analysis_text);
 const content=await researchAnalysisPreview(proof.workspace,proof.anchor,proof.run,proof.saved,analysisBody.role);
 expect(content).toBe(sample.analysis_text);expect([...content!]).toHaveLength(sample.characters);expect(new TextEncoder().encode(content!).length).toBe(sample.utf8_bytes);
 expect(researchPacketSize([{content:content!}])).toBe(sample.size);expect(proof.workspace.entries[0].content).toBe(sample.saved_text);
});
it.each(['missing_run','missing_save','workspace','bot','run','save_hash','entry','revision','source_label','entry_text','record_metadata','record_hash','selected_hash','duplicate_hash','source_order','unfinished'] as const)('withholds model preview for missing or changed proof: %s',async change=>{
 const proof=await analysisProofFixture(previewSamples.cases.find(sample=>sample.name==='mixed_ordered')!.records as ResearchResult[]);
 let run:typeof proof.run|null=proof.run,saved:typeof proof.saved|null=proof.saved;
 if(change==='missing_run')run=null;else if(change==='missing_save')saved=null;
 else if(change==='workspace')proof.run.workspace_id=modelUuid(999);
 else if(change==='bot')proof.run.bot=modelUuid(998);
 else if(change==='run')proof.run.run_id=modelUuid(997);
 else if(change==='save_hash')proof.anchor.save_request_sha256='f'.repeat(64);
 else if(change==='entry')proof.saved.entry_id=modelUuid(996);
 else if(change==='revision')proof.anchor.entry_revision=2;
 else if(change==='source_label')proof.workspace.entries[0].source_label='Ordinary evidence';
 else if(change==='entry_text')proof.workspace.entries[0].content+='Changed';
 else if(change==='record_metadata')proof.run.results[0].fields[0].text='UNVERIFIED METADATA';
 else if(change==='record_hash')proof.run.results[0].sha256='e'.repeat(64);
 else if(change==='selected_hash')proof.saved.request.source_hashes[0]='d'.repeat(64);
 else if(change==='duplicate_hash')proof.saved.request.source_hashes.push(proof.saved.request.source_hashes[0]);
 else if(change==='source_order')proof.saved.request.source_hashes.reverse();
 else proof.run.state='running';
 if(change==='source_order'||change==='selected_hash'){proof.saved.request_sha256=await researchDigest(proof.saved.request);proof.anchor.save_request_sha256=proof.saved.request_sha256;}
 expect(await researchAnalysisPreview(proof.workspace,proof.anchor,run,saved,analysisBody.role)).toBeNull();
});
it('excludes unselected retained records and all unrelated workspace text',async()=>{
 const proof=await analysisProofFixture(),expected=researchAnalysisText(proof.run.results);
 proof.run.results.push(...structuredClone(previewSamples.cases.find(sample=>sample.name==='legacy_ordered')!.records.filter(record=>record.id!==proof.run.results[0].id)) as ResearchResult[]);
 proof.workspace.entries.push({...proof.workspace.entries[0],id:modelUuid(995),kind:'scratchpad',content:'PRIVATE NOTE MUST NOT ENTER PREVIEW'});
 expect(await researchAnalysisPreview(proof.workspace,proof.anchor,proof.run,proof.saved,analysisBody.role)).toBe(expected);
});
