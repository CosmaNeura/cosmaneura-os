import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import normalization from './__fixtures__/model-normalization.json';
import {admissionFixture,conversationFixture,modelReceipt,modelUuid,pendingWorkspace,retryReceipt} from './model-work-test-fixture';
import {exactModelObservation,modelRequestHash,modelStrip,validAdmission,validConversation,validEntryModel,validHandoffRetry,validModelObservation,validModelOperation,validModelWorkspace,validRetryObservation} from './model-work-request';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
beforeEach(()=>vi.stubGlobal('crypto',webcrypto));afterEach(()=>vi.unstubAllGlobals());
it.each(normalization.cases)('matches actual legacy Pydantic normalization and ASCII digest: $case',async sample=>{
  expect(validConversation(sample.request)).toBe(true);expect(modelStrip(sample.request.content)).toBe(sample.normalized_content);
  expect(await modelRequestHash(sample.request)).toBe(sample.request_sha256);
});
it.each([
  {...conversationFixture,role:['visit_prep']},{...conversationFixture,content:'\ud800'},
  {...conversationFixture,content:'x'.repeat(4001)},{...conversationFixture,expected_revision:0},
  {...conversationFixture,team_revision:true},{...conversationFixture,extra:true},
  {...conversationFixture,content:' '.repeat(65536)+'one'},
])('rejects malformed or oversized exact direct request before transport',value=>expect(validConversation(value)).toBe(false));
it('retains scalar rather than UTF16 limits and separates retry hashing',async()=>{
  expect(validConversation({...conversationFixture,content:'😀'.repeat(4000)})).toBe(true);
  const body={expected_revision:7,previous_attempt_id:modelUuid(5),idempotency_key:'invented-retry-key'};
  expect(validHandoffRetry(body)).toBe(true);expect(validHandoffRetry({...body,previous_attempt_id:['invalid']})).toBe(false);
  const digest=await modelRequestHash(body);expect(digest).toMatch(/^[a-f0-9]{64}$/);expect(digest).not.toBe(await modelRequestHash(conversationFixture));
});
it.each(['reserved','running','completed','failed','unknown','abandoned'] as const)('accepts the closed admission state %s without invented usage',state=>{
  const value=admissionFixture(state);expect(validAdmission(value)).toBe(true);expect(validAdmission({...value,usage:'verified'})).toBe(false);
  expect(validAdmission({...value,usage:'verified',input_tokens:0,output_tokens:999999})).toBe(true);
  expect(validAdmission({...value,usage:'verified',input_tokens:1000000,output_tokens:0})).toBe(false);
});
it.each([
  {state:['reserved']},{dispatch:['not_started']},{usage:['unknown']},{unit:true},{admitted_at:'not-time'},
  {private_account:'hidden'},{state:'unknown',dispatch:'started'},{input_tokens:0},
])('refuses malformed admission or false dispatch/usage claims',patch=>expect(validAdmission({...admissionFixture(),...patch})).toBe(false));
it('binds direct receipts to the exact request and permits old saved entries omitted from current view',async()=>{
  const receipt=await modelReceipt();const operation={type:'ask' as const,body:conversationFixture};
  expect(validModelObservation(receipt)).toBe(true);expect(await exactModelObservation(receipt,modelUuid(71),operation)).toBe(true);
  expect(await exactModelObservation(receipt,modelUuid(72),operation)).toBe(false);
  expect(await exactModelObservation(receipt,modelUuid(71),{...operation,body:{...conversationFixture,content:'Changed'}})).toBe(false);
  const current={...(await pendingWorkspace()),revision:99,entries:[]};expect(await validModelWorkspace(current,modelUuid(71))).toBe(true);
  expect(validModelObservation({...receipt,outcome:'running'})).toBe(false);
  expect(validModelObservation({...receipt,outcome:'not_found',saved_entry:null,admission:null,reason:null})).toBe(true);
});
it('binds exact historical retry receipt independently of the current attempt',async()=>{
  const body={expected_revision:2,previous_attempt_id:modelUuid(702),idempotency_key:'old-retry-key'};
  const receipt=await retryReceipt(body,modelUuid(71),modelUuid(701));
  const operation={type:'retry' as const,handoffId:modelUuid(701),body};
  expect(validRetryObservation(receipt)).toBe(true);expect(await exactModelObservation(receipt,modelUuid(71),operation)).toBe(true);
  expect(await exactModelObservation(receipt,modelUuid(71),{...operation,handoffId:modelUuid(704)})).toBe(false);
  expect(await exactModelObservation(receipt,modelUuid(71),{...operation,body:{...body,previous_attempt_id:modelUuid(705)}})).toBe(false);
  expect(validRetryObservation({...receipt,recorded:{...receipt.recorded!,coverage:'retained_legacy',admission:null}})).toBe(true);
  expect(validRetryObservation({...receipt,recorded:{...receipt.recorded!,attempt_number:'2'}})).toBe(false);
});
it('validates second-device projection, immutable bot identity and unique admission joins',async()=>{
  const value=await pendingWorkspace();const metadata=value.entries[0].model_request!;
  expect(validEntryModel(metadata)).toBe(true);expect(await validModelWorkspace(value,value.id)).toBe(true);
  expect(validEntryModel({...metadata,request:{...metadata.request,role:'scribe'}})).toBe(false);
  expect(validEntryModel({...metadata,prepared_envelope:{private:true}})).toBe(false);
  expect(await validModelWorkspace({...value,entries:[...value.entries,{...value.entries[0],id:modelUuid(602)}]},value.id)).toBe(false);
  expect(await validModelWorkspace({...value,entries:[{...value.entries[0],content:'Substituted'}]},value.id)).toBe(false);
  expect(await validModelWorkspace({...value,model_contract_version:undefined},value.id)).toBe(false);
});
it('strictly preserves the old metadata-free operation and rejects partial or unknown negotiation',()=>{
  const old={type:'ask' as const,body:conversationFixture};expect(validModelOperation(old)).toBe(true);
  expect(validModelOperation({...old,model_contract:1})).toBe(false);expect(validModelOperation({...old,origin:'durable_admission_v1'})).toBe(false);
  expect(validModelOperation({...old,model_contract:1,origin:'durable_admission_v1'})).toBe(true);
  expect(validModelOperation({...old,model_contract:2,origin:'durable_admission_v1'})).toBe(false);
});

it('rejects contradictory recorded retry lifecycle or a repeated previous attempt identifier',async()=>{
 const {retryReceipt,modelUuid}=await import('./model-work-test-fixture');const value=await retryReceipt({expected_revision:1,previous_attempt_id:modelUuid(702),idempotency_key:'invented-retry'},modelUuid(71),modelUuid(701));
 expect(validRetryObservation(value)).toBe(true);
 for(const recorded of [{...value.recorded!,status:'completed'},{...value.recorded!,attempt_id:value.previous_attempt_id},{...value.recorded!,status:'failed'},{...value.recorded!,result_entry:{id:modelUuid(600),revision:2}}])expect(validRetryObservation({...value,recorded})).toBe(false);
});
