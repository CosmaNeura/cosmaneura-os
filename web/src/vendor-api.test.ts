import {afterEach,beforeEach,describe,it,expect,vi} from 'vitest';
import {vendorApi,readVendorPracticeCatalog} from './vendor-api';
import {actual,artifact,actualOptions,actualProposal,actualContent,actualAcceptance,shared} from './vendor-test-fixture';
import {vendorCanonical,vendorSha256} from './vendor-contract';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const identity={mode:'clerk_jwt' as const,getToken:async()=>'invented-test-token'};
const json=(value:unknown,headers:Record<string,string>={})=>new Response(JSON.stringify(value),{headers:{'Content-Type':'application/json','Cache-Control':'no-store',...headers}});
beforeEach(()=>{vi.stubGlobal('crypto',webcrypto);vi.stubEnv('VITE_API_BASE','http://127.0.0.1:8018');});
afterEach(()=>{vi.unstubAllGlobals();vi.unstubAllEnvs();vi.useRealTimers();});
describe('closed vendor HTTP client',()=>{
  it('negotiates exactly, refreshes credentials and keeps saved receipt recovery distinct from vendor reads',async()=>{
    const op=await actualProposal(),getToken=vi.fn(identity.getToken),fetcher=vi.fn().mockImplementation(()=>Promise.resolve(json(actual.proposal_receipt)));vi.stubGlobal('fetch',fetcher);
    await vendorApi.execute({...identity,getToken},op);await vendorApi.recover({...identity,getToken},op);
    expect(fetcher.mock.calls.map(c=>c[0])).toEqual([`http://127.0.0.1:8018/workspaces/${op.scope.id}/vendor-work`,`http://127.0.0.1:8018/workspaces/${op.scope.id}/vendor-work/resolve`]);
    expect(fetcher.mock.calls[0][1].body).toBe(vendorCanonical(op.request));expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual({command_kind:'propose',idempotency_key:op.request.idempotency_key,request_sha256:op.request_sha256});
    for(const call of fetcher.mock.calls){const init=call[1];const h=new Headers(init.headers);expect(h.get('X-Cosmas-Vendor-Contract')).toBe('1');expect(h.has('X-Cosmas-Artifact-Write-Key')).toBe(false);expect(h.has('X-Box-Id')).toBe(false);expect(init).toMatchObject({credentials:'omit',redirect:'error',cache:'no-store',referrerPolicy:'no-referrer'});}expect(getToken).toHaveBeenCalledTimes(2);
  });
  it('crosses actual staff accept and artifact recovery fixtures',async()=>{
    const op=await actualAcceptance(),content=await actualContent();const fetcher=vi.fn().mockResolvedValueOnce(json(shared.shared_accept_receipt)).mockResolvedValueOnce(json(artifact.artifact_replay_receipt));vi.stubGlobal('fetch',fetcher);
    await vendorApi.execute(identity,op);await vendorApi.recover(identity,content);expect(fetcher.mock.calls[0][0]).toContain('/handoffs');expect(fetcher.mock.calls[1][0]).toContain('/vendor-artifacts/resolve');
  });
  it('uploads exact raw PDF bytes and refuses changed bytes before credentials or dispatch',async()=>{
    const op=await actualContent(),bytes=new TextEncoder().encode('%PDF-1.7\nInvented raw HTTP custody\n%%EOF');expect(bytes.length).toBe(40);
    const fetcher=vi.fn().mockResolvedValue(json(artifact.artifact_content_receipt)),getToken=vi.fn(identity.getToken);vi.stubGlobal('fetch',fetcher);
    const file={size:bytes.length,arrayBuffer:async()=>bytes.buffer} as Blob;await vendorApi.upload({...identity,getToken},op,file);
    const init=fetcher.mock.calls[0][1];expect(init.method).toBe('PUT');expect(Array.from(init.body)).toEqual(Array.from(bytes));const headers=new Headers(init.headers);expect(headers.get('Content-Type')).toBe('application/pdf');expect(headers.get('X-Cosmas-Artifact-Write-Key')).toBe('same-local-content');
    const bad={size:bytes.length,arrayBuffer:async()=>new Uint8Array(bytes.length).buffer} as Blob;await expect(vendorApi.upload({...identity,getToken},op,bad)).rejects.toThrow();expect(fetcher).toHaveBeenCalledTimes(1);expect(getToken).toHaveBeenCalledTimes(1);
  });
  it.each(['private-field','wrong-scope','hash','duplicate','no-store','oversize'])('refuses malformed actual option response: %s',async fault=>{
    const value=structuredClone(actual.options) as any;let response:Response;
    if(fault==='private-field')value.secret='forbidden';if(fault==='wrong-scope')value.workspace_id='11111111-1111-4111-8111-111111111111';if(fault==='hash')value.connections[0].label+=' changed';
    response=fault==='duplicate'?new Response('{"contract_version":1,"contract_version":1}',{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}):fault==='oversize'?new Response(new Uint8Array(65537),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}):json(value,fault==='no-store'?{'Cache-Control':'public'}:{});
    vi.stubGlobal('fetch',vi.fn().mockResolvedValue(response));await expect(vendorApi.options(identity,actualOptions().workspace_id)).rejects.toThrow();
  });
  it('includes stalled credentials in the sole deadline and never dispatches their late resolution',async()=>{
    vi.useFakeTimers();let release!:(value:string)=>void;const fetcher=vi.fn();vi.stubGlobal('fetch',fetcher);
    const result=expect(vendorApi.options({...identity,getToken:()=>new Promise(r=>{release=r;})},actualOptions().workspace_id)).rejects.toMatchObject({status:503});
    await vi.advanceTimersByTimeAsync(30000);await result;release('late-test-token');await vi.advanceTimersByTimeAsync(1);expect(fetcher).not.toHaveBeenCalled();
  });
  it('bounds a stalled response without retrying or awaiting cancellation',async()=>{
    vi.useFakeTimers();const cancel=vi.fn().mockImplementation(()=>new Promise(()=>{})),fetcher=vi.fn().mockResolvedValue({status:200,ok:true,headers:new Headers({'Content-Type':'application/json','Cache-Control':'no-store'}),body:{getReader:()=>({read:()=>new Promise(()=>{}),cancel,releaseLock:()=>{}})}});vi.stubGlobal('fetch',fetcher);
    const result=expect(vendorApi.options(identity,actualOptions().workspace_id)).rejects.toMatchObject({status:503});await vi.advanceTimersByTimeAsync(30000);await result;expect(fetcher).toHaveBeenCalledTimes(1);expect(cancel).toHaveBeenCalled();
  });
  it('verifies complete preview bytes before returning any PDF',async()=>{
    const bytes=new TextEncoder().encode('%PDF-1.7\nInvented browser preview\n%%EOF');const doc={artifact_id:actual.options.source.note_id,sha256:await vendorSha256(bytes),byte_length:bytes.length,media_type:'application/pdf' as const};
    const fetcher=vi.fn().mockResolvedValueOnce(new Response(bytes,{headers:{'Content-Type':'application/pdf','Cache-Control':'no-store'}})).mockResolvedValueOnce(new Response(new Uint8Array(bytes.length),{headers:{'Content-Type':'application/pdf','Cache-Control':'no-store'}}));vi.stubGlobal('fetch',fetcher);
    expect(Array.from(await vendorApi.preview(identity,actualOptions().workspace_id,doc))).toEqual(Array.from(bytes));await expect(vendorApi.preview(identity,actualOptions().workspace_id,doc)).rejects.toThrow();
  });
  it('supports only exact UUID practice pages and validates mixed catalog through caller',async()=>{
    const fetcher=vi.fn().mockResolvedValue(json({invented:'bounded catalog'}));vi.stubGlobal('fetch',fetcher);const verify=vi.fn(async value=>value);
    await readVendorPracticeCatalog(identity,undefined,verify);await expect(readVendorPracticeCatalog(identity,'../../other',verify)).rejects.toThrow();expect(fetcher).toHaveBeenCalledTimes(1);expect(fetcher.mock.calls[0][0]).toBe('http://127.0.0.1:8018/practice-work');
  });
});
