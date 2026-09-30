import assert from 'node:assert/strict';
import test from 'node:test';
import {MAX_SCRIBE_SOURCE_REQUEST_BYTES, validScribeSourceRequest} from './scribe-source-requests.mjs';

const id = '00000000-0000-4000-8000-000000000001';
const packet = () => ({idempotency_key:'source-share-1',expected_revision:1,reviewed:true,share_with_team:true,
  selection:{version:1,session_id:id,source_transcript_version:1,working_transcript_id:id,
    working_transcript_version:2,snapshot_sha256:'a'.repeat(64)}});

test('admits only the exact existing-source and reviewed packet shapes', () => {
  assert.equal(validScribeSourceRequest('existing',{idempotency_key:'source-read-1'}),true);
  assert.equal(validScribeSourceRequest('source-packets',packet()),true);
  assert.equal(validScribeSourceRequest('existing',packet()),false);
  assert.equal(validScribeSourceRequest('operations',packet()),false);
  assert.equal(Buffer.byteLength(JSON.stringify(packet())) < MAX_SCRIBE_SOURCE_REQUEST_BYTES,true);
  for(const value of [null,[],true,'{}',new Date(),{}])
    for(const action of ['existing','source-packets']) assert.equal(validScribeSourceRequest(action,value),false);
});

test('rejects extra identity, endpoint, transcript and nested authority fields', () => {
  for(const field of ['owner_id','box_id','workspace_id','url','transcript','operation']) {
    assert.equal(validScribeSourceRequest('existing',{idempotency_key:'source-read-1',[field]:id}),false);
    assert.equal(validScribeSourceRequest('source-packets',{...packet(),[field]:id}),false);
    const body=packet();body.selection[field]=id;
    assert.equal(validScribeSourceRequest('source-packets',body),false);
  }
  for(const field of Object.keys(packet())) {
    const body=packet();delete body[field];assert.equal(validScribeSourceRequest('source-packets',body),false);
  }
  for(const field of Object.keys(packet().selection)) {
    const body=packet();delete body.selection[field];assert.equal(validScribeSourceRequest('source-packets',body),false);
  }
});

test('requires literal review, finite safe revisions and canonical source identifiers', () => {
  for(const field of ['reviewed','share_with_team']) for(const value of [false,1,0,'true',null]) {
    const body=packet();body[field]=value;assert.equal(validScribeSourceRequest('source-packets',body),false);
  }
  for(const value of [0,-1,1.5,true,'1',NaN,Infinity,Number.MAX_SAFE_INTEGER+1]) {
    const body=packet();body.expected_revision=value;assert.equal(validScribeSourceRequest('source-packets',body),false);
    for(const field of ['source_transcript_version','working_transcript_version']) {
      const body=packet();body.selection[field]=value;assert.equal(validScribeSourceRequest('source-packets',body),false);
    }
  }
  for(const value of [true,'1',2]) {const body=packet();body.selection.version=value;assert.equal(validScribeSourceRequest('source-packets',body),false);}
  for(const field of ['session_id','working_transcript_id']) for(const value of [null,4,'not-a-uuid',id+'?next=x','ABCDEF00-0000-4000-8000-000000000001']) {
    const body=packet();body.selection[field]=value;assert.equal(validScribeSourceRequest('source-packets',body),false);
  }
  for(const value of ['A'.repeat(64),'a'.repeat(63),'a'.repeat(65),0,null]) {
    const body=packet();body.selection.snapshot_sha256=value;assert.equal(validScribeSourceRequest('source-packets',body),false);
  }
  for(const value of ['', 'short', 'a'.repeat(101), 'source/read', 'source key',null,1])
    assert.equal(validScribeSourceRequest('existing',{idempotency_key:value}),false);
});
