import {act,type ReactNode} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';

vi.mock('./App',()=>({App:()=> 'Existing workspace root',ClerkBetaApp:()=> 'Existing beta login',
  StatusScreen:()=> 'Existing configuration screen',resolveRuntimeMode:()=> 'synth_os'}));
vi.mock('./EnrollmentEntry',async original=>{
  const actual=await original<typeof import('./EnrollmentEntry')>();
  return {...actual,EnrollmentEntry:({apiBase}:{apiBase?:string})=><p>Central account flow {apiBase}</p>};
});
vi.mock('./attach-build-info',()=>({attachBuildInfo:()=>()=>{}}));
vi.mock('./workspace-lifecycle',()=>({notifyWorkspaceLifecycle:()=>{}}));
vi.mock('@clerk/react',()=>({ClerkProvider:({children}:{children:ReactNode})=>children,
  SignIn:()=>null,SignUp:()=>null,UserButton:()=>null,useAuth:()=>({}),useClerk:()=>({}),useUser:()=>({})}));
import {RuntimeApp} from './runtime';

let root:Root,host:HTMLDivElement;
beforeEach(()=>{
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubEnv('VITE_WORKSPACE_HOSTED_ENABLED','false');
  vi.stubEnv('VITE_ENROLLMENT_ACCOUNT_ONLY','false');
  window.history.replaceState(null,'','/');host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.unstubAllEnvs();vi.unstubAllGlobals();});
it('renders saved account flow at root only with the explicit central build flag',async()=>{
  const props={runtimeMode:'synth_os' as const,workspaceEnabled:false,authenticatedWorkspace:false,
    enrollmentEnabled:true,enrollmentApiBase:'https://enrollment-api.staging.cosmas.ai'};
  await act(async()=>root.render(<RuntimeApp {...props}/>));expect(host.textContent).toBe('Existing workspace root');
  await act(async()=>root.render(<RuntimeApp {...props} enrollmentAccountOnly/>));
  expect(host.textContent).toContain('Central account flow https://enrollment-api.staging.cosmas.ai');
  await act(async()=>root.render(<RuntimeApp {...props} enrollmentAccountOnly enrollmentEnabled={false}/>));
  expect(host.textContent).toBe('Existing configuration screen');
});
it('keeps an obsolete workspace URL in the account flow even with mixed workspace flags',async()=>{
  window.history.replaceState(null,'','/workspaces');
  vi.stubEnv('VITE_COSMAS_ENV','synth_os');vi.stubEnv('VITE_WORKSPACE_ENABLED','true');
  vi.stubEnv('VITE_WORKSPACE_NATIVE_AUTH_ENABLED','true');
  await act(async()=>root.render(<RuntimeApp runtimeMode="synth_os" workspaceEnabled authenticatedWorkspace
    apiBase="http://localhost:8000" clerkPublishableKey="pk_test_beta" enrollmentEnabled enrollmentAccountOnly
    enrollmentApiBase="https://enrollment-api.staging.cosmas.ai"/>));
  expect(host.textContent).toContain('Central account flow');
  expect(host.textContent).not.toContain('Existing workspace');
});
it('keeps explicit returning sign-in in the account flow without the root flag',async()=>{
  window.history.replaceState(null,'','/sign-in');
  await act(async()=>root.render(<RuntimeApp runtimeMode="synth_os" enrollmentEnabled enrollmentAccountOnly={false}/>));
  expect(host.textContent).toContain('Central account flow');
});
