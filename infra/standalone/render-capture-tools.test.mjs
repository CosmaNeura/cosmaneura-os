import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {render,validateInput,Refused} from './render.mjs';
import {REVIEWED_CORE_CAPTURE_ORIGIN} from '../../clients/shared/beta-feature-profile.mjs';
import {PRODUCTION_NATIVE_PROFILE} from '../../clients/shared/operational-native-identity.mjs';

const sample=JSON.parse(await readFile(new URL('./invented-host-input.json',import.meta.url),'utf8'));
const CORE_SCOPE='api://invented-core-audience/.default';
const CORE_MI='00000000-0000-4000-8000-0000000000aa';
const CORE_UPLOAD_HOST='inventedcaptureacct.blob.core.windows.net';
const IMDS_HOST='169.254.169.254';
const IMDS_PATH='/metadata/identity/oauth2/token';

function ownedBeta({host='staging.cosmas.ai',microsoft=false,staging=false}={}){
  const value=structuredClone(sample);
  value.resource_scope='owned-cosmabot-vm-instance';
  value.web_origin=`https://${host}`;value.api_origin=`https://api.${host}`;
  value.identity.apiOrigin=value.api_origin;value.tls.hostnames=[host,`api.${host}`];
  if(host==='beta.cosmas.ai'&&!staging){
    value.identity.profile=PRODUCTION_NATIVE_PROFILE;
    value.identity.frontendOrigin='https://clerk.beta.cosmas.ai';
    value.identity.publishableKey='pk_live_'+Buffer.from('clerk.beta.cosmas.ai$').toString('base64');
  }
  if(staging){
    value.identity_policy='shared_staging';value.identity.profile='operational-staging-v1';
    value.identity.audience='';value.identity.frontendOrigin='https://invented-own-practice.clerk.accounts.dev';
    value.identity.publishableKey='pk_test_'+Buffer.from('invented-own-practice.clerk.accounts.dev$').toString('base64');
  }
  value.beta_features={model:{origin:'https://invented-owned-chief.openai.azure.com',
    endpoint:'https://invented-owned-chief.openai.azure.com/openai/v1',deployment:'gpt-4.1'},
    google:{client_id:'invented-client.apps.googleusercontent.com',
      callback_uri:value.api_origin+'/connections/google/callback',return_origin:value.web_origin}};
  if(microsoft)value.beta_features.microsoft={tenant_id:'10000000-0000-4000-8000-000000000001',
    client_id:'10000000-0000-4000-8000-000000000002',
    callback_uri:value.api_origin+'/connections/microsoft/callback',return_origin:value.web_origin};
  return value;
}

function withCaptureTools(value){
  return {...value,syntheticBetaCaptureAndTools:true,core_capture_origin:REVIEWED_CORE_CAPTURE_ORIGIN,
    core_web_origin:REVIEWED_CORE_CAPTURE_ORIGIN,core_capture_scope:CORE_SCOPE,
    core_capture_managed_identity_client_id:CORE_MI,core_capture_upload_host:CORE_UPLOAD_HOST};
}

function fingerprint(files){
  return createHash('sha256').update(JSON.stringify(files)).digest('hex');
}

function withoutHostInput(files){
  return Object.fromEntries(Object.entries(files).filter(([name])=>name!=='host-input.json'));
}

function assertRefused(fn,code){
  assert.throws(fn,error=>{
    assert.equal(error instanceof Refused,true);
    assert.equal(error.message,code);
    return true;
  });
}

function assertRealPatientStaysOff(value,path='root'){
  if(Array.isArray(value)){
    value.forEach((item,index)=>assertRealPatientStaysOff(item,`${path}[${index}]`));
    return;
  }
  if(!value||typeof value!=='object')return;
  for(const [key,child] of Object.entries(value)){
    // #361 renders REAL_PATIENT_RECORDING_ENABLED explicitly false; never true.
    if(key==='REAL_PATIENT_RECORDING_ENABLED')assert.equal(child,'false',path);
    else if(key==='real_patient_recording_enabled'||key==='real_patient_recording_process_switch')
      assert.equal(child,false,path);
    else assertRealPatientStaysOff(child,`${path}.${key}`);
  }
}

function assertNoRealPatientOn(files){
  assert.equal(files['api-public.json'].REAL_PATIENT_RECORDING_ENABLED,'false');
  for(const line of files['api-public.env'].split('\n')){
    if(!line)continue;
    const eq=line.indexOf('=');
    const key=eq===-1?line:line.slice(0,eq);
    const raw=eq===-1?'':line.slice(eq+1);
    // api-public.env JSON-encodes string flags, so the parsed value is 'false'.
    if(key==='REAL_PATIENT_RECORDING_ENABLED')assert.equal(JSON.parse(raw),'false');
  }
  for(const [name,value] of Object.entries(files)){
    if(typeof value!=='object'||value===null)continue;
    assertRealPatientStaysOff(value,name);
  }
  assert.equal(files['host-preparation.json'].optional_runtime_features.real_patient_recording_process_switch,false);
}

// Off-path must stay byte-identical to origin/main after #361 (eight Settings
// bools rendered explicitly false). Values match render-goldens.test.mjs.
const MAIN_DEDICATED_FINGERPRINT='a8157eea72ab7be14aca790f5e4fa27a7f3ea839a4d34682dce2cb4c448f372f';
// Updated for T-REL-7c staging ACCOUNT_DELETE KV/egress/DNS contract on owned staging.
const MAIN_OWNED_STAGING_FINGERPRINT='a2e8726ce2de6ea44208d8d73b69ac039243884b71e922222ee680ba1a0e8c7f';

test('opt-in absent keeps byte-identical capture-dark main output',()=>{
  const baseline=render(structuredClone(sample));
  const again=render(structuredClone(sample));
  assert.equal(fingerprint(baseline),fingerprint(again));
  assert.equal(fingerprint(baseline),MAIN_DEDICATED_FINGERPRINT);
  const env=baseline['api-public.json'];
  assert.equal(env.WORKSPACE_AGENT_TOOLS_ENABLED,'false');
  assert.equal(env.WORKSPACE_CAPTURE_BACKEND,'disabled');
  assert.equal(env.WORKSPACE_CAPTURE_NOTES_ENABLED,'false');
  // #361: proxy switch is present as explicit false when opt-in is absent.
  assert.equal(env.WORKSPACE_CAPTURE_PROXY_ENABLED,'false');
  assert.equal(Object.hasOwn(env,'WORKSPACE_CAPTURE_PROXY_ORIGIN'),false);
  assert.equal(env.CORE_CAPTURE_ORIGIN,'');
  assert.equal(env.CORE_WEB_ORIGIN,'');
  assert.equal(env.CORE_CAPTURE_SCOPE,'');
  assert.equal(env.CORE_CAPTURE_MANAGED_IDENTITY_CLIENT_ID,'');
  assert.equal(Object.hasOwn(env,'CORE_CAPTURE_UPLOAD_HOST'),false);
  assert.equal(env.REAL_PATIENT_RECORDING_ENABLED,'false');
  assert.equal(baseline['clients/web-build-env.json'].VITE_WORKSPACE_CAPTURE_ENABLED,'false');
  assert.equal(baseline['clients/standalone-profile.json'].clients.web.captureMode,'disabled');
  assert.deepEqual(baseline['host-preparation.json'].platform_connections,[]);
  assert.ok(baseline['network-requirements.json'].deny.includes('*.cosmaneura.com'));
  assert.ok(baseline['network-requirements.json'].deny.includes('169.254.0.0/16 metadata and link-local'));
  const owned=render(ownedBeta());
  assert.equal(fingerprint(owned),MAIN_OWNED_STAGING_FINGERPRINT);
  const ownedEnv=owned['api-public.json'];
  assert.equal(ownedEnv.WORKSPACE_AGENT_TOOLS_ENABLED,'false');
  assert.equal(ownedEnv.WORKSPACE_CAPTURE_BACKEND,'disabled');
  assert.equal(ownedEnv.WORKSPACE_CAPTURE_PROXY_ENABLED,'false');
  assert.equal(ownedEnv.REAL_PATIENT_RECORDING_ENABLED,'false');
  assert.equal(owned['clients/web-build-env.json'].VITE_WORKSPACE_CAPTURE_ENABLED,'false');
  assert.equal(Object.hasOwn(owned['host-preparation.json'].optional_runtime_features,'capture_and_agent_tools'),false);
  assert.deepEqual(owned['host-preparation.json'].platform_connections,[]);
});

test('opt-in false matches absent output except echoed host-input',()=>{
  const absent=render(ownedBeta());
  const offInput=ownedBeta();offInput.syntheticBetaCaptureAndTools=false;
  const off=render(offInput);
  assert.deepEqual(withoutHostInput(off),withoutHostInput(absent));
  assert.equal(off['api-public.env'],absent['api-public.env']);
  assert.equal(fingerprint(withoutHostInput(off)),fingerprint(withoutHostInput(absent)));
  assert.equal(off['host-input.json'].syntheticBetaCaptureAndTools,false);
  assert.notDeepEqual(off['host-input.json'],absent['host-input.json']);
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
  assert.equal(env.CORE_CAPTURE_UPLOAD_HOST,CORE_UPLOAD_HOST);
  assert.equal(env.DATA_MODE,'synthetic');
  assert.equal(env.COSMAS_ENV,'standalone_clerk_synthetic');
  for(const flag of [
    'WORKSPACE_ATHENA_CONNECTION_ENABLED','WORKSPACE_CORE_CONNECTION_ENABLED',
    'WORKSPACE_CORE_RECORD_ENABLED','WORKSPACE_SESSION_PREP_ENABLED',
    'WORKSPACE_PREP_ENABLED','WORKSPACE_ROUTINES_ENABLED',
    // #361 switches stay false under capture/tools opt-in except proxy (true above).
    'GOOGLE_CONNECTION_BROKER_ENABLED','WORKSPACE_ATHENA_FHIR_SANDBOX_ENABLED',
    'WORKSPACE_ENROLLMENT_MANAGED','COSMAS_EHR_REAL_DATA_ENABLED',
    'WORKSPACE_RX_SANDBOX_ENABLED','REAL_PATIENT_RECORDING_ENABLED',
    'WORKSPACE_EFAX_SANDBOX_ENABLED',
  ])assert.equal(env[flag],'false',flag);
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
    assert.equal(build.VITE_WORKSPACE_CAPTURE_MODE,client==='apple'?'ios_native':'browser_microphone');
  }
  assert.equal(files['clients/web-build-arguments.json'].VITE_WORKSPACE_CAPTURE_ENABLED,'true');
  assert.equal(files['host-preparation.json'].optional_runtime_features.capture_and_agent_tools,true);
  assert.equal(files['host-preparation.json'].optional_runtime_features.capture_content,
    'live microphone audio on a synthetic-only host; never relabelled as invented');
  assert.equal(files['host-preparation.json'].synthetic_only,true);
  assert.equal(files['host-preparation.json'].deployment_authorized,false);
  assert.match(files['host-preparation.json'].client_manifest_platform_access,/platformAccess:'disabled'/);
});

test('opt-in on declares Core capture egress, IMDS token path, platform connection and evidence',()=>{
  const files=render(withCaptureTools(ownedBeta()));
  const network=files['network-requirements.json'];
  const coreEgress=network.api_egress.find(item=>item.hostname==='staging-app.cosmaneura.com');
  const imdsEgress=network.api_egress.find(item=>item.hostname===IMDS_HOST);
  const uploadEgress=network.api_egress.find(item=>item.hostname===CORE_UPLOAD_HOST);
  assert.deepEqual(coreEgress,{protocol:'https',hostname:'staging-app.cosmaneura.com',tcp_port:443,
    redirects_allowed:false,adapter:'src/cosmas_os/adapters/core_capture_connection.py:174'});
  assert.deepEqual(imdsEgress,{protocol:'http',hostname:IMDS_HOST,tcp_port:80,path:IMDS_PATH,
    redirects_allowed:false,adapter:'src/cosmas_os/adapters/core_capture_connection.py:168-174'});
  assert.deepEqual(uploadEgress,{protocol:'https',hostname:CORE_UPLOAD_HOST,tcp_port:443,method:'PUT',
    redirects_allowed:false,adapter:'src/cosmas_os/application/capture_upload_proxy.py:295-311'});
  assert.equal(network.deny.includes('*.cosmaneura.com'),false);
  assert.ok(network.deny.includes('*.cosmaneura.com except staging-app.cosmaneura.com Core capture origin'));
  assert.equal(network.deny.includes('169.254.0.0/16 metadata and link-local'),false);
  assert.ok(network.deny.includes(`169.254.0.0/16 metadata and link-local except ${IMDS_HOST}${IMDS_PATH}`));
  assert.equal(
    network.dns,
    `Only the exact configured Clerk issuer, Clerk Backend API, optional own model, selected Google/Microsoft API hostnames, staging-app.cosmaneura.com Core capture, IMDS token host, and ${CORE_UPLOAD_HOST} Core capture upload blob; qualify resolver enforcement separately.`,
  );
  const clerkEgress=network.api_egress.find(item=>item.hostname==='api.clerk.com');
  assert.deepEqual(clerkEgress,{
    protocol:'https',hostname:'api.clerk.com',tcp_port:443,
    path:'/v1/users/',redirects_allowed:false,purpose:'account_delete_clerk_backend',
  });
  const evidence=files['host-preparation.json'].required_evidence.find(item=>item.startsWith('Host firewall and DNS'));
  assert.equal(
    evidence,
    `Host firewall and DNS qualification: only declared Clerk JWKS, Clerk Backend API, optional own model, selected Google/Microsoft, Core capture staging-app.cosmaneura.com, IMDS token endpoint, and Core capture upload blob ${CORE_UPLOAD_HOST}; runtime pins that upload host exactly on https:443; no other providers`,
  );
  assert.equal(files['api-public.json'].CORE_CAPTURE_UPLOAD_HOST,CORE_UPLOAD_HOST);
  assert.deepEqual(files['host-preparation.json'].platform_connections,[{
    kind:'core_staging_capture',origin:REVIEWED_CORE_CAPTURE_ORIGIN,web_origin:REVIEWED_CORE_CAPTURE_ORIGIN,
    scope:CORE_SCOPE,managed_identity_client_id:CORE_MI,upload_proxy_origin:'https://api.staging.cosmas.ai',
    upload_host:CORE_UPLOAD_HOST,
    upload_host_control:'Runtime pins CORE_CAPTURE_UPLOAD_HOST exactly (https:443 only); host egress is defense in depth',
    adapter:'src/cosmas_os/adapters/core_capture_connection.py:168-174',
    upload_adapter:'src/cosmas_os/application/capture_upload_proxy.py:295-311',
    content:'live microphone audio on a synthetic-only CosmaBot host; never relabelled as invented',
    real_patient_recording_process_switch:false}]);
});

test('opt-in never enables real-patient recording process switch',()=>{
  const files=render(withCaptureTools(ownedBeta({host:'beta.cosmas.ai'})));
  assertNoRealPatientOn(files);
  assert.equal(files['api-public.json'].DATA_MODE,'synthetic');
});

test('opt-in accepts shared_staging and Microsoft overlays on owned synthetic hosts',()=>{
  const staging=render(withCaptureTools(ownedBeta({staging:true})));
  assert.equal(staging['api-public.json'].CLERK_SESSION_POLICY,'shared_staging');
  assert.equal(staging['api-public.json'].WORKSPACE_CAPTURE_BACKEND,'core');
  assert.equal(staging['api-public.json'].WORKSPACE_AGENT_TOOLS_ENABLED,'true');
  assert.equal(staging['host-preparation.json'].platform_connections[0].kind,'core_staging_capture');
  const withMs=render(withCaptureTools(ownedBeta({microsoft:true})));
  assert.equal(withMs['api-public.json'].WORKSPACE_MICROSOFT_CONNECTION_ENABLED,'true');
  assert.equal(withMs['api-public.json'].WORKSPACE_CAPTURE_BACKEND,'core');
  assert.equal(withMs['api-public.json'].WORKSPACE_AGENT_TOOLS_ENABLED,'true');
  assert.ok(withMs['network-requirements.json'].api_egress.some(item=>item.hostname==='login.microsoftonline.com'));
  assert.ok(withMs['network-requirements.json'].api_egress.some(item=>item.hostname==='staging-app.cosmaneura.com'));
  assert.ok(withMs['network-requirements.json'].api_egress.some(item=>item.hostname===IMDS_HOST));
});

test('opt-in is refused for non-staging/production CosmaBot profiles with exact codes',()=>{
  const practice=structuredClone(sample);
  practice.syntheticBetaCaptureAndTools=true;
  practice.core_capture_origin=REVIEWED_CORE_CAPTURE_ORIGIN;
  practice.core_web_origin=REVIEWED_CORE_CAPTURE_ORIGIN;
  practice.core_capture_scope=CORE_SCOPE;
  practice.core_capture_managed_identity_client_id=CORE_MI;
  practice.core_capture_upload_host=CORE_UPLOAD_HOST;
  assertRefused(()=>validateInput(practice),'synthetic_beta_capture_tools_refused_for_profile');
  assertRefused(()=>render(practice),'synthetic_beta_capture_tools_refused_for_profile');
  const incomplete=ownedBeta();
  incomplete.resource_scope='dedicated-new-cosmabot-host';
  incomplete.web_origin='https://workspace.standalone.example.invalid';
  incomplete.api_origin='https://api.standalone.example.invalid';
  incomplete.identity.apiOrigin=incomplete.api_origin;
  incomplete.tls.hostnames=['api.standalone.example.invalid','workspace.standalone.example.invalid'];
  incomplete.beta_features.google.callback_uri=incomplete.api_origin+'/connections/google/callback';
  incomplete.beta_features.google.return_origin=incomplete.web_origin;
  assertRefused(()=>render(withCaptureTools(incomplete)),'synthetic_beta_capture_tools_refused_for_profile');
  for(const host of ['app.cosmas.ai','cosmas.ai']){
    assertRefused(()=>render(withCaptureTools(ownedBeta({host}))),'exact_owned_cosmabot_routes_required');
  }
  // Owned VM with a cosmaneura.com pair fails the exact owned-route check first.
  const ownedPlatform=ownedBeta();
  ownedPlatform.web_origin='https://workspace.cosmaneura.com';
  ownedPlatform.api_origin='https://api.cosmaneura.com';
  ownedPlatform.identity.apiOrigin=ownedPlatform.api_origin;
  ownedPlatform.tls.hostnames=['workspace.cosmaneura.com','api.cosmaneura.com'];
  ownedPlatform.beta_features.google.callback_uri=ownedPlatform.api_origin+'/connections/google/callback';
  ownedPlatform.beta_features.google.return_origin=ownedPlatform.web_origin;
  assertRefused(()=>render(withCaptureTools(ownedPlatform)),'exact_owned_cosmabot_routes_required');
  // Dedicated host with a *.cosmaneura.com web origin is refused at origin().
  const dedicatedPlatform=structuredClone(sample);
  dedicatedPlatform.web_origin='https://workspace.cosmaneura.com';
  dedicatedPlatform.api_origin='https://api.standalone.example.invalid';
  dedicatedPlatform.identity.apiOrigin=dedicatedPlatform.api_origin;
  dedicatedPlatform.tls.hostnames=['workspace.cosmaneura.com','api.standalone.example.invalid'];
  assertRefused(()=>render(withCaptureTools(dedicatedPlatform)),'dedicated_https_origin_required');
});

test('opt-in requires exact reviewed Core public inputs and rejects secrets with exact codes',()=>{
  const base=ownedBeta();
  assertRefused(()=>render({...base,syntheticBetaCaptureAndTools:true}),'input_shape');
  const missingUpload={...withCaptureTools(base)};
  delete missingUpload.core_capture_upload_host;
  assertRefused(()=>render(missingUpload),'input_shape');
  assertRefused(()=>render({...base,core_capture_upload_host:CORE_UPLOAD_HOST}),'input_shape');
  assertRefused(()=>render({...base,syntheticBetaCaptureAndTools:false,core_capture_upload_host:CORE_UPLOAD_HOST}),
    'input_shape');
  assertRefused(()=>render({...withCaptureTools(base),core_capture_origin:'https://app.cosmaneura.com'}),
    'reviewed_core_capture_origin_required');
  assertRefused(()=>render({...withCaptureTools(base),core_web_origin:'https://core.example.invalid'}),
    'reviewed_core_capture_origin_required');
  assertRefused(()=>render({...withCaptureTools(base),core_capture_scope:'https://not-api'}),
    'exact_core_capture_scope_required');
  assertRefused(()=>render({...withCaptureTools(base),core_capture_managed_identity_client_id:'not-a-uuid'}),
    'exact_core_capture_managed_identity_required');
  assertRefused(()=>render({...withCaptureTools(base),core_capture_upload_host:'InventedCaptureAcct.blob.core.windows.net'}),
    'exact_core_capture_upload_host_required');
  assertRefused(()=>render({...withCaptureTools(base),core_capture_upload_host:'inventedcaptureacct.blob.core.windows.net/extra'}),
    'exact_core_capture_upload_host_required');
  assertRefused(()=>render({...withCaptureTools(base),core_capture_upload_host:'https://inventedcaptureacct.blob.core.windows.net'}),
    'exact_core_capture_upload_host_required');
  assertRefused(()=>render({...withCaptureTools(base),syntheticBetaCaptureAndTools:'true'}),
    'synthetic_beta_capture_tools_boolean_required');
  assertRefused(()=>render({...withCaptureTools(base),core_capture_client_secret:'PRIVATE'}),'input_shape');
  assertRefused(()=>render({...withCaptureTools(base),secret:'DO_NOT_LOG'}),'input_shape');
});
