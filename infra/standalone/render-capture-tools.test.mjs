import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {render,validateInput,Refused} from './render.mjs';
import {REVIEWED_CORE_CAPTURE_ORIGIN} from '../../clients/shared/beta-feature-profile.mjs';

const sample=JSON.parse(await readFile(new URL('./invented-host-input.json',import.meta.url),'utf8'));
const CORE_SCOPE='api://invented-core-audience/.default';
const CORE_MI='00000000-0000-4000-8000-0000000000aa';

function ownedBeta({host='staging.cosmas.ai'}={}){
  const value=structuredClone(sample);
  value.resource_scope='owned-cosmabot-vm-instance';
  value.web_origin=`https://${host}`;value.api_origin=`https://api.${host}`;
  value.identity.apiOrigin=value.api_origin;value.tls.hostnames=[host,`api.${host}`];
  value.beta_features={model:{origin:'https://invented-owned-chief.openai.azure.com',
    endpoint:'https://invented-owned-chief.openai.azure.com/openai/v1',deployment:'gpt-4.1'},
    google:{client_id:'invented-client.apps.googleusercontent.com',
      callback_uri:value.api_origin+'/connections/google/callback',return_origin:value.web_origin}};
  return value;
}

function withCaptureTools(value){
  return {...value,syntheticBetaCaptureAndTools:true,core_capture_origin:REVIEWED_CORE_CAPTURE_ORIGIN,
    core_web_origin:REVIEWED_CORE_CAPTURE_ORIGIN,core_capture_scope:CORE_SCOPE,
    core_capture_managed_identity_client_id:CORE_MI};
}

function fingerprint(files){
  // Stable byte identity over every rendered artifact.
  return createHash('sha256').update(JSON.stringify(files)).digest('hex');
}

function withoutHostInput(files){
  return Object.fromEntries(Object.entries(files).filter(([name])=>name!=='host-input.json'));
}

// Golden SHA-256 of JSON.stringify(render(...)) from origin/main@c7bdd17b.
const MAIN_DEDICATED_FINGERPRINT='2cba849698b0d4d28a040dda92cfddd87510e884df914741b86cf0de3578d361';
const MAIN_OWNED_STAGING_FINGERPRINT='f60e83ec57f05c97373a37f4cde2dac2c1b368eae3750c0df575c0416bc41e4c';

test('opt-in absent keeps byte-identical capture-dark main output',()=>{
  const baseline=render(structuredClone(sample));
  const again=render(structuredClone(sample));
  assert.equal(fingerprint(baseline),fingerprint(again));
  assert.equal(fingerprint(baseline),MAIN_DEDICATED_FINGERPRINT);
  const env=baseline['api-public.json'];
  assert.equal(env.WORKSPACE_AGENT_TOOLS_ENABLED,'false');
  assert.equal(env.WORKSPACE_CAPTURE_BACKEND,'disabled');
  assert.equal(env.WORKSPACE_CAPTURE_NOTES_ENABLED,'false');
  assert.equal(Object.hasOwn(env,'WORKSPACE_CAPTURE_PROXY_ENABLED'),false);
  assert.equal(Object.hasOwn(env,'WORKSPACE_CAPTURE_PROXY_ORIGIN'),false);
  assert.equal(env.CORE_CAPTURE_ORIGIN,'');
  assert.equal(env.CORE_WEB_ORIGIN,'');
  assert.equal(env.CORE_CAPTURE_SCOPE,'');
  assert.equal(env.CORE_CAPTURE_MANAGED_IDENTITY_CLIENT_ID,'');
  assert.equal(Object.hasOwn(env,'REAL_PATIENT_RECORDING_ENABLED'),false);
  assert.equal(baseline['clients/web-build-env.json'].VITE_WORKSPACE_CAPTURE_ENABLED,'false');
  assert.equal(baseline['clients/standalone-profile.json'].clients.web.captureMode,'disabled');
  // Owned independent-beta without the opt-in stays capture/tools dark too.
  const owned=render(ownedBeta());
  assert.equal(fingerprint(owned),MAIN_OWNED_STAGING_FINGERPRINT);
  const ownedEnv=owned['api-public.json'];
  assert.equal(ownedEnv.WORKSPACE_AGENT_TOOLS_ENABLED,'false');
  assert.equal(ownedEnv.WORKSPACE_CAPTURE_BACKEND,'disabled');
  assert.equal(Object.hasOwn(ownedEnv,'WORKSPACE_CAPTURE_PROXY_ENABLED'),false);
  assert.equal(owned['clients/web-build-env.json'].VITE_WORKSPACE_CAPTURE_ENABLED,'false');
  assert.equal(Object.hasOwn(owned['host-preparation.json'].optional_runtime_features,'capture_and_agent_tools'),false);
});

test('opt-in false matches absent output except echoed host-input',()=>{
  const absent=render(ownedBeta());
  const offInput=ownedBeta();offInput.syntheticBetaCaptureAndTools=false;
  const off=render(offInput);
  assert.deepEqual(withoutHostInput(off),withoutHostInput(absent));
  assert.equal(off['api-public.env'],absent['api-public.env']);
  assert.equal(fingerprint(withoutHostInput(off)),fingerprint(withoutHostInput(absent)));
  assert.equal(off['host-input.json'].syntheticBetaCaptureAndTools,false);
});

test('opt-in on renders exact capture and agent-tools keys for synthetic staging beta',()=>{
  const files=render(withCaptureTools(ownedBeta()));
  const env=files['api-public.json'];
  assert.equal(env.WORKSPACE_AGENT_TOOLS_ENABLED,'true');
  assert.equal(env.WORKSPACE_CAPTURE_NOTES_ENABLED,'true');
  assert.equal(env.WORKSPACE_CAPTURE_BACKEND,'core');
  assert.equal(env.WORKSPACE_CAPTURE_PROXY_ENABLED,'true');
  assert.equal(env.WORKSPACE_CAPTURE_PROXY_ORIGIN,'https://api.staging.cosmas.ai');
  assert.equal(env.CORE_CAPTURE_ORIGIN,REVIEWED_CORE_CAPTURE_ORIGIN);
  assert.equal(env.CORE_WEB_ORIGIN,REVIEWED_CORE_CAPTURE_ORIGIN);
  assert.equal(env.CORE_CAPTURE_SCOPE,CORE_SCOPE);
  assert.equal(env.CORE_CAPTURE_MANAGED_IDENTITY_CLIENT_ID,CORE_MI);
  assert.equal(env.DATA_MODE,'synthetic');
  assert.equal(env.COSMAS_ENV,'standalone_clerk_synthetic');
  assert.match(files['api-public.env'],/^WORKSPACE_AGENT_TOOLS_ENABLED="true"$/m);
  assert.match(files['api-public.env'],/^WORKSPACE_CAPTURE_BACKEND="core"$/m);
  assert.match(files['api-public.env'],/^WORKSPACE_CAPTURE_PROXY_ENABLED="true"$/m);
  assert.match(files['api-public.env'],/^WORKSPACE_CAPTURE_PROXY_ORIGIN="https:\/\/api\.staging\.cosmas\.ai"$/m);
  for(const client of ['web','desktop','apple']){
    const build=files[`clients/${client}-build-env.json`];
    assert.equal(build.VITE_WORKSPACE_CAPTURE_ENABLED,'true');
    assert.equal(build.VITE_WORKSPACE_CAPTURE_NOTES_ENABLED,'true');
    assert.equal(build.VITE_COSMANEURA_WEB_ORIGIN,REVIEWED_CORE_CAPTURE_ORIGIN);
    assert.equal(build.VITE_CAPTURE_UPLOAD_ORIGINS,'https://api.staging.cosmas.ai');
  }
  assert.equal(files['clients/web-build-arguments.json'].VITE_WORKSPACE_CAPTURE_ENABLED,'true');
  assert.equal(files['host-preparation.json'].optional_runtime_features.capture_and_agent_tools,true);
  assert.equal(files['host-preparation.json'].synthetic_only,true);
  assert.equal(files['host-preparation.json'].deployment_authorized,false);
});

test('opt-in never enables real-patient recording',()=>{
  const files=render(withCaptureTools(ownedBeta({host:'beta.cosmas.ai'})));
  const env=files['api-public.json'];
  assert.equal(Object.hasOwn(env,'REAL_PATIENT_RECORDING_ENABLED'),false);
  assert.doesNotMatch(files['api-public.env'],/REAL_PATIENT_RECORDING_ENABLED\s*=\s*"?true"?/i);
  assert.equal(files['host-preparation.json'].optional_runtime_features.real_patient_recording,false);
  assert.equal(env.DATA_MODE,'synthetic');
  // Server process guard stays untouched; renderer must not ship the on switch.
  assert.equal(JSON.stringify(files).includes('REAL_PATIENT_RECORDING_ENABLED=true'),false);
  assert.equal(JSON.stringify(files).includes('"REAL_PATIENT_RECORDING_ENABLED":"true"'),false);
});

test('opt-in is refused for non-staging/production CosmaBot profiles',()=>{
  // Dedicated practice host (standalone-practice) cannot opt in.
  const practice=structuredClone(sample);
  practice.syntheticBetaCaptureAndTools=true;
  practice.core_capture_origin=REVIEWED_CORE_CAPTURE_ORIGIN;
  practice.core_web_origin=REVIEWED_CORE_CAPTURE_ORIGIN;
  practice.core_capture_scope=CORE_SCOPE;
  practice.core_capture_managed_identity_client_id=CORE_MI;
  assert.throws(()=>validateInput(practice),Refused);
  assert.throws(()=>render(practice),Refused);
  // Missing independent-beta google/model overlay on an owned host is already refused;
  // opt-in on a non-owned profile stays refused even when Core public fields look valid.
  const incomplete=ownedBeta();
  incomplete.resource_scope='dedicated-new-cosmabot-host';
  incomplete.web_origin='https://workspace.standalone.example.invalid';
  incomplete.api_origin='https://api.standalone.example.invalid';
  incomplete.identity.apiOrigin=incomplete.api_origin;
  incomplete.tls.hostnames=['api.standalone.example.invalid','workspace.standalone.example.invalid'];
  incomplete.beta_features.google.callback_uri=incomplete.api_origin+'/connections/google/callback';
  incomplete.beta_features.google.return_origin=incomplete.web_origin;
  assert.throws(()=>render(withCaptureTools(incomplete)),Refused);
});

test('opt-in requires exact reviewed Core public inputs and rejects secrets',()=>{
  const base=ownedBeta();
  assert.throws(()=>render({...base,syntheticBetaCaptureAndTools:true}),Refused);
  assert.throws(()=>render({...withCaptureTools(base),core_capture_origin:'https://app.cosmaneura.com'}),Refused);
  assert.throws(()=>render({...withCaptureTools(base),core_web_origin:'https://core.example.invalid'}),Refused);
  assert.throws(()=>render({...withCaptureTools(base),core_capture_scope:'https://not-api'}),Refused);
  assert.throws(()=>render({...withCaptureTools(base),core_capture_managed_identity_client_id:'not-a-uuid'}),Refused);
  assert.throws(()=>render({...withCaptureTools(base),syntheticBetaCaptureAndTools:'true'}),Refused);
  assert.throws(()=>render({...withCaptureTools(base),core_capture_client_secret:'PRIVATE'}),Refused);
  assert.throws(()=>render({...withCaptureTools(base),secret:'DO_NOT_LOG'}),Refused);
});
