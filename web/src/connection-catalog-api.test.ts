import {it,expect,afterEach,vi} from 'vitest';
vi.mock('./workspace-auth-headers',()=>({assertCurrentDesktopSession:()=>{},workspaceAuthHeaders:async()=>new Headers({'Authorization':'Bearer invented'})}));
vi.mock('./workspace-api',async original=>({...await original<typeof import('./workspace-api')>(),WORKSPACE_BUILD:true,WORKSPACE_AUTHENTICATED_BUILD:true}));
import {CONNECTION_IDS,connectionActionClientAvailable,parseConnectionCatalog,readConnectionCatalog} from './connection-catalog-api';
import type {AuthenticatedWorkspaceIdentity} from './workspace-api';
import {readinessFixture} from './connection-readiness-fixture';

const identity:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null};
afterEach(()=>{vi.unstubAllGlobals();vi.unstubAllEnvs();vi.useRealTimers();});

const response=()=>({version:1,services:CONNECTION_IDS.map(id=>({id,setup_available:id==='core'}))});
it('accepts only the complete boolean setup catalog without claiming connected accounts',()=>{
  expect(parseConnectionCatalog(response())).toEqual({core:true,google:false,microsoft:false,scheduling:false,messaging:false,payments:false,portals:false});
});
const responseV2=()=>{const value=readinessFixture();return {version:2,services:CONNECTION_IDS.map(id=>({id,setup_available:value[id],...value.readiness![id]}))};};
it('accepts v2 action readiness while preserving unknown account and provider results',()=>{
  const value=parseConnectionCatalog(responseV2());expect(value.google).toBe(true);
  expect(value.readiness?.portals).toMatchObject({state:'coming_soon',installed_account:'missing',account_status:'not_checked'});
});
it('matches compiled delivery work and independent source feature gates without inventing a vendor build flag',()=>{
  expect(connectionActionClientAvailable('spruce_administrative_message','messaging')).toBe(true);
  expect(connectionActionClientAvailable('fax_delivery','messaging')).toBe(true);
  vi.stubEnv('VITE_FAX_INBOUND_ENABLED','false');vi.stubEnv('VITE_EFAX_INBOUND_ENABLED','true');
  expect(connectionActionClientAvailable('reviewed_received_fax','messaging')).toBe(true);
  vi.stubEnv('VITE_EFAX_INBOUND_ENABLED','false');
  expect(connectionActionClientAvailable('reviewed_received_fax','messaging')).toBe(false);
  vi.stubEnv('VITE_WORKSPACE_GOOGLE_CONNECTION_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_MICROSOFT_CONNECTION_ENABLED','false');
  expect(connectionActionClientAvailable('mail_headers','google')).toBe(true);
  expect(connectionActionClientAvailable('mail_headers','microsoft')).toBe(false);
});
it.each(['false_success','extra_action','unsupported_runtime','unexpected_account'])('rejects %s readiness',kind=>{
 const value=responseV2();const row=value.services[6];
 if(kind==='false_success')row.setup_available=true;
 if(kind==='extra_action')row.actions.push({id:'unsafe_send',supported:true,runtime_available:true});
 if(kind==='unsupported_runtime')row.actions[0].runtime_available=true;
 if(kind==='unexpected_account')Object.assign(row,{account_status:'connected'});
 expect(()=>parseConnectionCatalog(value)).toThrow();
});
it.each(['duplicate','missing','extra','non_boolean'])('rejects a %s catalog',kind=>{
  const value=response();
  if(kind==='duplicate')value.services[1]=value.services[0];
  if(kind==='missing')value.services.pop();
  if(kind==='extra')Object.assign(value.services[0],{token:'must not be accepted'});
  if(kind==='non_boolean')Object.assign(value.services[0],{setup_available:'true'});
  expect(()=>parseConnectionCatalog(value)).toThrow();
});
it('reads only the bounded no-store catalog through the signed workspace request',async()=>{
  const fetcher=vi.fn().mockResolvedValue(new Response(JSON.stringify(response()),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}));
  vi.stubGlobal('fetch',fetcher);
  expect(await readConnectionCatalog(identity,new AbortController().signal)).toEqual(parseConnectionCatalog(response()));
  expect(fetcher.mock.calls[0][0]).toMatch(/\/connections\/catalog$/);
  expect(fetcher.mock.calls[0][1]).toMatchObject({method:'GET',credentials:'omit',cache:'no-store',redirect:'error'});
  expect(fetcher.mock.calls[0][1].headers.get('X-Cosmas-Connection-Contract')).toBe('2');
  fetcher.mockResolvedValue(new Response(' '.repeat(32769),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}));
  await expect(readConnectionCatalog(identity,new AbortController().signal)).rejects.toThrow();
});
it('falls back only to exact v1 on a legacy negotiation rejection without claiming action readiness',async()=>{
  const fetcher=vi.fn().mockResolvedValueOnce(new Response('{}',{status:426})).mockResolvedValueOnce(new Response(JSON.stringify(response()),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}));
  vi.stubGlobal('fetch',fetcher);
  const result=await readConnectionCatalog(identity,new AbortController().signal);
  expect(result.readiness).toBeUndefined();expect(fetcher).toHaveBeenCalledTimes(2);
  expect(fetcher.mock.calls.map(call=>call[1].headers.get('X-Cosmas-Connection-Contract'))).toEqual(['2','1']);
});
it('discards a response when the native account changes during its read',async()=>{
  let current=true;
  vi.stubGlobal('fetch',async()=>{current=false;return new Response(JSON.stringify(response()),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});});
  await expect(readConnectionCatalog({...identity,nativeSession:{revision:'invented',isCurrent:()=>current}},new AbortController().signal)).rejects.toMatchObject({status:401});
});
it('ends a stalled response at the deadline without waiting on the provider',async()=>{
  vi.useFakeTimers();vi.stubGlobal('fetch',()=>new Promise(()=>{}));
  const result=expect(readConnectionCatalog(identity,new AbortController().signal)).rejects.toMatchObject({status:503});
  await vi.advanceTimersByTimeAsync(15000);await result;
});
