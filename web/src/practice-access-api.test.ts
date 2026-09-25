import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {practiceAccessApi} from './practice-access-api';
import {validateAccessStatus,validateAccessList,type AccessDecision} from './practice-access-contract';
import {accessFixture as row,accessRequired,accessPending,accessConnected} from './practice-access-test-fixture';
import {coalesceNativeWorkspaceAuth} from '../../clients/capture/src/native/workspace-auth-requests';
import {parseNativeToken} from './native-auth';

const api='http://127.0.0.1:8000';
const json=(value:unknown,status=200,extra:Record<string,string>={})=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json','Cache-Control':'no-store',...extra}});
const identity=()=>({mode:'clerk_jwt' as const,getToken:vi.fn(async()=> 'invented.token')});
const command:AccessDecision={request_id:row.request_id,review_sha256:row.review_sha256,confirm:true,decision:'approve'};
beforeEach(()=>{vi.stubEnv('VITE_API_BASE',api);vi.stubEnv('VITE_WORKSPACE_HOSTED_ENABLED','false');vi.stubEnv('VITE_DESKTOP_SYNTHETIC_ENABLED','false');vi.stubGlobal('fetch',vi.fn());});
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();vi.unstubAllEnvs();vi.useRealTimers();});

it('uses five closed routes and fresh credentials without caller-selected identities',async()=>{
  const id=identity(),review={request_id:row.request_id,review_sha256:row.review_sha256,confirm:true as const};
  const submit={idempotency_key:row.request_id,display_name:row.display_name};
  vi.mocked(fetch).mockResolvedValueOnce(json(accessRequired)).mockResolvedValueOnce(json(accessPending))
    .mockResolvedValueOnce(json({...accessPending,state:'cancelled',request:{...row,state:'cancelled'}}))
    .mockResolvedValueOnce(json({contract_version:1,requests:[row]}))
    .mockResolvedValueOnce(json({contract_version:1,request:{...row,state:'approved'}}));
  expect(await practiceAccessApi.read(id)).toEqual(accessRequired);
  expect(await practiceAccessApi.request(id,submit)).toEqual(accessPending);
  expect((await practiceAccessApi.cancel(id,review)).state).toBe('cancelled');
  expect(await practiceAccessApi.pending(id)).toEqual([row]);
  expect((await practiceAccessApi.decide(id,command)).state).toBe('approved');
  const suffixes=['','/request','/cancel','/requests','/decide'];
  for(const [index,[url,init]] of vi.mocked(fetch).mock.calls.entries()){
    expect(url).toBe(api+'/practice-access'+suffixes[index]);
    const headers=new Headers(init?.headers);
    expect(headers.get('X-Cosmas-Practice-Access-Contract')).toBe('1');expect(headers.get('Authorization')).toBe('Bearer invented.token');
    expect(headers.has('X-Cosmas-Team-Contract')).toBe(false);expect(headers.has('X-Box-Id')).toBe(false);
    expect(init).toMatchObject({method:index===0||index===3?'GET':'POST',credentials:'omit',redirect:'error',cache:'no-store'});
  }
  expect(JSON.parse(vi.mocked(fetch).mock.calls[4][1]!.body as string)).toEqual(command);
  expect(id.getToken).toHaveBeenCalledTimes(5);
  expect(()=>practiceAccessApi.request(id,{...submit,subject:'user_other'} as typeof submit)).toThrow();
  expect(()=>practiceAccessApi.decide(id,{...command,confirm:false} as unknown as AccessDecision)).toThrow();
  expect(fetch).toHaveBeenCalledTimes(5);
});
it('rejects mismatched roles, private fields, duplicate requests, and an unrelated decision receipt',async()=>{
  for(const value of [{...accessConnected,request:row},{...accessPending,role:'owner'},{...accessPending,state:'approved'},
    {...accessPending,request:{...row,subject:'user_private'}},{...accessPending,request:{...row,expires_at:'2026-02-30T09:00:00+00:00'}}])expect(()=>validateAccessStatus(value)).toThrow();
  expect(()=>validateAccessList({contract_version:1,requests:[row,row]})).toThrow();
  vi.mocked(fetch).mockResolvedValue(json({contract_version:1,request:{...row,state:'approved',review_sha256:'b'.repeat(64)}}));
  await expect(practiceAccessApi.decide(identity(),command)).rejects.toMatchObject({status:502});
});
it('bounds bytes and rejects redirected, cached, encoded or duplicate-key responses',async()=>{
  const replies=[new Response(new Uint8Array(131073),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}),
    json(accessPending,200,{'Content-Length':'131073'}),json(accessPending,200,{'Cache-Control':'public'}),json(accessPending,200,{'Content-Encoding':'gzip'}),
    new Response('{"contract_version":1,"contract_version":1,"state":"connected","role":"owner","request":null}',{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}})];
  for(const reply of replies){vi.mocked(fetch).mockResolvedValueOnce(reply);await expect(practiceAccessApi.read(identity())).rejects.toMatchObject({status:502});}
  vi.mocked(fetch).mockResolvedValue(json({private:'do not display'},403));
  await expect(practiceAccessApi.read(identity())).rejects.toMatchObject({status:403});
});
it('cancels stalled credentials without dispatch or automatic retries',async()=>{
  const controller=new AbortController();let finish!:(value:string)=>void;
  const id={mode:'clerk_jwt' as const,getToken:()=>new Promise<string>(resolve=>{finish=resolve;})};
  const result=practiceAccessApi.request(id,{idempotency_key:row.request_id,display_name:row.display_name},controller.signal);
  controller.abort();await expect(result).rejects.toMatchObject({status:503});finish('late.token');await Promise.resolve();expect(fetch).not.toHaveBeenCalled();
});
it('uses the existing Apple native token boundary and discards a response after sign-out',async()=>{
  vi.stubGlobal('window',{location:{href:'capacitor://localhost/index.html'}});vi.stubEnv('VITE_WORKSPACE_APPLE_LOCAL_TRANSPORT_ENABLED','true');
  const revision=row.request_id;let current=true;
  const ready={phase:'ready',revision,identity:{userId:'user_invented',sessionId:'sess_invented',organizationId:'org_invented'}};
  const native={getState:vi.fn(async()=>ready),getToken:vi.fn(async()=>({token:'invented.native.token',revision})),
    signIn:vi.fn(async()=>ready),signOut:vi.fn(async()=>{current=false;return {phase:'signedOut',revision:'873c4f63-2c89-4a51-a834-41574da371aa',identity:null};}),
    addListener:vi.fn(async()=>({remove:async()=>{}}))};
  const auth=coalesceNativeWorkspaceAuth(native);await auth.getState();
  const id={mode:'clerk_jwt' as const,nativeSession:{revision,isCurrent:()=>current},getToken:async()=>parseNativeToken(await auth.getToken({expectedRevision:revision}),revision)};
  vi.mocked(fetch).mockResolvedValueOnce(json(accessRequired));expect(await practiceAccessApi.read(id)).toEqual(accessRequired);
  expect(native.getToken).toHaveBeenCalledWith({expectedRevision:revision});
  vi.mocked(fetch).mockImplementationOnce(async()=>{current=false;return json(accessConnected);});
  await expect(practiceAccessApi.read(id)).rejects.toMatchObject({status:401});
  await expect(practiceAccessApi.read(id)).rejects.toMatchObject({status:401});expect(fetch).toHaveBeenCalledTimes(2);
});
