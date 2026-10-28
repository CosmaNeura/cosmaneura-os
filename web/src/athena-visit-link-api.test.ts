import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import fixture from './__fixtures__/athena-visit-links.json';
import {validateAthenaVisitLinkCommand,validateAthenaVisitLinkResult,type AthenaVisitLinkCommand} from './athena-visit-link-api';
import {coreConnectionApi} from './core-connection-api';
import {coreDigest} from './core-connection-contract';
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
it.each(['appointment','source'])('rejects a valid linked %s that differs from the reviewed target',async fault=>{
 const item=structuredClone(fixture.link),encounter=item.response.athena_visit_link.encounter;
 if(fault==='appointment')encounter.appointment.appointment_ref='appointment_00000000000000000000000002';
 else encounter.patient.display_name='Invented updated display name';
 const {source_sha256:_old,...content}=encounter;
 encounter.source_sha256=await coreDigest(content);
 expect(encounter.connection_sha256).toBe(item.command.connection_sha256);
 expect(encounter.source_sha256).not.toBe(item.command.core_source_sha256);
 await expect(validateAthenaVisitLinkResult(item.response,item.command as AthenaVisitLinkCommand)).rejects.toMatchObject({status:502});
});
it('keeps status receipts valid when the current encounter projection has changed',async()=>{
 const item=structuredClone(fixture.status),encounter=item.response.athena_visit_link.encounter;
 encounter.patient.display_name='Invented updated display name';
 const {source_sha256:_old,...content}=encounter;
 encounter.source_sha256=await coreDigest(content);
 await expect(validateAthenaVisitLinkResult(item.response,item.command as AthenaVisitLinkCommand)).resolves.toEqual(item.response);
});
it.each(['lookup','link','status','unlink'] as const)('maps an invalid nested account timezone to a bounded error for %s',async name=>{
 const item=structuredClone(fixture[name]);item.response.athena_visit_link.account.department_timezone='Invalid/Zone';
 await expect(validateAthenaVisitLinkResult(item.response,item.command as AthenaVisitLinkCommand)).rejects.toMatchObject({status:502});
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
