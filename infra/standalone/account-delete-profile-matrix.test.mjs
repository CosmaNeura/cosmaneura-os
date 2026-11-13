import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {
  classifyAccountDeleteProfile,
  render,
  Refused,
  STAGING_WEB_ORIGIN,
  REVIEW_WEB_ORIGIN,
  REVIEW_CLERK_ISSUER,
  STAGING_SESSION_POLICY,
  REVIEW_SESSION_POLICY,
  ACCOUNT_DELETE_ENV_NAME,
  REVIEW_ACCOUNT_DELETE_HOST_KEY,
  STAGING_ACCOUNT_DELETE_VAULT_SECRET,
} from './render.mjs';

const matrix=JSON.parse(await readFile(new URL('./account-delete-profile-matrix.json',import.meta.url),'utf8'));
const sample=JSON.parse(await readFile(new URL('./invented-host-input.json',import.meta.url),'utf8'));

function liveKey(host){
  return 'pk_live_'+Buffer.from(`${host}$`).toString('base64');
}

function ownedCandidate({host,policy='audience',issuer=REVIEW_CLERK_ISSUER}={}){
  const value=structuredClone(sample);
  value.resource_scope='owned-cosmabot-vm-instance';
  value.web_origin=`https://${host}`;
  value.api_origin=`https://api.${host}`;
  value.identity.apiOrigin=value.api_origin;
  value.tls.hostnames=[host,`api.${host}`];
  value.identity_policy=policy;
  if(policy===STAGING_SESSION_POLICY){
    value.identity.profile='operational-staging-v1';
    value.identity.audience='';
    value.identity.frontendOrigin='https://invented-own-practice.clerk.accounts.dev';
    value.identity.publishableKey='pk_test_'+Buffer.from('invented-own-practice.clerk.accounts.dev$').toString('base64');
  }else if(host==='beta.cosmas.ai'){
    value.identity.profile='operational-production-v1';
    value.identity.audience='cosmas-os-beta-api';
    value.identity.frontendOrigin=issuer;
    value.identity.publishableKey=liveKey(new URL(issuer).hostname);
  }else{
    value.identity.profile='operational-beta-v1';
    value.identity.audience='cosmas-os-beta-api';
    value.identity.frontendOrigin=issuer;
    value.identity.publishableKey=liveKey(new URL(issuer).hostname);
  }
  value.beta_features={model:{origin:'https://invented-owned-chief.openai.azure.com',
    endpoint:'https://invented-owned-chief.openai.azure.com/openai/v1',deployment:'gpt-4.1'},
    google:{client_id:'invented-client.apps.googleusercontent.com',
      callback_uri:value.api_origin+'/connections/google/callback',return_origin:value.web_origin}};
  return value;
}

for(const row of matrix){
  test(`matrix ${row.id}: classifyAccountDeleteProfile => ${row.expect}`,()=>{
    const kind=classifyAccountDeleteProfile({
      web_origin:row.web_origin,
      identity_policy:row.policy,
      cors_origins:row.cors.split(',').map(item=>item.trim()).filter(Boolean),
      issuer:row.issuer,
    });
    const expected=row.expect==='none'?null:row.expect;
    assert.equal(kind,expected);
  });
}

// Owned synthetic hosts also exercise render() for rows whose CORS is the
// standard owned parties list (render builds CORS from web_origin; mixed CORS
// rows stay classify-only).
const ownedRenderRows=matrix.filter(row=>{
  try{
    const host=new URL(row.web_origin).hostname;
    if(host!=='staging.cosmas.ai'&&host!=='beta.cosmas.ai')return false;
    const parties=[row.web_origin,'app://cosmas','capacitor://localhost'].join(',');
    return row.render==='refuse'||row.cors===parties;
  }catch{
    return false;
  }
});
for(const row of ownedRenderRows){
  test(`matrix ${row.id}: render() mapping agrees with expect=${row.expect}`,()=>{
    const host=new URL(row.web_origin).hostname;
    const value=ownedCandidate({host,policy:row.policy,issuer:row.issuer});
    if(row.render==='refuse'||row.expect==='none'){
      assert.throws(()=>render(value),error=>error instanceof Refused);
      return;
    }
    const files=render(value);
    const privateEnv=files['host-preparation.json'].private_environment;
    assert.deepEqual(privateEnv.optional_exact_names,[ACCOUNT_DELETE_ENV_NAME]);
    if(row.expect==='staging'){
      assert.deepEqual(privateEnv.key_vault_secret_names,{
        [ACCOUNT_DELETE_ENV_NAME]:STAGING_ACCOUNT_DELETE_VAULT_SECRET,
      });
      assert.equal(privateEnv.key_vault_name,'kv-cbot-stg-stg0925c1');
    }else if(row.expect==='review'){
      assert.deepEqual(privateEnv.key_vault_secret_names,{
        [ACCOUNT_DELETE_ENV_NAME]:REVIEW_ACCOUNT_DELETE_HOST_KEY,
      });
      assert.equal(Object.hasOwn(privateEnv,'key_vault_name'),false);
      const clerkEgress=files['network-requirements.json'].api_egress
        .find(item=>item.hostname==='api.clerk.com');
      assert.ok(clerkEgress);
    }
  });
}

test('owned beta with shared_staging is refused by render validateInput',()=>{
  assert.throws(
    ()=>render(ownedCandidate({host:'beta.cosmas.ai',policy:STAGING_SESSION_POLICY})),
    error=>error instanceof Refused&&String(error.message||error).includes('production_review_requires_audience_policy'),
  );
});

test('owned staging render stays on staging vault secret name (byte-stable mapping)',()=>{
  const files=render(ownedCandidate({host:'staging.cosmas.ai',policy:REVIEW_SESSION_POLICY,issuer:'https://clerk.staging.cosmas.ai'}));
  // audience + staging host is staging kind via origin.
  const privateEnv=files['host-preparation.json'].private_environment;
  assert.deepEqual(privateEnv.optional_exact_names,[ACCOUNT_DELETE_ENV_NAME]);
  assert.deepEqual(privateEnv.key_vault_secret_names,{
    [ACCOUNT_DELETE_ENV_NAME]:STAGING_ACCOUNT_DELETE_VAULT_SECRET,
  });
  assert.equal(privateEnv.key_vault_name,'kv-cbot-stg-stg0925c1');
  assert.equal(privateEnv.key_vault_uri,'https://kv-cbot-stg-stg0925c1.vault.azure.net/');
  assert.notEqual(privateEnv.key_vault_secret_names[ACCOUNT_DELETE_ENV_NAME],REVIEW_ACCOUNT_DELETE_HOST_KEY);
});

test('constants stay aligned with entrypoint names',()=>{
  assert.equal(STAGING_WEB_ORIGIN,'https://staging.cosmas.ai');
  assert.equal(REVIEW_WEB_ORIGIN,'https://beta.cosmas.ai');
  assert.equal(REVIEW_CLERK_ISSUER,'https://clerk.beta.cosmas.ai');
  assert.equal(STAGING_SESSION_POLICY,'shared_staging');
  assert.equal(REVIEW_SESSION_POLICY,'audience');
});
