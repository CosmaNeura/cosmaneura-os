import {describe,it,expect} from 'vitest';
import actual from './__fixtures__/vendor-work/actual-http-r1.json';
import vectors from './__fixtures__/vendor-work/hash-vectors.json';
import maximumProposal from './__fixtures__/vendor-work/maximum-proposal.json';
import maximumDetail from './__fixtures__/vendor-work/maximum-detail.json';
import {normalizeVendor,parseVendorJson,validateVendor,vendorCanonical,vendorRequestDigest,verifyVendorReceipt,verifyVendorView} from './vendor-contract';

describe('actual W36 public contract crossing',()=>{
  it('matches all normalized Python Unicode request commitments',async()=>{
    for(const v of vectors){const normalized=normalizeVendor('VendorProposal',v.input);expect(normalized).toEqual(v.normalized);
      expect(await vendorRequestDigest('propose',{kind:'workspace',id:'11111111-1111-4111-8111-111111111111'},normalized)).toBe(v.request_sha256);
      const bytes=new TextEncoder().encode(vendorCanonical({domain:'cosmas-vendor-public-request.v1',value:{command_kind:'propose',scope:{kind:'workspace',id:'11111111-1111-4111-8111-111111111111'},request:normalized}}));
      expect(Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('')).toBe(v.canonical_utf8_hex);
    }
  });
  it('accepts maximum astral shapes by codepoints, not UTF-16 length',()=>{
    expect(validateVendor('VendorProposal',maximumProposal)).toEqual(maximumProposal);
    expect(validateVendor('Detail',maximumDetail)).toEqual(maximumDetail);
  });
  it('verifies actual HTTP option/review hashes and immutable recorded receipts',async()=>{
    await verifyVendorView('Options',actual.options);await verifyVendorView('Detail',actual.detail_pending);await verifyVendorView('Detail',actual.detail_approved);await verifyVendorView('Catalog',actual.catalog);
    for(const value of [actual.proposal_receipt,actual.approval_receipt,actual.resolved_proposal]){
      await verifyVendorReceipt(value,{scope:{kind:'workspace',id:actual.options.workspace_id},kind:value.command_kind,key:value.idempotency_key,sha256:value.request_sha256,operationId:actual.detail_pending.summary.operation_id});
    }
  });
  it('rejects a mutated public selection, review or receipt including publication summary',async()=>{
    const a=structuredClone(actual.options);a.connections[0].label+=' changed';await expect(verifyVendorView('Options',a)).rejects.toThrow();
    const b=structuredClone(actual.detail_pending);b.review.message+=' changed';await expect(verifyVendorView('Detail',b)).rejects.toThrow();
    const c=structuredClone(actual.proposal_receipt);c.summary.publication_recorded=true;await expect(verifyVendorReceipt(c,{scope:{kind:'workspace',id:c.scope.id},kind:c.command_kind,key:c.idempotency_key,sha256:c.request_sha256})).rejects.toThrow();
  });
  it('rejects wrong-scope or wrong-operation receipt recovery',async()=>{
    const v=actual.proposal_receipt;for(const change of [{scope:{kind:'workspace' as const,id:'11111111-1111-4111-8111-111111111111'}},{operationId:'11111111-1111-4111-8111-111111111111'},{sha256:'a'.repeat(64)}])await expect(verifyVendorReceipt(v,{scope:{kind:'workspace',id:v.scope.id},kind:v.command_kind,key:v.idempotency_key,sha256:v.request_sha256,...change})).rejects.toThrow();
  });
  it('keeps response normalization exact and proposals closed/action-bound',()=>{
    expect(()=>validateVendor('VendorProposal',vectors[0].input)).toThrow();
    for(const patch of [{message:null},{document:{}},{action:'spruce_fax'},{acknowledge_prior_uncertainty:false},{share_to_practice:1},{due_date:'2026-02-30'},{x:1},{message:'\ud800'}])expect(()=>normalizeVendor('VendorProposal',{...vectors[0].normalized,...patch})).toThrow();
    const invalid=structuredClone(actual.options);invalid.connections[0].actions=['srfax_fax'];expect(()=>validateVendor('Options',invalid)).toThrow();
  });
  it.each(['{"x":1,"x":2}','{"x":1.0}','{"x":1e0}','{"x":NaN}','{"x":2147483648}','{"x":"\\ud800"}','{"x":01}','{"x":1,}','[1,]','{"é":1}'])('rejects ambiguous raw JSON %s',(wire)=>expect(()=>parseVendorJson(wire)).toThrow());
  it('parses literal escaped keys safely and enforces depth',()=>{
    expect(vendorCanonical(parseVendorJson('{"__proto__":{"x":1},"a":"é😀"}'))).toBe('{"__proto__":{"x":1},"a":"é😀"}');
    expect(()=>parseVendorJson('{"x":1,"\\u0078":2}')).toThrow();expect(()=>parseVendorJson('['.repeat(32)+'0'+']'.repeat(32))).toThrow();
  });
  it('rejects trailing-newline identifiers/digests and non-JSON symbol/getter values',()=>{
    expect(()=>normalizeVendor('VendorProposal',{...vectors[0].normalized,proposed_operation_id:vectors[0].normalized.proposed_operation_id+'\n'})).toThrow();
    expect(()=>normalizeVendor('Selection',{id:vectors[0].normalized.connection.id,revision:1,public_sha256:'a'.repeat(64)+'\n'})).toThrow();
    expect(()=>vendorCanonical({[Symbol('hidden')]:1})).toThrow();expect(()=>vendorCanonical({get x(){return 1;}})).toThrow();
  });
});
