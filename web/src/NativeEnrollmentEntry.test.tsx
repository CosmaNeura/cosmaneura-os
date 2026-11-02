import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {NativeEnrollmentEntry} from './NativeEnrollmentEntry';
import {createNativeEnrollmentApi,parseNativeAccountState,nativeAccountEntryRequested,type NativeAccountState,type NativeEnrollmentPort} from './native-enrollment';
import {parseNativeAuthState} from './native-auth';
import {enrollmentConfig,enrollmentStatus} from './enrollment-test-fixture';
import {nativePracticeFixture} from './native-practice-test-fixture';
const revision='00000000-0000-4000-8000-000000000001';
const account:NativeAccountState={phase:'accountReady',revision,identity:{userId:'user_invented',sessionId:'sess_invented',email:'invented@example.invalid',displayName:'Invented clinician'}};
function port(initial:NativeAccountState={phase:'signedOut',revision,identity:null}){
  let current=initial;const listeners=new Set<(value:unknown)=>void>();
  const plugin:NativeEnrollmentPort={capabilities:vi.fn(async()=>({contract_version:'cosmabot.native-practice-connection.v1',available:true,enrollment_available:true})),
    accountStatus:vi.fn(async()=>current),beginAccountSignIn:vi.fn(async()=>{current=account;return current;}),
    accountToken:vi.fn(async()=>({revision,token:'invented.account.token'})),
    activatePracticeOrganization:vi.fn(async()=>{throw new Error('Not qualified');}),activateRegisteredPractice:vi.fn(async()=>{throw new Error('Not qualified');}),
    returnToBeta:vi.fn(async()=>{current={phase:'signedOut',revision:'00000000-0000-4000-8000-000000000002',identity:null};}),signOut:vi.fn(async()=>{}),
    addListener:vi.fn(async(_event,listener)=>{listeners.add(listener);return {remove:async()=>{listeners.delete(listener);}};}),
    openCheckout:vi.fn(async()=>{}),enrollmentRequest:vi.fn(async({operation})=>({status:200,body:operation==='config'?enrollmentConfig():operation==='status'?enrollmentStatus():
      operation==='practices'?{active_practice_id:null,practices:[]}:null})),openEnrollmentDestination:vi.fn(async()=>{}),
  };
  return {plugin,emit:(value:unknown)=>{for(const listener of listeners)listener(value);}};
}
let root:Root,host:HTMLDivElement;
beforeEach(()=>{vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubGlobal('fetch',vi.fn());host=document.createElement('div');document.body.append(host);root=createRoot(host);});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();vi.restoreAllMocks();});
async function click(text:string){const button=[...host.querySelectorAll('button')].find(value=>value.textContent===text);expect(button).toBeDefined();await act(async()=>button!.click());}
it('does not start native account or enrollment operations when unavailable',async()=>{
  const owner=port(),returned=vi.fn();await act(async()=>root.render(<NativeEnrollmentEntry plugin={owner.plugin} available={false} onReturn={returned}/>));
  expect(host.textContent).toContain('Practice connection is not available yet');expect(owner.plugin.capabilities).not.toHaveBeenCalled();
  expect(owner.plugin.enrollmentRequest).not.toHaveBeenCalled();expect(fetch).not.toHaveBeenCalled();
  await click('Return to existing workspace');expect(returned).toHaveBeenCalledOnce();
});
it('resumes only an immutable host-issued account presentation and ignores browser/query flags',()=>{
  const entry=Object.freeze({contract_version:'cosmabot.native-practice-entry.v1',entry:'account'});
  const page={location:{href:'capacitor://localhost/index.html'}};
  Object.defineProperty(page,'__cosmasNativePracticeEntry',{value:entry,writable:false,configurable:false});vi.stubGlobal('window',page);
  expect(nativeAccountEntryRequested(false)).toBe(false);expect(nativeAccountEntryRequested(true)).toBe(true);
  vi.stubGlobal('window',{location:{href:'capacitor://localhost/index.html?onboarding=true'},__cosmasNativePracticeEntry:entry});
  expect(nativeAccountEntryRequested(true)).toBe(false);
  vi.stubGlobal('window',{location:{href:'capacitor://localhost/index.html?onboarding=true'}});expect(nativeAccountEntryRequested(true)).toBe(false);
  expect(fetch).not.toHaveBeenCalled();
});
it('shows truthful unavailability when native enrollment transport is not qualified',async()=>{
  const owner=port();vi.mocked(owner.plugin.capabilities).mockResolvedValue({contract_version:'cosmabot.native-practice-connection.v1',available:true,enrollment_available:false});
  await act(async()=>root.render(<NativeEnrollmentEntry plugin={owner.plugin} available onReturn={vi.fn()}/>));
  expect(host.textContent).toContain('Practice connection is not available yet');expect(owner.plugin.accountStatus).not.toHaveBeenCalled();expect(owner.plugin.enrollmentRequest).not.toHaveBeenCalled();
});
it('starts a new synthetic account setup only after the explicit native sign-in action',async()=>{
  const owner=port();await act(async()=>root.render(<NativeEnrollmentEntry plugin={owner.plugin} available onReturn={vi.fn()}/>));
  expect(host.textContent).toContain('Connect a practice');expect(owner.plugin.beginAccountSignIn).not.toHaveBeenCalled();
  expect(vi.mocked(owner.plugin.enrollmentRequest).mock.calls.map(([input])=>input.operation)).toEqual(['config']);
  await click('Sign in or create account');expect(owner.plugin.beginAccountSignIn).toHaveBeenCalledOnce();
  expect(host.textContent).toContain('Your account');expect(host.querySelector('#enrollment-name')).not.toBeNull();
  expect(vi.mocked(owner.plugin.enrollmentRequest).mock.calls.map(([input])=>input.operation)).toEqual(['config','status','practices']);
  expect(owner.plugin.accountToken).not.toHaveBeenCalled();expect(owner.plugin.activateRegisteredPractice).not.toHaveBeenCalled();expect(fetch).not.toHaveBeenCalled();
});
it('takes a newly allocated UUID practice from native sign-in through membership confirmation to the owned Chief handoff',async()=>{
  const owner=port(),practiceId='20000000-0000-4000-8000-000000000001';
  let saved=enrollmentStatus('finishing_setup',4);saved.practice!.id=practiceId;saved.billing.status='trialing';
  saved.workspace={status:'ready',url:null,organization_id:'org_invented',box_id:'00000000-0000-4000-8000-000000000004'};
  const original=nativePracticeFixture(),snapshot={...original,profile:{...original.profile,
    practice:{...original.profile.practice,practice_id:practiceId},
    nativeIdentity:{...original.profile.nativeIdentity,apiOrigin:`https://api.${practiceId}.staging.cosmas.ai`},
    workspace:{...original.profile.workspace,url:`https://${practiceId}.staging.cosmas.ai/chief`}}};
  vi.mocked(owner.plugin.activatePracticeOrganization).mockResolvedValue({revision,token:'invented.scoped.token'});
  vi.mocked(owner.plugin.activateRegisteredPractice).mockResolvedValue(snapshot);
  vi.mocked(owner.plugin.enrollmentRequest).mockImplementation(async input=>{
    if(input.operation==='confirmWorkspace'){
      expect(input.body).toEqual({expected_revision:4,workspace_token:'invented.scoped.token'});
      saved={...saved,stage:'ready',revision:5,workspace:{...saved.workspace,url:snapshot.profile.workspace.url}};
    }
    return {status:200,body:input.operation==='config'?enrollmentConfig():input.operation==='practices'?{
      active_practice_id:practiceId,practices:[{id:practiceId,legal_name:saved.practice!.legal_name,
        display_name:saved.practice!.display_name,role:'owner',workspace_status:'ready'}]}:structuredClone(saved)};
  });
  await act(async()=>root.render(<NativeEnrollmentEntry plugin={owner.plugin} available onReturn={vi.fn()}/>));
  expect(owner.plugin.beginAccountSignIn).not.toHaveBeenCalled();await click('Sign in or create account');
  expect(host.textContent).toContain('Finishing setup');await click('Confirm practice account');
  expect(owner.plugin.activatePracticeOrganization).toHaveBeenCalledWith({expectedRevision:revision});
  expect(enrollmentConfig().allowed_workspace_origins).not.toContain(`https://${practiceId}.staging.cosmas.ai`);
  await click('Open Chief');expect(owner.plugin.activateRegisteredPractice).toHaveBeenCalledWith({expectedRevision:revision});
  expect(host.textContent).toContain('Opening your practice');expect(fetch).not.toHaveBeenCalled();
});
it('cannot turn an account without an organization into workspace access',()=>{
  expect(parseNativeAccountState(account).identity).not.toHaveProperty('organizationId');expect(()=>parseNativeAuthState(account)).toThrow();
  expect(()=>parseNativeAccountState({...account,identity:{...account.identity,organizationId:'org_invented'}})).toThrow();
});
it('requires native restoration after sign-in fails instead of reopening a retired beta graph',async()=>{
  const owner=port(),returned=vi.fn();vi.mocked(owner.plugin.beginAccountSignIn).mockRejectedValue(new Error('Sign-in did not finish'));
  await act(async()=>root.render(<NativeEnrollmentEntry plugin={owner.plugin} available onReturn={returned}/>));
  await click('Sign in or create account');expect(host.textContent).toContain('Practice connection is not available yet');
  const unavailable:NativeAccountState={phase:'unavailable',revision:'00000000-0000-4000-8000-000000000003',identity:null};
  vi.mocked(owner.plugin.accountStatus).mockResolvedValue(unavailable);vi.mocked(owner.plugin.returnToBeta).mockRejectedValueOnce(new Error('Still closing original sources'));
  await click('Return to existing workspace');expect(owner.plugin.returnToBeta).toHaveBeenCalledWith({expectedRevision:unavailable.revision});
  expect(returned).not.toHaveBeenCalled();await click('Return to existing workspace');expect(returned).toHaveBeenCalledOnce();
});
it('closes an account setup immediately on a changed or malformed native owner',async()=>{
  const owner=port(account);await act(async()=>root.render(<NativeEnrollmentEntry plugin={owner.plugin} available onReturn={vi.fn()}/>));
  expect(host.querySelector('#enrollment-name')).not.toBeNull();
  await act(async()=>owner.emit({...account,identity:{...account.identity,email:'changed@example.invalid'}}));
  expect(host.querySelector('#enrollment-name')).toBeNull();expect(host.textContent).toContain('Practice connection is not available yet');
});
it('uses closed native operations with no browser URL or token and rejects a late result after account switch',async()=>{
  let current:NativeAccountState|null=account;const owner=port(account);let finish!:(value:unknown)=>void;
  vi.mocked(owner.plugin.enrollmentRequest).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
  const api=createNativeEnrollmentApi(owner.plugin,()=>current,()=>true),identity={isCurrent:()=>current===account,getToken:vi.fn(async()=>null)};
  const pending=api.status(identity);expect(owner.plugin.enrollmentRequest).toHaveBeenCalledWith({expectedRevision:revision,operation:'status'});
  current={phase:'signedOut',revision:'00000000-0000-4000-8000-000000000002',identity:null};finish({status:200,body:enrollmentStatus()});
  await expect(pending).rejects.toMatchObject({status:401});expect(identity.getToken).not.toHaveBeenCalled();expect(fetch).not.toHaveBeenCalled();
});
