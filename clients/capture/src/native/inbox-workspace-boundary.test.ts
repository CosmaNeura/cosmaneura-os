import {webcrypto} from 'node:crypto';
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {coalesceNativeWorkspaceAuth} from './workspace-auth-requests';
import type {WorkspaceAuthPlugin} from './workspace-auth-plugin';
import {parseNativeToken,type NativeAuthState} from '../../../../web/src/native-auth';
import type {AuthenticatedWorkspaceIdentity} from '../../../../web/src/workspace-api';
import {accountIdentityApi} from '../../../../web/src/account-identity-api';
import {inboxApi} from '../../../../web/src/inbox-api';
import {inboxHandoffApi} from '../../../../web/src/inbox-handoff-api';
import {actual as inbox,inboxFixtureOperation,inboxFixtureScope} from '../../../../web/src/inbox-test-fixture';
import {inboxHandoffActor,inboxHandoffFixtureCatalog,inboxHandoffFixtureOperation,inboxHandoffReceipts,inboxHandoffSyntheticProposal} from '../../../../web/src/inbox-handoff-test-fixture';
import identities from '../../../../web/src/__fixtures__/account-identity/actual-account-identity-http.json';

// These are independent frozen synthetic backend vectors. They do not establish
// one shared actor across fixture runs or qualify actual WebKit/native execution.
const api='http://127.0.0.1:8046',token='invented.payload.signature';
const ready:NativeAuthState={phase:'ready',revision:'00000000-0000-4000-8000-000000000017',identity:{userId:'user_invented',sessionId:'sess_invented',organizationId:'org_invented'}};
const headers={'Content-Type':'application/json','Cache-Control':'no-store'};
const json=(body:unknown)=>new Response(JSON.stringify(body),{headers});
beforeEach(()=>{
  vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('window',{location:{href:'capacitor://localhost/index.html'}});vi.stubGlobal('fetch',vi.fn());
  vi.stubEnv('VITE_API_BASE',api);vi.stubEnv('VITE_WORKSPACE_APPLE_LOCAL_TRANSPORT_ENABLED','true');
});
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();vi.unstubAllEnvs();vi.useRealTimers();});

async function bridge(){
  let state=structuredClone(ready);
  const native={
    getState:vi.fn(async()=>structuredClone(state)),getToken:vi.fn(async(_options:{expectedRevision:string})=>({token,revision:ready.revision})),
    signIn:vi.fn(async()=>structuredClone(state)),signOut:vi.fn(async()=>{state={phase:'signedOut',revision:'00000000-0000-4000-8000-000000000018',identity:null};return structuredClone(state);}),
    addListener:vi.fn(async(_event:string,_listener:(state:unknown)=>void)=>({remove:async()=>{}})),
  } satisfies WorkspaceAuthPlugin;
  const auth=coalesceNativeWorkspaceAuth(native);await auth.getState();
  const identity:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>parseNativeToken(await auth.getToken({expectedRevision:ready.revision}),ready.revision)};
  return {native,auth,identity};
}
async function cases(){
  const handoff=await inboxHandoffFixtureCatalog();
  return [
    {name:'Inbox',path:'/inbox',header:'X-Cosmas-Inbox-Contract',contract:'1',body:inbox.catalog,maximum:131072,timeout:503,read:(id:AuthenticatedWorkspaceIdentity,signal?:AbortSignal)=>inboxApi.catalog(id,signal)},
    {name:'handoff',path:'/inbox-handoffs',header:'X-Cosmas-Inbox-Handoff-Contract',contract:'1',body:handoff,maximum:131072,timeout:503,read:(id:AuthenticatedWorkspaceIdentity,signal?:AbortSignal)=>inboxHandoffApi.catalog(id,inboxHandoffActor,signal)},
    {name:'identity',path:'/provider-team/identity',header:'X-Cosmas-Team-Contract',contract:'2',body:identities.owner.body,maximum:1024,timeout:504,read:(id:AuthenticatedWorkspaceIdentity,signal?:AbortSignal)=>accountIdentityApi.read(id,signal)},
  ];
}
function expectRequest(path:string,contract:string,value:string,index=0,method='GET'){
  const [url,init]=vi.mocked(fetch).mock.calls[index],actual=new Headers(init?.headers);
  expect(url).toBe(api+path);expect(init).toMatchObject({method,credentials:'omit',redirect:'error',cache:'no-store',referrerPolicy:'no-referrer'});
  expect(actual.get('Authorization')).toBe('Bearer '+token);expect(actual.get(contract)).toBe(value);expect(actual.get('X-Cosmas-Draft-Recovery')).toBe('2');
  for(const header of ['X-Box-Id','X-Actor-Principal-Id','X-Cosmas-Desktop-Session','Content-Encoding','Transfer-Encoding'])expect(actual.has(header)).toBe(false);
}

describe('Apple Inbox direct-fetch source compatibility',()=>{
  it('forwards all three exact contracts through qualified fresh native token acquisition',async()=>{
    const {native,identity}=await bridge(),entries=await cases();
    for(const [index,entry] of entries.entries()){
      vi.mocked(fetch).mockResolvedValueOnce(json(entry.body));expect(await entry.read(identity)).toEqual(entry.body);
      expectRequest(entry.path,entry.header,entry.contract,index);expect(vi.mocked(fetch).mock.calls[index][1]?.body).toBeUndefined();
    }
    expect(native.getToken).toHaveBeenCalledTimes(3);for(const call of native.getToken.mock.calls)expect(call).toEqual([{expectedRevision:ready.revision}]);
  });
  it('shares only overlapping acquisition for the three contracts and refreshes the next read',async()=>{
    const {native,identity}=await bridge(),entries=await cases();let release!:(v:{token:string;revision:string})=>void;
    native.getToken.mockImplementationOnce(()=>new Promise(resolve=>{release=resolve;}));
    vi.mocked(fetch).mockImplementation(async url=>json(entries.find(e=>api+e.path===url)!.body));
    const reads=Promise.all(entries.map(e=>e.read(identity)));await vi.waitFor(()=>expect(native.getToken).toHaveBeenCalledTimes(1));expect(fetch).not.toHaveBeenCalled();
    release({token,revision:ready.revision});expect(await reads).toEqual(entries.map(e=>e.body));expect(fetch).toHaveBeenCalledTimes(3);expect(native.getToken).toHaveBeenCalledTimes(1);
    await entries[2].read(identity);expect(native.getToken).toHaveBeenCalledTimes(2);
  });
  it('fences the entire overlapping acquisition on sign-out before any contract dispatch',async()=>{
    const {native,auth,identity}=await bridge(),entries=await cases();let release!:(v:{token:string;revision:string})=>void;
    native.getToken.mockImplementationOnce(()=>new Promise(resolve=>{release=resolve;}));
    const reads=Promise.all(entries.map(e=>e.read(identity).then(()=>false,()=>true)));
    await vi.waitFor(()=>expect(native.getToken).toHaveBeenCalledTimes(1));await auth.signOut();expect(await reads).toEqual([true,true,true]);
    release({token,revision:ready.revision});await Promise.resolve();expect(fetch).not.toHaveBeenCalled();
  });
  it('rejects every contract before native acquisition when the explicit Apple-origin gate is off',async()=>{
    const {native,identity}=await bridge();vi.stubEnv('VITE_WORKSPACE_APPLE_LOCAL_TRANSPORT_ENABLED','false');
    for(const entry of await cases())await expect(entry.read(identity)).rejects.toThrow();expect(native.getToken).not.toHaveBeenCalled();expect(fetch).not.toHaveBeenCalled();
  });
  it.each(['capacitor://outside/index.html','capacitor://localhost:8000/index.html','https://outside.invalid'])('rejects unqualified page %s before acquisition',async page=>{
    const {native,identity}=await bridge();vi.stubGlobal('window',{location:{href:page}});
    for(const entry of await cases())await expect(entry.read(identity)).rejects.toThrow();expect(native.getToken).not.toHaveBeenCalled();expect(fetch).not.toHaveBeenCalled();
  });
  it('sends exact frozen Inbox/handoff commands and their explicit resolvers without native HTTP translation',async()=>{
    const {identity}=await bridge(),operation=await inboxFixtureOperation(),handoff=await inboxHandoffFixtureOperation();
    vi.mocked(fetch).mockResolvedValueOnce(json(inbox.review_receipt)).mockResolvedValueOnce(json(inbox.review_receipt)).mockResolvedValueOnce(json(inboxHandoffReceipts[1])).mockResolvedValueOnce(json(inboxHandoffReceipts[1]));
    expect(await inboxApi.execute(identity,operation)).toEqual(inbox.review_receipt);expect(await inboxApi.recover(identity,operation)).toEqual(inbox.review_receipt);
    expect(await inboxHandoffApi.execute(identity,handoff)).toEqual(inboxHandoffReceipts[1]);expect(await inboxHandoffApi.recover(identity,handoff)).toEqual(inboxHandoffReceipts[1]);
    expectRequest(`/inbox/${operation.request.item_id}/review`,'X-Cosmas-Inbox-Contract','1',0,'POST');expectRequest('/inbox/resolve','X-Cosmas-Inbox-Contract','1',1,'POST');
    expectRequest(`/inbox-handoffs/${handoff.scope.id}/decide`,'X-Cosmas-Inbox-Handoff-Contract','1',2,'POST');expectRequest(`/inbox-handoffs/${handoff.scope.id}/resolve`,'X-Cosmas-Inbox-Handoff-Contract','1',3,'POST');
    expect(JSON.parse(vi.mocked(fetch).mock.calls[0][1]!.body as string)).toEqual(operation.request);expect(JSON.parse(vi.mocked(fetch).mock.calls[2][1]!.body as string)).toEqual(handoff.request);
    expect(fetch).toHaveBeenCalledTimes(4);
  });
  it('retains the separate workspace proposal path with an explicitly derived synthetic vector',async()=>{
    const {identity}=await bridge(),{operation,receipt}=await inboxHandoffSyntheticProposal();vi.mocked(fetch).mockResolvedValue(json(receipt));
    expect(await inboxHandoffApi.execute(identity,operation)).toEqual(receipt);expectRequest(`/workspaces/${operation.scope.id}/inbox-handoffs/propose`,'X-Cosmas-Inbox-Handoff-Contract','1',0,'POST');
    expect(JSON.parse(vi.mocked(fetch).mock.calls[0][1]!.body as string)).toEqual(operation.request);
  });
  it('preserves Inbox detail and history bounds on Apple without widening the response budget',async()=>{
    const {identity}=await bridge();vi.mocked(fetch).mockResolvedValueOnce(json(inbox.closed)).mockResolvedValueOnce(json(inbox.history));
    const bundle=await inboxApi.detail(identity,inboxFixtureScope,inbox.closed.summary.item_id);expect(bundle).toEqual({detail:inbox.closed,history:inbox.history});
    expectRequest(`/inbox/${inbox.closed.summary.item_id}`,'X-Cosmas-Inbox-Contract','1',0);expectRequest(`/inbox/${inbox.closed.summary.item_id}/history`,'X-Cosmas-Inbox-Contract','1',1);
    vi.mocked(fetch).mockResolvedValue(new Response(new Uint8Array(2097153),{headers}));await expect(inboxApi.history(identity,inboxFixtureScope,inbox.closed.summary.item_id)).rejects.toThrow();
  });
  it('bounds announced and streamed catalog/account bytes without another dispatch',async()=>{
    const {identity}=await bridge();
    for(const entry of await cases())for(const declared of [true,false]){
      const before=vi.mocked(fetch).mock.calls.length;vi.mocked(fetch).mockResolvedValue(new Response(new Uint8Array(entry.maximum+1),{headers:{...headers,...(declared?{'Content-Length':String(entry.maximum+1)}:{})}}));
      await expect(entry.read(identity)).rejects.toThrow();expect(fetch).toHaveBeenCalledTimes(before+1);
    }
  });
  it('keeps Inbox and handoff receipts within their separate byte limits without retrying a command',async()=>{
    const {identity}=await bridge(),operation=await inboxFixtureOperation(),handoff=await inboxHandoffFixtureOperation();
    vi.mocked(fetch).mockResolvedValueOnce(new Response(new Uint8Array(8193),{headers}));
    await expect(inboxApi.execute(identity,operation)).rejects.toThrow();expect(fetch).toHaveBeenCalledTimes(1);
    vi.mocked(fetch).mockResolvedValueOnce(new Response(new Uint8Array(16385),{headers}));
    await expect(inboxHandoffApi.execute(identity,handoff)).rejects.toThrow();expect(fetch).toHaveBeenCalledTimes(2);
  });
  it('retains the 15-second acquisition deadline for all contracts and never dispatches late credentials',async()=>{
    const {native,identity}=await bridge(),entries=await cases();vi.useFakeTimers();let release!:(v:{token:string;revision:string})=>void;
    native.getToken.mockImplementationOnce(()=>new Promise(resolve=>{release=resolve;}));
    const reads=entries.map(e=>expect(e.read(identity)).rejects.toMatchObject({status:e.timeout}));await vi.advanceTimersByTimeAsync(15000);await Promise.all(reads);
    release({token,revision:ready.revision});await vi.advanceTimersByTimeAsync(1);expect(fetch).not.toHaveBeenCalled();expect(native.getToken).toHaveBeenCalledTimes(1);
  });
  it('keeps whole-body reading inside the same deadline without waiting for uncooperative cancellation',async()=>{
    const {identity}=await bridge(),entries=await cases();vi.useFakeTimers();const cancel=vi.fn(()=>new Promise(()=>{}));
    vi.mocked(fetch).mockImplementation(async()=>({status:200,headers:new Headers(headers),body:{getReader:()=>({read:()=>new Promise(()=>{}),cancel})}} as unknown as Response));
    const reads=entries.map(e=>expect(e.read(identity)).rejects.toMatchObject({status:e.timeout}));await vi.advanceTimersByTimeAsync(15000);await Promise.all(reads);expect(cancel).toHaveBeenCalled();expect(fetch).toHaveBeenCalledTimes(3);
  });
});
