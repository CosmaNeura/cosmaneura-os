import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {nativePracticeFixture} from './native-practice-test-fixture';
import type {AuthenticatedWorkspaceIdentity} from './workspace-api';
vi.mock('../../clients/capture/src/native/practice-connection-plugin',()=>({nativePracticeConnectionAvailable:()=>true}));
const profile=nativePracticeFixture();
let current:boolean,owner:AuthenticatedWorkspaceIdentity,fetcher:ReturnType<typeof vi.fn<typeof fetch>>;
const body=(box=profile.profile.practice.box_id)=>({contract_version:1,box_id:box,actor_id:'00000000-0000-4000-8000-000000000006',recovery_scope:'a'.repeat(64)});
beforeEach(()=>{
  vi.resetModules();current=true;
  owner={mode:'clerk_jwt',getToken:vi.fn(async()=> 'invented.workspace.token'),nativeSession:{revision:profile.revision,isCurrent:()=>current,
    userId:profile.profile.session.subject,sessionId:profile.profile.session.session_id,organizationId:profile.profile.nativeIdentity.organizationId}};
  const page={location:{href:'capacitor://localhost/index.html'}};
  Object.defineProperty(page,'__cosmasRegisteredWorkspace',{value:profile,writable:false,configurable:false});vi.stubGlobal('window',page);
  for(const [key,value] of Object.entries({VITE_API_BASE:'https://api.staging.cosmas.ai',VITE_WORKSPACE_HOSTED_ENABLED:'true',
    VITE_WORKSPACE_ENABLED:'true',VITE_WORKSPACE_AUTHENTICATED_ENABLED:'true',VITE_WORKSPACE_NATIVE_AUTH_ENABLED:'true',
    VITE_COSMAS_ENV:'early_adopter_beta',VITE_WORKSPACE_DATA_MODE:'synthetic',VITE_WORKSPACE_HOSTED_CLIENT:'apple',
    VITE_WORKSPACE_HOSTED_API_ORIGIN:'https://api.staging.cosmas.ai'}))vi.stubEnv(key,value);
  fetcher=vi.fn<typeof fetch>(async url=>{const response=new Response(JSON.stringify(body()),{headers:{'Content-Type':'application/json','Cache-Control':'no-store','X-Cosmas-Workspace-Protocol':'1'}});
    Object.defineProperty(response,'url',{value:String(url)});return response;});vi.stubGlobal('fetch',fetcher);
});
afterEach(()=>{vi.unstubAllEnvs();vi.unstubAllGlobals();});
async function admitted(){const protocol=await import('./workspace-protocol');protocol.admitWorkspaceProtocol(owner,protocol.workspaceProtocolGeneration(owner));return import('./account-identity-api');}
it('routes a real account identity client to its paired practice API with its fresh native token and matching Box',async()=>{
  const {accountIdentityApi}=await admitted();await expect(accountIdentityApi.read(owner)).resolves.toEqual(body());
  expect(fetcher).toHaveBeenCalledOnce();const [url,request]=fetcher.mock.calls[0];
  expect(url).toBe(profile.profile.nativeIdentity.apiOrigin+'/provider-team/identity');
  expect(new Headers(request?.headers).get('Authorization')).toBe('Bearer invented.workspace.token');
  expect(request).toMatchObject({credentials:'omit',redirect:'error',cache:'no-store'});
  expect(String(url)).not.toContain('enrollment');
});
it('rejects a valid but wrong-Box account identity before displaying private practice data',async()=>{
  const {accountIdentityApi}=await admitted();fetcher.mockResolvedValue(new Response(JSON.stringify(body('00000000-0000-4000-8000-000000000007')),
    {headers:{'Content-Type':'application/json','Cache-Control':'no-store','X-Cosmas-Workspace-Protocol':'1'}}));
  await expect(accountIdentityApi.read(owner)).rejects.toMatchObject({status:401});
});
it('rejects an in-flight old native response after the owner is fenced',async()=>{
  const {accountIdentityApi}=await admitted();fetcher.mockImplementationOnce(async()=>{current=false;return new Response(JSON.stringify(body()),
    {headers:{'Content-Type':'application/json','Cache-Control':'no-store','X-Cosmas-Workspace-Protocol':'1'}});});
  await expect(accountIdentityApi.read(owner)).rejects.toMatchObject({status:401});expect(fetcher).toHaveBeenCalledOnce();
});
it('rejects a mutable browser-installed profile before acquiring a native token',async()=>{
  vi.stubGlobal('window',{location:{href:'capacitor://localhost/index.html'},__cosmasRegisteredWorkspace:profile});
  await expect(admitted()).rejects.toThrow('Secure session unavailable');
  expect(fetcher).not.toHaveBeenCalled();if(owner.mode!=='clerk_jwt')throw new Error();expect(owner.getToken).not.toHaveBeenCalled();
});
it('ignores a query-selected profile and retains the compiled beta destination',async()=>{
  vi.stubGlobal('window',{location:{href:'capacitor://localhost/index.html?profile=https://invented.staging.cosmas.ai'}});
  const {workspaceApiBase}=await import('./workspace-base');expect(workspaceApiBase(owner)).toBe('https://api.staging.cosmas.ai');
  expect(fetcher).not.toHaveBeenCalled();
});
