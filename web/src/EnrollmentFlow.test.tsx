import {act} from 'react';import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {EnrollmentFlow} from './EnrollmentFlow';import {createEnrollmentApi} from './enrollment-api';
import {enrollmentConfig,enrollmentDocument,enrollmentStatus} from './enrollment-test-fixture';
import {EnrollmentError,type EnrollmentConfig,type EnrollmentStatus} from './enrollment-contract';
let root:Root,host:HTMLDivElement,current:EnrollmentStatus,currentConfig:EnrollmentConfig;
const api=createEnrollmentApi('http://127.0.0.1:8910'),id={getToken:async()=> 'invented.token',isCurrent:()=>true},navigate=vi.fn();
beforeEach(()=>{vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);host=document.createElement('div');document.body.append(host);root=createRoot(host);current=enrollmentStatus();currentConfig=enrollmentConfig();vi.spyOn(api,'config').mockImplementation(async()=>structuredClone(currentConfig));
  vi.spyOn(api,'status').mockImplementation(async()=>structuredClone(current));vi.spyOn(api,'practices').mockImplementation(async()=>({active_practice_id:current.practice?.id??null,practices:current.practice?[{id:current.practice.id,legal_name:current.practice.legal_name,display_name:current.practice.display_name,role:current.practice.role,workspace_status:current.workspace.status}]:[]}));vi.spyOn(api,'document').mockResolvedValue(enrollmentDocument());navigate.mockClear();});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.useRealTimers();vi.restoreAllMocks();vi.unstubAllGlobals();});
const button=(name:string)=>[...host.querySelectorAll('button')].find(item=>item.textContent?.trim()===name)!;
async function click(name:string){expect(button(name),host.textContent??'').toBeDefined();await act(async()=>button(name).click());}
async function fill(name:string,value:string){await act(async()=>{const input=host.querySelector<HTMLInputElement>('#enrollment-'+name)!;
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,value);input.dispatchEvent(new Event('input',{bubbles:true}));});}
async function check(name:string){await act(async()=>host.querySelector<HTMLInputElement>('#enrollment-'+name)!.click());}
async function render(search=''){await act(async()=>root.render(<EnrollmentFlow api={api} identity={id} config={currentConfig} navigate={navigate} search={search}/>));}
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
it('reveals and focuses the agreement step after the practice form without stealing focus during signer edits',async()=>{
  const previous=Object.getOwnPropertyDescriptor(HTMLElement.prototype,'scrollIntoView'),scroll=vi.fn();
  Object.defineProperty(HTMLElement.prototype,'scrollIntoView',{configurable:true,value:scroll});
  try{
    current=enrollmentStatus('practice',1);
    vi.spyOn(api,'practice').mockImplementation(async()=>{current=enrollmentStatus('agreement',2);return current;});
    await render();
    for(const [field,value]of Object.entries({legal_name:'Invented Legal Practice',address_line1:'123 Invented Street',city:'Invented City',region:'NY',postal_code:'10001',administrative_email:'office@example.invalid'}))await fill(field,value);
    await check('covered');scroll.mockClear();await click('Save and continue');
    const heading=host.querySelector('h1')!;
    expect(heading.textContent).toBe('Review and sign for Invented Legal Practice');
    expect(document.activeElement).toBe(heading);expect(heading.tabIndex).toBe(-1);
    expect(scroll).toHaveBeenCalledOnce();expect(scroll).toHaveBeenCalledWith({block:'start',behavior:'auto'});
    const signer=host.querySelector<HTMLInputElement>('#enrollment-signature_title')!;signer.focus();
    await fill('signature_title','Practice owner');
    expect(document.activeElement).toBe(signer);expect(signer.value).toBe('Practice owner');expect(scroll).toHaveBeenCalledOnce();
  }finally{
    if(previous)Object.defineProperty(HTMLElement.prototype,'scrollIntoView',previous);
    else delete (HTMLElement.prototype as unknown as {scrollIntoView?:unknown}).scrollIntoView;
  }
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
it('recovers a saved pending checkout while new acquisition is closed before reusing the provider attempt',async()=>{
  currentConfig={...currentConfig,activation_available:false,checkout_recovery_available:true};
  current=enrollmentStatus('finishing_setup',3,2);current.billing.status='pending';current.workspace={...enrollmentStatus('ready',3,2).workspace,url:null,confirmation_available:true};
  vi.spyOn(api,'recover').mockImplementation(async()=>{current={...current,revision:4};return current;});
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
it('waits for saved status before reading configuration in progress and explicit recovery',async()=>{
  current=enrollmentStatus('activation_pending',3);current.workspace.status='failed';
  let initial!:(value:EnrollmentStatus)=>void;
  vi.mocked(api.status).mockImplementationOnce(()=>new Promise<EnrollmentStatus>(resolve=>{initial=resolve;}));
  const recover=vi.spyOn(api,'recover').mockImplementation(async()=>structuredClone(current));
  await render();expect(api.config).not.toHaveBeenCalled();expect(api.practices).not.toHaveBeenCalled();
  await act(async()=>initial(structuredClone(current)));
  expect(api.config).toHaveBeenCalledOnce();expect(api.practices).toHaveBeenCalledOnce();
  let saved!:(value:EnrollmentStatus)=>void;
  vi.mocked(api.status).mockImplementationOnce(()=>new Promise<EnrollmentStatus>(resolve=>{saved=resolve;}));
  await click('Check setup and payment');expect(api.config).toHaveBeenCalledOnce();expect(recover).not.toHaveBeenCalled();
  await act(async()=>saved(structuredClone(current)));
  expect(api.config).toHaveBeenCalledTimes(2);expect(recover).toHaveBeenCalledOnce();
  expect(current.workspace.status).toBe('failed');expect(button('Open Chief')).toBeUndefined();expect(navigate).not.toHaveBeenCalled();
});
it('explains saved workspace preparation and refreshes into payment without repeating completed steps',async()=>{
  vi.useFakeTimers();vi.spyOn(document,'visibilityState','get').mockReturnValue('visible');
  current=enrollmentStatus('activation_pending',3);current.workspace.status='provisioning';
  current.action_required='Your workspace is being prepared. Your trial has not been activated.';
  const writes=(['profile','practice','accept','recover','confirmWorkspace','checkout'] as const).map(method=>vi.spyOn(api,method));
  await render();expect(host.textContent).toContain('Your practice details and signed agreement are saved.');
  expect(host.textContent).toContain('This page checks progress automatically.');expect(host.textContent).not.toContain('An additional setup action is required.');
  expect(button('Open Chief')).toBeUndefined();expect(button('Continue securely with Stripe')).toBeUndefined();
  current={...current,stage:'payment',revision:4,action_required:null,workspace:{...current.workspace,status:'ready'}};
  currentConfig={...currentConfig,activation_available:true};
  await act(async()=>vi.advanceTimersByTimeAsync(15_000));
  expect(host.querySelector('h1')?.textContent).toBe('Start your 14-day free trial');
  expect(api.status).toHaveBeenCalledTimes(2);expect(api.practices).toHaveBeenCalledTimes(2);
  expect(host.textContent).toContain('First chargeNot started');expect(navigate).not.toHaveBeenCalled();writes.forEach(write=>expect(write).not.toHaveBeenCalled());
  await act(async()=>vi.advanceTimersByTimeAsync(60_000));expect(api.status).toHaveBeenCalledTimes(2);
});
it('keeps mobile actions reachable during a progress read and gives explicit setup confirmation priority',async()=>{
  vi.useFakeTimers();vi.spyOn(document,'visibilityState','get').mockReturnValue('visible');
  current=enrollmentStatus('activation_pending',3);current.workspace={status:'provisioning',url:null,organization_id:'org_invented',box_id:'10000000-0000-4000-8000-000000000003',confirmation_available:true};
  const prepare=vi.fn().mockResolvedValue('fresh.scoped.fixture');
  vi.spyOn(api,'confirmWorkspace').mockImplementation(async()=>{current={...current,stage:'payment',revision:4,workspace:{...current.workspace,status:'ready'}};return current;});
  await act(async()=>root.render(<EnrollmentFlow api={api} identity={id} config={enrollmentConfig()} navigate={navigate} prepareWorkspaceToken={prepare}/>));
  let resolve!:(status:EnrollmentStatus)=>void,signal:AbortSignal|undefined;
  vi.mocked(api.status).mockImplementationOnce(async(_identity,abort)=>{signal=abort;return new Promise<EnrollmentStatus>(done=>{resolve=done;});});
  const receipt=button('View agreement receipt');receipt.focus();await act(async()=>vi.advanceTimersByTimeAsync(15_000));
  expect(document.activeElement).toBe(receipt);
  for(const label of ['Continue setup','Check progress','View agreement receipt','Review practice'])expect(button(label).disabled).toBe(false);
  await click('Continue setup');expect(signal?.aborted).toBe(true);expect(api.confirmWorkspace).toHaveBeenCalledOnce();expect(prepare).toHaveBeenCalledOnce();
  const calls=vi.mocked(api.practices).mock.calls.length;
  await act(async()=>resolve(enrollmentStatus('ready',20)));
  expect(api.practices).toHaveBeenCalledTimes(calls);expect(host.querySelector('h1')?.textContent).toBe('Start your 14-day free trial');
  expect(button('Open Chief')).toBeUndefined();expect(navigate).not.toHaveBeenCalled();
});
it('pauses preparation checks while hidden or reviewing the saved practice and discards late reads',async()=>{
  vi.useFakeTimers();let visible:DocumentVisibilityState='visible';vi.spyOn(document,'visibilityState','get').mockImplementation(()=>visible);
  current=enrollmentStatus('activation_pending',3);current.workspace.status='provisioning';await render();
  visible='hidden';await act(async()=>document.dispatchEvent(new Event('visibilitychange')));
  await act(async()=>vi.advanceTimersByTimeAsync(30_000));expect(api.status).toHaveBeenCalledOnce();
  visible='visible';await act(async()=>document.dispatchEvent(new Event('visibilitychange')));expect(api.status).toHaveBeenCalledTimes(2);
  let resolve!:(status:EnrollmentStatus)=>void,signal:AbortSignal|undefined;
  vi.mocked(api.status).mockImplementationOnce(async(_identity,abort)=>{signal=abort;return new Promise<EnrollmentStatus>(done=>{resolve=done;});});
  await act(async()=>vi.advanceTimersByTimeAsync(15_000));await click('Review practice');expect(signal?.aborted).toBe(true);
  expect(host.querySelector('h1')?.textContent).toBe('Practice details');
  await act(async()=>{resolve(enrollmentStatus('agreement',20));await vi.advanceTimersByTimeAsync(30_000);});
  expect(api.status).toHaveBeenCalledTimes(3);expect(host.querySelector('h1')?.textContent).toBe('Practice details');expect(host.querySelector('iframe')).toBeNull();
  await click('Back to saved setup');expect(host.querySelector('h1')?.textContent).toBe('Your setup is saved');
  await act(async()=>vi.advanceTimersByTimeAsync(15_000));expect(api.status).toHaveBeenCalledTimes(4);
});
it('preserves saved setup after a failed progress read and resumes only through a reachable read retry',async()=>{
  vi.useFakeTimers();vi.spyOn(document,'visibilityState','get').mockReturnValue('visible');
  current=enrollmentStatus('activation_pending',3);current.workspace.status='provisioning';const recover=vi.spyOn(api,'recover');await render();
  vi.mocked(api.status).mockRejectedValueOnce(new EnrollmentError(503));await act(async()=>vi.advanceTimersByTimeAsync(15_000));
  expect(host.querySelector('[role="alert"]')?.textContent).toContain('The result could not be confirmed.');expect(button('View agreement receipt')).toBeDefined();
  expect(host.textContent).toContain('Use Check progress to reconnect.');expect(button('Check progress').disabled).toBe(false);
  await act(async()=>vi.advanceTimersByTimeAsync(60_000));expect(api.status).toHaveBeenCalledTimes(2);
  await click('Check progress');expect(api.status).toHaveBeenCalledTimes(3);expect(host.querySelector('[role="alert"]')).toBeNull();expect(recover).not.toHaveBeenCalled();
  await act(async()=>vi.advanceTimersByTimeAsync(15_000));expect(api.status).toHaveBeenCalledTimes(4);
});
it('preserves a different practice selection while a preparation read is pending',async()=>{
  vi.useFakeTimers();vi.spyOn(document,'visibilityState','get').mockReturnValue('visible');
  current=enrollmentStatus('activation_pending',3);current.workspace.status='provisioning';
  const otherId='20000000-0000-4000-8000-000000000001';
  vi.mocked(api.practices).mockImplementation(async()=>({active_practice_id:current.practice!.id,practices:[
    {id:current.practice!.id,legal_name:current.practice!.legal_name,display_name:current.practice!.display_name,role:'owner',workspace_status:'provisioning'},
    {id:otherId,legal_name:'Other Invented Practice',display_name:'Other Invented Practice',role:'owner',workspace_status:'ready'},
  ]}));
  const select=vi.spyOn(api,'selectPractice');await render();let resolve!:(status:EnrollmentStatus)=>void,signal:AbortSignal|undefined;
  vi.mocked(api.status).mockImplementationOnce(async(_identity,abort)=>{signal=abort;return new Promise<EnrollmentStatus>(done=>{resolve=done;});});
  await act(async()=>vi.advanceTimersByTimeAsync(15_000));const menu=host.querySelector('select')!;
  await act(async()=>{menu.value=otherId;menu.dispatchEvent(new Event('change',{bubbles:true}));});expect(signal?.aborted).toBe(true);
  await act(async()=>{resolve(structuredClone(current));await vi.advanceTimersByTimeAsync(30_000);});
  expect(menu.value).toBe(otherId);expect(button('Open selected practice').disabled).toBe(false);expect(api.status).toHaveBeenCalledTimes(2);
  expect(select).not.toHaveBeenCalled();expect(navigate).not.toHaveBeenCalled();
});
it.each([
  ['failed','Your workspace is being prepared. Your trial has not been activated.'],
  ['provisioning','Your practice membership is prepared. Refresh your account, select the practice and confirm again.'],
] as const)('keeps explicit recovery visible without polling workspace state %s',async(workspaceStatus,notice)=>{
  vi.useFakeTimers();vi.spyOn(document,'visibilityState','get').mockReturnValue('visible');
  current=enrollmentStatus('activation_pending',3);current.workspace.status=workspaceStatus;current.action_required=notice;await render();
  expect(host.textContent).toContain('An additional setup action is required.');expect(host.textContent).not.toContain('This page checks progress automatically.');
  expect(button('Check setup and payment').disabled).toBe(false);await act(async()=>vi.advanceTimersByTimeAsync(60_000));expect(api.status).toHaveBeenCalledOnce();
});
it('refreshes strict same-origin availability and enables payment after reopening without a reload or automatic checkout',async()=>{
  vi.useFakeTimers();vi.spyOn(document,'visibilityState','get').mockReturnValue('visible');
  current=enrollmentStatus('payment',4);current.workspace={...enrollmentStatus('ready',4).workspace,url:null,confirmation_available:true};
  vi.mocked(api.config).mockRestore();const requests=vi.fn(async(url:RequestInfo|URL,options?:RequestInit)=>{
    expect(url).toBe('http://127.0.0.1:8910/enrollment/v1/config');expect(options).toMatchObject({method:'GET',cache:'no-store',credentials:'omit',redirect:'error',referrerPolicy:'no-referrer'});
    expect(new Headers(options?.headers).has('Authorization')).toBe(false);
    return new Response(JSON.stringify(currentConfig),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
  });vi.stubGlobal('fetch',requests);
  const checkout=vi.spyOn(api,'checkout').mockImplementation(async()=>({status:'open',url:'https://checkout.stripe.com/c/pay/invented',enrollment:current}));
  await render();expect(button('Continue securely with Stripe').disabled).toBe(true);expect(host.textContent).not.toContain('A card is required.');
  currentConfig={...currentConfig,activation_available:true};await act(async()=>vi.advanceTimersByTimeAsync(15_000));
  expect(button('Continue securely with Stripe').disabled).toBe(false);expect(checkout).not.toHaveBeenCalled();expect(navigate).not.toHaveBeenCalled();
  expect(requests).toHaveBeenCalledTimes(2);await click('Continue securely with Stripe');
  expect(requests).toHaveBeenCalledTimes(3);expect(checkout).toHaveBeenCalledOnce();expect(navigate).toHaveBeenCalledWith('https://checkout.stripe.com/c/pay/invented');
});
it('rechecks availability before explicit checkout and preserves saved setup when the server closes it',async()=>{
  current=enrollmentStatus('payment',4);current.workspace={...enrollmentStatus('ready',4).workspace,url:null,confirmation_available:true};currentConfig={...currentConfig,activation_available:true};
  const checkout=vi.spyOn(api,'checkout');await render();expect(button('Continue securely with Stripe').disabled).toBe(false);
  currentConfig={...currentConfig,activation_available:false};await click('Continue securely with Stripe');
  expect(checkout).not.toHaveBeenCalled();expect(navigate).not.toHaveBeenCalled();expect(button('Continue securely with Stripe').disabled).toBe(true);
  expect(host.textContent).toContain('Trial activation is not available yet.');expect(button('Retry the same submission')).toBeUndefined();
  currentConfig={...currentConfig,activation_available:true};await click('Check progress');expect(button('Continue securely with Stripe').disabled).toBe(false);
});
it.each([
  ['payment',true,false],['payment',false,true],['finishing_setup',true,false],['finishing_setup',false,true],
] as const)('holds %s checkout when billing=%s and activation=%s',async(stage,billing,activation)=>{
  current=enrollmentStatus(stage,4);current.workspace={...enrollmentStatus('ready',4).workspace,url:null,confirmation_available:true};if(stage==='finishing_setup')current.billing.status='pending';
  currentConfig={...currentConfig,billing_configured:billing,activation_available:activation,checkout_recovery_available:activation};const checkout=vi.spyOn(api,'checkout');await render();
  const label=stage==='payment'?'Continue securely with Stripe':'Resume secure checkout';expect(button(label).disabled).toBe(true);
  await click(label);expect(checkout).not.toHaveBeenCalled();expect(navigate).not.toHaveBeenCalled();expect(host.textContent).toContain('Trial activation is not available yet.');
});
it('rejects a config response from another origin and keeps saved setup closed for payment',async()=>{
  vi.useFakeTimers();vi.spyOn(document,'visibilityState','get').mockReturnValue('visible');
  current=enrollmentStatus('payment',4);current.workspace={...enrollmentStatus('ready',4).workspace,url:null,confirmation_available:true};vi.mocked(api.config).mockRestore();
  const response=()=>new Response(JSON.stringify(currentConfig),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
  const requests=vi.fn(async()=>response());vi.stubGlobal('fetch',requests);await render();currentConfig={...currentConfig,activation_available:true};
  requests.mockImplementationOnce(async()=>{const value=response();Object.defineProperty(value,'url',{value:'https://other.example.invalid/enrollment/v1/config'});return value;});
  await act(async()=>vi.advanceTimersByTimeAsync(15_000));expect(button('Continue securely with Stripe').disabled).toBe(true);expect(host.querySelector('[role="alert"]')).not.toBeNull();
  expect(button('View agreement receipt')).toBeDefined();expect(navigate).not.toHaveBeenCalled();
});
it.each(['Clerk key','approved origins','origin policy','BAA'])('rejects a refreshed %s change without opening payment or repeating onboarding',async change=>{
  vi.useFakeTimers();vi.spyOn(document,'visibilityState','get').mockReturnValue('visible');
  current=enrollmentStatus('payment',4);current.workspace={...enrollmentStatus('ready',4).workspace,url:null,confirmation_available:true};const checkout=vi.spyOn(api,'checkout');await render();
  currentConfig={...currentConfig,activation_available:true};
  if(change==='Clerk key')currentConfig={...currentConfig,clerk_publishable_key:'pk_test_other'};
  if(change==='approved origins')currentConfig={...currentConfig,allowed_workspace_origins:[...currentConfig.allowed_workspace_origins,'https://other.example.invalid']};
  if(change==='origin policy')currentConfig={...currentConfig,workspace_origin_policy:'synthetic-practice-uuid-staging-v1'};
  if(change==='BAA')currentConfig={...currentConfig,baa:{...currentConfig.baa,sha256:'a'.repeat(64)}} as unknown as EnrollmentConfig; // Deliberately forged runtime response.
  await act(async()=>vi.advanceTimersByTimeAsync(15_000));expect(host.querySelector('[role="alert"]')).not.toBeNull();
  expect(button('Continue securely with Stripe').disabled).toBe(true);expect(button('View agreement receipt')).toBeDefined();expect(host.querySelector('iframe')).toBeNull();
  await act(async()=>vi.advanceTimersByTimeAsync(30_000));expect(api.config).toHaveBeenCalledTimes(2);expect(checkout).not.toHaveBeenCalled();expect(navigate).not.toHaveBeenCalled();
});
it('keeps failed preparation after billing recovery and reads independent provisioning progress with its URL still hidden',async()=>{
  vi.useFakeTimers();vi.spyOn(document,'visibilityState','get').mockReturnValue('visible');
  current=enrollmentStatus('activation_pending',3);current.workspace={status:'failed',url:null,organization_id:'org_invented',box_id:'10000000-0000-4000-8000-000000000003',confirmation_available:false};
  current.action_required='Your workspace is being prepared. Your trial has not been activated.';
  const prepare=vi.fn().mockResolvedValue('fresh.scoped.fixture');
  const recover=vi.spyOn(api,'recover').mockImplementation(async()=>structuredClone(current));
  const confirm=vi.spyOn(api,'confirmWorkspace').mockImplementation(async()=>{current={...current,revision:6,stage:'payment',action_required:null,workspace:{...current.workspace,status:'ready'}};return current;});
  await act(async()=>root.render(<EnrollmentFlow api={api} identity={id} config={currentConfig} navigate={navigate} prepareWorkspaceToken={prepare}/>));
  expect(host.textContent).toContain('workspace preparation could not finish');expect(button('Continue setup')).toBeUndefined();
  await click('Check setup and payment');expect(button('Continue setup')).toBeUndefined();expect(prepare).not.toHaveBeenCalled();expect(confirm).not.toHaveBeenCalled();
  expect(current.workspace.status).toBe('failed');expect(host.textContent).toContain('workspace preparation could not finish');
  // A separate private provisioner resumes work. Returning to saved setup observes it by GET.
  current={...current,revision:4,workspace:{...current.workspace,status:'provisioning'}};
  await act(async()=>root.render(<EnrollmentFlow key="returned" api={api} identity={id} config={currentConfig} navigate={navigate} prepareWorkspaceToken={prepare}/>));
  expect(recover).toHaveBeenCalledOnce();expect(button('Continue setup')).toBeUndefined();expect(host.textContent).toContain('Your workspace is being prepared.');
  current={...current,revision:5,workspace:{...current.workspace,confirmation_available:true}};
  await act(async()=>vi.advanceTimersByTimeAsync(15_000));expect(button('Continue setup').disabled).toBe(false);expect(current.workspace.url).toBeNull();expect(confirm).not.toHaveBeenCalled();
  await click('Continue setup');expect(confirm).toHaveBeenCalledOnce();expect(prepare).toHaveBeenCalledOnce();expect(button('Open Chief')).toBeUndefined();
  expect(button('Continue securely with Stripe').disabled).toBe(true);expect(current.billing.trial_ends_at).toBeNull();expect(navigate).not.toHaveBeenCalled();
  currentConfig={...currentConfig,activation_available:true};await act(async()=>vi.advanceTimersByTimeAsync(15_000));expect(button('Continue securely with Stripe').disabled).toBe(false);
});
it('rechecks saved-checkout recovery before a resume and stops when recovery itself is closed',async()=>{
  current=enrollmentStatus('finishing_setup',4);current.billing.status='pending';current.workspace={...enrollmentStatus('ready',4).workspace,url:null,confirmation_available:true};currentConfig={...currentConfig,activation_available:false,checkout_recovery_available:true};
  const checkout=vi.spyOn(api,'checkout');await render();expect(button('Resume secure checkout').disabled).toBe(false);
  currentConfig={...currentConfig,checkout_recovery_available:false};await click('Resume secure checkout');
  expect(checkout).not.toHaveBeenCalled();expect(navigate).not.toHaveBeenCalled();expect(button('Resume secure checkout').disabled).toBe(true);expect(button('Retry the same submission')).toBeUndefined();
});
it.each(['payment','finishing_setup'] as const)('does not use checkout recovery availability for new or nonpending %s enrollment',async stage=>{
  current=enrollmentStatus(stage,4);currentConfig={...currentConfig,activation_available:false,checkout_recovery_available:true};const checkout=vi.spyOn(api,'checkout');await render();
  expect(button('Resume secure checkout')).toBeUndefined();if(stage==='payment')expect(button('Continue securely with Stripe').disabled).toBe(true);
  expect(checkout).not.toHaveBeenCalled();expect(navigate).not.toHaveBeenCalled();
});
it('rechecks server confirmation availability and never posts when the private binding becomes unavailable',async()=>{
  current=enrollmentStatus('activation_pending',3);current.workspace={status:'provisioning',url:null,organization_id:'org_invented',box_id:'10000000-0000-4000-8000-000000000003',confirmation_available:true};
  const prepare=vi.fn(),confirm=vi.spyOn(api,'confirmWorkspace');await act(async()=>root.render(<EnrollmentFlow api={api} identity={id} config={currentConfig} navigate={navigate} prepareWorkspaceToken={prepare}/>));
  current={...current,revision:4,workspace:{...current.workspace,confirmation_available:false}};await click('Continue setup');
  expect(prepare).not.toHaveBeenCalled();expect(confirm).not.toHaveBeenCalled();expect(navigate).not.toHaveBeenCalled();expect(button('Retry the same submission')).toBeUndefined();
  await click('Check progress');expect(button('Continue setup')).toBeUndefined();expect(button('View agreement receipt')).toBeDefined();
});
it.each([undefined,false])('holds prebilling confirmation when the server flag is %s while preserving saved progress',async available=>{
  current=enrollmentStatus('activation_pending',3);current.workspace={status:'provisioning',url:null,organization_id:'org_invented',box_id:'10000000-0000-4000-8000-000000000003',confirmation_available:available};
  const prepare=vi.fn(),confirm=vi.spyOn(api,'confirmWorkspace');await act(async()=>root.render(<EnrollmentFlow api={api} identity={id} config={currentConfig} navigate={navigate} prepareWorkspaceToken={prepare}/>));
  expect(button('Continue setup')).toBeUndefined();expect(button('Check progress').disabled).toBe(false);expect(button('View agreement receipt')).toBeDefined();
  expect(prepare).not.toHaveBeenCalled();expect(confirm).not.toHaveBeenCalled();expect(button('Open Chief')).toBeUndefined();expect(navigate).not.toHaveBeenCalled();
});
it('keeps the browser Chief handoff closed for a UUID practice outside its exact configured origins',async()=>{
  current=enrollmentStatus('ready',5);current.workspace.url='https://20000000-0000-4000-8000-000000000001.staging.cosmas.ai/chief';
  const openWorkspace=vi.fn();await act(async()=>root.render(<EnrollmentFlow api={api} identity={id}
    config={enrollmentConfig()} navigate={navigate} openWorkspace={openWorkspace}/>));
  await click('Open Chief');expect(openWorkspace).not.toHaveBeenCalled();expect(navigate).not.toHaveBeenCalled();
  expect(host.textContent).toContain('The result could not be confirmed. Check saved progress before trying again.');
});
it('opens the newly allocated browser practice in Chief only after a fresh authenticated ready response',async()=>{
  current=enrollmentStatus('ready',5);current.workspace.url=`https://${current.practice!.id}.staging.cosmas.ai/chief`;
  vi.mocked(api.status).mockRestore();const token=vi.spyOn(id,'getToken');
  const requests=vi.fn(async(_url:RequestInfo|URL,_options?:RequestInit)=>new Response(JSON.stringify(current),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}));
  vi.stubGlobal('fetch',requests);const openWorkspace=vi.fn();
  const config={...enrollmentConfig(),workspace_origin_policy:'synthetic-practice-uuid-staging-v1' as const};
  vi.mocked(api.config).mockResolvedValue(config);
  await act(async()=>root.render(<EnrollmentFlow api={api} identity={id} config={config} navigate={navigate} openWorkspace={openWorkspace}/>));
  current={...current,revision:6};await click('Open Chief');
  expect(requests).toHaveBeenCalledTimes(2);expect(token).toHaveBeenCalledTimes(2);expect(token).toHaveBeenLastCalledWith({skipCache:true});
  const [url,options]=requests.mock.calls[1];
  expect(url).toBe('http://127.0.0.1:8910/enrollment/v1/status');
  expect(options).toMatchObject({cache:'no-store',credentials:'omit',redirect:'error'});
  expect(new Headers(options?.headers).get('Authorization')).toBe('Bearer invented.token');
  expect(openWorkspace).toHaveBeenCalledWith(expect.objectContaining({revision:6}),current.workspace.url);
  expect(navigate).not.toHaveBeenCalled();expect(localStorage.length).toBe(0);expect(sessionStorage.length).toBe(0);
});
it.each(['practice','organization','box','inactive policy'])('holds the allocated browser Chief handoff when %s changes',async change=>{
  current=enrollmentStatus('ready',5);current.workspace.url=`https://${current.practice!.id}.staging.cosmas.ai/chief`;
  const openWorkspace=vi.fn(),config={...enrollmentConfig(),workspace_origin_policy:change==='inactive policy'?'exact' as const:'synthetic-practice-uuid-staging-v1' as const};
  vi.mocked(api.config).mockResolvedValue(config);
  await act(async()=>root.render(<EnrollmentFlow api={api} identity={id} config={config} navigate={navigate} openWorkspace={openWorkspace}/>));
  if(change==='practice'){current={...current,practice:{...current.practice!,id:'20000000-0000-4000-8000-000000000001'},workspace:{...current.workspace,url:'https://20000000-0000-4000-8000-000000000001.staging.cosmas.ai/chief'}};}
  if(change==='organization')current={...current,workspace:{...current.workspace,organization_id:'org_other'}};
  if(change==='box')current={...current,workspace:{...current.workspace,box_id:'20000000-0000-4000-8000-000000000003'}};
  await click('Open Chief');expect(openWorkspace).not.toHaveBeenCalled();expect(navigate).not.toHaveBeenCalled();
  expect(host.textContent).toContain('The result could not be confirmed. Check saved progress before trying again.');
});
it('lets the accepted owner continue prebilling setup through the existing confirmation POST while keeping card and Chief held',async()=>{
  current=enrollmentStatus('activation_pending',3);current.workspace={status:'provisioning',url:null,organization_id:'org_invented',box_id:'10000000-0000-4000-8000-000000000003',confirmation_available:false};
  current.practice!.role='staff';const config={...enrollmentConfig(),billing_configured:false};
  vi.mocked(api.config).mockResolvedValue(config);
  const prepare=vi.fn().mockResolvedValue('fresh.scoped.fixture');let confirmations=0;
  const posted=vi.fn(async(url:RequestInfo|URL,options?:RequestInit)=>{
    expect(url).toBe('http://127.0.0.1:8910/enrollment/v1/workspace/confirm');expect(options?.method).toBe('POST');
    expect(new Headers(options?.headers).get('Authorization')).toBe('Bearer invented.token');
    expect(new Headers(options?.headers).get('Idempotency-Key')).toEqual(expect.any(String));
    expect(JSON.parse(String(options?.body))).toEqual({expected_revision:current.revision,workspace_token:'fresh.scoped.fixture'});
    current={...current,revision:current.revision+1};
    if(++confirmations===2)current={...current,stage:'payment',workspace:{...current.workspace,status:'ready'}};
    return new Response(JSON.stringify(current),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
  });vi.stubGlobal('fetch',posted);
  await act(async()=>root.render(<EnrollmentFlow key="staff" api={api} identity={id} config={config} navigate={navigate} prepareWorkspaceToken={prepare}/>));
  expect(button('Continue setup')).toBeUndefined();expect(prepare).not.toHaveBeenCalled();
  current.practice!.role='owner';current.workspace.confirmation_available=true;await act(async()=>root.render(<EnrollmentFlow key="owner" api={api} identity={id} config={config} navigate={navigate} prepareWorkspaceToken={prepare}/>));
  await click('Continue setup');expect(posted).toHaveBeenCalledOnce();expect(button('Continue setup')).toBeDefined();
  expect(button('Continue securely with Stripe')).toBeUndefined();expect(button('Open Chief')).toBeUndefined();
  await click('Continue setup');expect(posted).toHaveBeenCalledTimes(2);expect(prepare).toHaveBeenCalledTimes(2);
  expect(button('Continue setup')).toBeUndefined();expect(button('Continue securely with Stripe').disabled).toBe(true);
  expect(button('Open Chief')).toBeUndefined();expect(current.billing.status).toBe('none');expect(current.billing.trial_ends_at).toBeNull();
  expect(navigate).not.toHaveBeenCalled();expect(localStorage.length).toBe(0);expect(sessionStorage.length).toBe(0);
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
  current=enrollmentStatus('finishing_setup',4,5);current.practice!.role='staff';current.billing={...enrollmentStatus('ready',4,5).billing};current.workspace={...enrollmentStatus('ready',4,5).workspace,url:null,confirmation_available:true};
  const prepare=vi.fn().mockResolvedValue('fresh.scoped.fixture');vi.spyOn(api,'confirmWorkspace').mockImplementation(async()=>{current=enrollmentStatus('ready',5,5);current.practice!.role='staff';return current;});
  await act(async()=>root.render(<EnrollmentFlow api={api} identity={id} config={enrollmentConfig()} navigate={navigate} prepareWorkspaceToken={prepare}/>));
  expect(button('Open Chief')).toBeUndefined();await click('Confirm practice account');expect(prepare).toHaveBeenCalledOnce();
  expect(api.confirmWorkspace).toHaveBeenCalledWith(id,{expected_revision:4,workspace_token:'fresh.scoped.fixture'},expect.any(String),expect.any(AbortSignal));
  expect(button('Open Chief')).toBeDefined();expect(navigate).not.toHaveBeenCalled();
});
it('reloads prepared membership and repeats confirmation with fresh scoped proof without retaining a token',async()=>{
  current=enrollmentStatus('finishing_setup',4,5);current.practice!.role='staff';current.billing={...enrollmentStatus('ready',4,5).billing};current.workspace={...enrollmentStatus('ready',4,5).workspace,url:null,confirmation_available:true};
  const prepare=vi.fn().mockResolvedValueOnce('fresh.account.fixture').mockResolvedValueOnce('fresh.scoped.fixture');
  const confirm=vi.spyOn(api,'confirmWorkspace').mockImplementationOnce(async()=>({...current,action_required:'Your practice membership is prepared. Refresh your account, select the practice and confirm again.'})).mockImplementationOnce(async()=>{current=enrollmentStatus('ready',5,5);current.practice!.role='staff';return current;});
  await act(async()=>root.render(<EnrollmentFlow api={api} identity={id} config={enrollmentConfig()} navigate={navigate} prepareWorkspaceToken={prepare}/>));
  await click('Confirm practice account');expect(confirm).toHaveBeenCalledTimes(2);expect(confirm.mock.calls[0][1].workspace_token).toBe('fresh.account.fixture');expect(confirm.mock.calls[1][1].workspace_token).toBe('fresh.scoped.fixture');
  expect(confirm.mock.calls[0][2]).not.toBe(confirm.mock.calls[1][2]);expect(button('Open Chief')).toBeDefined();expect(localStorage.length).toBe(0);expect(sessionStorage.length).toBe(0);
});
