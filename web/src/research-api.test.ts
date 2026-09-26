import {beforeEach,afterEach,it,expect,vi} from 'vitest';
import {researchApi} from './research-api';
import {RESEARCH_DEADLINE_MS,RESEARCH_RESPONSE_BYTES} from './research-contract';
import {researchIdentity,researchWorkspaceId,researchBotId,researchRequest,researchObservation,researchCatalog,researchRunId,researchSaved,researchSavedPacket} from './research-test-fixture';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const response=(body:BodyInit,status=200,extra:Record<string,string>={})=>new Response(body,{status,headers:{'Content-Type':'application/json','Cache-Control':'no-store',...extra}});
beforeEach(()=>{vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('fetch',vi.fn());vi.stubEnv('VITE_API_BASE','http://127.0.0.1:8000');});afterEach(()=>{vi.unstubAllGlobals();vi.unstubAllEnvs();vi.useRealTimers();});
it('uses signed bounded same-service queries and exact saved-result resolution without reposting the public question',async()=>{
 const request=researchRequest(),o=await researchObservation(request);vi.mocked(fetch).mockImplementation(async()=>response(JSON.stringify(o)));expect(await researchApi.search(researchIdentity,researchWorkspaceId,request)).toEqual(o);
 const [url,options]=vi.mocked(fetch).mock.calls[0];expect(url).toBe('http://127.0.0.1:8000/workspaces/'+researchWorkspaceId+'/research/search');expect(options).toMatchObject({method:'POST',credentials:'omit',cache:'no-store',redirect:'error',referrerPolicy:'no-referrer',body:JSON.stringify(request)});expect(new Headers(options?.headers).get('X-Cosmas-Research-Contract')).toBe('1');
 await researchApi.resolve(researchIdentity,researchWorkspaceId,request);const [resolveUrl,resolve]=vi.mocked(fetch).mock.calls[1];expect(resolveUrl).toBe('http://127.0.0.1:8000/workspaces/'+researchWorkspaceId+'/research/resolve');expect(JSON.parse(resolve?.body as string)).toEqual({contract_version:1,idempotency_key:request.idempotency_key});
});
it('resolves saves using only their saved key and verifies the exact selected-source receipt',async()=>{
 const request={contract_version:1 as const,idempotency_key:researchRunId,expected_revision:2,source_hashes:['a'.repeat(64)]};vi.mocked(fetch).mockResolvedValue(response(JSON.stringify(await researchSaved(request))));await researchApi.resolveSave(researchIdentity,researchWorkspaceId,researchRunId,request);expect(JSON.parse(vi.mocked(fetch).mock.calls[0][1]?.body as string)).toEqual({contract_version:1,idempotency_key:researchRunId});expect(String(vi.mocked(fetch).mock.calls[0][0])).toContain('/save/resolve');
});
it.each(['https://outside.invalid','http://127.0.0.1:8000?target=x','http://127.0.0.1:8000/path'])('withholds credentials from an unqualified API %s',async base=>{vi.stubEnv('VITE_API_BASE',base);const getToken=vi.fn(async()=> 'token');await expect(researchApi.catalog({mode:'clerk_jwt',getToken})).rejects.toBeDefined();expect(getToken).not.toHaveBeenCalled();expect(fetch).not.toHaveBeenCalled();});
it.each([['duplicate','{"contract":"research.catalog.v1","contract":"research.catalog.v1"}',{}],['over-size','x'.repeat(RESEARCH_RESPONSE_BYTES+1),{}],['encoded','{}',{'Content-Encoding':'identity'}],['cache','{}',{'Cache-Control':'public'}],['html','{}',{'Content-Type':'text/html'}],['length','{}',{'Content-Length':'01'}]] as [string,string,Record<string,string>][])('rejects %s response without retry',async(_name,body,extra)=>{vi.mocked(fetch).mockResolvedValue(response(body,200,extra));await expect(researchApi.catalog(researchIdentity)).rejects.toMatchObject({status:502});expect(fetch).toHaveBeenCalledTimes(1);});
it('bounds stalled fresh credentials and prevents a late public query dispatch',async()=>{vi.useFakeTimers();let finish!:(v:string)=>void;const pending=researchApi.search({mode:'clerk_jwt',getToken:()=>new Promise(resolve=>{finish=resolve;})},researchWorkspaceId,researchRequest()).catch(e=>e);await vi.advanceTimersByTimeAsync(RESEARCH_DEADLINE_MS);expect((await pending).status).toBe(503);finish('late-invented-token');await Promise.resolve();expect(fetch).not.toHaveBeenCalled();});
it('cancels a stalled body and rejects a stale native session without adopting results',async()=>{
 const controller=new AbortController(),cancel=vi.fn();vi.mocked(fetch).mockResolvedValue(response(new ReadableStream({pull:()=>new Promise(()=>{}),cancel})));const pending=researchApi.catalog(researchIdentity,controller.signal).catch(e=>e);await vi.waitFor(()=>expect(fetch).toHaveBeenCalledTimes(1));controller.abort();expect((await pending).status).toBe(503);expect(cancel).toHaveBeenCalled();
 let current=true;vi.mocked(fetch).mockImplementation(async()=>{current=false;return response(JSON.stringify(researchCatalog()));});await expect(researchApi.catalog({...researchIdentity,nativeSession:{revision:researchRunId,isCurrent:()=>current}})).rejects.toMatchObject({status:401});
});
it('never exposes provider or authentication error text',async()=>{vi.mocked(fetch).mockResolvedValue(response('untrusted secret provider error',403,{'Content-Type':'text/plain'}));const error=await researchApi.catalog(researchIdentity).catch(e=>e);expect(error.status).toBe(403);expect(String(error)).not.toContain('untrusted secret');});
it('reads bound older history and saved packets using GET with no question or model body',async()=>{
 const packet=await researchSavedPacket(3),saved={contract:'research.saved_history.v1',workspace_id:researchWorkspaceId,bot:researchBotId,packets:[packet]};
 vi.mocked(fetch).mockResolvedValueOnce(response(JSON.stringify({contract:'research.history.v1',runs:[]}))).mockResolvedValueOnce(response(JSON.stringify(saved)));
 await researchApi.history(researchIdentity,researchWorkspaceId,researchBotId,undefined,researchRunId);
 expect(await researchApi.savedHistory(researchIdentity,researchWorkspaceId,researchBotId,undefined,packet.saved.entry_id)).toEqual(saved);
 expect(vi.mocked(fetch).mock.calls.map(([url,options])=>[url,options?.method,options?.body])).toEqual([
  ['http://127.0.0.1:8000/workspaces/'+researchWorkspaceId+'/research?bot='+researchBotId+'&before='+researchRunId,'GET',undefined],
  ['http://127.0.0.1:8000/workspaces/'+researchWorkspaceId+'/research/saved?bot='+researchBotId+'&before='+packet.saved.entry_id,'GET',undefined],
 ]);
});
it('rejects malformed pagination before acquiring credentials and preserves owner denial',async()=>{
 const getToken=vi.fn(async()=> 'invented');
 expect(()=>researchApi.history({mode:'clerk_jwt',getToken},researchWorkspaceId,researchBotId,undefined,'foreign?query')).toThrow();expect(getToken).not.toHaveBeenCalled();expect(fetch).not.toHaveBeenCalled();
 vi.mocked(fetch).mockResolvedValue(response('{"detail":"research_not_found"}',404));await expect(researchApi.savedHistory(researchIdentity,researchWorkspaceId,researchBotId,undefined,researchRunId)).rejects.toMatchObject({status:404,code:'research_not_found'});expect(fetch).toHaveBeenCalledOnce();
});
