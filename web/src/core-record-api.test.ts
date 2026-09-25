import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {coreRecordApi} from './core-record-api';
import {RECORD_LOCATION_DEADLINE_MS} from './core-record-location';
const workspace='00000000-0000-4000-8000-000000000001',origin='https://core.example.invalid';
const appointment='appointment_'+'0'.repeat(25)+'1';
const fixture=()=>({contract_version:1,workspace_id:workspace,appointment_ref:appointment,href:origin+'/notes/'+appointment,checked_at:new Date().toISOString()});
const credentials=()=>({mode:'clerk_jwt' as const,getToken:vi.fn(async()=>'invented-token')});
const headers={'Content-Type':'application/json','Cache-Control':'no-store'};
const response=(body:BodyInit=JSON.stringify(fixture()),status=200,extra:Record<string,string>={})=>new Response(body,{status,headers:{...headers,...extra}});
beforeEach(()=>{vi.stubGlobal('fetch',vi.fn());vi.stubEnv('VITE_API_BASE','http://127.0.0.1:8000');vi.stubEnv('VITE_COSMANEURA_WEB_ORIGIN',origin);});
afterEach(()=>{vi.unstubAllEnvs();vi.unstubAllGlobals();vi.useRealTimers();});

it('uses fresh signed credentials to read only the exact workspace location without a request body',async()=>{
  const value=fixture(),identity=credentials();vi.mocked(fetch).mockResolvedValue(response(JSON.stringify(value)));
  expect(await coreRecordApi.location(identity,workspace)).toEqual(value);expect(identity.getToken).toHaveBeenCalledExactlyOnceWith({skipCache:true});
  const [url,options]=vi.mocked(fetch).mock.calls[0];expect(url).toBe('http://127.0.0.1:8000/workspaces/'+workspace+'/cosmaneura-record/location');
  expect(options).toMatchObject({method:'GET',cache:'no-store',redirect:'error',credentials:'omit',referrerPolicy:'no-referrer'});
  expect(Object.hasOwn(options!,'body')).toBe(false);expect(new Headers(options?.headers).get('X-Cosmas-Record-Contract')).toBe('1');
});
it.each(['https://outside.invalid','http://127.0.0.1:8000?target=x','http://127.0.0.1:8000/other'])('does not give credentials to unqualified API %s',async base=>{
  vi.stubEnv('VITE_API_BASE',base);const identity=credentials();await expect(coreRecordApi.location(identity,workspace)).rejects.toBeDefined();
  expect(identity.getToken).not.toHaveBeenCalled();expect(fetch).not.toHaveBeenCalled();
});
it.each([
  ['oversized','x'.repeat(2049),{}],['duplicate','{"contract_version":1,"contract_version":1}',{}],
  ['encoded','{}',{'Content-Encoding':'identity'}],['cached','{}',{'Cache-Control':'public'}],
  ['length','{}',{'Content-Length':'01'}],['html','<html>',{'Content-Type':'text/html'}],
] as [string,string,Record<string,string>][])('rejects %s response without retry',async(_,body,extra)=>{
  vi.mocked(fetch).mockResolvedValue(response(body,200,extra));await expect(coreRecordApi.location(credentials(),workspace)).rejects.toMatchObject({status:502});
  expect(fetch).toHaveBeenCalledTimes(1);
});
it('rejects a redirected record destination and never follows it',async()=>{
  const value=response();Object.defineProperty(value,'redirected',{value:true});vi.mocked(fetch).mockResolvedValue(value);
  await expect(coreRecordApi.location(credentials(),workspace)).rejects.toMatchObject({status:502});expect(fetch).toHaveBeenCalledTimes(1);
});
it('preserves an access denial without leaking its raw body',async()=>{
  vi.mocked(fetch).mockResolvedValue(response('private server text',403,{'Content-Type':'text/plain'}));
  const error=await coreRecordApi.location(credentials(),workspace).catch(error=>error);
  expect(error.status).toBe(403);expect(String(error)).not.toContain('private server text');
});
it('a deadline includes stalled credentials and prevents late dispatch',async()=>{
  vi.useFakeTimers();let finish!:(v:string)=>void;
  const pending=coreRecordApi.location({mode:'clerk_jwt',getToken:()=>new Promise(r=>{finish=r;})},workspace).catch(error=>error);
  await vi.advanceTimersByTimeAsync(RECORD_LOCATION_DEADLINE_MS);expect((await pending).status).toBe(503);
  finish('late-invented-token');await Promise.resolve();expect(fetch).not.toHaveBeenCalled();
});
it('cancels a stalled body when its encounter is left',async()=>{
  const abort=new AbortController(),cancel=vi.fn();vi.mocked(fetch).mockResolvedValue(response(new ReadableStream({pull(){return new Promise(()=>{});},cancel})));
  const pending=coreRecordApi.location(credentials(),workspace,abort.signal).catch(error=>error);
  await vi.waitFor(()=>expect(fetch).toHaveBeenCalledTimes(1));abort.abort();expect((await pending).status).toBe(503);expect(cancel).toHaveBeenCalled();
});
it('does not expose a response after the Apple native session changes',async()=>{
  let current=true;vi.mocked(fetch).mockImplementation(async()=>{current=false;return response();});
  await expect(coreRecordApi.location({...credentials(),nativeSession:{revision:workspace,isCurrent:()=>current}},workspace)).rejects.toMatchObject({status:401});
});
