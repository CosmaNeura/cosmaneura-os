import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,describe,it,expect,vi} from 'vitest';
import actual from './__fixtures__/portal-work/actual-portal-result-review.json';
import {PortalWorkPanel,recordedPortalResult} from './PortalWorkPanel';
import {portalWorkApi} from './portal-work-api';
import {portalSetupApi} from './portal-setup-api';
import {vendorApi} from './vendor-api';
import {validateVendor,vendorDigest} from './vendor-contract';
import {verifyPortalCatalog} from './portal-setup-contract';
import {verifyPortalWorkDetail,verifyPortalWorkObservations,type PortalWorkDetail,type PortalWorkReceipt} from './portal-work-contract';
import {emptyPortalWorkRecovery,type PortalWorkRecoveryAccess,type PortalWorkRecoveryRecord} from './portal-work-recovery';
import {WorkspaceApiError} from './workspace-api';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const scope={kind:'workspace' as const,id:actual.workspace_id};
function recovery(){let saved:PortalWorkRecoveryRecord|null=null;const access:PortalWorkRecoveryAccess={load:vi.fn(async()=>saved),persist:vi.fn(async value=>{saved=structuredClone(value);}),authorize:vi.fn(async()=>{}),denied:vi.fn()};return {access,value:()=>saved};}

describe('fresh-device private portal result review using actual API fixtures',()=>{
 let root:Root,container:HTMLDivElement,current:PortalWorkDetail;
 beforeEach(async()=>{
  Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.stubGlobal('crypto',webcrypto);
  current=await verifyPortalWorkDetail(actual.result_detail);container=document.createElement('div');document.body.append(container);root=createRoot(container);
  vi.spyOn(vendorApi,'options').mockResolvedValue(validateVendor('Options',actual.options));
  vi.spyOn(portalSetupApi,'catalog').mockResolvedValue(await verifyPortalCatalog(actual.setup_catalog));
  vi.spyOn(portalWorkApi,'catalog').mockImplementation(async()=>{const {current_result:_,...compact}=current;return {contract_version:1,scope,items:[structuredClone(compact)]};});
  vi.spyOn(portalWorkApi,'detail').mockImplementation(async()=>verifyPortalWorkDetail(current));
  vi.spyOn(portalWorkApi,'observations').mockImplementation(async(_identity,d)=>verifyPortalWorkObservations(d.observation_head.sequence===actual.changed_detail.observation_head.sequence?actual.changed_observations:actual.observations,d));
  vi.spyOn(portalWorkApi,'execute').mockRejectedValue(new Error('Unexpected command'));
  vi.spyOn(vendorApi,'execute').mockRejectedValue(new Error('Unexpected document command'));
 });
 afterEach(async()=>{await act(async()=>root.unmount());container.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});
 const button=(label:string)=>Array.from(container.querySelectorAll('button')).find(b=>b.textContent===label)!;
 const waitUi=async(check:()=>void)=>{for(let i=0;i<150;i++){let done=false;await act(async()=>{await new Promise(r=>setTimeout(r,5));try{check();done=true;}catch{}});if(done)return;}check();};
 const click=async(label:string)=>{await waitUi(()=>{expect(button(label)).toBeTruthy();expect(button(label).matches(':disabled')).toBe(false);});await act(async()=>button(label).click());};
 const render=async(store:ReturnType<typeof recovery>,identity=actual.identity)=>{
  await act(async()=>root.render(<PortalWorkPanel identity={identity} workspaceId={actual.workspace_id} recovery={store.access}/>));
  await waitUi(()=>expect(button('Refresh portal work')?.disabled).toBe(false));
  await click('referral submit · '+current.review.mappings.recipient_label+' · approved');
  await waitUi(()=>expect(container.querySelector('[aria-label="Exact portal action review"]')).not.toBeNull());
 };
 const completionChecks=()=>Array.from(container.querySelectorAll('fieldset')).find(f=>f.querySelector('legend')?.textContent==='Verify completion')!.querySelectorAll<HTMLInputElement>('input[type=checkbox]');
 const review=async()=>{await click('Review recorded evidence');await waitUi(()=>expect(container.textContent).toContain('verified complete history'));await act(async()=>completionChecks().forEach(e=>e.click()));};
 it('shows validated saved evidence on a fresh device but restores no consent and performs no provider operation',async()=>{
  const store=recovery();await render(store);
  expect(store.value()?.pending??null).toBeNull();expect(store.value()?.history??[]).toEqual([]);
  expect(container.querySelector('[aria-label="Saved portal result"]')?.textContent).toContain(actual.result_detail.current_result.request.evidence);
  expect(Array.from(completionChecks()).every(c=>!c.checked)).toBe(true);
  expect(button('Verify portal completion').disabled).toBe(true);
  expect(portalWorkApi.execute).not.toHaveBeenCalled();expect(portalWorkApi.observations).not.toHaveBeenCalled();expect(vendorApi.execute).not.toHaveBeenCalled();
 });
 it('requires fresh complete evidence and three checks, then saves only a new exact verification against the original result',async()=>{
  const store=recovery();await render(store);
  await act(async()=>completionChecks().forEach(e=>e.click()));expect(button('Verify portal completion').disabled).toBe(true);
  await act(async()=>completionChecks().forEach(e=>e.click()));await review();
  vi.mocked(portalWorkApi.execute).mockImplementationOnce(async(_identity,op)=>{
   expect(op.kind).toBe('verify');expect(store.value()?.pending).toEqual({lane:'portal_work',operation:op});
   expect(op.request).toMatchObject({result_receipt_id:actual.result_detail.current_result.receipt_id,result_receipt_sha256:actual.result_detail.current_result.receipt_sha256,reviewed_result:true,reviewed_observations:true,outcome_confirmed:true});
   const r={...structuredClone(actual.verify_receipt),idempotency_key:op.request.idempotency_key,request_sha256:op.request_sha256};
   const {receipt_sha256:_,...body}=r;r.receipt_sha256=await vendorDigest('cosmas-portal-work-receipt.v1',body);
   current=await verifyPortalWorkDetail(actual.verified_detail);return r as PortalWorkReceipt;
  });
  await click('Verify portal completion');await waitUi(()=>expect(store.value()?.receipt?.outcome).toBe('recorded'));
  expect(portalWorkApi.execute).toHaveBeenCalledTimes(1);expect(store.value()?.history).toEqual([]);expect(store.value()?.pending?.operation.kind).toBe('verify');
 });
 it('keeps the original result visible and clears all completion consent when the current observation head changes',async()=>{
  const store=recovery();await render(store);await review();expect(button('Verify portal completion').disabled).toBe(false);
  current=await verifyPortalWorkDetail(actual.changed_detail);await click('Refresh portal work');
  await waitUi(()=>expect(container.textContent).toContain('Portal evidence has changed since this result was recorded'));
  expect(Array.from(completionChecks()).every(c=>!c.checked)).toBe(true);expect(button('Verify portal completion').disabled).toBe(true);
  expect(container.textContent).not.toContain('verified complete history');expect(container.textContent).toContain(actual.result_detail.current_result.request.evidence);
  await review();expect(button('Verify portal completion').disabled).toBe(true);expect(portalWorkApi.execute).not.toHaveBeenCalled();
 });
 it('clears prior consent when a newly recorded result replaces the original proof',async()=>{
  const store=recovery();await render(store);await review();expect(button('Verify portal completion').disabled).toBe(false);
  current=await verifyPortalWorkDetail(actual.newer_result_detail);await click('Refresh portal work');
  await waitUi(()=>expect(Array.from(completionChecks()).every(c=>!c.checked)).toBe(true));expect(button('Verify portal completion').disabled).toBe(true);expect(portalWorkApi.execute).not.toHaveBeenCalled();
 });
 it('keeps old-server missing evidence unavailable on a fresh device without inventing a result',async()=>{
  const {current_result:_,...old}=actual.result_detail;current=await verifyPortalWorkDetail(old);
  const store=recovery();await render(store);expect(container.textContent).toContain('This server did not provide the saved result evidence');
  await review();expect(button('Verify portal completion').disabled).toBe(true);expect(portalWorkApi.execute).not.toHaveBeenCalled();
  expect(recordedPortalResult(emptyPortalWorkRecovery(scope),current)).toBeNull();
 });
 it.each([401,403,404])('hides saved result evidence immediately when a fresh detail read denies access %s',async status=>{
  const store=recovery();await render(store);await review();
  vi.mocked(portalWorkApi.detail).mockRejectedValueOnce(new WorkspaceApiError(status));await click('Review recorded evidence');
  await waitUi(()=>expect(container.textContent).toContain('Access to private portal work is unavailable'));
  expect(container.textContent).not.toContain(actual.result_detail.current_result.request.evidence);expect(container.querySelector('[aria-label="Saved portal result"]')).toBeNull();
  expect(store.access.denied).toHaveBeenCalled();expect(portalWorkApi.execute).not.toHaveBeenCalled();
 });
 it('does not send verification when exact journal persistence fails',async()=>{
  const store=recovery();await render(store);await review();vi.mocked(store.access.persist).mockRejectedValueOnce(new Error('CAS changed'));
  await click('Verify portal completion');await waitUi(()=>expect(container.textContent).toContain('This action was not sent'));
  expect(portalWorkApi.execute).not.toHaveBeenCalled();expect(store.value()?.pending).toBeNull();
 });
});
