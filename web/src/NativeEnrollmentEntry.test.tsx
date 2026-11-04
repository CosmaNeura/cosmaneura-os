import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {NativeEnrollmentEntry} from './NativeEnrollmentEntry';
import {createNativeEnrollmentApi,parseNativeAccountState,nativeAccountEntryRequested,nativeSelectedPracticeCapabilities,type NativeAccountState,type NativeEnrollmentPort} from './native-enrollment';
import {parseNativeAuthState} from './native-auth';
import {enrollmentConfig,enrollmentStatus} from './enrollment-test-fixture';
import {nativePracticeFixture} from './native-practice-test-fixture';
import {useUnsavedWork} from './unsaved-work';
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
it('requires the separate exact native selected-practice capability and ignores unqualified hints',()=>{
  expect(nativeSelectedPracticeCapabilities({contract_version:'cosmabot.native-selected-practice.v1',available:true})).toBe(true);
  for(const value of [null,{contract_version:'cosmabot.native-practice-connection.v1',available:true},
    {contract_version:'cosmabot.native-selected-practice.v1',available:false},
    {contract_version:'cosmabot.native-selected-practice.v1',available:true,practiceId:'browser-choice'}])
    expect(nativeSelectedPracticeCapabilities(value)).toBe(false);
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
  expect(vi.mocked(owner.plugin.enrollmentRequest).mock.calls.map(([input])=>input.operation)).toEqual(['config','status','config','practices']);
  expect(owner.plugin.accountToken).not.toHaveBeenCalled();expect(owner.plugin.activateRegisteredPractice).not.toHaveBeenCalled();expect(fetch).not.toHaveBeenCalled();
});
function readyPracticePort(){
  const owner=port(account),snapshot=nativePracticeFixture();
  let saved=enrollmentStatus('ready',7);saved.practice!.id=snapshot.profile.practice.practice_id;
  saved.workspace={status:'ready',url:snapshot.profile.workspace.url,organization_id:snapshot.profile.nativeIdentity.organizationId,box_id:snapshot.profile.practice.box_id};
  vi.mocked(owner.plugin.activateRegisteredPractice).mockResolvedValue(snapshot);
  vi.mocked(owner.plugin.enrollmentRequest).mockImplementation(async({operation})=>({status:200,body:operation==='config'?enrollmentConfig():operation==='practices'?{
    active_practice_id:saved.practice!.id,practices:[{id:saved.practice!.id,legal_name:saved.practice!.legal_name,display_name:'Invented Ready Practice',role:'owner',workspace_status:'ready'},
      {id:'20000000-0000-4000-8000-000000000002',legal_name:'Invented Second Practice',display_name:'Invented Second Practice',role:'staff',workspace_status:'ready'}]}:structuredClone(saved)}));
  return {...owner,changeCurrent:()=>{saved={...saved,revision:8,practice:{...saved.practice!,id:'20000000-0000-4000-8000-000000000002'}};}};
}
it('takes an existing synthetic ready account straight from verified practices to Chief without an agreement or card stepper',async()=>{
  const owner=readyPracticePort();await act(async()=>root.render(<NativeEnrollmentEntry plugin={owner.plugin} available readyPractices onReturn={vi.fn()}/>));
  expect(host.querySelector('[aria-label="Ready practices"]')?.textContent).toContain('Invented Ready PracticeCurrent practice');
  expect(host.textContent).toContain('Invented Second Practice');expect(host.querySelector('select')).toBeNull();
  expect(host.querySelector('#enrollment-name')).toBeNull();expect(host.textContent).not.toContain('Agreement');expect(host.textContent).not.toContain('14-day');
  expect(owner.plugin.activateRegisteredPractice).not.toHaveBeenCalled();expect(owner.plugin.beginAccountSignIn).not.toHaveBeenCalled();
  await click('Open Chief');expect(owner.plugin.activateRegisteredPractice).toHaveBeenCalledWith({expectedRevision:revision});
  expect(host.textContent).toContain('Opening your practice');
  expect(vi.mocked(owner.plugin.enrollmentRequest).mock.calls.map(([input])=>input.operation)).toEqual(['config','status','practices','status','practices']);
  expect(owner.plugin.activatePracticeOrganization).not.toHaveBeenCalled();expect(owner.plugin.openCheckout).not.toHaveBeenCalled();expect(fetch).not.toHaveBeenCalled();
});
it('rechecks a saved current practice and refuses Chief when another selection is observed',async()=>{
  const owner=readyPracticePort();await act(async()=>root.render(<NativeEnrollmentEntry plugin={owner.plugin} available readyPractices onReturn={vi.fn()}/>));
  owner.changeCurrent();await click('Open Chief');expect(owner.plugin.activateRegisteredPractice).not.toHaveBeenCalled();
  expect(host.textContent).toContain('Your current practice changed');expect(host.querySelector('[aria-label="Ready practices"]')).toBeNull();
  expect(host.querySelector('#enrollment-name')).toBeNull();
});
it('keeps returning locked during a ready-practice check and clears names on an owner change',async()=>{
  const owner=readyPracticePort(),returned=vi.fn();let finish!:(value:unknown)=>void;
  await act(async()=>root.render(<NativeEnrollmentEntry plugin={owner.plugin} available readyPractices onReturn={returned}/>));
  vi.mocked(owner.plugin.enrollmentRequest).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
  await click('Check practices');
  for(const name of ['Return to original beta workspace','Check practices']){
    expect([...host.querySelectorAll('button')].find(button=>button.textContent===name)?.disabled).toBe(true);await click(name);
  }
  expect(returned).not.toHaveBeenCalled();expect(owner.plugin.returnToBeta).not.toHaveBeenCalled();
  await act(async()=>owner.emit({phase:'unavailable',revision:'00000000-0000-4000-8000-000000000003',identity:null}));
  expect(host.textContent).not.toContain('Invented Ready Practice');expect(host.querySelector('#enrollment-name')).toBeNull();
  await act(async()=>finish({status:200,body:enrollmentStatus('ready',9)}));expect(host.textContent).not.toContain('Invented Ready Practice');
  expect(owner.plugin.activateRegisteredPractice).not.toHaveBeenCalled();
});
it('starts the existing new-practice flow only through its separate explicit action',async()=>{
  const owner=port(account);await act(async()=>root.render(<NativeEnrollmentEntry plugin={owner.plugin} available readyPractices onReturn={vi.fn()}/>));
  expect(host.textContent).toContain('No ready practice');expect(host.querySelector('#enrollment-name')).toBeNull();
  await click('Create a new practice');expect(host.querySelector('#enrollment-name')).not.toBeNull();
  expect(owner.plugin.activateRegisteredPractice).not.toHaveBeenCalled();
});
type PracticeRevisions={account:number;originalPractice:number;selectedPractice:number};
function namedPracticePort(interrupt:false|'before-save'|'after-save'=false,revisions:PracticeRevisions={account:4,originalPractice:3,selectedPractice:3}){
  const owner=port(account),first=nativePracticeFixture(),practiceId='20000000-0000-4000-8000-000000000002',otherPracticeId='20000000-0000-4000-8000-000000000004';
  const second={...first,profile:{...first.profile,practice:{practice_id:practiceId,box_id:'20000000-0000-4000-8000-000000000003'},
    nativeIdentity:{...first.profile.nativeIdentity,organizationId:'org_second',apiOrigin:`https://api.${practiceId}.staging.cosmas.ai`},
    workspace:{...first.profile.workspace,url:`https://${practiceId}.staging.cosmas.ai/chief`}}};
  const originalRevision=revisions.account+revisions.originalPractice,selectedRevision=revisions.account+1+revisions.selectedPractice;
  let saved=enrollmentStatus('ready',originalRevision),otherCurrent=false;saved.practice!.id=first.profile.practice.practice_id;
  saved.workspace={status:'ready',url:first.profile.workspace.url,organization_id:first.profile.nativeIdentity.organizationId,box_id:first.profile.practice.box_id};
  owner.plugin.selectedPracticeCapabilities=vi.fn(async()=>({contract_version:'cosmabot.native-selected-practice.v1',available:true}));
  owner.plugin.activateSelectedPractice=vi.fn(async()=>second);
  vi.mocked(owner.plugin.enrollmentRequest).mockImplementation(async input=>{
    if(input.operation==='selectPractice'){
      expect(input.body).toEqual({expected_revision:originalRevision,practice_id:practiceId});expect(input.idempotencyKey).toMatch(/^[0-9a-f-]{36}$/);
      if(interrupt==='before-save'){interrupt=false;throw new Error('Synthetic uncertain transport');}
      saved={...saved,revision:selectedRevision,practice:{...saved.practice!,id:practiceId},workspace:{status:'ready',url:second.profile.workspace.url,
        organization_id:second.profile.nativeIdentity.organizationId,box_id:second.profile.practice.box_id}};
      if(interrupt==='after-save'){interrupt=false;throw new Error('Synthetic reply lost after save');}
    }
    return {status:200,body:input.operation==='config'?enrollmentConfig():input.operation==='practices'?{active_practice_id:saved.practice!.id,
      practices:[{id:first.profile.practice.practice_id,legal_name:'Invented First',display_name:'Invented First',role:'owner',workspace_status:'ready'},
        {id:practiceId,legal_name:'Invented Second',display_name:'Invented Second',role:'staff',workspace_status:'ready'},
        ...(otherCurrent?[{id:otherPracticeId,legal_name:'Invented Other',display_name:'Invented Other',role:'staff',workspace_status:'ready'}]:[])]}:structuredClone(saved)};
  });
  return {...owner,practiceId,changeCurrentAtSameRevision:()=>{otherCurrent=true;saved={...saved,practice:{...saved.practice!,id:otherPracticeId},
    workspace:{...saved.workspace,organization_id:'org_other',box_id:'20000000-0000-4000-8000-000000000005'}};}};
}
it('opens an explicitly chosen ready practice through the bound native operation without agreement or billing requests',async()=>{
  const owner=namedPracticePort();await act(async()=>root.render(<NativeEnrollmentEntry plugin={owner.plugin} available readyPractices onReturn={vi.fn()}/>));
  await click('Invented Second');expect(owner.plugin.activateSelectedPractice).not.toHaveBeenCalled();
  expect(vi.mocked(owner.plugin.enrollmentRequest).mock.calls.some(([input])=>input.operation==='selectPractice')).toBe(false);
  await click('Open selected practice');expect(owner.plugin.activateSelectedPractice).toHaveBeenCalledWith({expectedRevision:revision,expectedPracticeId:owner.practiceId,expectedRegistryRevision:8});
  expect(owner.plugin.activateRegisteredPractice).not.toHaveBeenCalled();expect(host.textContent).toContain('Opening your practice');
  expect(vi.mocked(owner.plugin.enrollmentRequest).mock.calls.map(([input])=>input.operation)).toEqual(['config','status','practices','selectPractice','status','practices']);
  expect(owner.plugin.activatePracticeOrganization).not.toHaveBeenCalled();expect(owner.plugin.openCheckout).not.toHaveBeenCalled();expect(fetch).not.toHaveBeenCalled();
});
it('keeps uncertain selection locked and retries only the same checked request and idempotency key',async()=>{
  const owner=namedPracticePort('before-save'),returned=vi.fn();
  await act(async()=>root.render(<NativeEnrollmentEntry plugin={owner.plugin} available readyPractices onReturn={returned}/>));
  await click('Invented Second');await click('Open selected practice');expect(host.textContent).toContain('Your practice choice may be saved');
  expect([...host.querySelectorAll('button')].find(button=>button.textContent==='Return to original beta workspace')?.disabled).toBe(true);
  expect(host.textContent).not.toContain('Retry saved choice');expect(owner.plugin.activateSelectedPractice).not.toHaveBeenCalled();
  await click('Check saved choice');await click('Retry saved choice');
  const selections=vi.mocked(owner.plugin.enrollmentRequest).mock.calls.map(([input])=>input).filter(input=>input.operation==='selectPractice');
  expect(selections).toHaveLength(2);expect(selections[0]).toEqual(selections[1]);
  expect(owner.plugin.activateSelectedPractice).toHaveBeenCalledOnce();expect(returned).not.toHaveBeenCalled();
});
it.each([
  {change:'higher',account:4,originalPractice:3,selectedPractice:3,selectedRevision:8},
  {change:'equal',account:4,originalPractice:10,selectedPractice:9,selectedRevision:14},
  {change:'lower',account:4,originalPractice:10,selectedPractice:5,selectedRevision:10},
])('recovers a saved choice with a $change composite revision after a lost reply without selecting twice or opening automatically',async({selectedRevision,...revisions})=>{
  const owner=namedPracticePort('after-save',revisions);await act(async()=>root.render(<NativeEnrollmentEntry plugin={owner.plugin} available readyPractices onReturn={vi.fn()}/>));
  await click('Invented Second');await click('Open selected practice');await click('Check saved choice');
  expect(owner.plugin.activateSelectedPractice).not.toHaveBeenCalled();expect(host.textContent).not.toContain('Retry saved choice');
  expect(host.textContent).not.toContain('Your current practice changed');expect(host.textContent).not.toContain('Your practice choice may be saved');
  expect([...host.querySelectorAll('button')].find(button=>button.textContent==='Return to original beta workspace')?.disabled).toBe(false);
  const open=[...host.querySelectorAll('button')].find(button=>button.textContent==='Open Chief');expect(open?.disabled).toBe(false);
  expect(vi.mocked(owner.plugin.enrollmentRequest).mock.calls.filter(([input])=>input.operation==='selectPractice')).toHaveLength(1);
  await click('Open Chief');expect(owner.plugin.activateSelectedPractice).toHaveBeenCalledWith({expectedRevision:revision,expectedPracticeId:owner.practiceId,expectedRegistryRevision:selectedRevision});
  expect(vi.mocked(owner.plugin.enrollmentRequest).mock.calls.filter(([input])=>input.operation==='selectPractice')).toHaveLength(1);
});
it('requires a fresh choice when another current practice has the pending choice’s expected composite revision',async()=>{
  const owner=namedPracticePort('before-save');await act(async()=>root.render(<NativeEnrollmentEntry plugin={owner.plugin} available readyPractices onReturn={vi.fn()}/>));
  await click('Invented Second');await click('Open selected practice');owner.changeCurrentAtSameRevision();await click('Check saved choice');
  expect(host.textContent).toContain('Your current practice changed');expect(host.textContent).not.toContain('Retry saved choice');
  expect(owner.plugin.activateSelectedPractice).not.toHaveBeenCalled();
  expect(vi.mocked(owner.plugin.enrollmentRequest).mock.calls.filter(([input])=>input.operation==='selectPractice')).toHaveLength(1);
  await click('Invented Second');await click('Open selected practice');
  const selections=vi.mocked(owner.plugin.enrollmentRequest).mock.calls.map(([input])=>input).filter(input=>input.operation==='selectPractice');
  expect(selections).toHaveLength(2);expect(selections[0].idempotencyKey).not.toBe(selections[1].idempotencyKey);
  expect(owner.plugin.activateSelectedPractice).toHaveBeenCalledOnce();
});
it('does not select or open another practice while an existing editor or request fence is active',async()=>{
  const owner=namedPracticePort();function WorkFence({pending}:{pending:boolean}){useUnsavedWork(pending);return null;}
  const screen=(pending:boolean)=><><WorkFence pending={pending}/><NativeEnrollmentEntry plugin={owner.plugin} available readyPractices onReturn={vi.fn()}/></>;
  await act(async()=>root.render(screen(true)));
  const choice=[...host.querySelectorAll('button')].find(button=>button.textContent==='Invented Second')!;
  expect(choice.disabled).toBe(true);await act(async()=>choice.click());
  expect(vi.mocked(owner.plugin.enrollmentRequest).mock.calls.some(([input])=>input.operation==='selectPractice')).toBe(false);
  expect(owner.plugin.activateSelectedPractice).not.toHaveBeenCalled();
  await act(async()=>root.render(screen(false)));expect(choice.disabled).toBe(false);
  await click('Invented Second');await click('Open selected practice');expect(owner.plugin.activateSelectedPractice).toHaveBeenCalledOnce();
});
it('takes a newly allocated UUID practice from native sign-in through membership confirmation to the owned Chief handoff',async()=>{
  const owner=port(),practiceId='20000000-0000-4000-8000-000000000001';
  let saved=enrollmentStatus('finishing_setup',4);saved.practice!.id=practiceId;saved.billing.status='trialing';
  saved.workspace={status:'ready',url:null,organization_id:'org_invented',box_id:'00000000-0000-4000-8000-000000000004',confirmation_available:true};
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
