import {act,useEffect} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {WorkspaceCompatibilityGate} from './WorkspaceCompatibilityGate';
import {enrollmentRecoveryDestination} from './WorkspaceEnrollmentRecoveryGate';
import {workspaceApi} from './workspace-api';
import {REQUIRED_WORKSPACE_CONTRACTS,workspaceFetch} from './workspace-protocol';
import {workspaceEnrollmentHold} from './workspace-enrollment-state';

const api='https://api.invented-clinic.workspace.cosmas.ai',headers={'X-Cosmas-Workspace-Protocol':'1','Content-Type':'application/json','Cache-Control':'no-store'};
const descriptor={contract_version:1,workspace_protocol:1,requests_require_protocol:true,contracts:{...REQUIRED_WORKSPACE_CONTRACTS}};
const response=(value:unknown,status=200,extra:Record<string,string>={})=>new Response(JSON.stringify(value),{status,headers:{...headers,...extra}});
let root:Root,host:HTMLDivElement,billing:'allowed'|'canceled'|'unpaid'|'unavailable';
const identity=()=>({mode:'clerk_jwt' as const,getToken:vi.fn(async()=> 'invented.fresh.token')});
beforeEach(()=>{vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);billing='allowed';
  vi.stubEnv('VITE_API_BASE',api);vi.stubEnv('VITE_WORKSPACE_HOSTED_API_ORIGIN',api);vi.stubEnv('VITE_WORKSPACE_WEB_ORIGIN','https://workspace.example.invalid');
  vi.stubEnv('VITE_WORKSPACE_HOSTED_CLIENT','web');vi.stubEnv('VITE_WORKSPACE_DATA_MODE','synthetic');vi.stubEnv('VITE_COSMAS_ENV','early_adopter_beta');vi.stubEnv('VITE_WORKSPACE_HOSTED_ENABLED','true');
  vi.stubEnv('VITE_WORKSPACE_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_AUTHENTICATED_ENABLED','true');
  vi.stubGlobal('window',{location:{href:'https://workspace.example.invalid/'}});host=document.createElement('div');document.body.append(host);root=createRoot(host);
  vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>{
    const path=new URL(String(input)).pathname;
    if(path==='/practice-access/compatibility')return response(descriptor);
    if(path==='/config')return response({enrollment_managed:true,enrollment_account_origin:'https://app.cosmas.ai',enrollment_recovery_url:'https://app.cosmas.ai/onboarding'});
    if(billing!=='allowed'){const code=billing==='unavailable'?'workspace_enrollment_admission_unavailable':'workspace_enrollment_access_required';return response({detail:code},billing==='unavailable'?503:403,{'X-Cosmas-Enrollment-Admission':code});}
    return response(path==='/account/identity'?{allowed:true}:[]);
  }));
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();vi.unstubAllEnvs();});
async function wait(check:()=>void){for(let i=0;i<100;i++){let done=false;await act(async()=>{await new Promise(resolve=>setTimeout(resolve,1));try{check();done=true;}catch{}});if(done)return;}check();}
async function checkAccess(){await act(async()=>[...host.querySelectorAll('button')].find(item=>item.textContent==='Check practice access')!.click());await wait(()=>expect(host.querySelector<HTMLButtonElement>('.workspace-enrollment-recovery button')?.disabled??false).toBe(false));}
it('pauses a bookmarked workspace for canceled/unpaid billing and resumes only after a fresh protected allowed response',async()=>{
  const id=identity(),mounted=vi.fn(),unmounted=vi.fn();const saved={key:'invented_saved_request',note:'Invented saved private note'},before=structuredClone(saved);
  function Workspace(){useEffect(()=>{mounted();return unmounted;},[]);return <p>{saved.note}</p>;}
  await act(async()=>root.render(<WorkspaceCompatibilityGate identity={id} accountControls={<span>Account menu</span>}><Workspace/></WorkspaceCompatibilityGate>));
  expect(host.textContent).toContain(saved.note);billing='canceled';
  await act(async()=>{await expect(workspaceApi.catalog(id)).rejects.toMatchObject({status:403,code:'workspace_enrollment_access_required'});});
  await wait(()=>expect(host.querySelector('a')?.getAttribute('href')).toBe('https://app.cosmas.ai/onboarding'));
  expect(host.textContent).toContain('Practice access is paused');expect(host.textContent).not.toContain(saved.note);expect(unmounted).toHaveBeenCalledOnce();expect(saved).toEqual(before);
  await checkAccess();expect(workspaceEnrollmentHold(id)).toBe('workspace_enrollment_access_required');expect(mounted).toHaveBeenCalledOnce();
  billing='unpaid';await checkAccess();expect(host.textContent).toContain('Practice access is still paused');expect(mounted).toHaveBeenCalledOnce();
  billing='allowed';await checkAccess();await wait(()=>expect(host.textContent).toContain(saved.note));expect(workspaceEnrollmentHold(id)).toBeNull();expect(mounted).toHaveBeenCalledTimes(2);
  expect(vi.mocked(fetch).mock.calls.filter(([url])=>String(url)===api+'/account/identity')).toHaveLength(3);
  expect(vi.mocked(fetch).mock.calls.every(([,init])=>init?.method==='GET'&&init.body===undefined)).toBe(true);expect(id.getToken).toHaveBeenCalledWith({skipCache:true});
});
it('withholds access when admission is unavailable and suppresses a late successful clinical response after a hold',async()=>{
  const id=identity();await act(async()=>root.render(<WorkspaceCompatibilityGate identity={id} accountControls={null}><p>Invented private content</p></WorkspaceCompatibilityGate>));
  let finish!:(value:Response)=>void;vi.mocked(fetch).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
  const late=workspaceFetch(id,api+'/workspaces',{headers:{'X-Cosmas-Workspace-Protocol':'1'}}).catch(error=>error);
  billing='unavailable';await act(async()=>{await expect(workspaceApi.catalog(id)).rejects.toMatchObject({status:503,code:'workspace_enrollment_admission_unavailable'});});
  finish(response({private:'late private content'}));expect(await late).toMatchObject({status:403});
  expect(host.textContent).not.toContain('Invented private content');expect(host.textContent).toContain('could not confirm your practice account');
});
it('accepts only the exact owned recovery destination bound by the managed runtime',()=>{
  expect(enrollmentRecoveryDestination('https://app.cosmas.ai/onboarding',undefined,'https://app.cosmas.ai')).toBe('https://app.cosmas.ai/onboarding');
  expect(enrollmentRecoveryDestination('https://app.cosmas.ai/onboarding')).toBeNull();
  for(const value of [null,'https://staging.cosmas.ai/onboarding','https://app.cosmas.ai.evil.invalid/onboarding','https://user@app.cosmas.ai/onboarding','https://app.cosmas.ai/onboarding?trial=new','https://app.cosmas.ai/sign-in'])expect(enrollmentRecoveryDestination(value,undefined,'https://app.cosmas.ai')).toBeNull();
});
it('admits only an explicitly configured stage recovery URL with the trusted staging API, and keeps production separate',()=>{
  const stage='https://staging.cosmas.ai/onboarding',production='https://app.cosmas.ai/onboarding';
  for(const origin of ['https://staging.cosmas.ai','https://api.staging.cosmas.ai','https://api.invented-clinic.staging.cosmas.ai']){
    expect(enrollmentRecoveryDestination(stage,origin,'https://staging.cosmas.ai')).toBe(stage);expect(enrollmentRecoveryDestination(null,origin,'https://staging.cosmas.ai')).toBeNull();expect(enrollmentRecoveryDestination(production,origin,'https://app.cosmas.ai')).toBeNull();
  }
  for(const origin of ['https://api.cosmas.ai','https://api.invented-clinic.workspace.cosmas.ai']){
    expect(enrollmentRecoveryDestination(production,origin,'https://app.cosmas.ai')).toBe(production);expect(enrollmentRecoveryDestination(stage,origin,'https://staging.cosmas.ai')).toBeNull();
  }
  for(const api of ['http://staging.cosmas.ai','https://staging.cosmas.ai.evil.invalid','https://staging.cosmas.ai:8443','https://user@staging.cosmas.ai','https://staging.cosmas.ai?next=evil','https://staging.cosmas.ai/#redirect'])expect(enrollmentRecoveryDestination(stage,api,'https://staging.cosmas.ai')).toBeNull();
  for(const value of [stage+'?next=https://app.cosmas.ai',stage+'#redirect','https://staging.cosmas.ai/sign-in','https://user@staging.cosmas.ai/onboarding','https://other.invalid/onboarding'])expect(enrollmentRecoveryDestination(value,'https://staging.cosmas.ai','https://staging.cosmas.ai')).toBeNull();
});
it('uses the separate staging account host only when it matches the immutable account binding',()=>{
  const account='https://onboarding.staging.cosmas.ai',url=account+'/onboarding',api='https://api.invented-clinic.staging.cosmas.ai';
  expect(enrollmentRecoveryDestination(url,api,account)).toBe(url);
  expect(enrollmentRecoveryDestination(url,api,'https://staging.cosmas.ai')).toBeNull();
  expect(enrollmentRecoveryDestination('https://staging.cosmas.ai/onboarding',api,account)).toBeNull();
  for(const binding of [undefined,null,account+'/',account+':443',account+'?next=evil','https://user@onboarding.staging.cosmas.ai','https://onboarding.staging.cosmas.ai.evil.invalid','https://other.invalid'])
    expect(enrollmentRecoveryDestination(url,api,binding)).toBeNull();
  expect(enrollmentRecoveryDestination('https://other.invalid/onboarding',api,'https://other.invalid')).toBeNull();
  expect(enrollmentRecoveryDestination(url,'https://api.cosmas.ai',account)).toBeNull();
});
it('renders recovery at the separately bound staging account host after a real hold',async()=>{
  const stageApi='https://api.invented-clinic.staging.cosmas.ai',account='https://onboarding.staging.cosmas.ai';
  vi.stubEnv('VITE_API_BASE',stageApi);vi.stubEnv('VITE_WORKSPACE_HOSTED_API_ORIGIN',stageApi);
  const existing=vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation((input,init)=>new URL(String(input)).pathname==='/config'
    ?Promise.resolve(response({enrollment_managed:true,enrollment_account_origin:account,enrollment_recovery_url:account+'/onboarding'})):existing(input,init));
  const id=identity();await act(async()=>root.render(<WorkspaceCompatibilityGate identity={id} accountControls={null}><p>Invented work</p></WorkspaceCompatibilityGate>));
  billing='canceled';await act(async()=>{await expect(workspaceApi.catalog(id)).rejects.toMatchObject({status:403});});
  await wait(()=>expect(host.querySelector('a')?.getAttribute('href')).toBe(account+'/onboarding'));
});
it('does not release an existing hold when the signed session becomes obsolete during recovery',async()=>{
  let current=true;const id={...identity(),nativeSession:{revision:'invented-session',isCurrent:()=>current}};
  await act(async()=>root.render(<WorkspaceCompatibilityGate identity={id} accountControls={null}><p>Invented private work</p></WorkspaceCompatibilityGate>));
  billing='canceled';await act(async()=>{await expect(workspaceApi.catalog(id)).rejects.toMatchObject({status:403});});
  let finish!:(value:Response)=>void;const existing=vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation((input,init)=>new URL(String(input)).pathname==='/account/identity'
    ?new Promise(resolve=>{finish=resolve;}):existing(input,init));
  billing='allowed';await act(async()=>{host.querySelector<HTMLButtonElement>('.workspace-enrollment-recovery button')!.click();});
  await wait(()=>expect(finish).toBeTypeOf('function'));current=false;
  await act(async()=>{finish(response({allowed:true}));});
  await wait(()=>expect(host.textContent).toContain('Practice access is still paused'));
  expect(workspaceEnrollmentHold(id)).toBe('workspace_enrollment_access_required');expect(host.textContent).not.toContain('Invented private work');
});
it('returns no recovery URL for missing, foreign or malformed API origins',()=>{
  for(const origin of ['', 'https://api.example.invalid','https://cosmas.ai','https://app.cosmas.ai','https://enrollment-api.staging.cosmas.ai','https://api.clinic.staging.cosmas.ai.evil.invalid','https://api.-clinic.staging.cosmas.ai','https://api.clinic-.workspace.cosmas.ai','https://api.clinic.extra.workspace.cosmas.ai','https://api.cosmas.ai/config','https://api.cosmas.ai?next=evil','https://api.cosmas.ai/#redirect','https://user@api.cosmas.ai','https://api.cosmas.ai:443','https://api.cosmas.ai/'])
    for(const account of ['https://app.cosmas.ai','https://staging.cosmas.ai','https://onboarding.staging.cosmas.ai'])expect(enrollmentRecoveryDestination(account+'/onboarding',origin,account)).toBeNull();
  vi.stubEnv('VITE_WORKSPACE_HOSTED_ENABLED','false');vi.stubEnv('VITE_API_BASE',undefined);expect(enrollmentRecoveryDestination('https://app.cosmas.ai/onboarding')).toBeNull();
});
it('cancels an enrollment denial without reading its opaque response body',async()=>{
  const id=identity();await act(async()=>root.render(<WorkspaceCompatibilityGate identity={id} accountControls={null}><p>Private workspace</p></WorkspaceCompatibilityGate>));
  const cancel=vi.fn(async()=>{}),read=vi.fn(),json=vi.fn();
  vi.mocked(fetch).mockResolvedValueOnce({status:403,ok:false,headers:new Headers({'X-Cosmas-Workspace-Protocol':'1','X-Cosmas-Enrollment-Admission':'workspace_enrollment_access_required'}),body:{cancel,getReader:read},json} as unknown as Response);
  await act(async()=>{await expect(workspaceApi.catalog(id)).rejects.toMatchObject({status:403,code:'workspace_enrollment_access_required'});});
  expect(cancel).toHaveBeenCalledOnce();expect(read).not.toHaveBeenCalled();expect(json).not.toHaveBeenCalled();
});
