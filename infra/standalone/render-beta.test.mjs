import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {render} from './render.mjs';

const sample=JSON.parse(await readFile(new URL('./invented-host-input.json',import.meta.url),'utf8'));
function candidate({model=true,google=true,owned=false}={}){
  const value=structuredClone(sample);
  if(owned){value.resource_scope='owned-cosmabot-vm-instance';value.web_origin='https://staging.cosmas.ai';
    value.api_origin='https://api.staging.cosmas.ai';value.identity.apiOrigin=value.api_origin;
    value.tls.hostnames=['staging.cosmas.ai','api.staging.cosmas.ai'];}
  value.beta_features={model:model?{origin:'https://invented-owned-chief.openai.azure.com',
    endpoint:'https://invented-owned-chief.openai.azure.com/openai/v1',deployment:'gpt-4.1'}:null,
    google:google?{client_id:'invented-client.apps.googleusercontent.com',
      callback_uri:value.api_origin+'/connections/google/callback',return_origin:value.web_origin}:null};
  return value;
}

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
