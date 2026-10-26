import {afterEach,beforeEach,expect,it,vi} from 'vitest';
vi.hoisted(()=>{vi.stubEnv('VITE_COSMAS_ENV','synth_os');vi.stubEnv('VITE_WORKSPACE_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_AUTHENTICATED_ENABLED','true');vi.stubEnv('VITE_EHR_READ_ENABLED','true');});
vi.mock('./workspace-auth-headers',()=>({assertCurrentDesktopSession:()=>{},workspaceAuthHeaders:async()=>new Headers({'Content-Type':'application/json','Authorization':'Bearer invented'})}));
import {ehrHash,ehrItemHash,ehrReadApi,ehrMatchesCommand,ehrSourceContent,validEhrCommand,validEhrReceipt,verifyEhrReviewResponse,type EhrReceipt} from './ehr-read-api';
import {emptyEhrReadRecovery,validateEhrReadRecovery} from './ehr-read-recovery';
import {ehrBinding,ehrPractice,ehrScope,ehrVisit,ehrUuid,ehrWindowReceipt,ehrVerifiedReceipt,ehrProblemsCommand,ehrProblemsReceipt,ehrReviewBody,ehrReviewResult} from './ehr-read-fixtures.test-support';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const identity={mode:'clerk_jwt' as const,getToken:async()=>null},response=(value:unknown)=>new Response(JSON.stringify(value),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
beforeEach(()=>vi.stubGlobal('crypto',webcrypto));afterEach(()=>vi.unstubAllGlobals());
async function fixture(){const window=await ehrWindowReceipt(),verified=await ehrVerifiedReceipt(window),command=ehrProblemsCommand(verified),problems=await ehrProblemsReceipt(verified,command);return {window,verified,command,problems};}
async function rehash(r:EhrReceipt){if(r.observation.kind==='window'||r.observation.kind==='lab_reports')throw new Error();r.observation.item.sha256=await ehrItemHash(r.observation.item);r.payload_sha256=await ehrHash(r.observation);return r;}
it('opts into problem availability without changing the legacy status command or reply',async()=>{
 const legacy={contract_version:1,provider:'elation',mode:'synthetic',status:'ready',...ehrBinding,practice:ehrPractice},fetcher=vi.fn().mockResolvedValueOnce(response(legacy)).mockResolvedValueOnce(response({...legacy,problems:'available'}));vi.stubGlobal('fetch',fetcher);
 expect(await ehrReadApi.status(identity)).toEqual(legacy);expect((await ehrReadApi.status(identity,undefined,'elation',true)).problems).toBe('available');expect(fetcher.mock.calls.map(c=>JSON.parse(c[1].body))).toEqual([{action:'status'},{action:'status',include_problems:true}]);
});
it('does not infer problem access from an old status reply',async()=>{vi.stubGlobal('fetch',vi.fn().mockResolvedValue(response({contract_version:1,provider:'elation',mode:'synthetic',status:'ready',...ehrBinding,practice:ehrPractice})));await expect(ehrReadApi.status(identity,undefined,'elation',true)).rejects.toMatchObject({status:502});});
it('requires the exact verified visit and forbids Tebra or demographic substitutes for a problem read',async()=>{
 const f=await fixture(),fetcher=vi.fn();vi.stubGlobal('fetch',fetcher);expect(validEhrCommand(f.command)).toBe(true);expect(validEhrCommand({...f.command,provider:'tebra'})).toBe(false);expect(validEhrCommand({...f.command,last_name:'Invented',birth_date:'1980-02-03'})).toBe(false);
 for(const anchor of [null,f.window,{...f.verified,connection_id:ehrUuid(999)}])await expect(ehrReadApi.execute(identity,f.command,anchor)).rejects.toMatchObject({status:422});expect(fetcher).not.toHaveBeenCalled();
});
it('uses one explicit problem command and restores its exact receipt with only resolve and inspect calls',async()=>{
 const f=await fixture(),fetcher=vi.fn().mockImplementation(async()=>response(f.problems));vi.stubGlobal('fetch',fetcher);
 expect(await ehrReadApi.execute(identity,f.command,f.verified)).toEqual(f.problems);expect(await ehrReadApi.resolve(identity,f.command,f.verified)).toEqual(f.problems);expect(await ehrReadApi.inspect(identity,f.problems)).toEqual(f.problems);expect(fetcher.mock.calls.map(c=>JSON.parse(c[1].body).action)).toEqual(['problems','resolve','inspect']);
});
it.each(['parent','patient','binding','transport'] as const)('rejects a self-consistent but wrong %s problem receipt for the reviewed appointment',async change=>{
 const f=await fixture(),r=structuredClone(f.problems);if(r.observation.kind!=='verified_problems')throw new Error();
 if(change==='parent')r.observation.parent.source_sha256='f'.repeat(64);else if(change==='patient')r.observation.item.patient.birth_date='1981-02-03';else if(change==='binding')r.binding_sha256='f'.repeat(64);else r.transport='vendor_sandbox';await rehash(r);
 expect(ehrMatchesCommand(r,f.command,f.verified)).toBe(false);vi.stubGlobal('fetch',vi.fn().mockResolvedValue(response(r)));await expect(ehrReadApi.resolve(identity,f.command,f.verified)).rejects.toMatchObject({status:502});
});
it.each(['description','status','verification_status','start_date','resolved_date','extra'] as const)('rejects invalid or undeclared problem row %s even with fresh public hashes',async field=>{
 const f=await fixture(),r=structuredClone(f.problems);if(r.observation.kind!=='verified_problems')throw new Error();const row=r.observation.item.problems.items[0] as unknown as Record<string,unknown>;
 row[field]=field==='description'?'Unsafe\nrow':field==='start_date'||field==='resolved_date'?'2026-02-30':field==='extra'?'undeclared':'unknown-value';await rehash(r);expect(await validEhrReceipt(r)).toBe(false);
});
it('binds the entire problem list to its distinct item hash and rejects a retained content mutation',async()=>{
 const f=await fixture(),r=structuredClone(f.problems);if(r.observation.kind!=='verified_problems')throw new Error();r.observation.item.problems.items[0].description='Changed concern';r.payload_sha256=await ehrHash(r.observation);expect(await validEhrReceipt(r)).toBe(false);
 const {sha256,...item}=f.problems.observation.kind==='verified_problems'?f.problems.observation.item:(()=>{throw new Error();})();expect(sha256).toBe(await ehrHash({kind:'ehr_verified_problems_item.v1',item}));
});
it.each(['end_of_results','more_rows_available','unknown'] as const)('retains empty %s results with no absence-of-disease claim',async coverage=>{
 const f=await fixture(),r=await ehrProblemsReceipt(f.verified,f.command,{coverage,total_count:null,items:[]});expect(await validEhrReceipt(r)).toBe(true);if(r.observation.kind!=='verified_problems')throw new Error();expect(ehrSourceContent(r.observation)).toContain('No problem rows returned; this does not establish absence of conditions.');expect(ehrSourceContent(r.observation)).toContain('reported total: not provided.');
});
it('refuses a source exceeding 5000 characters instead of silently shortening its rows',async()=>{
 const f=await fixture(),r=structuredClone(f.problems);if(r.observation.kind!=='verified_problems')throw new Error();const row=r.observation.item.problems.items[0];r.observation.item.problems.items=Array.from({length:25},()=>({...row,description:'x'.repeat(200)}));await rehash(r);expect(ehrSourceContent(r.observation).length).toBeGreaterThan(5000);expect(await validEhrReceipt(r)).toBe(false);
});
it('retains the verified appointment beside a pending or saved problem snapshot and validates its source receipt',async()=>{
 const f=await fixture(),base={...emptyEhrReadRecovery(ehrScope),binding:ehrBinding,window:f.window,verified:f.verified};
 const pending={...base,pending:{kind:'read' as const,request:f.command,anchor:f.verified}};expect(await validateEhrReadRecovery(pending,ehrScope)).toEqual(pending);
 const body=ehrReviewBody(f.problems),result=await ehrReviewResult(f.problems,body);expect(await verifyEhrReviewResponse(result,ehrVisit.id,body,f.problems)).toEqual(result);expect(result.workspace.entries[0].source_label).toBe('Elation: reviewed problem list');
 const saved={...base,problems:f.problems,saved:{workspace_id:ehrVisit.id,entry_id:result.entry_id,entry_revision:result.entry_revision,source_sha256:result.source.source_sha256,content_sha256:result.source.content_sha256,request_sha256:result.request_sha256,source_withheld:false},saved_request:body};expect(await validateEhrReadRecovery(saved,ehrScope)).toEqual(saved);await expect(validateEhrReadRecovery({...saved,verified:null},ehrScope)).rejects.toThrow();await expect(validateEhrReadRecovery({...saved,problems:{...f.problems,transport:'vendor_sandbox'}},ehrScope)).rejects.toThrow();
});
it('preserves legacy appointment recovery and source bytes without inserting a problems field',async()=>{
 const f=await fixture(),value={...emptyEhrReadRecovery(ehrScope),binding:ehrBinding,window:f.window,verified:f.verified};expect(await validateEhrReadRecovery(value,ehrScope)).toEqual(value);expect('problems' in value).toBe(false);if(f.verified.observation.kind!=='verified_visit')throw new Error();expect(ehrSourceContent(f.verified.observation)).toBe('Elation selected visit (synthetic frozen observation)\nPractice: Invented Maple practice\nPatient: Mira Invented\nBirth date: 1980-02-03\nStarts: 2026-10-25T13:00:00Z\nEnds: 2026-10-25T13:30:00Z\nAppointment status: Scheduled\nObserved: 2026-10-25T12:00:00Z\nCoverage: Showing this page; more appointments may be available.\n\nThis reviewed snapshot does not book or update the EHR.');
});

it('preserves the bounded unavailable capability refusal without treating it as a completed read',async()=>{
 const f=await fixture(),fetcher=vi.fn().mockResolvedValue(new Response(JSON.stringify({detail:'ehr_read_problems_unavailable'}),{status:404,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}));vi.stubGlobal('fetch',fetcher);await expect(ehrReadApi.execute(identity,f.command,f.verified)).rejects.toMatchObject({status:404,code:'ehr_read_problems_unavailable'});expect(fetcher).toHaveBeenCalledOnce();
});
