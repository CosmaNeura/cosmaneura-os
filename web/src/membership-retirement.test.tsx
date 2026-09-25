import {act} from 'react';
import {createRoot} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import actual from './__fixtures__/membership/actual-membership-retirement-http.json';
import {MembershipWorkPanel} from './MembershipWorkPanel';
import {membershipApi} from './membership-api';
import {validateMembership,verifyMembershipReceipt} from './membership-contract';
import {prepareMembershipOperation,verifyMembershipOperationReceipt} from './membership-operation';
import {emptyMembershipRecovery,validateMembershipRecovery,withMembershipCommand,hasUnresolvedMembershipCommand,persistMembershipRecovery,type MembershipRecoveryRecord} from './membership-recovery';
vi.mock('./PrivatePdfViewer',()=>({PrivatePdfViewer:()=>null}));
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
beforeEach(()=>{vi.stubGlobal('crypto',webcrypto);Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});});
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();vi.unstubAllEnvs();});
async function pending(){const scope=validateMembership('Scope',actual.scope),op=await prepareMembershipOperation(scope,'propose',validateMembership('Proposal',actual.old_request));return {op,record:{...emptyMembershipRecovery(scope),pending:op,receipt:await verifyMembershipOperationReceipt(op,actual.missing)}};}
it('validates actual retired, resolver and late-original proofs, then retains full original request and proof before a fresh action',async()=>{
 const {op,record}=await pending();expect(hasUnresolvedMembershipCommand(record)).toBe(true);const retired=await verifyMembershipOperationReceipt(op,actual.retired);expect(retired).toEqual(actual.resolved);expect(retired).toEqual(actual.late_original);
 const saved=await validateMembershipRecovery({...record,receipt:retired},op.scope);expect(hasUnresolvedMembershipCommand(saved)).toBe(false);
 const fresh=await prepareMembershipOperation(op.scope,'propose',validateMembership('Proposal',actual.fresh_request)),next=await validateMembershipRecovery(withMembershipCommand(saved,fresh),op.scope);
 expect(next.history).toEqual([{operation:op,receipt:retired}]);expect(next.pending).toEqual(fresh);expect(next.receipt).toBeNull();expect(saved.pending).toEqual(op);
});
it('rejects forged retirement scope/hash/reason, mismatched request and incomplete or duplicate retained history',async()=>{
 const {op,record}=await pending();
 for(const value of [{...actual.retired,receipt_sha256:'0'.repeat(64)},{...actual.retired,effect:{}},{...actual.retired,scope:{...op.scope,owner_id:crypto.randomUUID()}},{...actual.retired,retirement:{...actual.retired.retirement,reason:'service_timeout'}},{...actual.retired,unexpected:true}])await expect(verifyMembershipOperationReceipt(op,value)).rejects.toThrow();
 const forged={...op,request:{...op.request,instructions:'Different original content'}};await expect(verifyMembershipOperationReceipt(forged,actual.retired)).rejects.toThrow();
 const retired=await verifyMembershipOperationReceipt(op,actual.retired);await expect(validateMembershipRecovery({...record,receipt:retired,history:[{operation:op,receipt:retired}]},op.scope)).rejects.toThrow();
 await expect(validateMembershipRecovery({...record,history:[{operation:op,receipt:actual.missing}]},op.scope)).rejects.toThrow();
});
it('does not clear a missing receipt or lose pending proof/text on storage or capacity failure',async()=>{
 const {op,record}=await pending(),fresh=await prepareMembershipOperation(op.scope,'propose',validateMembership('Proposal',actual.fresh_request));expect(()=>withMembershipCommand(record,fresh)).toThrow();
 const retired=await verifyMembershipOperationReceipt(op,actual.retired),saved={...record,receipt:retired};saved.draft.instructions='Keep my unsent edit';
 const full={...saved,history:Array.from({length:100},()=>({operation:op,receipt:retired}))};expect(()=>withMembershipCommand(full,fresh)).toThrow();
 const before=structuredClone(saved);await expect(persistMembershipRecovery({load:async()=>saved,authorize:async()=>{},persist:async()=>{throw new Error('CAS failure');}},saved)).rejects.toThrow();expect(saved).toEqual(before);
});
it('sends only the exact typed retirement wrapper once and refuses a not_found retirement reply',async()=>{
 const {op}=await pending(),identity={boxId:op.scope.box_id,actorId:op.scope.owner_id};vi.stubEnv('VITE_API_BASE','http://127.0.0.1:8000');const fetcher=vi.fn(async()=>new Response(JSON.stringify(actual.retired),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}));vi.stubGlobal('fetch',fetcher);
 expect(await membershipApi.retire(identity,op)).toEqual(await verifyMembershipReceipt(actual.retired));expect(fetcher).toHaveBeenCalledOnce();const [path,init]=fetcher.mock.calls[0] as unknown as [string,RequestInit];expect(path).toBe(`http://127.0.0.1:8000/workspaces/${op.scope.workspace_id}/membership-work/retire`);expect(JSON.parse(init.body as string)).toEqual(actual.retire_request);expect(new Headers(init.headers).get('X-Cosmas-Membership-Contract')).toBe('1');expect(init).toMatchObject({method:'POST',redirect:'error',credentials:'omit'});
 fetcher.mockImplementation(async()=>new Response(JSON.stringify(actual.missing),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}));await expect(membershipApi.retire(identity,op)).rejects.toMatchObject({status:502});
});
it('requires an explicit fresh retirement choice and enables new preparation only after the proof is saved',async()=>{
 const {op,record}=await pending();let saved:MembershipRecoveryRecord|null=record;
 const access={load:async()=>saved,persist:async(v:MembershipRecoveryRecord|null)=>{saved=structuredClone(v);},authorize:async()=>{}};
 vi.spyOn(membershipApi,'options').mockResolvedValue(validateMembership('Options',actual.current_options));vi.spyOn(membershipApi,'catalog').mockResolvedValue({contract_version:1,scope:op.scope,items:[]});vi.spyOn(membershipApi,'retire').mockResolvedValue(await verifyMembershipReceipt(actual.retired));vi.spyOn(membershipApi,'execute');
 const container=document.createElement('div');document.body.append(container);const root=createRoot(container),identity={mode:'clerk_jwt' as const,getToken:async()=> 'invented-owner'};
 const button=(label:string)=>Array.from(container.querySelectorAll('button')).find(b=>b.textContent===label);
 const until=async(check:()=>void)=>{for(let i=0;i<150;i++){let done=false;await act(async()=>{await new Promise(r=>setTimeout(r,5));try{check();done=true;}catch{}});if(done)return;}check();};
 const click=async(label:string)=>{await until(()=>expect(button(label)?.matches(':disabled')).toBe(false));await act(async()=>button(label)!.click());};
 try{
  await act(async()=>root.render(<MembershipWorkPanel identity={identity} scope={op.scope} recovery={access} enabled/>));await click('Restore membership draft');await until(()=>expect(button('Close rejected saved request')).toBeDefined());
  expect(button('Use current reviewed note')?.matches(':disabled')).toBe(true);expect(button('Close rejected saved request')?.matches(':disabled')).toBe(true);expect(membershipApi.retire).not.toHaveBeenCalled();
  const input=Array.from(container.querySelectorAll('label')).find(l=>l.textContent?.startsWith('Prevent this exact rejected request'))!.querySelector('input')!;expect(input.checked).toBe(false);await act(async()=>input.click());await click('Close rejected saved request');
  await until(()=>expect(saved?.receipt?.outcome).toBe('retired'));expect(saved?.pending).toEqual(op);await until(()=>expect(button('Use current reviewed note')?.matches(':disabled')).toBe(false));expect(membershipApi.execute).not.toHaveBeenCalled();expect(Object.keys(saved!.draft)).not.toContain('retireChecked');
 }finally{await act(async()=>root.unmount());container.remove();}
});
