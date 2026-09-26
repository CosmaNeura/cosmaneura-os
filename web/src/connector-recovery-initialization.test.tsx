import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,describe,it,expect,vi} from 'vitest';
import {VendorWorkPanel} from './VendorWorkPanel';
import {FinanceWorkPanel} from './FinanceWorkPanel';
import {vendorApi} from './vendor-api';
import {financeApi} from './finance-api';
import {WorkspaceApiError} from './workspace-api';
import {actual as vendorActual,actualOptions,actualProposal} from './vendor-test-fixture';
import {actual as financeActual,actualFinanceOptions,actualFinanceCatalog,actualFinanceProposal} from './finance-test-fixture';
import {validateVendor} from './vendor-contract';
import {validateFinance} from './finance-contract';
import {emptyVendorRecovery,type VendorRecoveryRecord} from './vendor-recovery';
import {emptyFinanceRecovery,type FinanceRecoveryRecord} from './finance-recovery';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const identity={mode:'clerk_jwt' as const,getToken:async()=>'invented-local-token'};
type RecordValue=VendorRecoveryRecord|FinanceRecoveryRecord;
function store(initial:RecordValue|null){let saved=initial;return {value:()=>saved,access:{authorize:vi.fn(async()=>{}),load:vi.fn(async():Promise<unknown>=>saved),persist:vi.fn(async(value:RecordValue|null)=>{saved=structuredClone(value);}),denied:vi.fn()}};}
async function savedRecord(kind:'delivery'|'payment',complete=false):Promise<RecordValue>{
  if(kind==='delivery'){const op=await actualProposal();return {...emptyVendorRecovery(op.scope),pending:op,receipt:complete?validateVendor('CommandResponse',vendorActual.proposal_receipt):null};}
  const op=await actualFinanceProposal();return {...emptyFinanceRecovery(op.scope),pending:op,receipt:complete?validateFinance('FinanceResponse',financeActual.proposal_receipt):null};
}
describe('explicit initialization recovery without discarding edited data or sending work',()=>{
  let root:Root,container:HTMLDivElement;
  beforeEach(()=>{Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.stubGlobal('crypto',webcrypto);container=document.createElement('div');document.body.append(container);root=createRoot(container);
    vi.spyOn(vendorApi,'options').mockResolvedValue(actualOptions());vi.spyOn(vendorApi,'catalog').mockResolvedValue(validateVendor('Catalog',vendorActual.catalog));vi.spyOn(vendorApi,'execute');vi.spyOn(vendorApi,'recover');
    vi.spyOn(financeApi,'options').mockResolvedValue(actualFinanceOptions());vi.spyOn(financeApi,'catalog').mockResolvedValue(actualFinanceCatalog());vi.spyOn(financeApi,'execute');vi.spyOn(financeApi,'recover');
  });
  afterEach(async()=>{await act(async()=>root.unmount());container.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});
  const button=(text:string)=>Array.from(container.querySelectorAll('button')).find(b=>b.textContent===text);
  const waitUi=async(check:()=>void)=>{for(let i=0;i<200;i++){await act(async()=>{await new Promise(r=>setTimeout(r,5));});try{check();return;}catch{/* Wait for the observable result of validation. */}}check();};
  const click=async(text:string)=>{await waitUi(()=>{expect(button(text)).toBeTruthy();expect(button(text)!.matches(':disabled')).toBe(false);});await act(async()=>button(text)!.click());await waitUi(()=>expect(container.querySelector('[aria-busy="true"]')).toBeNull());};
  const render=async(kind:'delivery'|'payment',s:ReturnType<typeof store>)=>{await act(async()=>root.render(kind==='delivery'?<VendorWorkPanel identity={identity} workspaceId={actualOptions().workspace_id} recovery={s.access}/>:<FinanceWorkPanel identity={identity} workspaceId={actualFinanceOptions().workspace_id} recovery={s.access}/>));};
  const noActivity=()=>{expect(vendorApi.execute).not.toHaveBeenCalled();expect(vendorApi.recover).not.toHaveBeenCalled();expect(financeApi.execute).not.toHaveBeenCalled();expect(financeApi.recover).not.toHaveBeenCalled();};
  for(const kind of ['delivery','payment'] as const){
    it(`${kind}: retries a transient initialization failure, then offers the exact retained command for explicit restore`,async()=>{
      const original=await savedRecord(kind),s=store(original);s.access.authorize.mockRejectedValueOnce(new WorkspaceApiError(503));await render(kind,s);
      await waitUi(()=>expect(button('Retry loading private recovery')).toBeTruthy());expect(s.access.load).not.toHaveBeenCalled();expect(s.access.persist).not.toHaveBeenCalled();noActivity();
      await click('Retry loading private recovery');await waitUi(()=>expect(button(`Restore ${kind} draft`)).toBeTruthy());expect(s.access.authorize).toHaveBeenCalledTimes(2);expect(s.access.persist).not.toHaveBeenCalled();expect(s.value()).toEqual(original);noActivity();
      await click(`Restore ${kind} draft`);expect(s.value()?.pending).toEqual(original.pending);expect(s.value()?.receipt).toEqual(original.receipt);expect(button('Retry loading private recovery')).toBeUndefined();noActivity();
    });
    it.each([401,403,404])(`${kind}: failed reauthorization with %s withholds content and the retry`,async status=>{
      const s=store(await savedRecord(kind));s.access.authorize.mockRejectedValueOnce(new WorkspaceApiError(503)).mockRejectedValueOnce(new WorkspaceApiError(status));await render(kind,s);await click('Retry loading private recovery');
      expect(container.querySelector('textarea')).toBeNull();expect(button('Retry loading private recovery')).toBeUndefined();expect(s.access.load).not.toHaveBeenCalled();expect(s.access.persist).not.toHaveBeenCalled();expect(s.access.denied).toHaveBeenLastCalledWith(expect.objectContaining({status}));noActivity();
    });
    it.each(['CAS conflict','journal capacity']) (`${kind}: a ${'%s'} failure preserves edited text and proof without initialization retry`,async reason=>{
      const original=await savedRecord(kind,true),s=store(original);await render(kind,s);await click(`Restore ${kind} draft`);
      s.access.persist.mockRejectedValueOnce(new Error(reason));const text=Array.from(container.querySelectorAll('label')).find(l=>l.textContent?.startsWith(kind==='delivery'?'Expected outcome':'Expected payment outcome'))!.querySelector('textarea')!;
      await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(text,'Retain this edited local outcome');text.dispatchEvent(new Event('input',{bubbles:true}));});
      await waitUi(()=>expect(container.textContent).toContain('Previous saved commands and receipts are retained'));expect(text.value).toBe('Retain this edited local outcome');expect(s.value()?.pending).toEqual(original.pending);expect(s.value()?.receipt).toEqual(original.receipt);expect(button('Retry loading private recovery')).toBeUndefined();expect(s.access.load).toHaveBeenCalledTimes(1);noActivity();
    });
  }
  it('clears the delivery loading error only after a successful complete explicit refresh',async()=>{
    vi.mocked(vendorApi.options).mockRejectedValueOnce(new WorkspaceApiError(503));const s=store(null);await render('delivery',s);
    await waitUi(()=>expect(container.textContent).toContain('Delivery connections could not be loaded'));
    vi.mocked(vendorApi.catalog).mockRejectedValueOnce(new WorkspaceApiError(503));await click('Refresh local work and connections');expect(container.textContent).toContain('Delivery connections could not be loaded');
    await click('Refresh local work and connections');expect(container.textContent).not.toContain('Delivery connections could not be loaded');expect(container.textContent).toContain(actualOptions().connections[0].label);expect(s.access.persist).not.toHaveBeenCalled();noActivity();
  });
});
