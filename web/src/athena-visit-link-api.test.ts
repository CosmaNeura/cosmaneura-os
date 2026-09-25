import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import fixture from './__fixtures__/athena-visit-links.json';
import {validateAthenaVisitLinkCommand,validateAthenaVisitLinkResult,type AthenaVisitLinkCommand} from './athena-visit-link-api';
import {coreConnectionApi} from './core-connection-api';
vi.mock('./workspace-auth-headers',()=>({assertCurrentDesktopSession:()=>{},workspaceAuthHeaders:async()=>new Headers({'Authorization':'Bearer invented'})}));
beforeEach(()=>{vi.setSystemTime(new Date(fixture.lookup.response.athena_visit_link.checked_at));vi.stubEnv('VITE_API_BASE','http://127.0.0.1:8000');vi.stubEnv('VITE_COSMAS_ENV','synth_os');});
afterEach(()=>{vi.useRealTimers();vi.unstubAllEnvs();vi.unstubAllGlobals();});
it('validates the Python-generated lookup, review, save, removal and status contracts',async()=>{
 for(const [name,item] of Object.entries(fixture)){
  if(name==='encounters'||!('command' in item))continue;
  validateAthenaVisitLinkCommand(item.command as AthenaVisitLinkCommand);
  await expect(validateAthenaVisitLinkResult(item.response,item.command as AthenaVisitLinkCommand)).resolves.toEqual(item.response);
 }
});
it.each(['patient','command','confirmed','scope'])('rejects changed %s before display or saving',async fault=>{
 const item=structuredClone(fixture.link);
 if(fault==='patient')item.response.athena_visit_link.source.patient_ref='9002';
 if(fault==='command')item.response.athena_visit_link.command_sha256='f'.repeat(64);
 if(fault==='confirmed'){Object.assign(item.command,{confirmed:false});expect(()=>validateAthenaVisitLinkCommand(item.command as AthenaVisitLinkCommand)).toThrow();return;}
 if(fault==='scope')item.response.athena_visit_link.account.account_sha256='f'.repeat(64);
 await expect(validateAthenaVisitLinkResult(item.response,item.command as AthenaVisitLinkCommand)).rejects.toThrow();
});
it('sends one signed no-store Core request and rejects an Apple session revoked during the response',async()=>{
 const item=fixture.lookup,command=item.command as AthenaVisitLinkCommand;
 let current=true;
 const identity={mode:'clerk_jwt' as const,getToken:async()=>null,nativeSession:{revision:crypto.randomUUID(),isCurrent:()=>current}};
 const response=()=>new Response(JSON.stringify(item.response),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
 const fetcher=vi.fn(async()=>response());vi.stubGlobal('fetch',fetcher);
 expect(await coreConnectionApi.read(identity,command)).toEqual(item.response);
 expect(fetcher.mock.calls).toHaveLength(1);
 current=false;await expect(coreConnectionApi.read(identity,command)).rejects.toMatchObject({status:401});expect(fetcher.mock.calls).toHaveLength(1);
 current=true;fetcher.mockImplementation(async()=>{current=false;return response();});await expect(coreConnectionApi.read(identity,command)).rejects.toMatchObject({status:401});expect(fetcher.mock.calls).toHaveLength(2);
});
