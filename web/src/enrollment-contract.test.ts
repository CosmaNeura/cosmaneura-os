import {expect,it} from 'vitest';
import {BAA,validateEnrollmentStatus} from './enrollment-contract';
import {enrollmentStatus} from './enrollment-test-fixture';

it('preserves an older executed agreement identity while requiring the current unsigned offer',()=>{
  const saved=enrollmentStatus('ready');
  saved.agreement={accepted:true,doc_id:BAA.doc_id,version:'2.2',sha256:'aB'.repeat(32),receipt_id:'invented_saved_receipt'};
  const actual=validateEnrollmentStatus(saved);
  expect(actual.agreement).toEqual(saved.agreement);expect(actual.stage).toBe('ready');
  const offered=enrollmentStatus('agreement');
  expect(validateEnrollmentStatus(offered).agreement).toEqual({accepted:false,doc_id:BAA.doc_id,version:BAA.version,sha256:BAA.sha256,receipt_id:null});
});
it('rejects unsigned stale terms and malformed executed identities without rewriting them to current terms',()=>{
  const offered=enrollmentStatus('agreement');
  expect(()=>validateEnrollmentStatus({...offered,agreement:{...offered.agreement,version:'2.2',sha256:'a'.repeat(64)}})).toThrow();
  const saved=enrollmentStatus('activation_pending');
  const valid={accepted:true,doc_id:BAA.doc_id,version:'2.2',sha256:'a'.repeat(64),receipt_id:'invented_saved_receipt'};
  for(const change of [{receipt_id:null},{receipt_id:''},{doc_id:'OTHER-DOCUMENT'},{version:''},{version:' '},{version:'x'.repeat(101)},{sha256:'a'.repeat(63)},{sha256:'g'.repeat(64)}])
    expect(()=>validateEnrollmentStatus({...saved,agreement:{...valid,...change}})).toThrow();
});
