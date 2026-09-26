import {beforeEach,afterEach,describe,it,expect,vi} from 'vitest';
import actual from './__fixtures__/portal-work/actual-portal-result-review.json';
import {preparePortalWorkOperation,verifyPortalWorkDetail,verifyPortalWorkCatalog,verifyPortalWorkReceipt,verifyPortalWorkObservations} from './portal-work-contract';
import {vendorBytes,vendorDigest} from './vendor-contract';
import {portalWorkApi} from './portal-work-api';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
beforeEach(()=>vi.stubGlobal('crypto',webcrypto));afterEach(()=>{vi.unstubAllGlobals();vi.unstubAllEnvs();});

describe('actual PostgreSQL portal result disclosure contract',()=>{
 it('validates the new owner detail, original request, exact receipt and full observation chain',async()=>{
  const d=await verifyPortalWorkDetail(actual.result_detail),r=d.current_result!;
  const op=await preparePortalWorkOperation(d.scope,'result',d.ticket_id,r.request);
  expect(await verifyPortalWorkReceipt(d.latest_result,op)).toEqual(actual.result_resolved);
  expect(await verifyPortalWorkObservations(actual.observations,d)).toEqual(actual.observations);
  expect((await verifyPortalWorkDetail(actual.verified_detail)).current_result).toEqual(r);
  expect((await verifyPortalWorkDetail(actual.no_result_detail)).current_result).toBeNull();
  expect(await verifyPortalWorkCatalog(actual.catalog)).toEqual(actual.catalog);
  expect(actual.catalog.items.every(item=>!Object.hasOwn(item,'current_result'))).toBe(true);
 });
 it('retains exact old detail compatibility only when the new field is absent',async()=>{
  const {current_result:_,...old}=actual.result_detail;
  expect(await verifyPortalWorkDetail(old)).toEqual(old);
  await expect(verifyPortalWorkDetail({...old,current_result:undefined})).rejects.toThrow();
  await expect(verifyPortalWorkDetail({...old,current_result:null})).rejects.toThrow();
 });
 it.each(['text','key','request_hash','receipt_hash','receipt_id','timestamp','sequence','extra_request','extra_envelope','missing_request','missing_receipt','stale_receipt'])('rejects %s before exposing saved evidence',async change=>{
  const d=structuredClone(actual.result_detail) as any;
  if(change==='text')d.current_result.request.evidence='Unrecorded forged result';
  if(change==='key')d.current_result.request.idempotency_key='different-result-key';
  if(change==='request_hash')d.current_result.request_sha256='0'.repeat(64);
  if(change==='receipt_hash')d.current_result.receipt_sha256='0'.repeat(64);
  if(change==='receipt_id')d.current_result.receipt_id=crypto.randomUUID();
  if(change==='timestamp')d.current_result.recorded_at='2026-09-21T00:00:00.000000Z';
  if(change==='sequence')d.current_result.request.observation_head.sequence++;
  if(change==='extra_request')d.current_result.request.confirmed=true;
  if(change==='extra_envelope')d.current_result.hidden='unknown';
  if(change==='missing_request')delete d.current_result.request;
  if(change==='missing_receipt')d.latest_result=null;
  if(change==='stale_receipt')Object.assign(d,structuredClone(actual.newer_result_detail),{current_result:d.current_result});
  await expect(verifyPortalWorkDetail(d)).rejects.toThrow();
 });
 it('rejects a fully rehashed result request that claims a future or conflicting current observation head',async()=>{
  for(const head of [{...actual.result_detail.observation_head,sequence:actual.result_detail.observation_head.sequence+1},{...actual.result_detail.observation_head,sha256:'0'.repeat(64)}]){
   const d=structuredClone(actual.result_detail);d.current_result.request.observation_head=head;
   const op=await preparePortalWorkOperation(d.scope as any,'result',d.ticket_id,d.current_result.request as any);
   d.latest_result.request_sha256=d.current_result.request_sha256=op.request_sha256;
   const {receipt_sha256:_,...body}=d.latest_result;
   d.latest_result.receipt_sha256=d.current_result.receipt_sha256=await vendorDigest('cosmas-portal-work-receipt.v1',body);
   d.evidence_sha256=await vendorDigest('cosmas-portal-work-evidence.v1',{operation_id:d.operation_id,observation_head:d.observation_head,result_receipt_id:d.latest_result.effect.receipt_id,result_receipt_sha256:d.latest_result.receipt_sha256});
   await expect(verifyPortalWorkDetail(d)).rejects.toThrow();
  }
 });
 it('keeps the latest saved result readable after a late observation while exposing the changed head',async()=>{
  const d=await verifyPortalWorkDetail(actual.changed_detail);
  expect(d.current_result).toEqual(actual.result_detail.current_result);
  expect(d.current_result?.request.observation_head).not.toEqual(d.observation_head);
  expect(d.provider_requirement_met).toBe(false);
  await verifyPortalWorkObservations(actual.changed_observations,d);
  expect((await verifyPortalWorkDetail(actual.newer_result_detail)).current_result?.receipt_id).not.toBe(d.current_result?.receipt_id);
 });
 it('uses the existing bounded HTTP detail path and rejects forged evidence at the transport boundary',async()=>{
  vi.stubEnv('VITE_API_BASE','http://127.0.0.1:8000');
  const response=(v:unknown)=>new Response(JSON.stringify(v),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
  const fetch=vi.fn().mockResolvedValueOnce(response(actual.result_detail));vi.stubGlobal('fetch',fetch);
  expect(await portalWorkApi.detail(actual.identity,actual.workspace_id,actual.result_detail.ticket_id)).toEqual(actual.result_detail);
  expect(fetch.mock.calls[0][0]).toBe(`http://127.0.0.1:8000/workspaces/${actual.workspace_id}/portal-work/${actual.result_detail.ticket_id}`);
  const forged=structuredClone(actual.result_detail);forged.current_result.request.evidence='Never recorded';fetch.mockResolvedValueOnce(response(forged));
  await expect(portalWorkApi.detail(actual.identity,actual.workspace_id,actual.result_detail.ticket_id)).rejects.toMatchObject({status:502});
 });
 it('admits a legal Unicode detail above the old 32KiB bound within the explicit new 64KiB cap',async()=>{
  const d=structuredClone(actual.result_detail),review=d.review;
  review.profile_label='🧪'.repeat(80);
  for(const k of ['patient_label','practice_label','recipient_label'] as const)review.mappings[k]='🧪'.repeat(200);
  for(const k of ['practice_reference','patient_reference','recipient_reference'] as const)review.mappings[k]='r'.repeat(120);
  review.summary='🧪'.repeat(4000);review.expected_outcome='🧪'.repeat(500);
  d.review_sha256=await vendorDigest('cosmas-portal-work-review.v1',review);
  d.current_result.request.evidence='🧪'.repeat(2000);
  d.current_result.request.idempotency_key=d.latest_result.idempotency_key='k'.repeat(100);
  const op=await preparePortalWorkOperation(d.scope as any,'result',d.ticket_id,d.current_result.request as any);
  d.current_result.request_sha256=d.latest_result.request_sha256=op.request_sha256;
  const {receipt_sha256:_,...receipt}=d.latest_result;
  d.current_result.receipt_sha256=d.latest_result.receipt_sha256=await vendorDigest('cosmas-portal-work-receipt.v1',receipt);
  d.evidence_sha256=await vendorDigest('cosmas-portal-work-evidence.v1',{operation_id:d.operation_id,observation_head:d.observation_head,result_receipt_id:d.latest_result.effect.receipt_id,result_receipt_sha256:d.latest_result.receipt_sha256});
  expect(vendorBytes(d)).toBe(32873);expect(vendorBytes(d)).toBeLessThan(65536);
  expect(await verifyPortalWorkDetail(d)).toEqual(d);
  vi.stubEnv('VITE_API_BASE','http://127.0.0.1:8000');vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(JSON.stringify(d),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}})));
  expect(await portalWorkApi.detail(actual.identity,actual.workspace_id,d.ticket_id)).toEqual(d);
 });
 it.each(['declared','streamed'])('rejects a %s response above 64KiB before disclosure',async mode=>{
  vi.stubEnv('VITE_API_BASE','http://127.0.0.1:8000');
  const headers:Record<string,string>={'Content-Type':'application/json','Cache-Control':'no-store'};if(mode==='declared')headers['Content-Length']='65537';
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(' '.repeat(65537),{headers})));
  await expect(portalWorkApi.detail(actual.identity,actual.workspace_id,actual.result_detail.ticket_id)).rejects.toMatchObject({status:503});
  expect(fetch).toHaveBeenCalledTimes(1);
 });
});
