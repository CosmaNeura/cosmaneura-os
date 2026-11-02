import {afterEach,describe,expect,it,vi} from 'vitest';
import {validateRegisteredNativeProfile} from '../../clients/shared/native-practice-profile.mjs';
import {NativeWorkspaceTransport,workspaceApiBase,configuredWorkspaceApiBase} from './workspace-base';
import {nativePracticeFixture} from './native-practice-test-fixture';
import type {AuthenticatedWorkspaceIdentity} from './workspace-api';

vi.mock('../../clients/capture/src/native/practice-connection-plugin',()=>({nativePracticeConnectionAvailable:()=>false}));
const identityFor=(profile= nativePracticeFixture()):AuthenticatedWorkspaceIdentity=>({mode:'clerk_jwt',getToken:vi.fn(async()=>null),
  nativeSession:{revision:profile.revision,isCurrent:()=>true,userId:profile.profile.session.subject,
    sessionId:profile.profile.session.session_id,organizationId:profile.profile.nativeIdentity.organizationId}});
afterEach(()=>{vi.unstubAllEnvs();vi.unstubAllGlobals();});
describe('registered native practice routing',()=>{
  it('keeps browser and beta fallback exact and never consults enrollment',()=>{
    const fetcher=vi.fn();vi.stubGlobal('fetch',fetcher);vi.stubEnv('VITE_API_BASE',' https://api.staging.cosmas.ai/// ');
    expect(workspaceApiBase(identityFor())).toBe('https://api.staging.cosmas.ai');
    expect(fetcher).not.toHaveBeenCalled();vi.stubEnv('VITE_API_BASE','');
    expect(workspaceApiBase()).toBe('http://127.0.0.1:8000');expect(workspaceApiBase(undefined,'http://localhost:8000')).toBe('http://localhost:8000');
    expect(configuredWorkspaceApiBase()).toBe('');
  });
  it('binds the actual native revision, subject, session and Org before changing the API',()=>{
    const profile=nativePracticeFixture(),routing=new NativeWorkspaceTransport(()=>profile);
    expect(routing.resolve(identityFor(profile))).toBe(profile);
    const browser:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:vi.fn(async()=>null)};
    expect(()=>routing.resolve(browser)).toThrow('Secure session unavailable');
    for(const field of ['revision','userId','sessionId','organizationId'] as const){
      const identity=identityFor(profile);if(identity.mode!=='clerk_jwt')throw new Error();
      identity.nativeSession={...identity.nativeSession!,[field]:'wrong'};
      expect(()=>routing.resolve(identity)).toThrow('Secure session unavailable');
    }
  });
  it('never reroutes an old identity when the practice changes or disappears',()=>{
    let profile:ReturnType<typeof nativePracticeFixture>|null=nativePracticeFixture();
    const routing=new NativeWorkspaceTransport(()=>profile),old=identityFor(profile);
    expect(routing.resolve(old)).toBe(profile);
    profile=nativePracticeFixture('second','00000000-0000-4000-8000-000000000005');
    expect(()=>routing.resolve(old)).toThrow();expect(routing.resolve(identityFor(profile))).toBe(profile);
    profile=null;expect(()=>routing.resolve(old)).toThrow();
  });
  it('cannot carry a beta identity into a later registered practice',()=>{
    let profile:ReturnType<typeof nativePracticeFixture>|null=null;
    const routing=new NativeWorkspaceTransport(()=>profile),old=identityFor();expect(routing.resolve(old)).toBeNull();
    profile=nativePracticeFixture();expect(()=>routing.resolve(old)).toThrow();
  });
  it('rejects revoked native owners even when the injected profile has not changed',()=>{
    const profile=nativePracticeFixture(),routing=new NativeWorkspaceTransport(()=>profile),owner=identityFor(profile);
    if(owner.mode!=='clerk_jwt')throw new Error();owner.nativeSession={...owner.nativeSession!,isCurrent:()=>false};
    expect(()=>routing.resolve(owner)).toThrow();
  });
  it('retains an activated profile after handshake expiry; runtime session fences remain mandatory',()=>{
    const profile=nativePracticeFixture(),routing=new NativeWorkspaceTransport(()=>profile);
    expect(profile.profile.expires_at*1000).toBeLessThan(Date.now());
    expect(routing.resolve(identityFor(profile))).toBe(profile);
    expect(Object.isFrozen(profile.profile.workspace)).toBe(true);expect(Object.isFrozen(profile.profile.session)).toBe(true);
  });
  it.each(['https://cosmaneura.com/chief','https://invented.staging.cosmas.ai/chief?api=evil','https://other.staging.cosmas.ai/chief'])('rejects an unpaired or untrusted workspace %s',url=>{
    const profile=nativePracticeFixture().profile;expect(()=>validateRegisteredNativeProfile({...profile,workspace:{...profile.workspace,url}})).toThrow();
  });
  it('rejects a mismatched issuer, destination, signature digest, or extra browser state',()=>{
    const profile=nativePracticeFixture().profile;
    for(const altered of [{...profile,session:{...profile.session,issuer:'https://other.clerk.accounts.dev'}},
      {...profile,native_origin:'https://invented.staging.cosmas.ai'},
      {...profile,workspace:{...profile.workspace,native_qualification_sha256:'x'.repeat(64)}},
      {...profile,ready:true}])expect(()=>validateRegisteredNativeProfile(altered)).toThrow();
  });
  it('binds a server-registered UUID hostname to the actual practice UUID',()=>{
    const profile=nativePracticeFixture().profile,practice=profile.practice.practice_id;
    const paired=(label:string)=>({...profile,nativeIdentity:{...profile.nativeIdentity,apiOrigin:`https://api.${label}.staging.cosmas.ai`},
      workspace:{...profile.workspace,url:`https://${label}.staging.cosmas.ai/chief`}});
    expect(validateRegisteredNativeProfile(paired(practice)).practice.practice_id).toBe(practice);
    expect(()=>validateRegisteredNativeProfile(paired('00000000-0000-4000-8000-000000000007'))).toThrow();
  });
});
