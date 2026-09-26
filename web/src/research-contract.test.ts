import {beforeEach,afterEach,expect,it,vi} from 'vitest';
import {researchDigest,validateResearchCatalog,validResearchSearch,validResearchSave,validateResearchObservation,validateResearchHistory,validateResearchSaved,validateResearchSavedHistory,validateResearchDraft,type ResearchDraft} from './research-contract';
import {researchCatalog,researchRequest,researchObservation,researchWorkspaceId,researchBotId,researchRunId,researchSaved,researchSavedPacket} from './research-test-fixture';
import {DraftJournal,editorAddress} from './draft-journal';
import {editorDraft} from './editor-recovery';
import {memoryDraftStorage} from './draft-test-fixture';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
beforeEach(()=>vi.stubGlobal('crypto',webcrypto));afterEach(()=>vi.unstubAllGlobals());
it('verifies saved packet history ownership, exact receipts, descending revisions and page bounds',async()=>{
 const packets=await Promise.all([600,4,2].map(researchSavedPacket)),value={contract:'research.saved_history.v1',workspace_id:researchWorkspaceId,bot:researchBotId,packets};
 expect(await validateResearchSavedHistory(value,researchWorkspaceId,researchBotId)).toEqual(value);
 for(const changed of [
  {...value,workspace_id:researchRunId},{...value,bot:researchRunId},{...value,extra:true},
  {...value,packets:[...packets].reverse()},{...value,packets:[packets[0],packets[0]]},{...value,packets:Array(6).fill(packets[0])},
  {...value,packets:[{...packets[0],saved:{...packets[0].saved,request_sha256:'b'.repeat(64)}}]},
  {...value,packets:[{...packets[0],saved:{...packets[0].saved,workspace_id:researchRunId}}]},
 ])await expect(validateResearchSavedHistory(changed,researchWorkspaceId,researchBotId)).rejects.toThrow();
});
it('binds UTF8 search authority and source provenance to exact immutable hashes',async()=>{
 const request={...researchRequest(),query:'β-blockers: résumé'},observation=await researchObservation(request);
 expect((await validateResearchObservation(observation,researchWorkspaceId,request)).request).toEqual(request);
 expect(await researchDigest({b:'β',a:1})).toBe('f5b67e0a56a48eb004e359e07bde1af98e2c0922c3adca0fb25ca7964c95cebb');
 for(const modified of [{...observation,workspace_id:researchBotId},{...observation,request_sha256:'b'.repeat(64)},{...observation,query:'another question'},{...observation,results:[{...observation.results[0],excerpt:'changed source'}]},{...observation,results:[{...observation.results[0],url:'https://example.com/'}]}])await expect(validateResearchObservation(modified,researchWorkspaceId,request)).rejects.toThrow();
});
it('uses the exact Research key alphabet and 8 through 100 length for search, save and retained commands',()=>{
 const save={contract_version:1 as const,idempotency_key:'research:key-8',expected_revision:2,source_hashes:['a'.repeat(64)]};
 for(const key of ['a'.repeat(8),'A:_-09bc','a'.repeat(100)]){expect(validResearchSearch({...researchRequest(),idempotency_key:key})).toBe(true);expect(validResearchSave({...save,idempotency_key:key})).toBe(true);}
 for(const key of ['a'.repeat(7),'a'.repeat(101),'a'.repeat(255),'research.key','invalid key']){
  const request={...researchRequest(),idempotency_key:key};expect(validResearchSearch(request)).toBe(false);expect(validResearchSave({...save,idempotency_key:key})).toBe(false);
  expect(()=>validateResearchDraft({version:1,bot:researchBotId,topic:request.topic,query:request.query,sources:request.sources,pending:{kind:'search',request}},researchBotId)).toThrow();
 }
});
it('matches Python query whitespace without deleting BOM and still rejects C0 and DEL',()=>{
 for(const query of ['\ufeffGeneral public question','General\ufeff question','General public question'])expect(validResearchSearch({...researchRequest(),query})).toBe(true);
 for(const query of ['\u0085General public question','General public question\u0085','\u00a0General public question','\u001cGeneral question','General\tquestion','General\nquestion','General\u007fquestion'])expect(validResearchSearch({...researchRequest(),query})).toBe(false);
});
it('accepts only an exact single-revision evidence receipt',async()=>{
 const request={contract_version:1 as const,idempotency_key:researchRunId,expected_revision:2,source_hashes:['a'.repeat(64)]},saved=await researchSaved(request);
 expect(await validateResearchSaved(saved,researchWorkspaceId,researchRunId,request)).toEqual(saved);
 for(const entry_revision of [1,2,4,100])await expect(validateResearchSaved({...saved,entry_revision},researchWorkspaceId,researchRunId,request)).rejects.toThrow();
});
it('refuses whitespace-only non-null metadata and duplicate source identity even with different valid content hashes',async()=>{
 const observation=await researchObservation();
 for(const field of ['version','source_updated_at'] as const)for(const blank of [' ','\u0085','\u00a0\t']){
  const record={...observation.results[0],[field]:blank};const {sha256:_,...content}=record;record.sha256=await researchDigest(content);
  await expect(validateResearchObservation({...observation,results:[record]},researchWorkspaceId)).rejects.toThrow();
 }
 const record={...observation.results[0],title:'A different title for the same source version'};const {sha256:_,...content}=record;record.sha256=await researchDigest(content);
 await expect(validateResearchObservation({...observation,results:[observation.results[0],record]},researchWorkspaceId)).rejects.toThrow();
 const nextVersion={...record,version:'next version'};const {sha256:__,...changed}=nextVersion;nextVersion.sha256=await researchDigest(changed);
 expect(await validateResearchObservation({...observation,results:[observation.results[0],nextVersion]},researchWorkspaceId)).toMatchObject({results:[observation.results[0],nextVersion]});
});
it('rejects rootless, fragment and normalized authority citations while accepting exact source paths',async()=>{
 const observation=await researchObservation();
 const verify=async(url:string)=>{const result={...observation.results[0],url};const {sha256:_,...body}=result;result.sha256=await researchDigest(body);return validateResearchObservation({...observation,results:[result]},researchWorkspaceId);};
 for(const url of ['https://pubmed.ncbi.nlm.nih.gov','https://pubmed.ncbi.nlm.nih.gov/12345/#','https://PUBMED.NCBI.NLM.NIH.GOV/12345/','https://pubmed.ncbi.nlm.nih.gov:443/12345/','https://pubmed.ncbi.nlm.nih.gov/12345/\u0085','https://pubmed.ncbi.nlm.nih.gov/12345/\ud800'])await expect(verify(url),url).rejects.toThrow();
 for(const url of ['https://pubmed.ncbi.nlm.nih.gov/','https://pubmed.ncbi.nlm.nih.gov/12345/?term=notes%23x','https://pubmed.ncbi.nlm.nih.gov/12345/?term=notes\ufeffx'])expect((await verify(url)).results[0].url).toBe(url);
});
it('retains strict explicit ISO retrieval time with valid calendar, clock and offset ranges',async()=>{
 const observation=await researchObservation();
 const verify=async(retrieved_at:string)=>{const result={...observation.results[0],retrieved_at};const {sha256:_,...body}=result;result.sha256=await researchDigest(body);return validateResearchObservation({...observation,results:[result]},researchWorkspaceId);};
 for(const value of ['2026-09-22T18:00:00','2026-02-29T18:00:00Z','2026-09-22T24:00:00Z','2026-09-22T18:60:00Z','2026-09-22T18:00:60Z','2026-09-22T18:00:00+00:60','2026-09-22T18:00:00+01:99','2026-09-22T18:00:00+24:00','2026-09-22T18:00:00.1234567890Z'])await expect(verify(value),value).rejects.toThrow();
 for(const value of ['2024-02-29T18:00:00Z','2026-09-22T18:00:00.123456789-04:30','2026-09-22T18:00:00+23:59','2026-09-22T18:00:00-00:00'])expect((await verify(value)).results[0].retrieved_at).toBe(value);
});
it('accepts only reviewed general queries for matching known sources, with no encounter payload or invented connector',()=>{
 expect(validResearchSearch(researchRequest())).toBe(true);
 for(const request of [{...researchRequest(),public_query_confirmed:false},{...researchRequest(),bot:'research'},{...researchRequest(),query:'line\npatient'},{...researchRequest(),query:'x'.repeat(501)},{...researchRequest(),sources:['pubmed','pubmed']},{...researchRequest(),topic:'trials'},{...researchRequest(),encounter_text:'private'},{...researchRequest(),sources:['chatgpt_plugin']}])expect(validResearchSearch(request)).toBe(false);
 const c=researchCatalog(false);expect(validateResearchCatalog(c).sources.every(s=>s.state==='not_configured')).toBe(true);expect(()=>validateResearchCatalog({...c,sources:[...c.sources,{...c.sources[0],id:'unknown'}]})).toThrow();
});
it('verifies dated/versioned records, truncation, save selection and bounded own-bot history',async()=>{
 const o=await researchObservation();expect(await validateResearchHistory({contract:'research.history.v1',runs:[o]},researchWorkspaceId,researchBotId)).toMatchObject({runs:[o]});
 await expect(validateResearchHistory({contract:'research.history.v1',runs:[o]},researchWorkspaceId,researchRunId)).rejects.toThrow();
 await expect(validateResearchHistory({contract:'research.history.v1',runs:Array(6).fill(o)},researchWorkspaceId,researchBotId)).rejects.toThrow();
 const request={contract_version:1 as const,idempotency_key:researchRunId,expected_revision:2,source_hashes:[o.results[0].sha256]},saved=await researchSaved(request);expect(await validateResearchSaved(saved,researchWorkspaceId,researchRunId,request)).toEqual(saved);
 await expect(validateResearchSaved({...saved,entry_revision:2},researchWorkspaceId,researchRunId,request)).rejects.toThrow();await expect(validateResearchSaved(saved,researchWorkspaceId,researchBotId,request)).rejects.toThrow();
});
it('persists exact unconfirmed public query in the existing scoped journal and refuses altered recovery',async()=>{
 const factory=memoryDraftStorage(),scope={scope:'b'.repeat(64)},kind=`research:${researchBotId}` as const,address=editorAddress(researchWorkspaceId,kind),journal=new DraftJournal(await factory(scope));await journal.load(address);
 const request=researchRequest(),data:ResearchDraft={version:1,bot:researchBotId,topic:request.topic,query:request.query,sources:request.sources,pending:{kind:'search',request}},draft=editorDraft(researchWorkspaceId,kind,data,request.idempotency_key);
 await journal.persist(address,draft);journal.close();const next=new DraftJournal(await factory(scope));expect(await next.load(address)).toEqual(draft);
 expect(()=>validateResearchDraft({...data,bot:researchRunId},researchBotId)).toThrow();await expect(next.persist(address,{...draft,data:{...data,query:'changed after review'}})).rejects.toMatchObject({code:'integrity'});await expect(next.persist(address,{...draft,pending:null})).rejects.toMatchObject({code:'integrity'});expect(await next.load(address)).toEqual(draft);next.close();
});
