import {afterEach,expect,it,vi} from 'vitest';
import {consumeWorkspaceStartupTeam,readWorkspaceTeam,type WorkspaceStartupTeam} from './workspace-team-read';
import {admitWorkspaceProtocol,workspaceProtocolGeneration,workspaceFetch} from './workspace-protocol';
import {WorkspaceApiError,type ProviderTeam} from './workspace-api';

const team:ProviderTeam={revision:1,template_version:'provider-team-v1',recovery_scope:'a'.repeat(64),configuration:{practice_context:'Invented practice',bots:[]},members:[],llm:{enabled:false,model:'offline'}};
const account=()=>({mode:'clerk_jwt' as const,getToken:async()=> 'invented.token'});
const deferred=()=>{let resolve!:(value:ProviderTeam)=>void,reject!:(cause:unknown)=>void;const promise=new Promise<ProviderTeam>((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
afterEach(()=>{vi.unstubAllEnvs();vi.unstubAllGlobals();vi.restoreAllMocks();});

it('joins only unresolved reads and gives each subscriber a separate result',async()=>{
  const identity=account(),pending=deferred(),read=vi.fn(()=>pending.promise);
  const a=readWorkspaceTeam(identity,read),b=readWorkspaceTeam(identity,read);await Promise.resolve();expect(read).toHaveBeenCalledOnce();
  pending.resolve(team);const [first,second]=await Promise.all([a,b]);first.configuration.practice_context='Changed locally';expect(second.configuration.practice_context).toBe('Invented practice');
  const next=vi.fn(async()=>team);await readWorkspaceTeam(identity,next);expect(next).toHaveBeenCalledOnce();
});
it('cancels one subscriber immediately while retaining the other read',async()=>{
  const identity=account(),pending=deferred(),controller=new AbortController();let transport!:AbortSignal;
  const read=vi.fn((signal:AbortSignal)=>{transport=signal;return pending.promise;});
  const a=readWorkspaceTeam(identity,read,controller.signal),failure=a.catch(error=>error),b=readWorkspaceTeam(identity,read);
  await Promise.resolve();controller.abort();expect((await failure).status).toBe(503);expect(transport.aborted).toBe(false);pending.resolve(team);expect(await b).toEqual(team);
});
it('last subscriber cancellation aborts the transport and a later caller dispatches afresh',async()=>{
  const identity=account(),pending=deferred(),controller=new AbortController();let transport!:AbortSignal;
  const first=readWorkspaceTeam(identity,signal=>{transport=signal;return pending.promise;},controller.signal),failure=first.catch(error=>error);
  await Promise.resolve();controller.abort();expect((await failure).status).toBe(503);expect(transport.aborted).toBe(true);
  const fresh=vi.fn(async()=>team);expect(await readWorkspaceTeam(identity,fresh)).toEqual(team);expect(fresh).toHaveBeenCalledOnce();pending.resolve(team);
});
it('does not merge identities and propagates a denied read without retaining an error',async()=>{
  const pending=deferred(),a=account(),b=account(),read=vi.fn(()=>pending.promise);
  const first=readWorkspaceTeam(a,read).catch(error=>error),second=readWorkspaceTeam(b,read).catch(error=>error);await Promise.resolve();expect(read).toHaveBeenCalledTimes(2);
  pending.reject(new WorkspaceApiError(403));expect((await first).status).toBe(403);expect((await second).status).toBe(403);
  expect(await readWorkspaceTeam(a,async()=>team)).toEqual(team);
});
it('does not dispatch before compatibility and aborts all callers on a protocol block',async()=>{
  vi.stubEnv('VITE_WORKSPACE_HOSTED_ENABLED','true');const identity=account(),read=vi.fn(async()=>team);
  await expect(readWorkspaceTeam(identity,read)).rejects.toMatchObject({status:503});expect(read).not.toHaveBeenCalled();
  admitWorkspaceProtocol(identity,workspaceProtocolGeneration(identity));const pending=deferred();let transport!:AbortSignal;
  const result=readWorkspaceTeam(identity,signal=>{transport=signal;return pending.promise;}).catch(error=>error);await Promise.resolve();
  vi.stubGlobal('fetch',vi.fn(async()=>new Response('',{status:426})));
  await expect(workspaceFetch(identity,'https://api.example.invalid/provider-team',{headers:{'X-Cosmas-Workspace-Protocol':'1'}})).rejects.toMatchObject({status:503});
  expect((await result).status).toBe(503);expect(transport.aborted).toBe(true);pending.resolve(team);
});
it('rechecks native account validity after the shared response',async()=>{
  let current=true;const identity={mode:'desktop_native' as const,revision:'invented',isCurrent:()=>current},pending=deferred();
  const result=readWorkspaceTeam(identity,()=>pending.promise).catch(error=>error);await Promise.resolve();current=false;pending.resolve(team);expect((await result).status).toBe(401);
  const read=vi.fn(async()=>team);await expect(readWorkspaceTeam(identity,read)).rejects.toMatchObject({status:401});expect(read).not.toHaveBeenCalled();
});
it('rejects an already aborted consumer without dispatching',async()=>{
  const controller=new AbortController(),read=vi.fn(async()=>team);controller.abort();await expect(readWorkspaceTeam(account(),read,controller.signal)).rejects.toMatchObject({status:503});expect(read).not.toHaveBeenCalled();
});
it('consumes a startup result once for its exact live owner and deadline',()=>{
  const identity=account(),startup:WorkspaceStartupTeam={identity,protocolGeneration:workspaceProtocolGeneration(identity),expiresAt:performance.now()+1000,value:team};
  expect(consumeWorkspaceStartupTeam(startup,account())).toBeUndefined();expect(consumeWorkspaceStartupTeam({...startup,expiresAt:performance.now()-1},identity)).toBeUndefined();
  const value=consumeWorkspaceStartupTeam(startup,identity)!;value.configuration.practice_context='Changed';expect(team.configuration.practice_context).toBe('Invented practice');expect(consumeWorkspaceStartupTeam(startup,identity)).toBeUndefined();
});
it('refuses startup handoff after native revocation or protocol generation changes',async()=>{
  let current=true;const identity={mode:'desktop_native' as const,revision:'invented',isCurrent:()=>current};
  const startup:WorkspaceStartupTeam={identity,protocolGeneration:workspaceProtocolGeneration(identity),expiresAt:performance.now()+1000,value:team};current=false;expect(consumeWorkspaceStartupTeam(startup,identity)).toBeUndefined();
  vi.stubEnv('VITE_WORKSPACE_HOSTED_ENABLED','true');const browser=account();admitWorkspaceProtocol(browser,workspaceProtocolGeneration(browser));const other={...startup,identity:browser,protocolGeneration:workspaceProtocolGeneration(browser)};
  vi.stubGlobal('fetch',vi.fn(async()=>new Response('',{status:426})));await workspaceFetch(browser,'https://api.example.invalid/provider-team',{headers:{'X-Cosmas-Workspace-Protocol':'1'}}).catch(()=>{});expect(consumeWorkspaceStartupTeam(other,browser)).toBeUndefined();
});
