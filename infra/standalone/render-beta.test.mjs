import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {render} from './render.mjs';
import {REVIEWED_CORE_CAPTURE_ORIGIN} from '../../clients/shared/beta-feature-profile.mjs';

const sample=JSON.parse(await readFile(new URL('./invented-host-input.json',import.meta.url),'utf8'));
function captureFixtureFor(apiOrigin){
  return {origin:REVIEWED_CORE_CAPTURE_ORIGIN,web_origin:REVIEWED_CORE_CAPTURE_ORIGIN,
    scope:'api://invented-core-audience/.default',managed_identity_client_id:'00000000-0000-4000-8000-0000000000aa',
    // Independent-beta: CosmaBot API origin only (S2S proxy). Never Scribe blob.
    upload_origins:[apiOrigin]};
}
function candidate({model=true,google=true,owned=false,host='staging.cosmas.ai'}={}){
  const value=structuredClone(sample);
  if(owned){value.resource_scope='owned-cosmabot-vm-instance';value.web_origin=`https://${host}`;
    value.api_origin=`https://api.${host}`;value.identity.apiOrigin=value.api_origin;
    value.tls.hostnames=[host,`api.${host}`];}
  value.beta_features={model:model?{origin:'https://invented-owned-chief.openai.azure.com',
    endpoint:'https://invented-owned-chief.openai.azure.com/openai/v1',deployment:'gpt-4.1'}:null,
    google:google?{client_id:'invented-client.apps.googleusercontent.com',
      callback_uri:value.api_origin+'/connections/google/callback',return_origin:value.web_origin}:null,
    capture:google?captureFixtureFor(value.api_origin):null};
  return value;
}

test('optional public features bind server, clients, private field names and explicit egress',()=>{
  for(const model of [false,true])for(const google of [false,true]){
    const value=candidate({model,google}),files=render(value),env=files['api-public.json'];
    const contract=files['host-preparation.json'];
    assert.equal(env.WORKSPACE_LLM_BACKEND,model?'azure_gpt41':'disabled');
    assert.equal(env.WORKSPACE_GOOGLE_CONNECTION_ENABLED,String(google));
    assert.equal(env.WORKSPACE_CAPTURE_BACKEND,google?'core':'disabled');
    assert.equal(env.WORKSPACE_AGENT_TOOLS_ENABLED,google?'true':'false');
    assert.equal(env.WORKSPACE_CAPTURE_NOTES_ENABLED,google?'true':'false');
    if(google){
      assert.equal(env.CORE_CAPTURE_ORIGIN,REVIEWED_CORE_CAPTURE_ORIGIN);
      assert.equal(env.CORE_WEB_ORIGIN,REVIEWED_CORE_CAPTURE_ORIGIN);
      assert.equal(env.CORE_CAPTURE_SCOPE,'api://invented-core-audience/.default');
      assert.equal(env.CORE_CAPTURE_MANAGED_IDENTITY_CLIENT_ID,'00000000-0000-4000-8000-0000000000aa');
      assert.equal(env.WORKSPACE_CAPTURE_PROXY_ORIGIN,value.api_origin);
      assert.equal(contract.core_capture_permission.app_role,'AgentApi.Access');
      assert.equal(files['clients/web-build-env.json'].VITE_CAPTURE_UPLOAD_ORIGINS,value.api_origin);
    }else{
      assert.equal(env.CORE_CAPTURE_ORIGIN,'');
      assert.equal(contract.core_capture_permission,undefined);
    }
    for(const client of ['web','desktop','apple']){
      const profile=files['clients/standalone-profile.json'].clients[client];
      assert.equal(profile.profile,google?'independent-beta-v1':'standalone-practice-v1');
      assert.equal(files[`clients/${client}-build-env.json`].VITE_WORKSPACE_GOOGLE_CONNECTION_ENABLED,String(google));
      assert.equal(files[`clients/${client}-build-env.json`].VITE_WORKSPACE_CAPTURE_ENABLED,google?'true':'false');
      assert.equal(files[`clients/${client}-build-env.json`].VITE_COSMANEURA_WEB_ORIGIN,google?REVIEWED_CORE_CAPTURE_ORIGIN:'');
    }
    assert.deepEqual(contract.private_environment.exact_names,['DATABASE_URL','HUMAN_DEPLOY_EVIDENCE_REF',
      ...(model?['WORKSPACE_LLM_API_KEY']:[]),...(google?['GOOGLE_CONNECTION_CLIENT_SECRET','GOOGLE_CONNECTION_ENCRYPTION_KEY']:[])]);
    for(const name of contract.private_environment.exact_names)assert.equal(Object.hasOwn(env,name),false);
    const expectedEgress=1+Number(model)+4*Number(google)+(google?2:0);
    assert.equal(files['network-requirements.json'].api_egress.length,expectedEgress);
    assert.deepEqual(contract.external_workers,[]);assert.deepEqual(contract.platform_connections,[]);
    assert.equal(contract.optional_runtime_features.live_provider_acceptance,false);
  }
});

test('independent Core capture refuses wrong origin, scope, MI, uploads and non-Google capture',()=>{
  const changes=[
    v=>{v.beta_features.capture.origin='https://app.cosmaneura.com';},
    v=>{v.beta_features.capture.web_origin='https://app.cosmaneura.com';},
    v=>{v.beta_features.capture.scope='https://not-an-api-scope';},
    v=>{v.beta_features.capture.scope='api://audience/not-default';},
    v=>{v.beta_features.capture.managed_identity_client_id='not-a-uuid';},
    v=>{v.beta_features.capture.upload_origins=[];},
    v=>{v.beta_features.capture.upload_origins=['https://uploads.example.invalid/path'];},
    v=>{v.beta_features.capture.upload_origins=['https://api.assemblyai.com'];},
    v=>{v.beta_features.capture.upload_origins=['https://cosmaneurastaginguploads.blob.core.windows.net'];},
    v=>{v.beta_features.capture.upload_origins=['https://staging-app.cosmaneura.com'];},
    v=>{v.beta_features.google=null;},
    v=>{v.beta_features.capture=null;},
    v=>{delete v.beta_features.capture;},
  ];
  for(const change of changes){const value=candidate({owned:true});change(value);assert.throws(()=>render(value));}
  // Capture without Google is refused even when capture payload looks valid.
  const standalone=candidate({google:false,owned:false});
  standalone.beta_features.capture=captureFixtureFor(standalone.api_origin);
  assert.throws(()=>render(standalone));
});

test('existing owned VM scope admits only retained CosmaBot routes and cannot create another TLS listener',()=>{
  const files=render(candidate({owned:true})),contract=files['host-preparation.json'];
  assert.equal(contract.resource_identity.host_name,'vm-cosmabot-staging-eus2-lab01');
  assert.equal(files['api-public.json'].STANDALONE_ROOT,`/var/lib/cosmabot/standalone/${sample.instance_id}/app`);
  assert.equal(files['https.review.conf'],undefined);assert.equal(files['cosmabot-https.review.service'],undefined);
  assert.equal(contract.existing_proxy.new_tls_listener_forbidden,true);
  assert.equal(contract.existing_proxy.old_services_and_data_retained,true);
  assert.equal(contract.existing_proxy.cutover_and_rollback_qualified,false);
  assert.equal(contract.deployment_authorized,false);
  assert.equal(files['api-public.json'].WORKSPACE_CAPTURE_BACKEND,'core');
  assert.equal(files['api-public.json'].REAL_PATIENT_RECORDING_ENABLED,'false');
  assert.equal(files['api-public.json'].COSMAS_EHR_REAL_DATA_ENABLED,'false');
  assert.deepEqual(contract.private_environment.optional_exact_names,['ACCOUNT_DELETE_CLERK_SECRET_KEY']);
  assert.equal(contract.private_environment.key_vault_name,'kv-cbot-stg-stg0925c1');
  assert.deepEqual(contract.private_environment.key_vault_secret_names,{
    ACCOUNT_DELETE_CLERK_SECRET_KEY:'account-delete-clerk-secret-key',
  });
  assert.ok(files['network-requirements.json'].api_egress.some(item=>item.hostname==='api.clerk.com'));
});

test('owned beta.cosmas.ai stays synthetic and every other host stays refused',()=>{
  const files=render(candidate({owned:true,host:'beta.cosmas.ai'})),env=files['api-public.json'];
  assert.equal(env.COSMAS_ENV,'standalone_clerk_synthetic');
  assert.equal(env.DATA_MODE,'synthetic');
  assert.equal(files['host-preparation.json'].synthetic_only,true);
  assert.equal(files['host-preparation.json'].deployment_authorized,false);
  assert.equal(files['clients/web-build-env.json'].VITE_WORKSPACE_DATA_MODE,'synthetic');
  assert.equal(env.CORS_ALLOWED_ORIGINS,['https://beta.cosmas.ai','app://cosmas','capacitor://localhost'].join(','));
  // Production / beta profile: no account-delete Key Vault mapping; exact_names unchanged.
  const privateEnv=files['host-preparation.json'].private_environment;
  assert.equal(Object.hasOwn(privateEnv,'optional_exact_names'),false);
  assert.equal(Object.hasOwn(privateEnv,'key_vault_secret_names'),false);
  assert.ok(!files['network-requirements.json'].api_egress.some(item=>item.hostname==='api.clerk.com'));
  for(const extra of ['data_mode','cosmas_env','phi']){
    const switched=candidate({owned:true,host:'beta.cosmas.ai'});
    switched[extra]='authorized_beta';
    assert.throws(()=>render(switched));
  }
  const featureSwitch=candidate({owned:true,host:'beta.cosmas.ai'});
  featureSwitch.beta_features.data_mode='authorized_beta';
  assert.throws(()=>render(featureSwitch));
  const hosts=[
    ['https://app.cosmaneura.com','https://api.cosmaneura.com'],
    ['https://cosmas.ai','https://api.cosmas.ai'],
    ['https://www.cosmas.ai','https://api.www.cosmas.ai'],
    ['https://app.cosmas.ai','https://api.cosmas.ai'],
    ['https://foo.cosmaneura.com','https://api.foo.cosmaneura.com'],
    ['https://random.example.invalid','https://api.random.example.invalid'],
    ['https://beta.cosmas.ai','https://api.staging.cosmas.ai'],
  ];
  for(const [web,api] of hosts){
    const refused=candidate({owned:true,host:'beta.cosmas.ai'});
    refused.web_origin=web;refused.api_origin=api;refused.identity.apiOrigin=api;
    refused.tls.hostnames=[new URL(web).hostname,new URL(api).hostname];
    refused.beta_features.google.callback_uri=api+'/connections/google/callback';
    refused.beta_features.google.return_origin=web;
    assert.throws(()=>render(refused));
  }
});

test('public overlay rejects credentials, alternate destinations, models, profiles and legacy routes',()=>{
  const changes=[
    v=>{v.beta_features.secret='PRIVATE';},v=>{v.beta_features.model.api_key='PRIVATE';},
    v=>{v.beta_features.google.client_secret='PRIVATE';},v=>{v.beta_features.google.encryption_key='PRIVATE';},
    v=>{v.beta_features.model.deployment='other';},v=>{v.beta_features.model.origin+='\n';},
    v=>{v.beta_features.model.endpoint+='?alternate=1';},v=>{v.beta_features.model.origin='https://model.cosmaneura.com';},
    v=>{v.beta_features.google.client_id+='\n';},v=>{v.beta_features.google.callback_uri='https://api.cosmaneura.com/connections/google/callback';},
    v=>{v.beta_features.google.return_origin='https://other.example.invalid';},
    v=>{v.beta_features.google=null;v.beta_features.capture=null;},v=>{v.web_origin='https://app.cosmas.ai';},
    v=>{v.api_origin='https://api.cosmas.ai';v.identity.apiOrigin=v.api_origin;},
    v=>{v.resource_scope='dedicated-new-cosmabot-host';},v=>{delete v.beta_features;},
  ];
  for(const change of changes){const value=candidate({owned:true});change(value);assert.throws(()=>render(value));}
});
