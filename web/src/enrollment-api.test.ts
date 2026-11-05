import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {createEnrollmentApi,enrollmentApiBase,stripeDestination,workspaceDestination} from './enrollment-api';
import {enrollmentConfig,enrollmentDocument,enrollmentStatus} from './enrollment-test-fixture';
import {validateEnrollmentConfig,validateEnrollmentPractices,validateEnrollmentStatus} from './enrollment-contract';
const base='http://127.0.0.1:8910',api=createEnrollmentApi(base);
const identity=()=>({getToken:vi.fn().mockResolvedValue('invented.signed.session'),isCurrent:vi.fn(()=>true)});
const json=(value:unknown,status=200)=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
beforeEach(()=>vi.stubGlobal('fetch',vi.fn()));
afterEach(()=>{vi.unstubAllGlobals();vi.unstubAllEnvs();vi.useRealTimers();});
it('uses the dedicated endpoint and a fresh token without caller-selected clinical identity',async()=>{
  const id=identity();vi.mocked(fetch).mockResolvedValue(json(enrollmentStatus()));await api.status(id);
  expect(id.getToken).toHaveBeenCalledWith({skipCache:true});const [url,options]=vi.mocked(fetch).mock.calls[0];
  expect(url).toBe(base+'/enrollment/v1/status');expect(options).toMatchObject({credentials:'omit',redirect:'error',cache:'no-store',referrerPolicy:'no-referrer'});
  const headers=new Headers(options?.headers);expect(headers.get('Authorization')).toBe('Bearer invented.signed.session');
  expect(headers.get('X-Cosmas-Enrollment-Contract')).toBe('enrollment.v1');
  expect(headers.has('X-Box-Id')).toBe(false);expect(headers.has('X-Actor-Principal-Id')).toBe(false);
});
it('freezes the approved practice quantity and sends no browser price or return URL to Checkout',async()=>{
  vi.mocked(fetch).mockResolvedValue(json({status:'pending',url:null,enrollment:enrollmentStatus('finishing_setup',4,5)}));
  await api.checkout(identity(),{expected_revision:3},'attempt_invented');
  const options=vi.mocked(fetch).mock.calls[0][1];expect(JSON.parse(options?.body as string)).toEqual({expected_revision:3});
  expect(new Headers(options?.headers).get('Idempotency-Key')).toBe('attempt_invented');
});
it('sends fresh workspace proof only to the signed confirmation operation, with no caller-selected routing',async()=>{
  vi.mocked(fetch).mockResolvedValue(json(enrollmentStatus('finishing_setup',4,5)));
  await api.confirmWorkspace(identity(),{expected_revision:3,workspace_token:'fresh.scoped.fixture'},'confirm_invented');
  const [url,options]=vi.mocked(fetch).mock.calls[0];expect(url).toBe(base+'/enrollment/v1/workspace/confirm');
  expect(JSON.parse(options?.body as string)).toEqual({expected_revision:3,workspace_token:'fresh.scoped.fixture'});
});
it('rejects a token acquired after the current account changes',async()=>{
  const id=identity();id.getToken.mockImplementation(async()=>{id.isCurrent.mockReturnValue(false);return 'obsolete';});
  await expect(api.status(id)).rejects.toMatchObject({status:401});expect(fetch).not.toHaveBeenCalled();
});
it('preserves a distinct authorized-signer denial while refusing untrusted server error text',async()=>{
  vi.mocked(fetch).mockResolvedValue(json({detail:{code:'enrollment_signer_required',message:'private server detail'}},403));
  await expect(api.accept(identity(),{expected_revision:3,doc_id:'CN-BAA-CUST-CW',version:'2.3',sha256:'a'.repeat(64),signature_name:'Invented Staff',signature_title:'Staff',authority_confirmed:true,accepted:true},'denied_attempt')).rejects.toMatchObject({status:403,code:'enrollment_signer_required'});
  vi.mocked(fetch).mockResolvedValue(new Response('private identity detail',{status:403}));
  await expect(api.status(identity())).rejects.toMatchObject({status:403,code:'enrollment_access_denied'});
});
it('bounds a login provider that ignores abort and emits no later request',async()=>{
  vi.useFakeTimers();const id=identity();id.getToken.mockImplementation(()=>new Promise(()=>{}));
  const result=api.status(id).catch(error=>error);await vi.advanceTimersByTimeAsync(15001);
  expect(await result).toMatchObject({status:504});expect(fetch).not.toHaveBeenCalled();
});
it('fails closed for forged ready state, wrong BAA, wrong price, or unqualified production configuration',()=>{
  const ready=enrollmentStatus('ready',5,5);expect(validateEnrollmentStatus(ready).quote?.monthly_total_cents).toBe(150000);
  expect(()=>validateEnrollmentStatus({...ready,billing:{...ready.billing,status:'none'}})).toThrow();
  expect(()=>validateEnrollmentStatus({...ready,workspace:{...ready.workspace,organization_id:null}})).toThrow();
  expect(()=>validateEnrollmentStatus({...ready,quote:{...ready.quote,monthly_total_cents:30000}})).toThrow();
  expect(()=>validateEnrollmentConfig({...enrollmentConfig(),baa:{...enrollmentConfig().baa,sha256:'a'.repeat(64)}})).toThrow();
  expect(()=>validateEnrollmentConfig({...enrollmentConfig(),data_mode:'production',production_qualified:false})).toThrow();
});
it('defaults absent confirmation availability to false and accepts only a server boolean without granting ready access',()=>{
  const pending=enrollmentStatus('activation_pending',3);
  expect(validateEnrollmentStatus(pending).workspace.confirmation_available).toBe(false);
  const offered={...pending,workspace:{...pending.workspace,confirmation_available:true,organization_id:'org_invented',box_id:'10000000-0000-4000-8000-000000000003'}};
  expect(validateEnrollmentStatus(offered).workspace).toMatchObject({url:null,confirmation_available:true});
  for(const value of ['true',1,null,{}])expect(()=>validateEnrollmentStatus({...offered,workspace:{...offered.workspace,confirmation_available:value}})).toThrow();
  expect(()=>validateEnrollmentStatus({...offered,stage:'ready'})).toThrow();
});
it('defaults absent checkout recovery availability to false and rejects malformed recovery flags',()=>{
  const config={...enrollmentConfig()};delete config.checkout_recovery_available;
  expect(validateEnrollmentConfig(config).checkout_recovery_available).toBe(false);
  expect(validateEnrollmentConfig({...config,activation_available:false,checkout_recovery_available:true}).checkout_recovery_available).toBe(true);
  for(const value of ['true',1,null,{}])expect(()=>validateEnrollmentConfig({...config,checkout_recovery_available:value})).toThrow();
});
it('accepts compatible saved runtime names while preserving the full legal practice name',()=>{
  const status=enrollmentStatus('ready',5),name='N'.repeat(120);status.profile!.display_name=name;status.practice!.display_name=name;status.practice!.legal_name='L'.repeat(160);
  expect(validateEnrollmentStatus(status).practice).toMatchObject({display_name:name,legal_name:'L'.repeat(160)});
  const prefill={...enrollmentStatus(),profile:{display_name:'N'.repeat(160),title:'',email:'owner@example.invalid'}};
  expect(validateEnrollmentStatus(prefill).profile?.display_name).toHaveLength(160);
});
it.each(['N'.repeat(121),'Invented\tName','Invented\nName','Invented\u007fName',' Invented Name '])('rejects incompatible saved profile, practice and roster names (%j)',name=>{
  const status=enrollmentStatus('ready',5);
  expect(()=>validateEnrollmentStatus({...status,profile:{...status.profile!,display_name:name}})).toThrow();
  expect(()=>validateEnrollmentStatus({...status,practice:{...status.practice!,display_name:name}})).toThrow();
  expect(()=>validateEnrollmentPractices({active_practice_id:status.practice!.id,practices:[{id:status.practice!.id,legal_name:status.practice!.legal_name,display_name:name,role:'owner',workspace_status:'ready'}]})).toThrow();
});
it('hashes the actual full agreement before presenting a claimed pinned document',async()=>{
  vi.mocked(fetch).mockResolvedValue(json(enrollmentDocument()));
  await expect(api.document(identity())).rejects.toMatchObject({code:'enrollment_document_changed'});
});
it('rejects unrelated credentials destinations and unsupported native enrollment transport',()=>{
  expect(stripeDestination('https://checkout.stripe.com/c/pay/invented')).toContain('checkout.stripe.com');
  expect(()=>stripeDestination('https://checkout.stripe.com.evil.invalid/')).toThrow();
  expect(()=>workspaceDestination('https://other.example.invalid/','https://app.example.invalid/onboarding')).toThrow();
  expect(workspaceDestination('https://workspace.example.invalid/','https://app.example.invalid/onboarding',['https://workspace.example.invalid'])).toBe('https://workspace.example.invalid/');
  expect(()=>enrollmentApiBase(base,'app://cosmas/index.html')).toThrow();
  expect(()=>enrollmentApiBase('http://user:password@localhost:8910','http://localhost:5173/onboarding')).toThrow();
});
it('defaults missing workspace policy to exact and rejects unknown or non-synthetic UUID policies',()=>{
  expect(validateEnrollmentConfig(enrollmentConfig()).workspace_origin_policy).toBe('exact');
  expect(validateEnrollmentConfig({...enrollmentConfig(),workspace_origin_policy:'synthetic-practice-uuid-staging-v1'}).workspace_origin_policy).toBe('synthetic-practice-uuid-staging-v1');
  for(const policy of ['*','uuid',null,['exact']])expect(()=>validateEnrollmentConfig({...enrollmentConfig(),workspace_origin_policy:policy})).toThrow();
  expect(()=>validateEnrollmentConfig({...enrollmentConfig(),data_mode:'disabled',enabled:false,workspace_origin_policy:'synthetic-practice-uuid-staging-v1'})).toThrow();
});
it('permits only the current authenticated ready practice UUID Chief destination under explicit synthetic policy',()=>{
  const ready=enrollmentStatus('ready',5),config={...enrollmentConfig(),workspace_origin_policy:'synthetic-practice-uuid-staging-v1' as const};
  ready.workspace.url=`https://${ready.practice!.id}.staging.cosmas.ai/chief`;
  const context={config,current:structuredClone(ready),ready};
  expect(workspaceDestination(ready.workspace.url,'https://account.example.invalid/onboarding',[],context)).toBe(ready.workspace.url);
  const legacy=enrollmentStatus('ready',5);
  expect(workspaceDestination(legacy.workspace.url!,'https://account.example.invalid/onboarding',config.allowed_workspace_origins,
    {config,current:structuredClone(legacy),ready:legacy})).toBe(legacy.workspace.url);
  expect(()=>workspaceDestination(ready.workspace.url!,'https://account.example.invalid/onboarding',[],
    {...context,config:{...config,enabled:false}})).toThrow();
  expect(()=>workspaceDestination(ready.workspace.url!,'https://account.example.invalid/onboarding',[],
    {...context,config:{...config,auth_configured:false}})).toThrow();
  expect(()=>workspaceDestination(ready.workspace.url!,'https://account.example.invalid/onboarding')).toThrow();
  const foreign='https://20000000-0000-4000-8000-000000000001.staging.cosmas.ai/chief';
  expect(()=>workspaceDestination(foreign,'https://account.example.invalid/onboarding',[new URL(foreign).origin],{...context,ready:{...ready,workspace:{...ready.workspace,url:foreign}}})).toThrow();
});
it('opens a production practice UUID workspace only under the production policy and production data mode',()=>{
  const production={...enrollmentConfig(),data_mode:'production' as const,production_qualified:true,
    clerk_publishable_key:'pk_live_invented_fixture',workspace_origin_policy:'practice-uuid-production-v1' as const};
  expect(validateEnrollmentConfig(production).workspace_origin_policy).toBe('practice-uuid-production-v1');
  expect(()=>validateEnrollmentConfig({...production,data_mode:'synthetic'})).toThrow();
  expect(()=>validateEnrollmentConfig({...enrollmentConfig(),workspace_origin_policy:'synthetic-practice-uuid-staging-v1',data_mode:'production'})).toThrow();
  const ready=enrollmentStatus('ready',5);ready.workspace.url=`https://${ready.practice!.id}.workspace.cosmas.ai/chief`;
  const context={config:production,current:structuredClone(ready),ready};
  expect(workspaceDestination(ready.workspace.url,'https://app.cosmas.ai/onboarding',[],context)).toBe(ready.workspace.url);
  // A staging host is never opened from production enrollment, and vice versa.
  const staging=structuredClone(ready);staging.workspace.url=`https://${ready.practice!.id}.staging.cosmas.ai/chief`;
  expect(()=>workspaceDestination(staging.workspace.url!,'https://app.cosmas.ai/onboarding',[],{config:production,current:structuredClone(staging),ready:staging})).toThrow();
  const stagingConfig={...enrollmentConfig(),workspace_origin_policy:'synthetic-practice-uuid-staging-v1' as const};
  expect(()=>workspaceDestination(ready.workspace.url!,'https://onboarding.staging.cosmas.ai/onboarding',[],{...context,config:stagingConfig})).toThrow();
  const foreign='https://20000000-0000-4000-8000-000000000001.workspace.cosmas.ai/chief';
  expect(()=>workspaceDestination(foreign,'https://app.cosmas.ai/onboarding',[],{...context,ready:{...ready,workspace:{...ready.workspace,url:foreign}}})).toThrow();
});
it.each([
  ['noncanonical practice',(ready:ReturnType<typeof enrollmentStatus>)=>{ready.practice!.id=ready.practice!.id.toUpperCase().replace(/^1/,'A');}],
  ['noncanonical Box',(ready:ReturnType<typeof enrollmentStatus>)=>{ready.workspace.box_id='box_browser';}],
  ['query',(ready:ReturnType<typeof enrollmentStatus>)=>{ready.workspace.url+='?return=foreign';}],
  ['fragment',(ready:ReturnType<typeof enrollmentStatus>)=>{ready.workspace.url+='#chief';}],
  ['port',(ready:ReturnType<typeof enrollmentStatus>)=>{ready.workspace.url=ready.workspace.url!.replace('/chief',':443/chief');}],
  ['credentials',(ready:ReturnType<typeof enrollmentStatus>)=>{ready.workspace.url=ready.workspace.url!.replace('https://','https://user:password@');}],
  ['wrong path',(ready:ReturnType<typeof enrollmentStatus>)=>{ready.workspace.url=ready.workspace.url!.replace('/chief','/settings');}],
  ['not ready',(ready:ReturnType<typeof enrollmentStatus>)=>{ready.workspace.status='provisioning';}],
] as const)('rejects an allocated browser destination with %s',(_name,change)=>{
  const ready=enrollmentStatus('ready',5);ready.workspace.url=`https://${ready.practice!.id}.staging.cosmas.ai/chief`;
  const current=structuredClone(ready);change(ready);
  expect(()=>workspaceDestination(ready.workspace.url!,'https://account.example.invalid/onboarding',[],{config:{...enrollmentConfig(),workspace_origin_policy:'synthetic-practice-uuid-staging-v1'},current,ready})).toThrow();
});
