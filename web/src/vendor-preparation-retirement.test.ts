import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import fixtures from './vendor-preparation-api-fixture.json';
import {vendorApi} from './vendor-api';
import {validateVendor,vendorCanonical} from './vendor-contract';
import {prepareVendorOperation,verifyOperationReceipt,type VendorOperation} from './vendor-operation';
import {emptyVendorRecovery,hasUnresolvedVendorCommand,recordVendorReceipt,validateVendorRecovery,withVendorCommand,type VendorRecoveryRecord} from './vendor-recovery';

const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const identity={mode:'clerk_jwt' as const,getToken:async()=>'invented-local-token'};
const kinds=['propose','artifact_intent','artifact_content'] as const;
const pdf='%PDF-1.7\nInvented preparation retirement document\n%%EOF';
const json=(value:unknown)=>new Response(JSON.stringify(value),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
beforeEach(()=>{vi.stubGlobal('crypto',webcrypto);vi.stubEnv('VITE_API_BASE','http://127.0.0.1:8018');});
afterEach(()=>{vi.unstubAllGlobals();vi.unstubAllEnvs();});

async function operation(kind:typeof kinds[number]):Promise<VendorOperation>{
  const fixture=fixtures[kind],wrapper=validateVendor('VendorPreparationRetire',fixture.request);
  const scope=validateVendor('Scope',fixture.retired.scope);
  const target=kind==='artifact_content'?fixtures.artifact_content.request.request.artifact_id:null;
  const op=await prepareVendorOperation(scope,kind,target,wrapper.request);
  expect(op.request_sha256).toBe(wrapper.request_sha256);
  return op;
}

describe('actual API preparation retirement and durable recovery',()=>{
  it.each(kinds)('verifies %s proof on retirement, receipt recovery and a late original',async kind=>{
    const fixture=fixtures[kind],op=await operation(kind);
    for(const receipt of [fixture.retired,fixture.resolved,fixture.late_original]){
      const proof=await verifyOperationReceipt(op,receipt);
      expect(proof.outcome).toBe('retired');
      if(proof.outcome==='retired')expect(proof.retirement).toEqual(fixture.retired.retirement);
    }
    const fetcher=vi.fn().mockResolvedValueOnce(json(fixture.retired)).mockResolvedValueOnce(json(fixture.resolved)).mockResolvedValueOnce(json(fixture.late_original));
    vi.stubGlobal('fetch',fetcher);
    expect((await vendorApi.retire(identity,op)).outcome).toBe('retired');
    expect(fetcher.mock.calls[0][0]).toBe(`http://127.0.0.1:8018/workspaces/${op.scope.id}/vendor-preparations/retire`);
    expect(fetcher.mock.calls[0][1].method).toBe('POST');
    expect(fetcher.mock.calls[0][1].body).toBe(vendorCanonical(fixture.request));
    expect((await vendorApi.recover(identity,op)).outcome).toBe('retired');
    // jsdom's Blob omits arrayBuffer; supply the browser interface with exact fixture bytes.
    const bytes=new TextEncoder().encode(pdf),file={size:bytes.byteLength,arrayBuffer:async()=>bytes.buffer} as Blob;
    const late=kind==='artifact_content'?await vendorApi.upload(identity,op,file):await vendorApi.execute(identity,op);
    expect(late.outcome).toBe('retired');
  });

  it.each(kinds)('retains %s original request and proof when corrected preparation starts and reopens',async kind=>{
    const op=await operation(kind),fixture=fixtures[kind];
    let persisted:VendorRecoveryRecord={...emptyVendorRecovery(op.scope),pending:op,receipt:await verifyOperationReceipt(op,fixture.not_found)};
    persisted.draft.message='Keep the clinician\'s edited follow-up.';
    expect(hasUnresolvedVendorCommand(persisted)).toBe(true);
    const access={load:async()=>persisted,persist:vi.fn(async(value:VendorRecoveryRecord|null)=>{if(value)persisted=value;}),authorize:vi.fn(async()=>{})};
    const closed=await recordVendorReceipt(access,persisted,fixture.retired);
    expect(hasUnresolvedVendorCommand(closed)).toBe(false);
    const next=await prepareVendorOperation(op.scope,op.kind,op.target_id,{...op.request,idempotency_key:'corrected-distinct-preparation'});
    const reopened=await validateVendorRecovery(JSON.parse(JSON.stringify(withVendorCommand(closed,next))),op.scope);
    expect(reopened.retired_commands).toEqual([{operation:op,receipt:closed.receipt}]);
    expect(reopened.receipts).toContainEqual(closed.receipt);
    expect(reopened.draft.message).toBe(persisted.draft.message);
    expect(reopened.pending).toEqual(next);
    expect(reopened.receipt).toBeNull();
  });

  it.each(kinds)('keeps %s unresolved after proof storage fails and rejects an unconfirmed or altered proof',async kind=>{
    const op=await operation(kind),fixture=fixtures[kind];
    const record={...emptyVendorRecovery(op.scope),pending:op,receipt:await verifyOperationReceipt(op,fixture.not_found)};
    const before=vendorCanonical(record),access={load:async()=>record,persist:vi.fn(async()=>{throw new Error('journal conflict');}),authorize:vi.fn(async()=>{})};
    await expect(recordVendorReceipt(access,record,fixture.retired)).rejects.toThrow('journal conflict');
    expect(vendorCanonical(record)).toBe(before);
    expect(hasUnresolvedVendorCommand(record)).toBe(true);
    vi.stubGlobal('fetch',vi.fn().mockResolvedValue(json(fixture.not_found)));
    await expect(vendorApi.retire(identity,op)).rejects.toMatchObject({status:502});
    for(const bad of [
      {...fixture.retired,request_sha256:'0'.repeat(64)},
      {...fixture.retired,scope:{kind:'workspace',id:crypto.randomUUID()}},
      {...fixture.retired,retirement:{...fixture.retired.retirement,receipt_sha256:'0'.repeat(64)}},
      {...fixture.retired,retirement:{...fixture.retired.retirement,ticket_id:crypto.randomUUID()}},
    ])await expect(verifyOperationReceipt(op,bad)).rejects.toThrow();
  });

  it('preserves the real recorded winner and unfinished content custody when retirement loses',async()=>{
    const fixture=fixtures['content-winner'],wrapper=validateVendor('VendorPreparationRetire',fixture.request);
    const receipt=validateVendor('ArtifactResponse',fixture.recorded),scope=receipt.scope;
    const op=await prepareVendorOperation(scope,'artifact_content',fixture.request.request.artifact_id,validateVendor('VendorArtifactContent',wrapper.request));
    expect(op.request_sha256).toBe(wrapper.request_sha256);
    const record={...emptyVendorRecovery(scope),artifact:receipt.artifact,artifact_write:op,pending:op};
    const before=await validateVendorRecovery(record,scope);
    vi.stubGlobal('fetch',vi.fn().mockResolvedValue(json(fixture.recorded)));
    const winner=await vendorApi.retire(identity,op);
    expect(winner.outcome).toBe('recorded');
    let persisted:VendorRecoveryRecord|null=null;
    const saved=await recordVendorReceipt({load:async()=>before,persist:async value=>{persisted=value;},authorize:async()=>{}},before,winner);
    expect(persisted).toEqual(saved);
    expect(saved.artifact_write).toEqual(op);
    expect(saved.artifact).toEqual(fixture.recorded.artifact);
    expect(saved.artifact?.state).toBe('receiving');
    expect(saved.retired_commands).toEqual([]);
    const reopened=await validateVendorRecovery(JSON.parse(JSON.stringify(saved)),scope);
    expect(reopened.artifact?.generation).toBe(1);
    expect(reopened.artifact?.lease_until).toBe(fixture.recorded.artifact.lease_until);
  });
});
