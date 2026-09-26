import test from 'node:test';
import assert from 'node:assert/strict';
import {schedulingNavigationConfig,validSchedulingNavigationUrl} from './scheduling-navigation.mjs';
import {parseCosmaneuraRequest} from './cosmaneura-navigation.mjs';
const config=schedulingNavigationConfig('invented.apps.googleusercontent.com','https://api.example.invalid/connections/scheduling/google/callback');
const fields={client_id:config.clientId,redirect_uri:config.callbackUri,response_type:'code',scope:'openid email',state:'s'.repeat(43),nonce:'n'.repeat(43),access_type:'offline',prompt:'consent select_account',code_challenge_method:'S256',code_challenge:'c'.repeat(43)};
const url=v=>'https://accounts.google.com/o/oauth2/v2/auth?'+new URLSearchParams(v);
test('Google sign-in requires installed exact client/callback and closed OAuth parameters',()=>{
 assert.equal(schedulingNavigationConfig(),null);assert.equal(validSchedulingNavigationUrl(url(fields),null),false);
 assert.equal(validSchedulingNavigationUrl(url(fields),config),true);
 for(const [key,value] of [['client_id','attacker.apps.googleusercontent.com'],['redirect_uri','https://other.example.invalid/connections/scheduling/google/callback'],['scope','openid email https://www.googleapis.com/auth/gmail.readonly'],['state','short'],['code_challenge_method','plain']])assert.equal(validSchedulingNavigationUrl(url({...fields,[key]:value}),config),false);
 for(const bad of [url(fields)+'&state=duplicate',url(fields)+'#fragment',url(fields)+'&login_hint=private@example.invalid',url(fields).replace('accounts.google.com','accounts.google.com.evil.invalid')])assert.equal(validSchedulingNavigationUrl(bad,config),false);
 assert.throws(()=>schedulingNavigationConfig(config.clientId,''));
 const request={schemaVersion:1,requestId:'12345678-1234-4234-8234-123456789abc',expectedRevision:'12345678-1234-4234-8234-123456789def',href:url(fields)};
 assert.deepEqual(parseCosmaneuraRequest(request,null,config),request);
 assert.throws(()=>parseCosmaneuraRequest(request,null));
});
