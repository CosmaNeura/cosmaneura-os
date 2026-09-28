import {it,expect,afterEach,vi} from 'vitest';
vi.mock('./workspace-auth-headers',()=>({assertCurrentDesktopSession:()=>{},workspaceAuthHeaders:async()=>new Headers({'Authorization':'Bearer invented'})}));
import {CONNECTION_IDS,parseConnectionCatalog,readConnectionCatalog} from './connection-catalog-api';
import type {AuthenticatedWorkspaceIdentity} from './workspace-api';

const identity:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null};
afterEach(()=>{vi.unstubAllGlobals();vi.useRealTimers();});

const response=()=>({version:1,services:CONNECTION_IDS.map(id=>({id,setup_available:id==='core'}))});
it('accepts only the complete boolean setup catalog without claiming connected accounts',()=>{
  expect(parseConnectionCatalog(response())).toEqual({core:true,google:false,microsoft:false,scheduling:false,messaging:false,payments:false,portals:false});
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
  expect(fetcher.mock.calls[0][1].headers.get('X-Cosmas-Connection-Contract')).toBe('1');
  fetcher.mockResolvedValue(new Response(' '.repeat(4097),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}));
  await expect(readConnectionCatalog(identity,new AbortController().signal)).rejects.toThrow();
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
