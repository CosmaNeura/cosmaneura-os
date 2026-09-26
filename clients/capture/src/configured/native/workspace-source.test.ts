import {expect, it, vi} from 'vitest';
import {ownedWorkspaceSource} from './workspace-source';
import type {ActiveCaptureState} from '../flow/types';
import type {CaptureSource, CaptureSourceStartOptions} from '../capture';
import {MockCaptureService} from '../mock-bff/state';

function setup() {
  const sessionId='11111111-1111-4111-8111-111111111111', revision='22222222-2222-4222-8222-222222222222';
  const until=new Date(Date.now()+60_000).toISOString();
  let active:ActiveCaptureState={schemaVersion:2,sessionId,phase:'recording',reviewAfterUpload:true,
    captureAuthorizedUntil:until,aggregatePlaintextBudgetBytes:1_000_000,completeIdempotencyKey:'same-completion',
    recordedChunks:0,recordedPlaintextBytes:0,startedAt:new Date().toISOString(),
    lease:{protocol_version:'1.0',session_id:sessionId,lease_id:'33333333-3333-4333-8333-333333333333',
      receipt_id:'44444444-4444-4444-8444-444444444444',generation:1,issued_at:new Date().toISOString(),expires_at:until}};
  const source:CaptureSource={kind:'microphone',start:vi.fn().mockResolvedValue(undefined),stop:vi.fn().mockResolvedValue(undefined)};
  const native={prepareProviderSource:vi.fn().mockResolvedValue({revision,sessionId}),closeProviderSource:vi.fn().mockResolvedValue(undefined)};
  const identity={revision,isCurrent:vi.fn(()=>true)};
  const owned=ownedWorkspaceSource(source,{getActiveCaptureState:async()=>active},'workspace-fixture',sessionId,identity,native);
  // The source boundary passes capabilities through unchanged; PCM validation belongs to its driver.
  const options:CaptureSourceStartOptions={capabilities:new MockCaptureService().capabilities(),onChunk:async()=>{}};
  return {owned,source,native,identity,options,change:()=>{active={...active,phase:'paused'};}};
}

it.each(['changed recording','changed identity'] as const)('does not start after delayed native preparation and %s',async change=>{
  const s=setup();let release:()=>void=()=>{};
  s.native.prepareProviderSource.mockImplementationOnce(()=>new Promise(resolve=>{release=()=>resolve({revision:s.identity.revision,sessionId:'11111111-1111-4111-8111-111111111111'});}));
  const pending=s.owned.start(s.options);
  const refused=expect(pending).rejects.toThrow(change==='changed identity'?'capture_access_unavailable':'capture_state_conflict');
  await vi.waitFor(()=>expect(s.native.prepareProviderSource).toHaveBeenCalledOnce());
  if(change==='changed recording')s.change();else s.identity.isCurrent.mockReturnValue(false);
  release();await refused;expect(s.source.start).not.toHaveBeenCalled();
  await s.owned.stop();expect(s.native.closeProviderSource).toHaveBeenCalledOnce();
});

it('confirms physical stop before retrying native retirement, without restarting or changing the source',async()=>{
  const s=setup(),order:string[]=[];
  s.source.stop=vi.fn(async()=>{order.push('physical-stop');});
  s.native.closeProviderSource.mockImplementationOnce(async()=>{order.push('retirement-lost');throw new Error('invented offline');})
    .mockImplementationOnce(async()=>{order.push('retirement-confirmed');});
  await s.owned.start(s.options);
  await expect(s.owned.stop()).rejects.toMatchObject({code:'capture_stop_acknowledgement_pending'});
  await s.owned.stop();
  expect(order).toEqual(['physical-stop','retirement-lost','physical-stop','retirement-confirmed']);
  expect(s.source.start).toHaveBeenCalledOnce();expect(s.native.prepareProviderSource).toHaveBeenCalledOnce();
  expect(s.native.closeProviderSource.mock.calls[1]).toEqual(s.native.closeProviderSource.mock.calls[0]);
});
