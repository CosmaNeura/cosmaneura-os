import {afterEach,beforeEach,expect,it,vi} from "vitest";
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>("node:crypto");
import {teamSetupApi} from "./team-setup-api";
import {requestTeamPayload,workspaceApi,type AuthenticatedWorkspaceIdentity} from "./workspace-api";
import {TEAM_REQUEST_BYTES,TEAM_RESPONSE_BYTES} from "./team-setup-request";
import legacySetup from "./__fixtures__/team-setup.json";
import legacyRehearsal from "./__fixtures__/team-rehearsal.json";
import {upgradeSetupFixture,upgradeRehearsalFixture} from './team-policy-test-fixture';
// Explicit current-client derivatives; original W33 actual response fixtures remain unchanged.
const actualSetup=upgradeSetupFixture(legacySetup as import('./team-setup-api').TeamSetup);
const actualRehearsal=upgradeRehearsalFixture(legacyRehearsal as import('./team-setup-request').TeamRehearsal);
import type {TeamConfiguration} from "./workspace-api";
const access:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=> 'invented-private-token'};
const json=(value:unknown,status=200,headers:Record<string,string>={})=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json','Cache-Control':'private, no-store',...headers}});
beforeEach(()=>{vi.stubEnv('VITE_API_BASE','http://127.0.0.1:8018');vi.stubGlobal('crypto',webcrypto);});
afterEach(()=>{vi.unstubAllEnvs();vi.unstubAllGlobals();vi.useRealTimers();});
it('uses only compatible team routes and the exact header with fresh credentials and no identity fallback',async()=>{
  const token=vi.fn().mockResolvedValue('invented-private-token'),identity:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:token};
  const fetcher=vi.fn<typeof fetch>().mockResolvedValueOnce(json(actualSetup)).mockResolvedValueOnce(json(actualRehearsal));vi.stubGlobal('fetch',fetcher);
  expect(await teamSetupApi.read(identity)).toEqual(actualSetup);
  const body={expected_revision:actualRehearsal.expected_revision,configuration:actualRehearsal.configuration as TeamConfiguration,scenario_id:'team_policy_setup.v1' as const};
  expect(await teamSetupApi.rehearse(identity,body)).toEqual(actualRehearsal);
  expect(fetcher.mock.calls.map(c=>String(c[0]))).toEqual(['http://127.0.0.1:8018/provider-team/setup','http://127.0.0.1:8018/provider-team/rehearsal']);
  for(const [,init]of fetcher.mock.calls){const h=new Headers(init?.headers);expect(h.get('X-Cosmas-Team-Contract')).toBe('4');expect(h.get('Authorization')).toBe('Bearer invented-private-token');expect(h.has('X-Box-Id')).toBe(false);expect(init).toMatchObject({credentials:'omit',cache:'no-store',redirect:'error',referrerPolicy:'no-referrer'});}
  expect(token.mock.calls).toEqual([[{skipCache:true}],[{skipCache:true}]]);expect(fetcher.mock.calls[1][1]?.body).toBe(JSON.stringify(body));
});
it.each(['missing-no-store','wrong-type','wrong-status','unknown-field','wrong-hash','private-source','wrong-revision'])('withholds invalid setup response: %s',async fault=>{
  const value=structuredClone(actualSetup) as any;let headers:Record<string,string>={},status=200;
  if(fault==='missing-no-store')headers['Cache-Control']='private';if(fault==='wrong-type')headers['Content-Type']='text/plain';if(fault==='wrong-status')status=201;
  if(fault==='unknown-field')value.external_authority=true;if(fault==='wrong-hash')value.setup.configuration_sha256='0'.repeat(64);
  if(fault==='private-source')value.setup.capabilities[0].sources.push({kind:'account',key:'core',state:'reviewed',patient:'private'});
  if(fault==='wrong-revision')value.setup.team_revision++;
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(json(value,status,headers)));await expect(teamSetupApi.read(access)).rejects.toBeTruthy();
});
it('retains only a safe closed error code without reflecting private response fields',async()=>{
  const fetcher=vi.fn().mockResolvedValueOnce(json({detail:'team_setup_prerequisites_changed'},409)).mockResolvedValueOnce(json({detail:'team_setup_prerequisites_changed',private:'secret'},409)).mockResolvedValueOnce(json({detail:'private secret'},426));vi.stubGlobal('fetch',fetcher);
  await expect(teamSetupApi.read(access)).rejects.toMatchObject({status:409,code:'team_setup_prerequisites_changed'});
  await expect(teamSetupApi.read(access)).rejects.toMatchObject({status:409,code:undefined});await expect(teamSetupApi.read(access)).rejects.not.toHaveProperty('message',expect.stringContaining('private secret'));
});
it('does not acquire a credential for an already aborted request',async()=>{
  const controller=new AbortController();controller.abort();const token=vi.fn(),fetcher=vi.fn();vi.stubGlobal('fetch',fetcher);
  await expect(teamSetupApi.read({mode:'clerk_jwt',getToken:token},controller.signal)).rejects.toMatchObject({status:503});expect(token).not.toHaveBeenCalled();expect(fetcher).not.toHaveBeenCalled();
});
it('bounds a stuck credential and prevents a late credential from dispatching',async()=>{
  vi.useFakeTimers();let resolve!:(value:string)=>void;const fetcher=vi.fn();vi.stubGlobal('fetch',fetcher);
  const check=expect(teamSetupApi.read({mode:'clerk_jwt',getToken:()=>new Promise(r=>{resolve=r;})})).rejects.toMatchObject({status:503});
  await vi.advanceTimersByTimeAsync(30000);await check;resolve('late-secret');await vi.advanceTimersByTimeAsync(1);expect(fetcher).not.toHaveBeenCalled();
});
it('keeps hashing and response validation inside the same credential and body deadline',async()=>{
  vi.useFakeTimers();let resolveToken!:(value:string)=>void;const digest=vi.fn(()=>new Promise<ArrayBuffer>(()=>{}));
  vi.stubGlobal('crypto',{subtle:{digest}});vi.stubGlobal('fetch',vi.fn().mockResolvedValue(json(actualSetup)));
  const check=expect(teamSetupApi.read({mode:'clerk_jwt',getToken:()=>new Promise(r=>{resolveToken=r;})})).rejects.toMatchObject({status:503});
  await vi.advanceTimersByTimeAsync(20000);resolveToken('invented');await vi.advanceTimersByTimeAsync(1);expect(digest).toHaveBeenCalledOnce();
  await vi.advanceTimersByTimeAsync(9999);await check;
});
it('aborts a stalled body explicitly and refuses responses over the response bound',async()=>{
  let canceled=false;const controller=new AbortController();const fetcher=vi.fn().mockResolvedValueOnce(new Response(new ReadableStream({cancel(){canceled=true;}}),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}))
    .mockResolvedValueOnce(new Response(new Uint8Array(TEAM_RESPONSE_BYTES+1),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}));vi.stubGlobal('fetch',fetcher);
  const check=expect(teamSetupApi.read(access,controller.signal)).rejects.toMatchObject({status:503});await new Promise(r=>setTimeout(r,0));controller.abort();await check;expect(canceled).toBe(true);
  await expect(teamSetupApi.read(access)).rejects.toMatchObject({status:503});
});
it('enforces request and response byte boundaries rather than character counts',async()=>{
  const fetcher=vi.fn().mockResolvedValue(json({ok:true}));vi.stubGlobal('fetch',fetcher);
  const exact={body:'x'.repeat(TEAM_REQUEST_BYTES-11)};expect(new TextEncoder().encode(JSON.stringify(exact)).length).toBe(TEAM_REQUEST_BYTES);
  await requestTeamPayload(access,'/provider-team/rehearsal',exact);expect(fetcher).toHaveBeenCalledOnce();
  await expect(requestTeamPayload(access,'/provider-team/rehearsal',{body:exact.body+'x'})).rejects.toMatchObject({status:422});expect(fetcher).toHaveBeenCalledOnce();
  const response='"'+'x'.repeat(TEAM_RESPONSE_BYTES-2)+'"';vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(response,{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}})));
  expect((await requestTeamPayload(access,'/provider-team/setup') as string).length).toBe(TEAM_RESPONSE_BYTES-2);
});
it('validates exact historical saved effect and rejects a mismatching configuration instead of treating it as activation',async()=>{
  const body={expected_revision:0,idempotency_key:'same-preset-request',configuration:actualSetup.team.configuration as TeamConfiguration};
  const bad=structuredClone(actualSetup.team);bad.configuration.bots[0].enabled=false;
  const fetcher=vi.fn().mockResolvedValueOnce(json(actualSetup.team)).mockResolvedValueOnce(json(bad));vi.stubGlobal('fetch',fetcher);
  await expect(workspaceApi.saveTeam(access,body)).resolves.toMatchObject({revision:1});await expect(workspaceApi.saveTeam(access,body)).rejects.toMatchObject({status:503});
});

it('negotiates small closed resource and usage reads without adding private inventory fields',async()=>{
 const {resourcesFixture,usageFixture}=await import('./team-policy-test-fixture');const fetcher=vi.fn().mockResolvedValueOnce(json(resourcesFixture)).mockResolvedValueOnce(json(usageFixture));vi.stubGlobal('fetch',fetcher);
 expect(await teamSetupApi.resources(access)).toEqual(resourcesFixture);expect(await teamSetupApi.usage(access)).toEqual(usageFixture);
 expect(fetcher.mock.calls.map(c=>String(c[0]))).toEqual(['http://127.0.0.1:8018/provider-team/resources','http://127.0.0.1:8018/provider-team/usage']);
 for(const [,init]of fetcher.mock.calls){expect(init.method).toBe('GET');expect(init.body).toBeUndefined();expect(new Headers(init.headers).get('X-Cosmas-Team-Contract')).toBe('4');}
});
it('limits resources and usage to 16 KiB independently of the 8 MiB setup bound',async()=>{
 const fetcher=vi.fn().mockImplementation(()=>Promise.resolve(new Response(new Uint8Array(16385),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}})));vi.stubGlobal('fetch',fetcher);
 await expect(teamSetupApi.resources(access)).rejects.toMatchObject({status:503});await expect(teamSetupApi.usage(access)).rejects.toMatchObject({status:503});
});
it('withholds malformed source inventory and unknown token totals rather than displaying invented readiness',async()=>{
 const {resourcesFixture,usageFixture}=await import('./team-policy-test-fixture');vi.stubGlobal('fetch',vi.fn().mockResolvedValueOnce(json({...resourcesFixture,resources:[{...resourcesFixture.resources[0],account_id:'private'}]})).mockResolvedValueOnce(json({...usageFixture,verified_input_tokens:null,verified_output_tokens:null})));
 await expect(teamSetupApi.resources(access)).rejects.toMatchObject({status:503});await expect(teamSetupApi.usage(access)).rejects.toMatchObject({status:503});
});
