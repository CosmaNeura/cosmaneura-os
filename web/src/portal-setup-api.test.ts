import {afterEach,beforeEach,describe,it,expect,vi} from 'vitest';
import {portalSetupApi} from './portal-setup-api';
import {portalFixture,actualPortalProposal} from './portal-setup-test-fixture';
import {vendorCanonical} from './vendor-contract';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const identity={mode:'clerk_jwt' as const,getToken:async()=>'invented-token'};
const json=(value:unknown,headers:Record<string,string>={})=>new Response(JSON.stringify(value),{headers:{'Content-Type':'application/json','Cache-Control':'no-store',...headers}});
beforeEach(()=>{vi.stubGlobal('crypto',webcrypto);vi.stubEnv('VITE_API_BASE','http://127.0.0.1:8018');});
afterEach(()=>{vi.unstubAllGlobals();vi.unstubAllEnvs();vi.useRealTimers();});
describe('closed portal setup HTTP client',()=>{
  it('uses exact persisted request and resolve paths, refreshed auth and no cookies',async()=>{
    const op=await actualPortalProposal(),getToken=vi.fn(identity.getToken),fetcher=vi.fn().mockImplementation(async()=>json(portalFixture.proposal_receipt));vi.stubGlobal('fetch',fetcher);
    await portalSetupApi.command({...identity,getToken},op);await portalSetupApi.resolve({...identity,getToken},op);
    expect(fetcher.mock.calls.map(c=>c[0])).toEqual(['http://127.0.0.1:8018/portal-setup/propose','http://127.0.0.1:8018/portal-setup/resolve']);
    expect(fetcher.mock.calls[0][1].body).toBe(vendorCanonical(op.request));expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual({command_kind:'propose',idempotency_key:op.request.idempotency_key,request_sha256:op.request_sha256});
    for(const call of fetcher.mock.calls){expect(new Headers(call[1].headers).get('X-Cosmas-Portal-Contract')).toBe('1');expect(call[1]).toMatchObject({credentials:'omit',redirect:'error',cache:'no-store',referrerPolicy:'no-referrer'});}expect(getToken).toHaveBeenCalledTimes(2);
  });
  it.each(['no-store','duplicate','extra','oversize'])('rejects a malformed catalog response: %s',async fault=>{
    const response=fault==='no-store'?json(portalFixture.catalog_pending,{'Cache-Control':'public'}):fault==='duplicate'?new Response('{"contract_version":1,"contract_version":1}',{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}):fault==='oversize'?new Response(new Uint8Array(2097153),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}):json({...portalFixture.catalog_pending,endpoint:'unapproved'});
    vi.stubGlobal('fetch',vi.fn().mockResolvedValue(response));await expect(portalSetupApi.catalog(identity)).rejects.toThrow();
  });
  it('includes stalled credential acquisition in one deadline and never dispatches a late token',async()=>{
    vi.useFakeTimers();let release!:(value:string)=>void;const fetcher=vi.fn();vi.stubGlobal('fetch',fetcher);
    const result=expect(portalSetupApi.catalog({...identity,getToken:()=>new Promise(r=>{release=r;})})).rejects.toMatchObject({status:503});await vi.advanceTimersByTimeAsync(15000);await result;release('late-invented-token');await vi.advanceTimersByTimeAsync(1);expect(fetcher).not.toHaveBeenCalled();
  });
  it('bounds stalled body reading without retry or blocking on cancellation',async()=>{
    vi.useFakeTimers();const cancel=vi.fn().mockImplementation(()=>new Promise(()=>{})),fetcher=vi.fn().mockResolvedValue({status:200,headers:new Headers({'Content-Type':'application/json','Cache-Control':'no-store'}),body:{getReader:()=>({read:()=>new Promise(()=>{}),cancel})}});vi.stubGlobal('fetch',fetcher);
    const result=expect(portalSetupApi.catalog(identity)).rejects.toMatchObject({status:503});await vi.advanceTimersByTimeAsync(15000);await result;expect(cancel).toHaveBeenCalled();expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it('rejects arbitrary paths before acquiring credentials',()=>{
    const fetcher=vi.fn();vi.stubGlobal('fetch',fetcher);expect(()=>portalSetupApi.detail(identity,'../secrets')).toThrow();expect(fetcher).not.toHaveBeenCalled();
  });
});
