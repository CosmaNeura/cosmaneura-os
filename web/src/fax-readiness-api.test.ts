import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {FAX_PROVIDERS,parseFaxReadiness,readFaxReadiness,type FaxReadiness} from './fax-readiness-api';

export const faxReadinessFixture=():FaxReadiness=>({
  contract_version:1,scope:{box_id:'00000000-0000-4000-8000-000000000001',owner_id:'00000000-0000-4000-8000-000000000002'},
  enabled:true,work_enabled:true,delivery_enabled:false,credential_access_configured:false,document_storage_configured:false,
  providers:FAX_PROVIDERS.map(id=>({id,installed_accounts:0,active_accounts:0,review_required_accounts:0,unavailable_accounts:0,prepare_enabled_accounts:0})),
});
const identity={mode:'clerk_jwt' as const,getToken:async()=>'invented-token'};
const json=(value:unknown)=>new Response(JSON.stringify(value),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
beforeEach(()=>vi.stubEnv('VITE_API_BASE','http://127.0.0.1:8018'));
afterEach(()=>{vi.unstubAllGlobals();vi.unstubAllEnvs();vi.useRealTimers();});

it('accepts the complete four-provider account-only configuration without proving delivery',()=>{
  const value=faxReadinessFixture();
  expect(parseFaxReadiness(value)).toEqual(value);
  expect(JSON.stringify(value)).not.toMatch(/patient|destination|credential_ref|delivered|verified/);
});
it.each(['recipient','account-id','duplicate','missing','unsupported','negative','fraction','too-many','prepared-without-active','active-without-installed','non-boolean'])('rejects an invalid or overbroad readiness response: %s',fault=>{
  const value=faxReadinessFixture();
  if(fault==='recipient')Object.assign(value,{patients:[{label:'Not permitted'}]});
  if(fault==='account-id')Object.assign(value.providers[0],{account_id:'Not permitted'});
  if(fault==='duplicate')value.providers[1]=value.providers[0];
  if(fault==='missing')value.providers.pop();
  if(fault==='unsupported')Object.assign(value.providers[0],{id:'unknown-provider'});
  if(fault==='negative')value.providers[0].installed_accounts=-1;
  if(fault==='fraction')value.providers[0].installed_accounts=0.5;
  if(fault==='too-many')value.providers[0].installed_accounts=51;
  if(fault==='prepared-without-active')value.providers[0].prepare_enabled_accounts=1;
  if(fault==='active-without-installed')value.providers[0].active_accounts=1;
  if(fault==='non-boolean')Object.assign(value,{credential_access_configured:'true'});
  expect(()=>parseFaxReadiness(value)).toThrow();
});
it('reads only the 4KiB no-store readiness endpoint through the existing authenticated setup contract',async()=>{
  const fetcher=vi.fn().mockResolvedValue(json(faxReadinessFixture()));vi.stubGlobal('fetch',fetcher);
  expect(await readFaxReadiness(identity,new AbortController().signal)).toEqual(faxReadinessFixture());
  expect(fetcher).toHaveBeenCalledTimes(1);
  const [url,options]=fetcher.mock.calls[0];
  expect(url).toBe('http://127.0.0.1:8018/vendor-settings/readiness');
  expect(options).toMatchObject({method:'GET',credentials:'omit',cache:'no-store',redirect:'error',body:undefined});
  expect(new Headers(options.headers).get('X-Cosmas-Vendor-Setup-Contract')).toBe('1');
  fetcher.mockResolvedValue(new Response(new Uint8Array(4097),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}));
  await expect(readFaxReadiness(identity,new AbortController().signal)).rejects.toThrow();
});
it('preserves denial and ends a stalled read without retries or optimistic setup',async()=>{
  const fetcher=vi.fn().mockResolvedValue(new Response('',{status:403}));vi.stubGlobal('fetch',fetcher);
  await expect(readFaxReadiness(identity,new AbortController().signal)).rejects.toMatchObject({status:403});
  vi.useFakeTimers();fetcher.mockImplementation(()=>new Promise(()=>{}));
  const result=expect(readFaxReadiness(identity,new AbortController().signal)).rejects.toMatchObject({status:503});
  await vi.advanceTimersByTimeAsync(15000);await result;
  expect(fetcher).toHaveBeenCalledTimes(2);
});
it('does not read setup after the caller cancels',async()=>{
  const fetcher=vi.fn();vi.stubGlobal('fetch',fetcher);const controller=new AbortController();controller.abort();
  await expect(readFaxReadiness(identity,controller.signal)).rejects.toMatchObject({status:503});
  expect(fetcher).not.toHaveBeenCalled();
});
it('discards readiness when the native account changes while response bytes are being read',async()=>{
  let current=true;
  const bytes=new TextEncoder().encode(JSON.stringify(faxReadinessFixture()));
  vi.stubGlobal('fetch',async()=>new Response(new ReadableStream({start(controller){current=false;controller.enqueue(bytes);controller.close();}}),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}));
  await expect(readFaxReadiness({...identity,nativeSession:{revision:'invented',isCurrent:()=>current}},new AbortController().signal)).rejects.toMatchObject({status:401});
});
