// @vitest-environment node
import {describe,expect,it,vi} from 'vitest';
import type {PendingSave} from './model';
import {WorkspaceSession} from './workspace-session';

const operation:PendingSave={type:'entry',body:{expected_revision:1,
  idempotency_key:'00000000-0000-4000-8000-000000000001',kind:'scratchpad',content:'Invented private draft'}};

describe('workspace session ownership',()=>{
  it('retains the exact unconfirmed request when an error is dismissed',()=>{
    const session=new WorkspaceSession();
    const retry=vi.fn(async()=>{});
    session.setPending(operation);
    session.setError('The request could not be confirmed.');
    session.setReadRetry({run:retry});
    session.setError('');
    expect(session.getSnapshot()).toMatchObject({pending:operation,error:'',readRetry:null});
    expect(session.getSnapshot().pending).toBe(operation);
    expect(retry).not.toHaveBeenCalled();
  });

  it('keeps request state when one presentation unsubscribes and another observes it',()=>{
    const session=new WorkspaceSession();
    const workspace=vi.fn(),messages=vi.fn();
    const leaveWorkspace=session.subscribe(workspace);
    session.setPending(operation);
    const retained=session.getSnapshot();
    leaveWorkspace();
    const leaveMessages=session.subscribe(messages);
    expect(session.getSnapshot()).toBe(retained);
    session.setBusy(true);
    expect(workspace).toHaveBeenCalledTimes(1);
    expect(messages).toHaveBeenCalledTimes(1);
    expect(session.getSnapshot().pending).toBe(operation);
    leaveMessages();
    expect(session.getSnapshot().pending).toBe(operation);
  });

  it('invalidates the same lifetime cell captured by existing async operations',()=>{
    const session=new WorkspaceSession();
    const captured=session.generation;
    const admitted=captured.current;
    session.setPending(operation);
    session.invalidate();
    expect(captured).toBe(session.generation);
    expect(captured.current).not.toBe(admitted);
    // Invalidating a callback does not itself retry or discard its saved request.
    expect(session.getSnapshot().pending).toBe(operation);
  });

  it('publishes an error and removes its old read retry in the same snapshot',()=>{
    const session=new WorkspaceSession();
    const retry=vi.fn(async()=>{});
    session.setReadRetry({run:retry});
    const observed:ReturnType<WorkspaceSession['getSnapshot']>[]=[];
    session.subscribe(()=>observed.push(session.getSnapshot()));
    session.setError('Workspace access is unavailable.');
    expect(observed).toHaveLength(1);
    expect(observed[0]).toMatchObject({error:'Workspace access is unavailable.',readRetry:null});
    expect(retry).not.toHaveBeenCalled();
  });
});
