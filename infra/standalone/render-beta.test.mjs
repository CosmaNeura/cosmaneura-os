import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {render} from './render.mjs';

const sample=JSON.parse(await readFile(new URL('./invented-host-input.json',import.meta.url),'utf8'));
function candidate({model=true,google=true,owned=false,host='staging.cosmas.ai'}={}){
  const value=structuredClone(sample);
  if(owned){value.resource_scope='owned-cosmabot-vm-instance';value.web_origin=`https://${host}`;
    value.api_origin=`https://api.${host}`;value.identity.apiOrigin=value.api_origin;
    value.tls.hostnames=[host,`api.${host}`];}
  value.beta_features={model:model?{origin:'https://invented-owned-chief.openai.azure.com',
    endpoint:'https://invented-owned-chief.openai.azure.com/openai/v1',deployment:'gpt-4.1'}:null,
    google:google?{client_id:'invented-client.apps.googleusercontent.com',
      callback_uri:value.api_origin+'/connections/google/callback',return_origin:value.web_origin}:null};
  return value;
}

test('explicit Microsoft overlay binds existing broker, client gates and protected custody names',()=>{
  const value=candidate({owned:true});
  value.beta_features.microsoft={tenant_id:'10000000-0000-4000-8000-000000000001',client_id:'10000000-0000-4000-8000-000000000002',
    callback_uri:value.api_origin+'/connections/microsoft/callback',return_origin:value.web_origin};
  const files=render(value),env=files['api-public.json'],contract=files['host-preparation.json'];
  for(const flag of ['WORKSPACE_MICROSOFT_CONNECTION_ENABLED','WORKSPACE_MICROSOFT_MESSAGE_ENABLED','WORKSPACE_MICROSOFT_CALENDAR_ENABLED']){
    assert.equal(env[flag],'true');assert.equal(render(candidate({owned:true}))['api-public.json'][flag],'false');
  }
  for(const client of ['web','desktop','apple']){
    assert.equal(files[`clients/${client}-build-env.json`].VITE_WORKSPACE_MICROSOFT_CONNECTION_ENABLED,'true');
    assert.equal(files[`clients/${client}-build-env.json`].VITE_MICROSOFT_MESSAGE_ENABLED,'true');
  }
  assert.equal(files['clients/web-build-arguments.json'].VITE_MICROSOFT_MESSAGE_ENABLED,'true');
  for(const secret of ['MICROSOFT_CONNECTION_CLIENT_SECRET','MICROSOFT_CONNECTION_ENCRYPTION_KEY']){
    assert.ok(contract.private_environment.exact_names.includes(secret));assert.equal(Object.hasOwn(env,secret),false);
  }
  assert.equal(contract.optional_runtime_features.microsoft,true);
  assert.equal(contract.optional_runtime_features.live_provider_acceptance,false);
  assert.deepEqual(files['network-requirements.json'].api_egress.slice(-2).map(item=>item.hostname),['login.microsoftonline.com','graph.microsoft.com']);
  for(const change of [m=>{m.tenant_id='common';},m=>{m.client_id='not-a-uuid';},
    m=>{m.callback_uri='https://api.cosmaneura.com/connections/microsoft/callback';},
    m=>{m.return_origin='https://other.example.invalid';},m=>{m.client_secret='invented';}]){
    const altered=structuredClone(value);change(altered.beta_features.microsoft);assert.throws(()=>render(altered));
  }
});

test('organizations overlay declares required multitenant registration without performing it',()=>{
  const value=candidate({owned:true});
  value.beta_features.microsoft={tenant_id:'organizations',client_id:'10000000-0000-4000-8000-000000000002',
    callback_uri:value.api_origin+'/connections/microsoft/callback',return_origin:value.web_origin};
  const files=render(value),contract=files['host-preparation.json'];
  assert.equal(files['api-public.json'].MICROSOFT_CONNECTION_TENANT_ID,'organizations');
  assert.equal(contract.microsoft_registration.required_sign_in_audience,'AzureADMultipleOrgs');
  assert.equal(contract.microsoft_registration.account_type,'any_work_or_school_tenant');
  assert.equal(contract.microsoft_registration.provider_registration_performed,false);
  assert.equal(contract.optional_runtime_features.live_provider_acceptance,false);
  for(const authority of ['common','consumers','Organizations','organizations/','https://login.microsoftonline.com/organizations']){
    const altered=structuredClone(value);altered.beta_features.microsoft.tenant_id=authority;
    assert.throws(()=>render(altered));
  }
});

test('optional public features bind server, clients, private field names and explicit egress',()=>{
  for(const model of [false,true])for(const google of [false,true]){
    const value=candidate({model,google}),files=render(value),env=files['api-public.json'];
    const contract=files['host-preparation.json'];
    assert.equal(env.WORKSPACE_LLM_BACKEND,model?'azure_gpt41':'disabled');
    assert.equal(env.WORKSPACE_GOOGLE_CONNECTION_ENABLED,String(google));
    for(const client of ['web','desktop','apple']){
      const profile=files['clients/standalone-profile.json'].clients[client];
      assert.equal(profile.profile,google?'independent-beta-v1':'standalone-practice-v1');
      assert.equal(files[`clients/${client}-build-env.json`].VITE_WORKSPACE_GOOGLE_CONNECTION_ENABLED,String(google));
      assert.equal(files[`clients/${client}-build-env.json`].VITE_COSMANEURA_WEB_ORIGIN,'');
    }
    assert.deepEqual(contract.private_environment.exact_names,['DATABASE_URL','HUMAN_DEPLOY_EVIDENCE_REF',
      ...(model?['WORKSPACE_LLM_API_KEY']:[]),...(google?['GOOGLE_CONNECTION_CLIENT_SECRET','GOOGLE_CONNECTION_ENCRYPTION_KEY']:[])]);
    for(const name of contract.private_environment.exact_names)assert.equal(Object.hasOwn(env,name),false);
    assert.equal(files['network-requirements.json'].api_egress.length,1+Number(model)+4*Number(google));
    assert.deepEqual(contract.external_workers,[]);assert.deepEqual(contract.platform_connections,[]);
    assert.equal(contract.optional_runtime_features.live_provider_acceptance,false);
  }
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
  assert.deepEqual(contract.private_environment.optional_exact_names,['ACCOUNT_DELETE_CLERK_SECRET_KEY']);
  assert.equal(contract.private_environment.key_vault_name,'kv-cbot-stg-stg0925c1');
  assert.deepEqual(contract.private_environment.key_vault_secret_names,{
    ACCOUNT_DELETE_CLERK_SECRET_KEY:'account-delete-clerk-secret-key',
  });
  const clerkEgress=files['network-requirements.json'].api_egress.find(item=>item.hostname==='api.clerk.com');
  assert.deepEqual(clerkEgress,{
    protocol:'https',hostname:'api.clerk.com',tcp_port:443,
    path:'/v1/users/',redirects_allowed:false,purpose:'account_delete_clerk_backend',
  });
  assert.equal(
    files['network-requirements.json'].dns,
    'Only the exact configured Clerk issuer, Clerk Backend API, optional own model and selected Google/Microsoft API hostnames; qualify resolver enforcement separately.',
  );
  const evidence=contract.required_evidence.find(item=>item.startsWith('Host firewall and DNS'));
  assert.equal(
    evidence,
    'Host firewall and DNS qualification: only declared Clerk JWKS, Clerk Backend API, optional own model and selected Google/Microsoft API egress; no metadata or other providers',
  );
});

test('owned beta.cosmas.ai stays synthetic and every other host stays refused',()=>{
  const files=render(candidate({owned:true,host:'beta.cosmas.ai'})),env=files['api-public.json'];
  assert.equal(env.COSMAS_ENV,'standalone_clerk_synthetic');
  assert.equal(env.DATA_MODE,'synthetic');
  assert.equal(files['host-preparation.json'].synthetic_only,true);
  assert.equal(files['host-preparation.json'].deployment_authorized,false);
  assert.equal(files['clients/web-build-env.json'].VITE_WORKSPACE_DATA_MODE,'synthetic');
  assert.equal(env.CORS_ALLOWED_ORIGINS,['https://beta.cosmas.ai','app://cosmas','capacitor://localhost'].join(','));
  // Production-review: key-name allowance only. No Key Vault fields, no api.clerk.com egress.
  const privateEnv=files['host-preparation.json'].private_environment;
  assert.deepEqual(privateEnv.optional_exact_names,['ACCOUNT_DELETE_CLERK_SECRET_KEY']);
  assert.equal(Object.hasOwn(privateEnv,'key_vault_secret_names'),false);
  assert.equal(Object.hasOwn(privateEnv,'key_vault_name'),false);
  assert.equal(Object.hasOwn(privateEnv,'key_vault_uri'),false);
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
    v=>{v.beta_features.google=null;},v=>{v.web_origin='https://app.cosmas.ai';},
    v=>{v.api_origin='https://api.cosmas.ai';v.identity.apiOrigin=v.api_origin;},
    v=>{v.resource_scope='dedicated-new-cosmabot-host';},v=>{delete v.beta_features;},
  ];
  for(const change of changes){const value=candidate({owned:true});change(value);assert.throws(()=>render(value));}
});
