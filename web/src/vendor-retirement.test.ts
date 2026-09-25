import {afterEach,beforeEach,describe,it,expect,vi} from 'vitest';
import {retirement,actualRetiredVerification,actualCompletedVerification} from './vendor-test-fixture';
import {vendorApi} from './vendor-api';
import connectedRetirements from './vendor-connected-retirement-fixture.json';
import {vendorCanonical,vendorDigest,vendorBytes,validateVendor,VENDOR_JOURNAL_BYTES} from './vendor-contract';
import {prepareVendorOperation,verifyOperationReceipt,type VendorOperation} from './vendor-operation';
import {emptyVendorRecovery,validateVendorRecovery,withVendorCommand,hasUnresolvedVendorCommand,persistVendorRecovery,type VendorRecoveryRecord} from './vendor-recovery';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const identity={mode:'clerk_jwt' as const,getToken:async()=>'invented-local-token'};
const json=(value:unknown)=>new Response(JSON.stringify(value),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
beforeEach(()=>{vi.stubGlobal('crypto',webcrypto);vi.stubEnv('VITE_API_BASE','http://127.0.0.1:8018');});afterEach(()=>{vi.unstubAllGlobals();vi.unstubAllEnvs();});
export function notFoundVerification(op:VendorOperation){return validateVendor('CommandResponse',{contract_version:1,scope:op.scope,command_kind:op.kind,idempotency_key:op.request.idempotency_key,request_sha256:op.request_sha256,outcome:'not_found',effect:null,summary:null,observed_at:retirement.retired.observed_at});}
describe('exact permanent verification retirement',()=>{
  it.each(connectedRetirements)('retains actual connected $request.command_kind retirement through API recovery and new work',async fixture=>{
    const kind=fixture.request.command_kind as 'decide'|'submit';
    const request=validateVendor(kind==='decide'?'VendorDecision':'BoundCommand',fixture.request.request);
    const scope={kind:'workspace' as const,id:fixture.proof.scope.id};
    const op=await prepareVendorOperation(scope,kind,fixture.proof.retirement.ticket_id,request);
    expect(op.request_sha256).toBe(fixture.request.request_sha256);
    const proof=await verifyOperationReceipt(op,fixture.proof);expect(proof.outcome).toBe('retired');
    const fetcher=vi.fn().mockImplementation(async()=>json(fixture.proof));vi.stubGlobal('fetch',fetcher);
    expect(await vendorApi.retire(identity,op)).toEqual(proof);
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual(fixture.request);
    expect(await vendorApi.execute(identity,op)).toEqual(proof);
    expect(await vendorApi.recover(identity,op)).toEqual(proof);
    const next=await prepareVendorOperation(scope,'submit',op.target_id,{expected_version:request.expected_version,
      operation_id:request.operation_id,revision_id:request.revision_id,payload_hash:request.payload_hash,idempotency_key:'next-distinct-reviewed-command'});
    const saved=await validateVendorRecovery(withVendorCommand({...emptyVendorRecovery(scope),pending:op,receipt:proof},next),scope);
    expect(saved.retired_commands).toEqual([{operation:op,receipt:proof}]);expect(saved.receipts).toContainEqual(proof);
    await expect(verifyOperationReceipt({...op,kind:kind==='decide'?'submit':'decide'},fixture.proof)).rejects.toThrow();
    expect(()=>validateVendor('VendorRetire',{...fixture.request,command_kind:kind==='decide'?'submit':'verify'})).toThrow();
  });
  it('verifies actual PostgreSQL/HTTP original request and retired/resolved/late verify proof hashes',async()=>{
    const op=await actualRetiredVerification();expect(op.request_sha256).toBe(retirement.request.request_sha256);for(const value of [retirement.retired,retirement.resolved,retirement.late_verify]){const proof=await verifyOperationReceipt(op,value);expect(proof.outcome).toBe('retired');if(proof.outcome==='retired')expect(proof.retirement).toEqual(retirement.retired.retirement);}
    const completed=await actualCompletedVerification();expect(completed.request_sha256).toBe(retirement.completed.request_sha256);expect((await verifyOperationReceipt(completed,retirement.completed)).outcome).toBe('recorded');
  });
  it('sends only the exact verify wrapper and distinguishes retirement from the original completion receipt',async()=>{
    const retired=await actualRetiredVerification(),completed=await actualCompletedVerification(),fetcher=vi.fn().mockResolvedValueOnce(json(retirement.retired)).mockResolvedValueOnce(json(retirement.completed));vi.stubGlobal('fetch',fetcher);
    expect((await vendorApi.retire(identity,retired)).outcome).toBe('retired');expect((await vendorApi.retire(identity,completed)).outcome).toBe('recorded');expect(fetcher.mock.calls[0][0]).toBe(`http://127.0.0.1:8018/workspaces/${retired.scope.id}/vendor-work/${retired.target_id}/retire`);expect(fetcher.mock.calls[0][1].body).toBe(vendorCanonical(retirement.request));expect(new Headers(fetcher.mock.calls[0][1].headers).get('X-Cosmas-Vendor-Contract')).toBe('1');
  });
  it('permits the same permanent proof on an exact resolver or late original verify',async()=>{
    const op=await actualRetiredVerification(),fetcher=vi.fn().mockImplementation(async()=>json(retirement.resolved));vi.stubGlobal('fetch',fetcher);expect((await vendorApi.recover(identity,op)).outcome).toBe('retired');expect((await vendorApi.execute(identity,op)).outcome).toBe('retired');expect(fetcher.mock.calls.map(c=>c[0])).toEqual([`http://127.0.0.1:8018/workspaces/${op.scope.id}/vendor-work/resolve`,`http://127.0.0.1:8018/workspaces/${op.scope.id}/vendor-work/${op.target_id}/verify`]);
  });
  it('never treats not_found as a successful retirement response',async()=>{
    const op=await actualRetiredVerification();vi.stubGlobal('fetch',vi.fn().mockResolvedValue(json(notFoundVerification(op))));await expect(vendorApi.retire(identity,op)).rejects.toMatchObject({status:502});
  });
  it('rejects staff scope and changed exact requests before authentication or HTTP',async()=>{
    const fetcher=vi.fn(),getToken=vi.fn(identity.getToken);vi.stubGlobal('fetch',fetcher);const op=await actualRetiredVerification();await expect(vendorApi.retire({...identity,getToken},{...op,scope:{kind:'practice_work',id:op.target_id!}})).rejects.toThrow();await expect(vendorApi.retire({...identity,getToken},{...op,request_sha256:'0'.repeat(64)})).rejects.toThrow();expect(fetcher).not.toHaveBeenCalled();expect(getToken).not.toHaveBeenCalled();
  });
  it('rejects changed proof hashes, action/target scopes, unexpected fields and forged recorded-winning effects',async()=>{
    const op=await actualRetiredVerification();for(const value of [{...retirement.retired,scope:{kind:'workspace',id:crypto.randomUUID()}},{...retirement.retired,command_kind:'submit'},{...retirement.retired,retirement:{...retirement.retired.retirement,operation_id:crypto.randomUUID()}},{...retirement.retired,secret:'forbidden'}])await expect(verifyOperationReceipt(op,value)).rejects.toThrow();
    const value=structuredClone(retirement.retired);value.retirement.receipt_sha256='0'.repeat(64);await expect(verifyOperationReceipt(op,value)).rejects.toThrow();
    const completed=await actualCompletedVerification(),bad=structuredClone(retirement.completed);bad.summary.effect='approved';const {receipt_sha256:_,...effect}=bad.effect;bad.effect.receipt_sha256=await vendorDigest('cosmas-vendor-public-receipt.v1',{scope:bad.scope,command_kind:bad.command_kind,idempotency_key:bad.idempotency_key,request_sha256:bad.request_sha256,effect,summary:bad.summary});await expect(verifyOperationReceipt(completed,bad)).rejects.toThrow();
  });
  it('keeps exact original request and retirement proof when a new explicit owner result starts',async()=>{
    const op=await actualRetiredVerification(),proof=validateVendor('RetirementResponse',retirement.retired),r={...emptyVendorRecovery(op.scope),pending:op,receipt:proof};expect(hasUnresolvedVendorCommand({...r,receipt:notFoundVerification(op)})).toBe(true);expect(hasUnresolvedVendorCommand(r)).toBe(false);
    const b=validateVendor('VendorVerify',retirement.request.request),next=await prepareVendorOperation(op.scope,'result',op.target_id,{expected_version:b.expected_version,operation_id:b.operation_id,revision_id:b.revision_id,payload_hash:b.payload_hash,idempotency_key:'new-manual-owner-result',observation_head:b.observation_head,evidence_sha256:b.evidence_sha256,disposition:'verified_in_vendor',evidence:'Invented manual outcome verified directly.'});
    const saved=await validateVendorRecovery(withVendorCommand(r,next),op.scope);expect(saved.retired_commands).toEqual([{operation:op,receipt:proof}]);expect(saved.receipts).toContainEqual(proof);expect(saved.pending).toEqual(next);expect(saved.receipt).toBeNull();
  });
  it('fails closed on duplicate or cross-scope retired-command history without deleting the current proof',async()=>{
    const op=await actualRetiredVerification(),proof=validateVendor('RetirementResponse',retirement.retired),pair={operation:op,receipt:proof},r={...emptyVendorRecovery(op.scope),pending:op,receipt:proof,retired_commands:[pair]};await validateVendorRecovery(r,op.scope);
    await expect(validateVendorRecovery({...r,retired_commands:[pair,pair]},op.scope)).rejects.toThrow();await expect(validateVendorRecovery({...r,retired_commands:[{...pair,operation:{...op,scope:{kind:'workspace',id:crypto.randomUUID()}}}]},op.scope)).rejects.toThrow();await expect(validateVendorRecovery({...r,retired_commands:Array(101).fill(pair)},op.scope)).rejects.toThrow();expect(r.pending).toEqual(op);expect(r.receipt).toEqual(proof);
  });
  it('retains the previous exact pending/proof and edited text when a new command would exceed the journal cap',async()=>{
    const op=await actualRetiredVerification(),proof=validateVendor('RetirementResponse',retirement.retired),r:VendorRecoveryRecord={...emptyVendorRecovery(op.scope),pending:op,receipt:proof};r.draft.message='😀'.repeat(4000);
    const b=validateVendor('VendorVerify',retirement.request.request),next=await prepareVendorOperation(op.scope,'result',op.target_id,{expected_version:b.expected_version,operation_id:b.operation_id,revision_id:b.revision_id,payload_hash:b.payload_hash,idempotency_key:'new-bounded-owner-result',observation_head:b.observation_head,evidence_sha256:b.evidence_sha256,disposition:'verified_in_vendor',evidence:'😀'.repeat(2000)});
    for(let i=0;vendorBytes(withVendorCommand(r,next))<=VENDOR_JOURNAL_BYTES;i++){
      expect(i).toBeLessThan(100);const prior=await prepareVendorOperation(op.scope,'verify',op.target_id,{...b,idempotency_key:`retired-history-${i}`}),p=structuredClone(proof);p.idempotency_key=prior.request.idempotency_key;p.request_sha256=prior.request_sha256;p.retirement.receipt_id=crypto.randomUUID();const {receipt_sha256:_,...metadata}=p.retirement;p.retirement.receipt_sha256=await vendorDigest('cosmas-vendor-public-retirement.v1',{scope:p.scope,command_kind:p.command_kind,idempotency_key:p.idempotency_key,request_sha256:p.request_sha256,retirement:metadata});r.retired_commands.push({operation:prior,receipt:p});r.receipts.push(p);
    }
    expect(vendorBytes(r)).toBeLessThanOrEqual(VENDOR_JOURNAL_BYTES);await validateVendorRecovery(r,op.scope);const before=vendorCanonical(r),access={load:async()=>r,persist:vi.fn(async()=>{}),authorize:vi.fn(async()=>{})};
    await expect(persistVendorRecovery(access,withVendorCommand(r,next))).rejects.toThrow();expect(access.persist).not.toHaveBeenCalled();expect(vendorCanonical(await access.load())).toBe(before);expect(r.pending).toEqual(op);expect(r.receipt).toEqual(proof);expect(r.draft.message).toBe('😀'.repeat(4000));
  });
});
