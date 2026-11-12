import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {render} from './render.mjs';

const sample=JSON.parse(await readFile(new URL('./invented-host-input.json',import.meta.url),'utf8'));
const fingerprint=files=>createHash('sha256').update(JSON.stringify(files)).digest('hex');

// Regenerated because (1) api-public.json gained eight Settings bools rendered
// as explicit 'false' (same off-state as unset defaults in config.py) and
// (2) invented-host-input.json schema_revision was aligned to
// EXPECTED_SCHEMA_REVISION a46f2c09d853. Off-state flag behavior is unchanged.
const DEDICATED_AUDIENCE_FINGERPRINT='3147f8057ec581a0b9fa0be0b67d8fa3cc5afb4d8c6577308032e98c6026974d';
const DEDICATED_SHARED_STAGING_FINGERPRINT='189bf8a9a175e7f5a4e95797b360c52223b9dc07c4c8438a59d0ce97157ab2ad';
const OWNED_STAGING_FINGERPRINT='5d6b26f717eca58011088027465a0599ed570b7619ad4e69105dbaccded86ca9';

const EXPLICIT_FALSE=[
  'WORKSPACE_CAPTURE_PROXY_ENABLED','GOOGLE_CONNECTION_BROKER_ENABLED',
  'WORKSPACE_ATHENA_FHIR_SANDBOX_ENABLED','WORKSPACE_ENROLLMENT_MANAGED',
  'COSMAS_EHR_REAL_DATA_ENABLED','WORKSPACE_RX_SANDBOX_ENABLED',
  'REAL_PATIENT_RECORDING_ENABLED','WORKSPACE_EFAX_SANDBOX_ENABLED',
];

test('audience dedicated package fingerprint and explicit-false backend switches',()=>{
  const files=render(structuredClone(sample));
  assert.equal(fingerprint(files),DEDICATED_AUDIENCE_FINGERPRINT);
  for(const flag of EXPLICIT_FALSE)assert.equal(files['api-public.json'][flag],'false',flag);
});

test('shared_staging dedicated package fingerprint and explicit-false backend switches',()=>{
  const value=structuredClone(sample);
  value.identity_policy='shared_staging';value.identity.profile='operational-staging-v1';
  value.identity.audience='';
  value.identity.frontendOrigin='https://invented-own-practice.clerk.accounts.dev';
  value.identity.publishableKey='pk_test_'+Buffer.from('invented-own-practice.clerk.accounts.dev$').toString('base64');
  const files=render(value);
  assert.equal(fingerprint(files),DEDICATED_SHARED_STAGING_FINGERPRINT);
  for(const flag of EXPLICIT_FALSE)assert.equal(files['api-public.json'][flag],'false',flag);
});

test('owned staging package fingerprint keeps the eight switches false',()=>{
  const value=structuredClone(sample);
  value.resource_scope='owned-cosmabot-vm-instance';
  value.web_origin='https://staging.cosmas.ai';value.api_origin='https://api.staging.cosmas.ai';
  value.identity.apiOrigin=value.api_origin;value.tls.hostnames=['staging.cosmas.ai','api.staging.cosmas.ai'];
  value.beta_features={model:{origin:'https://invented-owned-chief.openai.azure.com',
    endpoint:'https://invented-owned-chief.openai.azure.com/openai/v1',deployment:'gpt-4.1'},
    google:{client_id:'invented-client.apps.googleusercontent.com',
      callback_uri:value.api_origin+'/connections/google/callback',return_origin:value.web_origin}};
  const files=render(value);
  assert.equal(fingerprint(files),OWNED_STAGING_FINGERPRINT);
  for(const flag of EXPLICIT_FALSE)assert.equal(files['api-public.json'][flag],'false',flag);
});
