import {act} from 'react';import {createRoot,type Root} from 'react-dom/client';import {afterEach,beforeEach,expect,it,vi} from 'vitest';
const clerk=vi.hoisted(()=>({keys:[] as string[],signedIn:false}));
vi.mock('@clerk/react',()=>({ClerkProvider:({publishableKey,children}:{publishableKey:string;children:unknown})=>{clerk.keys.push(publishableKey);return children;},
  SignUp:()=> 'Clerk Google Microsoft password signup',SignIn:()=> 'Clerk sign in and password recovery',UserButton:()=> 'Account menu',
  useAuth:()=>({isLoaded:true,isSignedIn:clerk.signedIn,getToken:vi.fn(),userId:null,sessionId:null,orgId:null}),useUser:()=>({user:null}),useClerk:()=>({setActive:vi.fn()})}));
import {EnrollmentEntry,enrollmentRouteRequested} from './EnrollmentEntry';import {enrollmentConfig} from './enrollment-test-fixture';
import {enrollmentApiBase} from './enrollment-api';
let root:Root,host:HTMLDivElement;
beforeEach(()=>{clerk.keys=[];vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);host=document.createElement('div');document.body.append(host);root=createRoot(host);window.history.replaceState(null,'','/onboarding?plan=small&seats=5');vi.stubGlobal('fetch',vi.fn());});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();});
const json=(value:unknown)=>new Response(JSON.stringify(value),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
it('admits browser onboarding and its alias while preserving the existing workspace and native entry',()=>{
  expect(enrollmentRouteRequested(true,'https://app.example.invalid/onboarding?plan=small&seats=5')).toBe(true);
  expect(enrollmentRouteRequested(true,'https://app.example.invalid/enroll')).toBe(true);
  expect(enrollmentRouteRequested(false,'https://app.example.invalid/onboarding')).toBe(false);
  expect(enrollmentRouteRequested(true,'https://app.example.invalid/')).toBe(false);
  expect(enrollmentRouteRequested(true,'app://cosmas/onboarding')).toBe(false);
  expect(enrollmentRouteRequested(true,'capacitor://localhost/onboarding')).toBe(false);
});
it('admits separate staging enrollment routes with their independent HTTPS account API',()=>{
  for(const route of ['/onboarding','/enroll','/sign-in','/sign-up'])expect(enrollmentRouteRequested(true,'https://onboarding.staging.cosmas.ai'+route)).toBe(true);
  expect(enrollmentApiBase('https://enrollment-api.staging.cosmas.ai','https://onboarding.staging.cosmas.ai/onboarding')).toBe('https://enrollment-api.staging.cosmas.ai');
  expect(enrollmentRouteRequested(false,'https://staging.cosmas.ai/onboarding')).toBe(false);
});
it('opens the account root only for an explicitly enabled account-only build',()=>{
  const root='https://onboarding.staging.cosmas.ai/?invite=invented';
  expect(enrollmentRouteRequested(true,root,true)).toBe(true);
  expect(enrollmentRouteRequested(true,root,false)).toBe(false);
  expect(enrollmentRouteRequested(false,root,true)).toBe(false);
  for(const route of ['/sign-in','/sign-up','/onboarding','/enroll'])for(const accountOnly of [false,true])
    expect(enrollmentRouteRequested(true,'https://onboarding.staging.cosmas.ai'+route,accountOnly)).toBe(true);
  for(const href of ['app://cosmas/','capacitor://localhost/','https://onboarding.staging.cosmas.ai/workspaces'])expect(enrollmentRouteRequested(true,href,true)).toBe(false);
});
it('checks server admission before mounting Clerk signup for a person without an organization',async()=>{
  vi.mocked(fetch).mockResolvedValue(json(enrollmentConfig()));await act(async()=>root.render(<EnrollmentEntry apiBase="http://127.0.0.1:8910"/>));
  expect(fetch).toHaveBeenCalledOnce();expect(clerk.keys).toEqual(['pk_test_invented']);
  expect(host.textContent).toContain('Clerk Google Microsoft password signup');expect(host.textContent).toContain('Your trial starts when your workspace is ready');
});
it('mounts returning account and password recovery on the matching enrollment route',async()=>{
  window.history.replaceState(null,'','/sign-in');vi.mocked(fetch).mockResolvedValue(json(enrollmentConfig()));await act(async()=>root.render(<EnrollmentEntry apiBase="http://127.0.0.1:8910"/>));
  expect(host.textContent).toContain('Clerk sign in and password recovery');
});
it('stays closed before a qualified account configuration is installed',async()=>{
  vi.mocked(fetch).mockResolvedValue(json({...enrollmentConfig(),enabled:false}));await act(async()=>root.render(<EnrollmentEntry apiBase="http://127.0.0.1:8910"/>));
  expect(clerk.keys).toEqual([]);expect(host.textContent).toContain('Your account and trial have not been created');
});
it('refuses an enrollment key that differs from the supplied build identity',async()=>{
  vi.mocked(fetch).mockResolvedValue(json(enrollmentConfig()));await act(async()=>root.render(<EnrollmentEntry apiBase="http://127.0.0.1:8910" publishableKey="pk_test_different"/>));
  expect(clerk.keys).toEqual([]);expect(host.textContent).toContain('Account setup is not available yet');
});
