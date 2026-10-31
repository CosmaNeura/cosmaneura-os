import {act} from 'react';import {createRoot,type Root} from 'react-dom/client';import {afterEach,expect,it,vi} from 'vitest';
import {EnrollmentFlow} from './EnrollmentFlow';import {createEnrollmentApi,type EnrollmentIdentity} from './enrollment-api';
import {EnrollmentError} from './enrollment-contract';
const environment=(globalThis as typeof globalThis&{process?:{env:Record<string,string|undefined>}}).process?.env;
const base=environment?.COSMAS_ENROLLMENT_LAB_URL;
const actualFetch=globalThis.fetch.bind(globalThis);let roots:Root[]=[];
afterEach(async()=>{await act(async()=>roots.forEach(root=>root.unmount()));roots=[];document.body.replaceChildren();vi.restoreAllMocks();vi.unstubAllGlobals();});
it.skipIf(!base)('runs signed account, legal practice, denied staff signer, pending activation, canceled checkout return and paid-seat recovery through the real synthetic API',async()=>{
  const address=new URL(base!);expect(address.protocol).toBe('http:');expect(['127.0.0.1','localhost']).toContain(address.hostname);
  const util='node:util';const {transferableAbortController}=await import(/* @vite-ignore */util) as {transferableAbortController:()=>AbortController};
  const native=transferableAbortController();vi.stubGlobal('AbortController',native.constructor);vi.stubGlobal('AbortSignal',native.signal.constructor);
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);
  const cryptoModule='node:crypto';const {webcrypto}=await import(/* @vite-ignore */cryptoModule) as {webcrypto:Crypto};vi.stubGlobal('crypto',webcrypto);
  vi.stubGlobal('fetch',async(input:RequestInfo|URL,init?:RequestInit)=>{const response=await actualFetch(input,init);
    return new Response(await response.arrayBuffer(),{status:response.status,headers:response.headers});});
  async function lab(path:string,body:object){const response=await fetch(base+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    if(response.status===404&&path==='/lab/reset')return;
    expect(response.ok).toBe(true);const value=await response.json();expect(value.data_mode).toBe('synthetic');return value;}
  await lab('/lab/reset',{});
  const api=createEnrollmentApi(base!),config=await api.config();expect(config.data_mode).toBe('synthetic');
  const owner=await lab('/lab/session',{user:'owner-a'}) as {token:string;email:string;display_name:string};
  const staff=await lab('/lab/session',{user:'staff-a'}) as {token:string;email:string;display_name:string};
  const ownerId:EnrollmentIdentity={getToken:async()=>owner.token,isCurrent:()=>true};
  const staffId:EnrollmentIdentity={getToken:async()=>staff.token,isCurrent:()=>true};
  const ownerHost=document.createElement('div'),staffHost=document.createElement('div');document.body.append(ownerHost,staffHost);
  let ownerRoot=createRoot(ownerHost),staffRoot=createRoot(staffHost);roots.push(ownerRoot,staffRoot);
  const navigations:string[]=[];
  async function wait(check:()=>void){const end=performance.now()+10000;while(performance.now()<end){let done=false;
    await act(async()=>{await new Promise(resolve=>setTimeout(resolve,10));try{check();done=true;}catch{}});if(done)return;}check();}
  const button=(host:HTMLElement,label:string)=>[...host.querySelectorAll('button')].find(item=>item.textContent?.trim()===label)!;
  async function click(host:HTMLElement,label:string){await wait(()=>{expect(button(host,label),host.textContent??'').toBeTruthy();expect(button(host,label).disabled).toBe(false);});await act(async()=>button(host,label).click());await wait(()=>expect(host.querySelector('[aria-busy="true"]')).toBeNull());}
  async function fill(host:HTMLElement,name:string,value:string){await wait(()=>expect(host.querySelector('#enrollment-'+name),host.textContent??'').toBeTruthy());await act(async()=>{
    const input=host.querySelector<HTMLInputElement>('#enrollment-'+name)!;Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,value);input.dispatchEvent(new Event('input',{bubbles:true}));});}
  async function checked(host:HTMLElement,name:string){await act(async()=>host.querySelector<HTMLInputElement>('#enrollment-'+name)!.click());}
  const ownerFlow=()=>ownerRoot.render(<EnrollmentFlow api={api} identity={ownerId} config={config} initialName={owner.display_name} initialEmail={owner.email} search="?plan=small&seats=5&price=1" navigate={url=>navigations.push(url)}/>);
  await act(ownerFlow);await fill(ownerHost,'name','Invented Owner');await fill(ownerHost,'title','Owner');await click(ownerHost,'Save and continue');
  await wait(()=>expect(ownerHost.textContent).toContain('Set up your practice'));
  expect(ownerHost.textContent).toContain('$700/month');
  for(const [field,value]of Object.entries({legal_name:'Invented Onboarding Clinic',address_line1:'123 Invented Street',city:'Invented City',region:'NY',postal_code:'10001',administrative_email:'office@example.invalid'}))await fill(ownerHost,field,value);
  await checked(ownerHost,'covered');await click(ownerHost,'Save and continue');await wait(()=>expect(ownerHost.querySelector('iframe')).toBeTruthy());
  const savedPractice=await api.status(ownerId);expect(savedPractice.practice?.human_seats).toBe(5);expect(savedPractice.quote?.monthly_total_cents).toBe(70000);
  const invitation=await api.invitation(ownerId,{expected_revision:savedPractice.revision,email:staff.email,role:'staff',can_sign:false},crypto.randomUUID());
  await act(async()=>staffRoot.render(<EnrollmentFlow api={api} identity={staffId} config={config} initialName={staff.display_name} initialEmail={staff.email} search={'?invite='+encodeURIComponent(invitation.token)} navigate={url=>navigations.push(url)}/>));
  await wait(()=>expect(button(staffHost,'Join practice')||staffHost.querySelector('#enrollment-name')).toBeTruthy());
  if(staffHost.querySelector('#enrollment-name')){await fill(staffHost,'name','Invented Staff');await fill(staffHost,'title','Staff');await click(staffHost,'Save and continue');}
  await click(staffHost,'Join practice');await wait(()=>expect(staffHost.querySelector('iframe')).toBeTruthy());
  await wait(()=>expect(staffHost.textContent).toContain('An authorized representative must sign'));
  const staffStatus=await api.status(staffId);expect(staffStatus.practice?.can_sign).toBe(false);
  await expect(api.accept(staffId,{expected_revision:staffStatus.revision,doc_id:config.baa.doc_id,version:config.baa.version,sha256:config.baa.sha256,
    signature_name:'Invented Staff',signature_title:'Staff',authority_confirmed:true,accepted:true},crypto.randomUUID())).rejects.toMatchObject({status:403,code:'enrollment_signer_required'});
  expect((await api.status(staffId)).agreement?.accepted).toBe(false);
  expect(navigations).toEqual([]);
  // Staff membership changed the practice revision; reload before the owner signs.
  await act(async()=>ownerRoot.unmount());roots=roots.filter(root=>root!==ownerRoot);ownerRoot=createRoot(ownerHost);roots.push(ownerRoot);await act(ownerFlow);
  await wait(()=>expect(ownerHost.querySelector('iframe')).toBeTruthy());await checked(ownerHost,'authority');await checked(ownerHost,'accepted');await click(ownerHost,'Accept agreement');
  await wait(()=>expect(ownerHost.textContent).toContain('Your trial clock has not started'));
  const accepted=await api.status(ownerId);expect(accepted.billing.trial_ends_at).toBeNull();expect(accepted.stage).toBe('activation_pending');
  await click(ownerHost,'View agreement receipt');await wait(()=>expect(ownerHost.textContent).toContain('Agreement acceptance receipt'));
  await lab('/lab/qualify',{practice_id:accepted.practice!.id});await click(ownerHost,'Check setup and payment');await click(ownerHost,'Continue securely with Stripe');
  await wait(()=>expect(navigations).toHaveLength(1));const firstCheckout=navigations[0];expect(firstCheckout).toContain('https://checkout.stripe.com/');
  // Browser cancellation abandons hosted Checkout; reopening recovers the same server/provider attempt.
  await act(async()=>ownerRoot.unmount());roots=roots.filter(root=>root!==ownerRoot);ownerRoot=createRoot(ownerHost);roots.push(ownerRoot);await act(ownerFlow);
  await wait(()=>expect(ownerHost.textContent).toContain('Finishing setup'));expect((await api.status(ownerId)).billing.trial_ends_at).toBeNull();
  await click(ownerHost,'Check setup and payment');await click(ownerHost,'Resume secure checkout');await wait(()=>expect(navigations).toHaveLength(2));expect(navigations[1]).toBe(firstCheckout);
  const checkoutNumber=new URL(firstCheckout).pathname.match(/^\/c\/synthetic([0-9]+)$/)?.[1];expect(checkoutNumber).toBeTruthy();await lab('/lab/checkout/complete',{session_id:'cs_synthetic'+checkoutNumber});
  await click(ownerHost,'Check setup and payment');await wait(()=>expect(button(ownerHost,'Open Chief')).toBeTruthy());
  const ready=await api.status(ownerId);expect(ready.stage).toBe('ready');expect(ready.quote?.monthly_total_cents).toBe(70000);expect(ready.agreement?.accepted).toBe(true);
  await click(ownerHost,'Open Chief');await wait(()=>expect(navigations).toContain(ready.workspace.url));
  // Staff access is granted only after the real signed confirmation endpoint verifies membership proof.
  let staffConfirmations=0;
  await act(async()=>staffRoot.unmount());roots=roots.filter(root=>root!==staffRoot);staffRoot=createRoot(staffHost);roots.push(staffRoot);
  await act(async()=>staffRoot.render(<EnrollmentFlow api={api} identity={staffId} config={config} search="" navigate={url=>navigations.push(url)}
    prepareWorkspaceToken={async value=>{staffConfirmations++;const session=await lab('/lab/session',{user:'staff-a',...(staffConfirmations>1?{organization_id:value.workspace.organization_id}:{})});return session.token;}}/>));
  await wait(()=>expect(button(staffHost,'Confirm practice account')).toBeTruthy());expect(button(staffHost,'Open Chief')).toBeUndefined();
  await click(staffHost,'Confirm practice account');await wait(()=>expect(button(staffHost,'Open Chief'),staffHost.textContent??'').toBeTruthy());expect(staffConfirmations).toBe(2);
  expect((await api.status(staffId)).stage).toBe('ready');expect(button(staffHost,'Manage billing or cancel')).toBeUndefined();
  // Ordinary team invitations use purchased human seats and no implicit signing authority.
  const teammate=await lab('/lab/session',{user:'signer-a'}) as {token:string;email:string;display_name:string};
  const teammateInvite=vi.spyOn(api,'invitation');await click(ownerHost,'Invite a teammate');await fill(ownerHost,'team_email',teammate.email);await click(ownerHost,'Create teammate invitation');
  await wait(()=>expect(ownerHost.querySelector<HTMLInputElement>('input[readonly]')?.value).toContain('/onboarding?invite='));
  expect(teammateInvite).toHaveBeenLastCalledWith(ownerId,expect.objectContaining({role:'staff',can_sign:false,email:teammate.email}),expect.any(String),expect.any(AbortSignal));
  expect(ownerHost.textContent).toContain('No email was sent');
  // A lost profile response is recovered through real durable status, with no second write.
  const second=await lab('/lab/session',{user:'owner-b'}) as {token:string;email:string;display_name:string};
  const secondId:EnrollmentIdentity={getToken:async()=>second.token,isCurrent:()=>true};
  const originalProfile=api.profile;const submitted=vi.spyOn(api,'profile').mockImplementationOnce(async(...args)=>{await originalProfile(...args);throw new EnrollmentError(503);});
  await act(async()=>ownerRoot.render(<EnrollmentFlow key="owner-b" api={api} identity={secondId} config={config} initialName={second.display_name} initialEmail={second.email}/>));
  await fill(ownerHost,'name','Invented Second Owner');await click(ownerHost,'Save and continue');await wait(()=>expect(button(ownerHost,'Check saved progress')).toBeTruthy());
  await click(ownerHost,'Check saved progress');await wait(()=>expect(ownerHost.textContent).toContain('Set up your practice'));expect(submitted).toHaveBeenCalledOnce();
  // A second legal practice has its own revision. Joining and explicitly switching must never mix scope.
  await act(async()=>ownerHost.querySelectorAll<HTMLInputElement>('input[name="enrollment-plan"]')[1].click());
  for(const [field,value]of Object.entries({legal_name:'Invented Second Legal Clinic',address_line1:'456 Invented Road',city:'Invented City',region:'NY',postal_code:'10002',administrative_email:'second@example.invalid'}))await fill(ownerHost,field,value);
  await checked(ownerHost,'covered');await click(ownerHost,'Save and continue');await wait(()=>expect(ownerHost.querySelector('iframe')).toBeTruthy());
  const practiceB=await api.status(secondId);const practiceA=await api.status(staffId);expect(practiceB.revision).toBeLessThan(practiceA.revision);
  const secondInvite=await api.invitation(secondId,{expected_revision:practiceB.revision,email:staff.email,role:'staff',can_sign:false},crypto.randomUUID());
  await act(async()=>staffRoot.unmount());roots=roots.filter(root=>root!==staffRoot);staffRoot=createRoot(staffHost);roots.push(staffRoot);
  await act(async()=>staffRoot.render(<EnrollmentFlow api={api} identity={staffId} config={config} search={'?invite='+encodeURIComponent(secondInvite.token)} navigate={url=>navigations.push(url)}/>));
  await click(staffHost,'Join practice');await wait(()=>expect(staffHost.textContent).toContain('Review and sign for Invented Second Legal Clinic'));
  expect((await api.status(staffId)).practice?.id).toBe(practiceB.practice?.id);
  await act(async()=>{const select=staffHost.querySelector<HTMLSelectElement>('select')!;select.value=practiceA.practice!.id;select.dispatchEvent(new Event('change',{bubbles:true}));});
  await click(staffHost,'Open selected practice');await wait(()=>expect(staffHost.textContent).toContain('Invented Onboarding Clinic'));
  expect((await api.status(staffId)).practice?.id).toBe(practiceA.practice?.id);
  await act(async()=>{const select=staffHost.querySelector<HTMLSelectElement>('select')!;select.value=practiceB.practice!.id;select.dispatchEvent(new Event('change',{bubbles:true}));});
  await click(staffHost,'Open selected practice');await wait(()=>expect(staffHost.textContent).toContain('Review and sign for Invented Second Legal Clinic'));
  expect((await api.status(staffId)).practice?.id).toBe(practiceB.practice?.id);
  expect(localStorage.length).toBe(0);expect(sessionStorage.length).toBe(0);
},45000);
