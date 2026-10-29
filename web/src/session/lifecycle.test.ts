// @vitest-environment node
import {describe,expect,it,vi} from 'vitest';
import {WorkspaceApiError} from '../workspace-api';
import {WorkspaceSession} from './workspace-session';
import type {LifecycleContext} from './lifecycle';
import type {PendingSave} from './model';

const operation:PendingSave={type:'entry',body:{expected_revision:3,
  idempotency_key:'00000000-0000-4000-8000-000000000003',kind:'scratchpad',content:'Invented retained note'}};
const context=():LifecycleContext=>({clear:vi.fn(),recoveryFailed:vi.fn(),invalidateSetup:vi.fn()});

describe('session failure and connection recovery',()=>{
  it.each([401,403,404,426])('clears private content before reporting access failure %s',status=>{
    const session=new WorkspaceSession(),host=context();
    host.clear=vi.fn(()=>{session.invalidate();session.setIdentity(null);session.setPending(null);});
    session.setIdentity({boxId:'invented-box',actorId:'invented-human'});session.setPending(operation);
    session.lifecycle.failure(new WorkspaceApiError(status),host);
    expect(host.clear).toHaveBeenCalledOnce();
    expect(session.getSnapshot()).toMatchObject({identity:null,pending:null});
    expect(session.getSnapshot().error).toContain(status===426?'Update required':'Workspace access is unavailable');
  });

  it('retains an uncertain write and only offers the supplied read retry',async()=>{
    const session=new WorkspaceSession(),host=context(),retry=vi.fn(async()=>{});
    session.setPending(operation);
    session.lifecycle.failure(new Error('Invented transport interruption'),host,retry);
    expect(session.getSnapshot().pending).toBe(operation);
    expect(retry).not.toHaveBeenCalled();
    await session.getSnapshot().readRetry?.run();
    expect(retry).toHaveBeenCalledOnce();
    expect(session.getSnapshot().pending).toBe(operation);
    expect(host.clear).not.toHaveBeenCalled();
  });

  it('offers no general retry for an ordinary save whose outcome is uncertain',()=>{
    const session=new WorkspaceSession();session.setPending(operation);
    session.setReadRetry({run:vi.fn(async()=>{})});
    session.lifecycle.failure(new Error('Invented lost save reply'),context());
    expect(session.getSnapshot().pending).toBe(operation);
    expect(session.getSnapshot().readRetry).toBeNull();
  });

  it('invalidates reviewed setup and rejected requests on a conflict',()=>{
    const session=new WorkspaceSession(),host=context();session.setPending(operation);
    session.lifecycle.failure(new WorkspaceApiError(409),host);
    expect(session.getSnapshot()).toMatchObject({pending:null,conflict:true});
    expect(host.invalidateSetup).toHaveBeenCalledOnce();
  });

  it.each([400,422])('retains model requests despite a %s response requiring an exact status check',status=>{
    const model:PendingSave={type:'ask',body:{expected_revision:3,team_revision:1,
      idempotency_key:'00000000-0000-4000-8000-000000000004',role:'chief',content:'Invented question'}};
    const session=new WorkspaceSession(),host=context();session.setPending(model);
    const oldRetry=vi.fn(async()=>{});session.setReadRetry({run:oldRetry});
    session.lifecycle.modelFailure(new WorkspaceApiError(status),host);
    expect(session.getSnapshot().pending).toBe(model);
    expect(session.getSnapshot().readRetry).toBeNull();
    expect(oldRetry).not.toHaveBeenCalled();
    expect(host.invalidateSetup).not.toHaveBeenCalled();
  });

  it('drops a stale protocol pause after the same connection recovers',()=>{
    const session=new WorkspaceSession({protocolPhase:()=> 'ready',protocolGeneration:()=>4});
    const host=context();host.authenticated={mode:'clerk_jwt',getToken:vi.fn()};
    session.setPending(operation);session.setConflict(true);
    session.lifecycle.failure(new WorkspaceApiError(503,'workspace_protocol_required'),host);
    expect(session.getSnapshot()).toMatchObject({connectionError:null,error:'',conflict:true,pending:operation});
    expect(host.clear).not.toHaveBeenCalled();
  });

  it('reports a connection pause separately without changing the exact pending request',()=>{
    const session=new WorkspaceSession({protocolPhase:()=> 'pending',protocolGeneration:()=>4});
    const host=context();host.authenticated={mode:'clerk_jwt',getToken:vi.fn()};
    session.setPending(operation);session.setConflict(true);
    session.lifecycle.failure(new WorkspaceApiError(503,'workspace_protocol_required'),host);
    expect(session.getSnapshot().connectionError).toMatchObject({identity:host.authenticated,generation:4});
    expect(session.getSnapshot()).toMatchObject({error:'',conflict:true,pending:operation});
  });

  it('does not let a late connection check overwrite a newer session',async()=>{
    let finish!:()=>void;
    const check=vi.fn(()=>new Promise<void>(resolve=>{finish=resolve;}));
    const session=new WorkspaceSession({checkSyntheticConnection:check});
    const checking=session.lifecycle.recheckSyntheticConnection(context(),false);
    session.invalidate();session.setBusy(false);session.setMessage('New workspace');
    finish();await checking;
    expect(session.getSnapshot()).toMatchObject({busy:false,message:'New workspace'});
  });

  it('rechecks only connectivity and never checks while an exact write or navigation lock is pending',async()=>{
    const check=vi.fn(async()=>{}),session=new WorkspaceSession({checkSyntheticConnection:check});
    session.setPending(operation);await session.lifecycle.recheckSyntheticConnection(context(),false);
    session.setPending(null);await session.lifecycle.recheckSyntheticConnection(context(),true);
    expect(check).not.toHaveBeenCalled();
    await session.lifecycle.recheckSyntheticConnection(context(),false);
    expect(check).toHaveBeenCalledOnce();
    expect(session.getSnapshot().message).toContain('service is available');
  });
});
