import test from 'node:test';
import assert from 'node:assert/strict';
import {microsoftNavigationConfig,validMicrosoftNavigationUrl} from './microsoft-navigation.mjs';
import {parseCosmaneuraRequest} from './cosmaneura-navigation.mjs';
import {connectorApiRoute} from './connector-api-routes.mjs';
const tenant='11111111-1111-4111-8111-111111111111',client='22222222-2222-4222-8222-222222222222';
const config=microsoftNavigationConfig(tenant,client,'https://api.example.invalid/connections/microsoft/callback');
const fields={client_id:client,redirect_uri:config.callbackUri,response_type:'code',response_mode:'query',scope:'offline_access User.Read Mail.Read Calendars.Read',state:'s'.repeat(43),prompt:'select_account',code_challenge_method:'S256',code_challenge:'c'.repeat(43)};
const url=v=>`https://login.microsoftonline.com/${tenant}/oauth2/v2.0/authorize?`+new URLSearchParams(v);
test('only configured tenant/client/callback and read-only Microsoft consent can leave the native app',()=>{
 assert.equal(microsoftNavigationConfig(),null);assert.equal(validMicrosoftNavigationUrl(url(fields),null),false);
 assert.equal(validMicrosoftNavigationUrl(url(fields),config),true);
 for(const [key,value] of [['client_id',tenant],['redirect_uri','https://other.example.invalid/connections/microsoft/callback'],['scope',fields.scope+' Mail.Send'],['state','short'],['code_challenge_method','plain'],['response_mode','fragment']])assert.equal(validMicrosoftNavigationUrl(url({...fields,[key]:value}),config),false);
 for(const bad of [url(fields)+'&state=duplicate',url(fields)+'#fragment',url(fields)+'&login_hint=private@example.invalid',url(fields).replace(tenant,'common'),url(fields).replace('login.microsoftonline.com','login.microsoftonline.com.evil.invalid')])assert.equal(validMicrosoftNavigationUrl(bad,config),false);
 assert.throws(()=>microsoftNavigationConfig(tenant,client,''));
 const request={schemaVersion:1,requestId:'12345678-1234-4234-8234-123456789abc',expectedRevision:'12345678-1234-4234-8234-123456789def',href:url(fields)};
 assert.deepEqual(parseCosmaneuraRequest(request,null,null,config),request);assert.throws(()=>parseCosmaneuraRequest(request,null));
 assert.throws(()=>parseCosmaneuraRequest({...request,schemaVersion:2},null,null,config));
});
test('the native proxy admits only the bounded authenticated Microsoft command',()=>{
 assert.deepEqual(connectorApiRoute('/connections/microsoft/session','POST'),{header:'X-Cosmas-Microsoft-Connection',input:1024,output:131072,seconds:50,strictResponse:true,errorOutput:2048});
 for(const method of ['GET','PUT','DELETE'])assert.equal(connectorApiRoute('/connections/microsoft/session',method),null);
 assert.equal(connectorApiRoute('/connections/microsoft/session?token=anything','POST'),null);
});
