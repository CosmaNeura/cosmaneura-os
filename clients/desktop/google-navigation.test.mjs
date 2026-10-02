import test from 'node:test';
import assert from 'node:assert/strict';
import {googleNavigationConfig,validGoogleNavigationUrl} from './google-navigation.mjs';
import {parseCosmaneuraRequest} from './cosmaneura-navigation.mjs';
import {connectorApiRoute} from './connector-api-routes.mjs';
const config=googleNavigationConfig('invented.apps.googleusercontent.com','https://api.example.invalid/connections/google/callback');
const fields={client_id:config.clientId,redirect_uri:config.callbackUri,response_type:'code',access_type:'offline',include_granted_scopes:'false',scope:'openid email https://www.googleapis.com/auth/gmail.metadata',state:'s'.repeat(43),prompt:'consent select_account',code_challenge_method:'S256',code_challenge:'c'.repeat(43)};
const url=v=>'https://accounts.google.com/o/oauth2/v2/auth?'+new URLSearchParams(v);
test('native Google handoff binds the reviewed client, callback and metadata grant without widening Scheduling',()=>{
 assert.equal(googleNavigationConfig(),null);assert.equal(validGoogleNavigationUrl(url(fields),config),true);
 for(const [key,value] of [['scope','openid email https://www.googleapis.com/auth/gmail.send'],['include_granted_scopes','true'],['redirect_uri','https://api.example.invalid/connections/scheduling/google/callback'],['client_id','other.apps.googleusercontent.com'],['code_challenge_method','plain']])assert.equal(validGoogleNavigationUrl(url({...fields,[key]:value}),config),false);
 for(const bad of [url(fields)+'&state=duplicate',url(fields)+'#fragment',url(fields)+'&login_hint=person@example.invalid',url(fields).replace('accounts.google.com','accounts.google.com.evil.invalid')])assert.equal(validGoogleNavigationUrl(bad,config),false);
 const request={schemaVersion:1,requestId:'12345678-1234-4234-8234-123456789abc',expectedRevision:'12345678-1234-4234-8234-123456789def',href:url(fields)};
 assert.deepEqual(parseCosmaneuraRequest(request,null,null,null,config),request);
 assert.throws(()=>parseCosmaneuraRequest(request,null));
});
test('native proxy admits only the protected bounded Google command',()=>{
 assert.deepEqual(connectorApiRoute('/connections/google/session','POST'),{header:'X-Cosmas-Google-Connection',input:1024,output:131072,seconds:50,strictResponse:true,errorOutput:2048});
 for(const method of ['GET','PUT','DELETE'])assert.equal(connectorApiRoute('/connections/google/session',method),null);
 assert.equal(connectorApiRoute('/connections/google/session?code=anything','POST'),null);
});
test('Google calendar consent admits only the exact read-only scope',()=>{
 const scope=fields.scope+' https://www.googleapis.com/auth/calendar.events.readonly';
 assert.equal(validGoogleNavigationUrl(url({...fields,scope}),config),true);
 for(const invalid of [scope.replace('events.readonly','events'),scope+' https://www.googleapis.com/auth/gmail.send',scope+' openid']){
  assert.equal(validGoogleNavigationUrl(url({...fields,scope:invalid}),config),false);
 }
});
test('separate full-message consent admits only the pinned read-only permission set',()=>{
 const scope=fields.scope+' https://www.googleapis.com/auth/calendar.events.readonly https://www.googleapis.com/auth/gmail.readonly';
 assert.equal(validGoogleNavigationUrl(url({...fields,scope}),config),true);
 for(const invalid of [scope.replace('gmail.readonly','gmail.modify'),scope+' https://www.googleapis.com/auth/gmail.send',scope+' https://www.googleapis.com/auth/gmail.readonly',scope.replace('openid email','email openid')]){
  assert.equal(validGoogleNavigationUrl(url({...fields,scope:invalid}),config),false);
 }
});
