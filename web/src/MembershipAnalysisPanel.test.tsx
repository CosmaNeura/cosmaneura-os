import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {beforeEach,afterEach,it,expect,vi} from 'vitest';
import {MembershipAnalysisPanel} from './MembershipAnalysisPanel';
import {membershipApi} from './membership-api';
import {financeApi} from './finance-api';
import membership from './__fixtures__/membership-analysis-w88.json';
import payment from './__fixtures__/payment-analysis-w88.json';
import type {ConversationInput} from './workspace-api';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
let root:Root,element:HTMLDivElement;
const submit=vi.fn(async(_body:ConversationInput)=>{}),identity={mode:'clerk_jwt' as const,getToken:async()=>null};
beforeEach(()=>{vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);submit.mockClear();element=document.createElement('div');document.body.append(element);root=createRoot(element);
  vi.spyOn(membershipApi,'bootstrap').mockResolvedValue({scope:membership.detail.scope} as never);
  vi.spyOn(membershipApi,'catalog').mockResolvedValue({items:[membership.detail.summary]} as never);
  vi.spyOn(membershipApi,'detail').mockResolvedValue({detail:membership.detail} as never);
  vi.spyOn(financeApi,'catalog').mockResolvedValue({items:[payment.detail.summary],next_cursor:null} as never);
  vi.spyOn(financeApi,'detail').mockResolvedValue(payment.detail as never);
});
afterEach(async()=>{await act(async()=>root.unmount());element.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});
async function mount(kind:'membership'|'payment'='membership',revision=3){const f=kind==='membership'?membership:payment;await act(async()=>root.render(<MembershipAnalysisPanel identity={identity} workspaceId={f.workspace.id} workspaceRevision={revision} teamRevision={1} botAddress={f.request.role} enabled modelEnabled locked={false} onSubmit={submit} onDenied={()=>{}} onOpenWork={()=>{}} membershipEnabled={kind==='membership'} paymentEnabled={kind==='payment'}/>));}
const button=(name:string)=>[...element.querySelectorAll('button')].find(b=>b.textContent===name)!;
async function choose(kind:'membership'|'payment'){const f=kind==='membership'?membership:payment;await act(async()=>{const select=element.querySelectorAll('select')[1];select.value=f.detail.summary.ticket_id;select.dispatchEvent(new Event('change',{bubbles:true}));});await act(async()=>button('Review selected evidence').click());await vi.waitFor(async()=>{await act(async()=>{await new Promise(r=>setTimeout(r,0));});expect(button('Ask Membership/Billing')).toBeDefined();});}
for(const kind of ['membership','payment'] as const)it(`${kind} requires evidence review and fresh consent, sends one request`,async()=>{
  await mount(kind);expect(submit).not.toHaveBeenCalled();await choose(kind);expect(button('Ask Membership/Billing').disabled).toBe(true);
  await act(async()=>element.querySelector('input')!.click());const b=button('Ask Membership/Billing');await act(async()=>{b.click();b.click();});
  expect(submit).toHaveBeenCalledTimes(1);expect(submit.mock.calls[0][0].membership_analysis).toEqual((kind==='membership'?membership:payment).request.membership_analysis);
});
it('encounter revision change clears reviewed evidence and consent',async()=>{
  await mount();await choose('membership');await act(async()=>element.querySelector('input')!.click());await mount('membership',4);
  expect(element.querySelector('input')).toBeNull();expect(submit).not.toHaveBeenCalled();
});
it('ignores a detail reply from a previous encounter revision',async()=>{
  let finish!:(value:never)=>void;vi.mocked(membershipApi.detail).mockImplementationOnce(()=>new Promise(r=>{finish=r;}));
  await mount();const select=element.querySelectorAll('select')[1];await act(async()=>{select.value=membership.detail.summary.ticket_id;select.dispatchEvent(new Event('change',{bubbles:true}));});
  await act(async()=>button('Review selected evidence').click());await mount('membership',4);await act(async()=>finish({detail:membership.detail} as never));
  expect(element.querySelector('input')).toBeNull();expect(submit).not.toHaveBeenCalled();
});
