import {act} from 'react';import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {EnrollmentFlow} from './EnrollmentFlow';import {createEnrollmentApi} from './enrollment-api';
import {enrollmentConfig,enrollmentDocument,enrollmentStatus} from './enrollment-test-fixture';
import {EnrollmentError,type EnrollmentStatus} from './enrollment-contract';
let root:Root,host:HTMLDivElement,current:EnrollmentStatus;
const api=createEnrollmentApi('http://127.0.0.1:8910'),id={getToken:async()=> 'invented.token',isCurrent:()=>true},navigate=vi.fn();
beforeEach(()=>{vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);host=document.createElement('div');document.body.append(host);root=createRoot(host);current=enrollmentStatus();
  vi.spyOn(api,'status').mockImplementation(async()=>structuredClone(current));vi.spyOn(api,'practices').mockImplementation(async()=>({active_practice_id:current.practice?.id??null,practices:current.practice?[{id:current.practice.id,legal_name:current.practice.legal_name,display_name:current.practice.display_name,role:current.practice.role,workspace_status:current.workspace.status}]:[]}));vi.spyOn(api,'document').mockResolvedValue(enrollmentDocument());navigate.mockClear();});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});
const button=(name:string)=>[...host.querySelectorAll('button')].find(item=>item.textContent?.trim()===name)!;
async function click(name:string){expect(button(name),host.textContent??'').toBeDefined();await act(async()=>button(name).click());}
async function fill(name:string,value:string){await act(async()=>{const input=host.querySelector<HTMLInputElement>('#enrollment-'+name)!;
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,value);input.dispatchEvent(new Event('input',{bubbles:true}));});}
async function check(name:string){await act(async()=>host.querySelector<HTMLInputElement>('#enrollment-'+name)!.click());}
async function render(search=''){await act(async()=>root.render(<EnrollmentFlow api={api} identity={id} config={enrollmentConfig()} navigate={navigate} search={search}/>));}
it('saves account and legal practice with every human seat counted at the approved price',async()=>{
  vi.spyOn(api,'profile').mockImplementation(async()=>{current=enrollmentStatus('practice',1);return current;});
  vi.spyOn(api,'practice').mockImplementation(async()=>{current=enrollmentStatus('agreement',2,5);return current;});
  await render('?plan=small&seats=5&price=1');await fill('name','Invented Owner');await fill('title','Owner');await click('Save and continue');
  expect(host.textContent).toContain('$700/month');
  for(const [field,value]of Object.entries({legal_name:'Invented Legal Practice',address_line1:'123 Invented Street',city:'Invented City',region:'NY',postal_code:'10001',administrative_email:'office@example.invalid'}))await fill(field,value);
  await check('covered');await click('Save and continue');
  expect(api.practice).toHaveBeenCalledWith(id,expect.objectContaining({human_seats:5,country:'US',covered_entity:true}),expect.any(String),expect.any(AbortSignal));
  expect(host.textContent).toContain('Review and sign for Invented Legal Practice');expect(host.querySelector('iframe')?.getAttribute('sandbox')).toBe('');
  expect(localStorage.length).toBe(0);expect(sessionStorage.length).toBe(0);
});
it('keeps an overlong provider name editable and saves only a valid 120-character workspace name',async()=>{
  current.profile={display_name:'N'.repeat(121),title:'',email:'owner@example.invalid'};
  const save=vi.spyOn(api,'profile').mockImplementation(async(_identity,body)=>{current={...enrollmentStatus('practice',1),profile:{...enrollmentStatus('practice',1).profile!,display_name:body.display_name}};return current;});
  await render();expect(host.querySelector<HTMLInputElement>('#enrollment-name')?.maxLength).toBe(120);
  await click('Save and continue');expect(host.textContent).toContain('Use 120 characters or fewer.');expect(save).not.toHaveBeenCalled();
  await fill('name','Invented\tOwner');await click('Save and continue');expect(host.textContent).toContain('Use a name without tabs, line breaks or control characters.');expect(save).not.toHaveBeenCalled();
  await fill('name',' '+ 'N'.repeat(120)+' ');await click('Save and continue');
  expect(save).toHaveBeenCalledWith(id,{expected_revision:0,display_name:'N'.repeat(120),title:''},expect.any(String),expect.any(AbortSignal));
  expect(host.textContent).toContain('Set up your practice');
});
it('requires a shorter workspace display name for a 160-character legal name before proceeding to the agreement',async()=>{
  current=enrollmentStatus('practice',1);const legal='L'.repeat(160),display='D'.repeat(120);
  const save=vi.spyOn(api,'practice').mockImplementation(async(_identity,body)=>{current={...enrollmentStatus('agreement',2),practice:{...enrollmentStatus('agreement',2).practice!,legal_name:body.legal_name,display_name:body.display_name}};return current;});
  await render();expect(host.querySelector<HTMLInputElement>('#enrollment-legal_name')?.maxLength).toBe(160);expect(host.querySelector<HTMLInputElement>('#enrollment-display_name')?.maxLength).toBe(120);
  for(const [field,value]of Object.entries({legal_name:legal,address_line1:'123 Invented Street',city:'Invented City',region:'NY',postal_code:'10001',administrative_email:'office@example.invalid'}))await fill(field,value);
  await check('covered');await fill('display_name',' ');await click('Save and continue');
  expect(host.textContent).toContain('Enter a practice display name with 120 characters or fewer.');expect(save).not.toHaveBeenCalled();expect(host.querySelector('iframe')).toBeNull();
  await fill('display_name','D'.repeat(121));await click('Save and continue');expect(save).not.toHaveBeenCalled();
  await fill('display_name','Invented\tPractice');await click('Save and continue');expect(host.textContent).toContain('Use a display name without tabs, line breaks or control characters.');expect(save).not.toHaveBeenCalled();
  await fill('display_name',' '+display+' ');await click('Save and continue');
  expect(save).toHaveBeenCalledWith(id,expect.objectContaining({expected_revision:1,legal_name:legal,display_name:display}),expect.any(String),expect.any(AbortSignal));
  expect(host.textContent).toContain('Review and sign for '+legal);
});
it('validates the legal-name fallback when the optional display name contains only spaces',async()=>{
  current=enrollmentStatus('practice',1);const save=vi.spyOn(api,'practice').mockImplementation(async()=>{current=enrollmentStatus('agreement',2);return current;});
  await render();for(const [field,value]of Object.entries({legal_name:'Invented\tLegal Practice',display_name:' ',address_line1:'123 Invented Street',city:'Invented City',region:'NY',postal_code:'10001',administrative_email:'office@example.invalid'}))await fill(field,value);
  await check('covered');await click('Save and continue');expect(host.textContent).toContain('Use a display name without tabs, line breaks or control characters.');expect(save).not.toHaveBeenCalled();
  await fill('legal_name',' Invented Legal Practice ');await click('Save and continue');
  expect(save).toHaveBeenCalledWith(id,expect.objectContaining({legal_name:'Invented Legal Practice',display_name:'Invented Legal Practice'}),expect.any(String),expect.any(AbortSignal));
});
it('offers authorized representative recovery when the server denies signing',async()=>{
  current=enrollmentStatus('agreement',2);vi.spyOn(api,'accept').mockRejectedValue(new EnrollmentError(403,'enrollment_signer_required'));
  await render();await check('authority');await check('accepted');await click('Accept agreement');
  expect(host.textContent).toContain('An authorized representative must sign');expect(host.textContent).toContain('Use an authorized representative');
  expect(host.textContent).toContain('Invented Legal Practice');expect(navigate).not.toHaveBeenCalled();
});
it('recovers a canceled checkout return with the server before reusing the provider attempt',async()=>{
  current=enrollmentStatus('finishing_setup',3,2);current.billing.status='pending';vi.spyOn(api,'recover').mockImplementation(async()=>{current=enrollmentStatus('finishing_setup',4,2);current.billing.status='pending';return current;});
  vi.spyOn(api,'checkout').mockImplementation(async()=>({url:'https://checkout.stripe.com/c/pay/invented',status:'open',enrollment:current}));
  await render();await click('Check setup and payment');await click('Resume secure checkout');
  expect(api.recover).toHaveBeenCalledOnce();expect(api.checkout).toHaveBeenCalledWith(id,{expected_revision:4},expect.any(String),expect.any(AbortSignal));
  expect(navigate).toHaveBeenCalledWith('https://checkout.stripe.com/c/pay/invented');
});
it('shows pending activation with no trial dates or unconfirmed Chief access',async()=>{
  current=enrollmentStatus('activation_pending',3);await render();expect(host.textContent).toContain('Your trial clock has not started');
  expect(button('Open Chief')).toBeUndefined();expect(button('Continue securely with Stripe')).toBeUndefined();
  expect(host.textContent).toContain('First chargeNot started');
});
it('checks an uncertain submission then replays the exact key and immutable body',async()=>{
  const submitted=vi.spyOn(api,'profile').mockRejectedValueOnce(new EnrollmentError(503)).mockImplementation(async()=>{current=enrollmentStatus('practice',1);return current;});
  await render();await fill('name','Invented Owner');await click('Save and continue');
  expect(button('Retry the same submission').disabled).toBe(true);await click('Check saved progress');await click('Retry the same submission');
  expect(submitted.mock.calls).toHaveLength(2);expect(submitted.mock.calls[0][1]).toEqual(submitted.mock.calls[1][1]);expect(submitted.mock.calls[0][2]).toBe(submitted.mock.calls[1][2]);
  expect(host.textContent).toContain('Set up your practice');
});
it('recovers a completed submission by read without another write and clears fields after denial',async()=>{
  vi.spyOn(api,'profile').mockImplementation(async()=>{current=enrollmentStatus('practice',1);throw new EnrollmentError(503);});
  await render();await fill('name','Invented Owner');await click('Save and continue');await click('Check saved progress');
  expect(api.profile).toHaveBeenCalledOnce();expect(button('Retry the same submission')).toBeUndefined();
  vi.mocked(api.status).mockRejectedValueOnce(new EnrollmentError(403));await click('Back');await click('Back to saved setup');
  // An explicit current-account denial discards visible private enrollment details.
  await act(async()=>{root.render(<EnrollmentFlow key="changed" api={api} identity={id} config={enrollmentConfig()} navigate={navigate}/>);});
  expect(host.textContent).not.toContain('Invented Owner');
});
it('keeps 11+ humans on negotiated pricing and never starts unpriced checkout',async()=>{
  current=enrollmentStatus('negotiated',3,11);await render();expect(host.textContent).toContain('No unpriced subscription or trial has started');
  expect(button('Continue securely with Stripe')).toBeUndefined();
});
it('keeps invitation recipients on Account until their provider-prefilled name is confirmed and saved',async()=>{
  current=enrollmentStatus();current.profile={display_name:'Invented Provider Name',title:'',email:'staff@example.invalid'};
  await render('?invite=invitation_invented');expect(host.textContent).toContain('Welcome to CosmaBot');expect(button('Join practice')).toBeUndefined();
});
it('accepts a lower revision when a verified invitation switches the active legal practice',async()=>{
  current=enrollmentStatus('ready',60,5);const second={...enrollmentStatus('ready',5,2),practice:{...enrollmentStatus('ready',5,2).practice!,id:'20000000-0000-4000-8000-000000000001',legal_name:'Invented Second Legal Practice',display_name:'Invented Second Practice'}};
  vi.spyOn(api,'join').mockImplementation(async()=>{current=second;return current;});await render('?invite=invitation_invented');await click('Join practice');
  expect(host.textContent).toContain('Welcome to Invented Second Practice');expect(host.textContent).not.toContain('Welcome to Invented Practice');
});
it.each(['active','past_due','unpaid','canceled'])('shows saved %s billing without promising zero due or a new trial',async state=>{
  current=enrollmentStatus(state==='active'?'ready':state==='canceled'?'canceled':'payment_action_required',4,5);current.billing.status=state;
  await render();expect(host.textContent).not.toContain('Due today');expect(host.textContent).not.toContain('Trial duration');
  expect(button('Continue securely with Stripe')).toBeUndefined();expect(button('Manage billing or cancel')).toBeDefined();
});
it('creates an ordinary paid-seat teammate invitation with signing authority off by default',async()=>{
  current=enrollmentStatus('ready',4,5);vi.spyOn(api,'invitation').mockImplementation(async()=>({id:'invitation',token:'invented_token',expires_at:'2026-11-07T12:00:00Z',role:'staff',can_sign:false,enrollment:{...current,revision:5}}));
  await render();await click('Invite a teammate');await fill('team_email','staff@example.invalid');await click('Create teammate invitation');
  expect(api.invitation).toHaveBeenCalledWith(id,{expected_revision:4,email:'staff@example.invalid',role:'staff',can_sign:false},expect.any(String),expect.any(AbortSignal));
  expect(host.querySelector<HTMLInputElement>('input[readonly]')?.value).toContain('/onboarding?invite=');expect(host.textContent).toContain('No email was sent');
});
it('confirms a pre-ready member account with fresh proof and waits for server-ready admission',async()=>{
  current=enrollmentStatus('finishing_setup',4,5);current.practice!.role='staff';current.billing.status='trialing';current.workspace.organization_id='org_invented';current.workspace.url=null;
  const prepare=vi.fn().mockResolvedValue('fresh.scoped.fixture');vi.spyOn(api,'confirmWorkspace').mockImplementation(async()=>{current=enrollmentStatus('ready',5,5);current.practice!.role='staff';return current;});
  await act(async()=>root.render(<EnrollmentFlow api={api} identity={id} config={enrollmentConfig()} navigate={navigate} prepareWorkspaceToken={prepare}/>));
  expect(button('Open Chief')).toBeUndefined();await click('Confirm practice account');expect(prepare).toHaveBeenCalledOnce();
  expect(api.confirmWorkspace).toHaveBeenCalledWith(id,{expected_revision:4,workspace_token:'fresh.scoped.fixture'},expect.any(String),expect.any(AbortSignal));
  expect(button('Open Chief')).toBeDefined();expect(navigate).not.toHaveBeenCalled();
});
it('reloads prepared membership and repeats confirmation with fresh scoped proof without retaining a token',async()=>{
  current=enrollmentStatus('finishing_setup',4,5);current.practice!.role='staff';current.billing.status='trialing';current.workspace.organization_id='org_invented';current.workspace.url=null;
  const prepare=vi.fn().mockResolvedValueOnce('fresh.account.fixture').mockResolvedValueOnce('fresh.scoped.fixture');
  const confirm=vi.spyOn(api,'confirmWorkspace').mockImplementationOnce(async()=>({...current,action_required:'Your practice membership is prepared. Refresh your account, select the practice and confirm again.'})).mockImplementationOnce(async()=>{current=enrollmentStatus('ready',5,5);current.practice!.role='staff';return current;});
  await act(async()=>root.render(<EnrollmentFlow api={api} identity={id} config={enrollmentConfig()} navigate={navigate} prepareWorkspaceToken={prepare}/>));
  await click('Confirm practice account');expect(confirm).toHaveBeenCalledTimes(2);expect(confirm.mock.calls[0][1].workspace_token).toBe('fresh.account.fixture');expect(confirm.mock.calls[1][1].workspace_token).toBe('fresh.scoped.fixture');
  expect(confirm.mock.calls[0][2]).not.toBe(confirm.mock.calls[1][2]);expect(button('Open Chief')).toBeDefined();expect(localStorage.length).toBe(0);expect(sessionStorage.length).toBe(0);
});
