import {afterEach,beforeEach,expect,it,vi} from 'vitest';
vi.hoisted(()=>{vi.stubEnv('VITE_API_BASE','http://127.0.0.1:8000');vi.stubEnv('VITE_COSMAS_ENV','synth_os');vi.stubEnv('VITE_WORKSPACE_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_AUTHENTICATED_ENABLED','true');});
import {efaxInboundApi,verifyEFaxReceipt,validateEFaxStatus,validateEFaxProposal,validateEFaxPending,efaxUtcSeconds,type EFaxPending} from './efax-inbound-api';
import {efaxScope,efaxStatus,efaxReceipt,efaxProposal,efaxUuid,efaxPdf} from './efax-inbound-fixtures.test-support';
import {vendorSha256} from './vendor-contract';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const identity={mode:'clerk_jwt' as const,getToken:async()=> 'invented-token'};
const observe:EFaxPending={kind:'observe',request:{idempotency_key:efaxUuid(20),grant_id:efaxUuid(4),starts_at:'2026-09-25T18:00:00Z',ends_at:'2026-10-02T18:00:00Z',limit:25,offset:0}};
const response=(value:unknown,status=200,headers:Record<string,string>={})=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json','Cache-Control':'no-store',...headers}});
beforeEach(()=>{vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('fetch',vi.fn());});afterEach(()=>vi.unstubAllGlobals());
it('uses scoped auth, closed headers, no-store and redirect denial without logging secrets',async()=>{
 vi.mocked(fetch).mockResolvedValueOnce(response(efaxStatus));expect(await efaxInboundApi.status(identity,efaxScope)).toEqual(efaxStatus);const [url,init]=vi.mocked(fetch).mock.calls[0];expect(url).toBe('http://127.0.0.1:8000/efax-inbound');expect(init?.method).toBe('GET');expect(init?.cache).toBe('no-store');expect(init?.redirect).toBe('error');expect(init?.credentials).toBe('omit');expect(new Headers(init?.headers).get('X-Cosmas-EFax-Inbound')).toBe('1');expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer invented-token');
});
it('verifies exact public command commitments and scope while treating private hashes as opaque',async()=>{
 const r=await efaxReceipt(observe);expect(await verifyEFaxReceipt(r,efaxScope,observe)).toEqual(r);
 await expect(verifyEFaxReceipt({...r,public_request_sha256:'f'.repeat(64)},efaxScope,observe)).rejects.toThrow();await expect(verifyEFaxReceipt({...r,idempotency_key:efaxUuid(21)},efaxScope,observe)).rejects.toThrow();await expect(verifyEFaxReceipt({...r,scope:{...efaxScope,owner_id:efaxUuid(99)}},efaxScope,observe)).rejects.toThrow();
});
it('normalizes newly chosen dates before persistence and rejects noncanonical saved command timestamps before any transport',async()=>{
 expect(efaxUtcSeconds(new Date('2026-10-02T14:00:00.987-04:00'))).toBe('2026-10-02T18:00:00Z');
 for(const ends_at of ['2026-10-02T18:00:00.000Z','2026-10-02T14:00:00-04:00','2026-02-30T18:00:00Z']){
  const p={...observe,request:{...observe.request,ends_at}};expect(()=>validateEFaxPending(p)).toThrow();await expect(efaxInboundApi.command(identity,efaxScope,p)).rejects.toThrow();await expect(efaxInboundApi.resolve(identity,efaxScope,p)).rejects.toThrow();
 }
 const grant:EFaxPending={kind:'grant',request:{idempotency_key:efaxUuid(29),installation_id:efaxUuid(3),reviewed_account:true,reviewed_mark_read:false,image_enabled:false,expires_at:'2026-10-03T18:00:00.001Z'}};await expect(efaxInboundApi.command(identity,efaxScope,grant)).rejects.toThrow();expect(fetch).not.toHaveBeenCalled();
});
it('validates closed missing-reservation receipts including image no-retry and document masking defaults',async()=>{
 const acquire:EFaxPending={kind:'acquire',request:{idempotency_key:efaxUuid(22),ticket_id:efaxUuid(7),revision_id:efaxUuid(9),expected_version:2,approval_sha256:'e'.repeat(64)}};
 const missing={contract_version:1,scope:efaxScope,idempotency_key:acquire.request.idempotency_key,kind:'acquire',state:'not_found',retry_allowed:false,content_available:false,source_withheld:false,document:null};vi.mocked(fetch).mockResolvedValueOnce(response(missing));expect(await efaxInboundApi.resolve(identity,efaxScope,acquire)).toEqual(missing);
 for(const changed of [{...missing,retry_allowed:true},{...missing,document:{sha256:'f'.repeat(64),byte_length:10,pages:1}},{...missing,idempotency_key:efaxUuid(99)},{...missing,kind:'recover'}]){vi.mocked(fetch).mockResolvedValueOnce(response(changed));await expect(efaxInboundApi.resolve(identity,efaxScope,acquire)).rejects.toThrow();}
 const revoke:EFaxPending={kind:'revoke',request:{idempotency_key:efaxUuid(23),grant_id:efaxUuid(4)}};vi.mocked(fetch).mockResolvedValueOnce(response({contract_version:1,scope:efaxScope,idempotency_key:revoke.request.idempotency_key,kind:'recover',state:'not_found'}));expect((await efaxInboundApi.resolve(identity,efaxScope,revoke)).state).toBe('not_found');expect(fetch).toHaveBeenCalledTimes(6);
});
it('rejects growth, unknown status, wrong metadata hash and complete-inbox claims',async()=>{
 expect(()=>validateEFaxStatus({...efaxStatus,enabled:'token'},efaxScope)).toThrow();expect(()=>validateEFaxStatus({...efaxStatus,grants:[...efaxStatus.grants,...efaxStatus.grants]},efaxScope)).toThrow();const r=await efaxReceipt(observe);
 await expect(verifyEFaxReceipt({...r,snapshot:{...r.snapshot,inbox_complete:true}},efaxScope,observe)).rejects.toThrow();const p=await efaxProposal();await expect(validateEFaxProposal({...p,fax:{...p.fax,originating_fax_tsid:'changed'}},efaxScope,p.ticket_id)).rejects.toThrow();
});
it.each([{headers:{'Cache-Control':'private'}},{headers:{'Content-Encoding':'gzip'}},{headers:{'Content-Length':'9999999'}},{headers:{'Content-Type':'text/plain'}}])('rejects untrusted response headers without retry',async options=>{
 vi.mocked(fetch).mockResolvedValueOnce(response(efaxStatus,200,Object.fromEntries(Object.entries(options.headers).filter((pair):pair is [string,string]=>typeof pair[1]==='string'))));await expect(efaxInboundApi.status(identity,efaxScope)).rejects.toThrow();expect(fetch).toHaveBeenCalledOnce();
});
it('rejects duplicate keys, malformed bodies and body growth without retry',async()=>{
 for(const body of ['{"contract_version":1,"contract_version":1}','{broken','x'.repeat(65537)]){vi.mocked(fetch).mockResolvedValueOnce(new Response(body,{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}));await expect(efaxInboundApi.status(identity,efaxScope)).rejects.toThrow();}expect(fetch).toHaveBeenCalledTimes(3);
});
it('bounds and hash-verifies only a current acquired local PDF with attachment headers',async()=>{
 const p:EFaxPending={kind:'acquire',request:{idempotency_key:efaxUuid(22),ticket_id:efaxUuid(7),revision_id:efaxUuid(9),expected_version:2,approval_sha256:'e'.repeat(64)}};const r={...await efaxReceipt(p),state:'acquired' as const,content_available:true,document:{sha256:await vendorSha256(efaxPdf),byte_length:efaxPdf.length,pages:1}};
 const pdf=()=>new Response(new Uint8Array(efaxPdf),{headers:{'Content-Type':'application/pdf','Cache-Control':'no-store','Content-Disposition':'attachment; filename=received-fax.pdf','X-Content-Type-Options':'nosniff'}});
 vi.mocked(fetch).mockResolvedValueOnce(pdf());expect(Array.from(await efaxInboundApi.document(identity,r))).toEqual(Array.from(efaxPdf));vi.mocked(fetch).mockResolvedValueOnce(pdf());await expect(efaxInboundApi.document(identity,{...r,document:{...r.document,sha256:'f'.repeat(64)}})).rejects.toThrow();await expect(efaxInboundApi.document(identity,{...r,source_withheld:true})).rejects.toThrow();expect(fetch).toHaveBeenCalledTimes(2);
});
it('rejects unknown or malformed acquired outcomes instead of authorizing document access',async()=>{
 const p:EFaxPending={kind:'acquire',request:{idempotency_key:efaxUuid(22),ticket_id:efaxUuid(7),revision_id:efaxUuid(9),expected_version:2,approval_sha256:'e'.repeat(64)}},r=await efaxReceipt(p);
 for(const changed of [{...r,state:'fax_delivered'},{...r,content_available:true},{...r,source_withheld:true,document:{sha256:'f'.repeat(64),byte_length:10,pages:1}},{...r,document:undefined},{...r,version:4}])await expect(verifyEFaxReceipt(changed,efaxScope,p)).rejects.toThrow();expect(fetch).not.toHaveBeenCalled();
});
it('cancels ignored transports and never adopts a late private response',async()=>{
 let finish!:(r:Response)=>void;vi.mocked(fetch).mockReturnValueOnce(new Promise(r=>{finish=r;}));const c=new AbortController(),pending=efaxInboundApi.status(identity,efaxScope,c.signal);for(let n=0;n<20&&!vi.mocked(fetch).mock.calls.length;n++)await Promise.resolve();c.abort();await expect(pending).rejects.toThrow();finish(response(efaxStatus));expect(fetch).toHaveBeenCalledOnce();
});
