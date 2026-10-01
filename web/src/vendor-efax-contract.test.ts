import {expect,it} from 'vitest';
import proposal from './__fixtures__/vendor-work/maximum-proposal.json';
import {normalizeVendor} from './vendor-contract';
import {validateVendorSetup} from './vendor-setup-contract';
import {setupFixture} from './vendor-setup-test-fixture';
import {vendorActionLabels} from './VendorWorkPanel';
import {FAX_PROVIDERS} from './fax-readiness-api';

it('offers eFax as a fourth provider and applies the same PDF-only proposal boundary',()=>{
  const base=structuredClone(proposal) as Record<string,unknown>;delete base.message;delete base.uploaded_media_operation_id;
  const value={...base,action:'efax_fax',document:{artifact_id:'00000000-0000-4000-8000-000000000005',sha256:'a'.repeat(64),byte_length:8,media_type:'application/pdf'}};
  expect(FAX_PROVIDERS).toContain('efax');expect(vendorActionLabels.efax_fax).toBe('eFax');
  expect(normalizeVendor('VendorProposal',value).action).toBe('efax_fax');
  for(const field of ['document','correspondence']){const missing={...value} as Record<string,unknown>;delete missing[field];expect(()=>normalizeVendor('VendorProposal',missing)).toThrow();}
  expect(()=>normalizeVendor('VendorProposal',{...value,message:'Unreviewed text'})).toThrow();
});
it('allows only eFax fax capability and production account setup',async()=>{
  const f=await setupFixture(),installed={...f.installed,vendor:'efax',capabilities:['efax_fax'],account_reference:'invented_api_user'};
  expect(validateVendorSetup('InstalledAccount',installed).vendor).toBe('efax');
  for(const patch of [{environment:'sandbox'},{capabilities:['spruce_secure_message']},{api_key:'not-allowed'}])expect(()=>validateVendorSetup('InstalledAccount',{...installed,...patch})).toThrow();
});
