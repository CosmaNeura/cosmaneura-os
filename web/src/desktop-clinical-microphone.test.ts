import {expect,it,vi} from 'vitest';
import type {CaptureFlowStore} from '../../clients/capture/src/configured/flow/types';
import type {AuthenticatedWorkspaceIdentity} from './workspace-api';
import {desktopClinicalMicrophone} from './desktop-clinical-microphone';
const workspaceId=crypto.randomUUID(),sessionId=crypto.randomUUID(),revision=crypto.randomUUID(),permitId=crypto.randomUUID();
function fixture(){let current=true,confirmed=true,callback:(v:{permitId:string})=>void=()=>{};
  const active={phase:'recording',sessionId,reviewAfterUpload:true,captureAuthorizedUntil:new Date(Date.now()+90000).toISOString(),lease:{lease_id:crypto.randomUUID(),receipt_id:crypto.randomUUID(),generation:1}};
  const flow={getActiveCaptureState:vi.fn(async()=>active)} as unknown as Pick<CaptureFlowStore,'getActiveCaptureState'>;
  const identity={mode:'desktop_native',revision,isCurrent:()=>current} as Extract<AuthenticatedWorkspaceIdentity,{mode:'desktop_native'}>;
  const source={kind:'microphone' as const,start:vi.fn(async()=>{}),stop:vi.fn(async()=>{if(!confirmed)throw Error('Physical stop unknown');})};
  const port={enabled:true,clinicalAcquire:vi.fn(async(v:{requestId:string})=>({requestId:v.requestId,permitId,revision,expiresAt:active.captureAuthorizedUntil,admitted:true})),clinicalRelease:vi.fn(async(v:{requestId:string})=>({requestId:v.requestId,released:true})),clinicalActive:vi.fn(async(v:{requestId:string})=>({requestId:v.requestId,active:true})),onPrivateRevoked:(fn:typeof callback)=>{callback=fn;return()=>{};}};
  return {source,port,active,flow,runtime:desktopClinicalMicrophone(source,flow,workspaceId,sessionId,identity,port),loseIdentity:()=>{current=false;},denyStop:()=>{confirmed=false;},confirmStop:()=>{confirmed=true;},revoke:()=>callback({permitId})};
}
const startOptions={onChunk:async()=>{},capabilities:{} as never};
it('passes exact saved lease handles through native authorization before browser audio',async()=>{
  const f=fixture();await f.runtime.start(startOptions);expect(f.port.clinicalAcquire.mock.calls[0]![0]).toMatchObject({workspaceId,sessionId,revision,leaseId:f.active.lease.lease_id,leaseReceiptId:f.active.lease.receipt_id,leaseGeneration:1,firstSequenceNumber:0});
  expect(f.source.start).toHaveBeenCalledOnce();await f.runtime.stop();expect(f.port.clinicalRelease).toHaveBeenCalledOnce();
  expect(f.source.stop.mock.invocationCallOrder[0]).toBeLessThan(f.port.clinicalRelease.mock.invocationCallOrder[0]!);
});
it('failed native authority stops without starting and resolves only its returned local stop handle',async()=>{
  const f=fixture();f.port.clinicalAcquire.mockImplementationOnce(async v=>({requestId:v.requestId,permitId,revision,expiresAt:f.active.captureAuthorizedUntil,admitted:false}));
  await expect(f.runtime.start(startOptions)).rejects.toThrow();expect(f.source.start).not.toHaveBeenCalled();expect(f.port.clinicalRelease.mock.calls[0]![0]).toMatchObject({permitId});
});
it('identity changed after native admission never starts a stale browser source',async()=>{
  const f=fixture();f.port.clinicalAcquire.mockImplementationOnce(async v=>{f.loseIdentity();return {requestId:v.requestId,permitId,revision,expiresAt:f.active.captureAuthorizedUntil,admitted:true};});
  await expect(f.runtime.start(startOptions)).rejects.toThrow();expect(f.source.start).not.toHaveBeenCalled();expect(f.port.clinicalRelease).toHaveBeenCalledOnce();
});
it('expired native Start window stops the real source and retains exact stop cleanup',async()=>{
  const f=fixture();f.port.clinicalActive.mockRejectedValueOnce(Error('Native Start window expired'));
  await expect(f.runtime.start(startOptions)).rejects.toThrow();expect(f.source.start).toHaveBeenCalledOnce();expect(f.source.stop).toHaveBeenCalledOnce();expect(f.port.clinicalRelease).toHaveBeenCalledOnce();
});
it('unconfirmed browser stop retains the clinical permit until exact retry',async()=>{
  const f=fixture();await f.runtime.start(startOptions);f.denyStop();await expect(f.runtime.stop()).rejects.toThrow();expect(f.port.clinicalRelease).not.toHaveBeenCalled();
  f.confirmStop();await f.runtime.stop();expect(f.port.clinicalRelease.mock.calls[0]![0]).toMatchObject({permitId});
});
it('native revocation closes physical tracks and saved stop custody without panel cooperation',async()=>{
  const f=fixture();await f.runtime.start(startOptions);f.revoke();await vi.waitFor(()=>expect(f.port.clinicalRelease).toHaveBeenCalledOnce());expect(f.source.stop).toHaveBeenCalledOnce();
});
