import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {render} from './render.mjs';

const sample=JSON.parse(await readFile(new URL('./invented-host-input.json',import.meta.url),'utf8'));
const fingerprint=files=>createHash('sha256').update(JSON.stringify(files)).digest('hex');

// Regenerated after post-#354 follow-up: invented-host-input.json beta identity
// frontendOrigin/publishableKey moved to clerk.cosmas.ai. Shared_staging golden
// overrides identity and stays byte-identical. Off-state flag behavior unchanged.
// Generator (from repo root):
//   node --input-type=module -e "
//   import {readFile} from 'node:fs/promises';
//   import {createHash} from 'node:crypto';
//   import {render} from './infra/standalone/render.mjs';
//   const sample=JSON.parse(await readFile('./infra/standalone/invented-host-input.json','utf8'));
//   const fp=f=>createHash('sha256').update(JSON.stringify(f)).digest('hex');
//   console.log(fp(render(structuredClone(sample))));
//   "
// Regenerated after #405/#404 merge + AZURE_ENABLED explicit false.
const DEDICATED_AUDIENCE_FINGERPRINT='5b7ca3642180f4bff544dafb8fc56887bd4c22b8eec47e66721776c6b9b76ab7';
const DEDICATED_SHARED_STAGING_FINGERPRINT='04ffe90de8d2281f1fb6d17382dcab96c84ca8c403d724887966bbe4d90b3e20';
const OWNED_STAGING_FINGERPRINT='d16c716ba578ef8f24ed178bbb213c0733b14134ca8a197485ab0b0a570d993b';

const EXPLICIT_FALSE=[
  'WORKSPACE_CAPTURE_PROXY_ENABLED','GOOGLE_CONNECTION_BROKER_ENABLED',
  'WORKSPACE_ATHENA_FHIR_SANDBOX_ENABLED','WORKSPACE_ENROLLMENT_MANAGED',
  'COSMAS_EHR_REAL_DATA_ENABLED','WORKSPACE_RX_SANDBOX_ENABLED',
  'REAL_PATIENT_RECORDING_ENABLED','WORKSPACE_EFAX_SANDBOX_ENABLED',
  'INDEPENDENT_RECORDING_TRANSCRIPTION_ENABLED',
  'INDEPENDENT_RECORDING_TRANSCRIPTION_AZURE_ENABLED',
  'RECORDING_AUDIO_48H_RETENTION_ENABLED',
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

test('owned staging package fingerprint keeps the ten switches false',()=>{
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
