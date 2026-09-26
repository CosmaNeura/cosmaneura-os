import {beforeEach,afterEach,describe,it,expect,vi} from 'vitest';
import actual from './__fixtures__/membership/actual-membership-cross-device-evidence.json';
import {verifyMembershipBundle,type MembershipReviewBundle} from './membership-operation';
import {verifyMembershipSavedFinance,membershipSavedDocument} from './membership-saved-evidence';
import {vendorApi} from './vendor-api';
import {vendorDigest} from './vendor-contract';
import {membershipApi} from './membership-api';
import {WorkspaceApiError} from './workspace-api';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
let bundle:MembershipReviewBundle;
beforeEach(async()=>{vi.stubGlobal('crypto',webcrypto);bundle=await verifyMembershipBundle(actual.membership_detail,actual.membership_history);vi.stubEnv('VITE_API_BASE','http://127.0.0.1:8000');vi.stubEnv('VITE_DESKTOP_SYNTHETIC_ENABLED','true');});
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();vi.unstubAllEnvs();vi.useRealTimers();});
const identity=()=>({boxId:bundle.detail.scope.box_id,actorId:bundle.detail.scope.owner_id});
const response=(value:unknown,status=200)=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
describe('cross-device original server finance evidence',()=>{
 it('validates the actual PG/HTTP original request, receipt and current detail',async()=>{expect(await verifyMembershipSavedFinance(actual.response,bundle.detail.scope,bundle)).toEqual(actual.response);});
 it.each(['scope','membership','request','receipt','detail','extra'])('rejects malformed or mismatched %s',async part=>{
  const v=structuredClone(actual.response) as Record<string,any>;
  if(part==='scope')v.scope.owner_id=crypto.randomUUID();if(part==='membership')v.membership.result_receipt_id=crypto.randomUUID();if(part==='request')v.request.idempotency_key='invented-different-original';if(part==='receipt')v.receipt.receipt_sha256='0'.repeat(64);if(part==='detail')v.detail.summary.conflicting_evidence=true;if(part==='extra')v.authority='automatic';
  await expect(verifyMembershipSavedFinance(v,bundle.detail.scope,bundle)).rejects.toThrow();
 });
 it('cannot replace the original request even with a self-consistent different receipt hash',async()=>{
  const v=structuredClone(actual.response);v.request.idempotency_key='another-exact-verify-key';v.receipt.idempotency_key=v.request.idempotency_key;v.receipt.request_sha256=await vendorDigest('cosmas-finance-public-request.v1',{command_kind:'verify',scope:v.receipt.scope,request:v.request});
  v.receipt.receipt_sha256=await vendorDigest('cosmas-finance-public-receipt.v1',{scope:v.receipt.scope,command_kind:'verify',idempotency_key:v.receipt.idempotency_key,request_sha256:v.receipt.request_sha256,effect:v.receipt.effect});
  await expect(verifyMembershipSavedFinance(v,bundle.detail.scope,bundle)).rejects.toThrow();
 });
 it('uses only the exact GET route and 64 KiB authenticated read contract',async()=>{
  const fetcher=vi.fn(async()=>response(actual.response));vi.stubGlobal('fetch',fetcher);expect((await membershipApi.savedFinance(identity(),bundle.detail.scope,bundle)).detail).toEqual(actual.response.detail);
  const [url,init]=fetcher.mock.calls[0] as unknown as [string,RequestInit];expect(url).toBe(`http://127.0.0.1:8000/workspaces/${bundle.detail.scope.workspace_id}/membership-work/${bundle.detail.summary.ticket_id}/results/${bundle.detail.latest_result!.receipt_id}/finance-evidence`);expect(init.method).toBe('GET');expect(init.body).toBeUndefined();expect(init.redirect).toBe('error');expect(init.credentials).toBe('omit');expect(new Headers(init.headers).get('X-Cosmas-Membership-Contract')).toBe('1');
 });
 it.each([401,403,404])('withholds denied response %s before decoding',async status=>{vi.stubGlobal('fetch',vi.fn(async()=>response(actual.response,status)));await expect(membershipApi.savedFinance(identity(),bundle.detail.scope,bundle)).rejects.toMatchObject({status});});
 it.each(['oversize','no-store','duplicate','extra','binding'])('rejects unsafe actual transport response %s',async mode=>{
  let r:Response;
  if(mode==='oversize')r=new Response(' '.repeat(65537),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
  else if(mode==='no-store')r=new Response(JSON.stringify(actual.response),{headers:{'Content-Type':'application/json'}});
  else if(mode==='duplicate')r=new Response(JSON.stringify(actual.response).replace('"contract_version":1','"contract_version":1,"contract_version":1'),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
  else r=response({...actual.response,...(mode==='extra'?{unknown:true}:{membership:{...actual.response.membership,version:2}})});
  vi.stubGlobal('fetch',vi.fn(async()=>r));await expect(membershipApi.savedFinance(identity(),bundle.detail.scope,bundle)).rejects.toBeInstanceOf(WorkspaceApiError);
 });
 it('aborts stalled GET within the original 15 second budget with no retry',async()=>{
  vi.useFakeTimers();const fetcher=vi.fn(()=>new Promise<Response>(()=>{}));vi.stubGlobal('fetch',fetcher);const p=membershipApi.savedFinance(identity(),bundle.detail.scope,bundle);const rejected=expect(p).rejects.toMatchObject({status:503});await vi.advanceTimersByTimeAsync(15001);await rejected;expect(fetcher).toHaveBeenCalledOnce();
 });
 it('uses the saved exact document on a second device despite a historical note',async()=>{
  bundle.detail.summary.source_current=false;const bytes=Uint8Array.from(atob(actual.pdf_base64),c=>c.charCodeAt(0));const preview=vi.spyOn(vendorApi,'preview').mockResolvedValue(bytes);const result=await membershipSavedDocument.preview(identity(),bundle.detail.scope,bundle);expect(result.document).toEqual(bundle.detail.latest_result!.request.ledger!.document);expect(result.bytes).toEqual(bytes);expect(preview).toHaveBeenCalledWith(identity(),bundle.detail.scope.workspace_id,result.document,undefined);
 });
 it('rejects altered PDF bytes and late bytes after caller cancellation',async()=>{
  const bytes=Uint8Array.from(atob(actual.pdf_base64),c=>c.charCodeAt(0));bytes[20]^=1;vi.spyOn(vendorApi,'preview').mockResolvedValue(bytes);await expect(membershipSavedDocument.preview(identity(),bundle.detail.scope,bundle)).rejects.toThrow();
  vi.mocked(vendorApi.preview).mockResolvedValue(Uint8Array.from(atob(actual.pdf_base64),c=>c.charCodeAt(0)));const abort=new AbortController();abort.abort();await expect(membershipSavedDocument.preview(identity(),bundle.detail.scope,bundle,abort.signal)).rejects.toThrow();
 });
});
