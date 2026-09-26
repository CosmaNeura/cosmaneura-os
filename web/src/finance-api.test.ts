import {beforeEach,afterEach,describe,it,expect,vi} from 'vitest';
import {financeApi} from './finance-api';
import {actual,actualFinanceProposal,actualFinanceOptions} from './finance-test-fixture';
import {vendorCanonical} from './vendor-contract';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const identity={mode:'clerk_jwt' as const,getToken:async()=>'invented-local-token'};
const json=(value:unknown,headers:Record<string,string>={})=>new Response(JSON.stringify(value),{headers:{'Content-Type':'application/json','Cache-Control':'no-store',...headers}});
beforeEach(()=>{vi.stubGlobal('crypto',webcrypto);vi.stubEnv('VITE_API_BASE','http://127.0.0.1:8018');});afterEach(()=>{vi.unstubAllGlobals();vi.unstubAllEnvs();vi.useRealTimers();});
describe('private finance bounded HTTP transport',()=>{
  it('sends exact approved protocol request and keeps recovery separate from Stripe reads',async()=>{
    const op=await actualFinanceProposal(),getToken=vi.fn(identity.getToken),fetcher=vi.fn().mockImplementation(async()=>json(actual.proposal_receipt));vi.stubGlobal('fetch',fetcher);
    await financeApi.execute({...identity,getToken},op);await financeApi.recover({...identity,getToken},op);
    expect(fetcher.mock.calls.map(c=>c[0])).toEqual([`http://127.0.0.1:8018/workspaces/${op.scope.id}/finance-work`,`http://127.0.0.1:8018/workspaces/${op.scope.id}/finance-work/resolve`]);
    expect(fetcher.mock.calls[0][1].body).toBe(vendorCanonical(op.request));expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual({command_kind:op.kind,idempotency_key:op.request.idempotency_key,request_sha256:op.request_sha256});
    for(const c of fetcher.mock.calls){const h=new Headers(c[1].headers);expect(h.get('X-Cosmas-Finance-Contract')).toBe('1');expect(h.has('X-Cosmas-Vendor-Contract')).toBe(false);expect(h.has('X-Box-Id')).toBe(false);expect(c[1]).toMatchObject({credentials:'omit',redirect:'error',cache:'no-store',referrerPolicy:'no-referrer'});}expect(getToken).toHaveBeenCalledTimes(2);
  });
  it.each(['private','scope','selection-hash','duplicate','no-store','oversize'])('rejects invalid finance response %s',async fault=>{
    const value=structuredClone(actual.options) as any;if(fault==='private')value.credential='forbidden';if(fault==='scope')value.workspace_id=crypto.randomUUID();if(fault==='selection-hash')value.customers[0].label+=' altered';
    const response=fault==='duplicate'?new Response('{"contract_version":1,"contract_version":1}',{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}):fault==='oversize'?new Response(new Uint8Array(65537),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}):json(value,fault==='no-store'?{'Cache-Control':'public'}:{});
    const fetcher=vi.fn().mockResolvedValue(response);vi.stubGlobal('fetch',fetcher);await expect(financeApi.options(identity,actual.options.workspace_id)).rejects.toThrow();expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it('validates path and cursor before credentials or network access',async()=>{
    const fetcher=vi.fn(),getToken=vi.fn(identity.getToken);vi.stubGlobal('fetch',fetcher);await expect(financeApi.catalog({...identity,getToken},actual.options.workspace_id,'../redirect')).rejects.toThrow();await expect(financeApi.options({...identity,getToken},'../other')).rejects.toThrow();expect(fetcher).not.toHaveBeenCalled();expect(getToken).not.toHaveBeenCalled();
  });
  it('includes credentials in one deadline without late dispatch',async()=>{
    vi.useFakeTimers();let release!:(v:string)=>void;const fetcher=vi.fn();vi.stubGlobal('fetch',fetcher);const result=expect(financeApi.options({...identity,getToken:()=>new Promise(r=>{release=r;})},actualFinanceOptions().workspace_id)).rejects.toMatchObject({status:503});
    await vi.advanceTimersByTimeAsync(30000);await result;release('late-local-token');await vi.advanceTimersByTimeAsync(1);expect(fetcher).not.toHaveBeenCalled();
  });
  it('bounds a stalled body and never retries or waits for stalled cancellation',async()=>{
    vi.useFakeTimers();const cancel=vi.fn().mockImplementation(()=>new Promise(()=>{})),fetcher=vi.fn().mockResolvedValue({status:200,ok:true,headers:new Headers({'Content-Type':'application/json','Cache-Control':'no-store'}),body:{getReader:()=>({read:()=>new Promise(()=>{}),cancel,releaseLock:()=>{}})}});vi.stubGlobal('fetch',fetcher);
    const result=expect(financeApi.options(identity,actual.options.workspace_id)).rejects.toMatchObject({status:503});await vi.advanceTimersByTimeAsync(30000);await result;expect(fetcher).toHaveBeenCalledTimes(1);expect(cancel).toHaveBeenCalled();
  });
});
