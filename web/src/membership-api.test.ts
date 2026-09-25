import {beforeEach,afterEach,describe,it,expect,vi} from 'vitest';
import {membershipApi} from './membership-api';
import {http,process,membershipFixtureIdentity as identity,membershipFixtureScope as scope} from './membership-test-fixture';
import {prepareMembershipOperation} from './membership-operation';
import {validateMembership} from './membership-contract';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const response=(v:unknown,status=200,headers?:Record<string,string>)=>new Response(JSON.stringify(v),{status,headers:{'Content-Type':'application/json','Cache-Control':'no-store',...headers}});
beforeEach(()=>{vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('fetch',vi.fn());vi.stubEnv('VITE_API_BASE','http://127.0.0.1:8000');});afterEach(()=>{vi.unstubAllGlobals();vi.unstubAllEnvs();vi.useRealTimers();});
describe('bounded membership transport',()=>{
 it('bootstraps the exact authorized owner/workspace scope from the bounded options route',async()=>{
  const options={...http.options,scope},identity={mode:'clerk_jwt' as const,getToken:async()=> 'invented-token'};
  vi.mocked(fetch).mockImplementation(async()=>response(options));
  expect((await membershipApi.bootstrap(identity,scope.workspace_id)).scope).toEqual(scope);expect(fetch).toHaveBeenCalledTimes(1);expect(String(vi.mocked(fetch).mock.calls[0][0])).toMatch(new RegExp(`/workspaces/${scope.workspace_id}/membership-work/options$`));
 });
 it.each(['workspace','owner','box'])('rejects bootstrap response with another synthetic %s binding',async part=>{
  const changed={...scope,[part==='workspace'?'workspace_id':part==='owner'?'owner_id':'box_id']:crypto.randomUUID()};vi.mocked(fetch).mockImplementation(async()=>response({...http.options,scope:changed}));await expect(membershipApi.bootstrap(identity,scope.workspace_id)).rejects.toMatchObject({status:403});
 });
 it('rejects a non-UUID bootstrap target before I/O',async()=>{await expect(membershipApi.bootstrap(identity,'../other')).rejects.toMatchObject({status:502});expect(fetch).not.toHaveBeenCalled();});
 it('reads detail plus full history with exact header and owner scope before disclosure',async()=>{
  vi.mocked(fetch).mockImplementation(async url=>response(String(url).endsWith('/history')?process.history:process.detail));
  const got=await membershipApi.detail(identity,scope,process.detail.summary.ticket_id);expect(got.detail).toEqual(process.detail);expect(fetch).toHaveBeenCalledTimes(2);
  for(const [url,init]of vi.mocked(fetch).mock.calls){expect(String(url)).toMatch(new RegExp(`/workspaces/${scope.workspace_id}/membership-work/${process.detail.summary.ticket_id}(?:/history)?$`));expect(new Headers(init?.headers).get('X-Cosmas-Membership-Contract')).toBe('1');expect(init).toMatchObject({method:'GET',credentials:'omit',redirect:'error',cache:'no-store'});}
 });
 it('posts the exact original request once and recovers only its local receipt',async()=>{
  const op=await prepareMembershipOperation(scope,'propose',validateMembership('Proposal',process.proposal_request));vi.mocked(fetch).mockImplementation(async()=>response(process.proposal_receipt));
  await membershipApi.execute(identity,op);expect(JSON.parse(vi.mocked(fetch).mock.calls[0][1]!.body as string)).toEqual(op.request);
  await membershipApi.recover(identity,op);expect(String(vi.mocked(fetch).mock.calls[1][0])).toMatch(/\/resolve$/);expect(JSON.parse(vi.mocked(fetch).mock.calls[1][1]!.body as string)).toEqual({command_kind:op.kind,idempotency_key:op.request.idempotency_key,request_sha256:op.request_sha256});expect(fetch).toHaveBeenCalledTimes(2);
 });
 it.each([401,403,404,426])('fails closed on authority/contract denial %s without consuming private text',async status=>{
  vi.mocked(fetch).mockResolvedValue(response({private:'must not display'},status));await expect(membershipApi.catalog(identity,scope)).rejects.toMatchObject({status});expect(fetch).toHaveBeenCalledTimes(1);
 });
 it('rejects another owner scope before network access',async()=>{await expect(membershipApi.catalog(identity,{...scope,owner_id:crypto.randomUUID()})).rejects.toMatchObject({status:403});expect(fetch).not.toHaveBeenCalled();});
 it('rejects incomplete histories and does not expose latest result from detail alone',async()=>{
  vi.mocked(fetch).mockImplementation(async url=>response(String(url).endsWith('/history')?{...process.history,items:process.history.items.slice(1)}:process.detail));await expect(membershipApi.detail(identity,scope,process.detail.summary.ticket_id)).rejects.toMatchObject({status:502});
 });
 it.each(['declared','streamed'])('enforces the detail32KiB bound for %s excess',async mode=>{
  vi.mocked(fetch).mockImplementation(async url=>String(url).endsWith('/history')?response(process.history):new Response(' '.repeat(32769),{headers:{'Content-Type':'application/json','Cache-Control':'no-store',...(mode==='declared'?{'Content-Length':'32769'}:{})}}));await expect(membershipApi.detail(identity,scope,process.detail.summary.ticket_id)).rejects.toMatchObject({status:503});
 });
 it('caps errors at2KiB and does not retry a failed command',async()=>{
  const op=await prepareMembershipOperation(scope,'propose',validateMembership('Proposal',process.proposal_request));vi.mocked(fetch).mockResolvedValue(new Response(' '.repeat(2049),{status:409,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}));await expect(membershipApi.execute(identity,op)).rejects.toMatchObject({status:503});expect(fetch).toHaveBeenCalledTimes(1);
 });
 it('rejects malformed JSON, duplicate keys and missing no-store',async()=>{
  const s=validateMembership('Scope',http.options.scope),i={boxId:s.box_id,actorId:s.owner_id};
  vi.mocked(fetch).mockResolvedValueOnce(new Response('{"a":1,"a":2}',{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}));await expect(membershipApi.options(i,s)).rejects.toMatchObject({status:502});
  vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify(http.options),{headers:{'Content-Type':'application/json'}}));await expect(membershipApi.options(i,s)).rejects.toMatchObject({status:503});
 });
 it('ends an incomplete read at the shared15s deadline without retries',async()=>{
  vi.useFakeTimers();vi.mocked(fetch).mockImplementation(()=>new Promise(()=>{}));const pending=expect(membershipApi.catalog(identity,scope)).rejects.toMatchObject({status:503});await vi.advanceTimersByTimeAsync(15001);await pending;expect(fetch).toHaveBeenCalledTimes(1);expect(vi.mocked(fetch).mock.calls[0][1]?.signal?.aborted).toBe(true);
 });
});
