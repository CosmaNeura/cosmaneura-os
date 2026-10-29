import test from 'node:test';
import assert from 'node:assert/strict';
import {googleNavigationConfig,validGoogleNavigationUrl} from './google-navigation.mjs';
import {COSMANEURA_CHANNELS,installCosmaneuraNavigation,parseCosmaneuraRequest} from './cosmaneura-navigation.mjs';
import {EventEmitter} from 'node:events';
import {randomUUID} from 'node:crypto';
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

test('Google capability and explicit handoff work on routed pages with the same account and frame fences',async()=>{
 const handlers=new Map(),listeners=new Map(),opened=[];
 const renderer=Object.assign(new EventEmitter(),{mainFrame:{url:'app://cosmas/index.html#cosmas/settings'},isDestroyed:()=>false,getURL:()=>renderer.mainFrame.url});
 const revision='00000000-0000-4000-8000-000000000084';
 const state={phase:'ready',revision,identity:{userId:'user_invented',sessionId:'sess_invented',organizationId:'org_invented'}};
 let current=state;
 const auth={snapshot:()=>current,getState:async()=>current};
 const dispose=installCosmaneuraNavigation({ipcMain:{on:(k,f)=>listeners.set(k,f),removeListener:k=>listeners.delete(k),handle:(k,f)=>handlers.set(k,f),removeHandler:k=>handlers.delete(k)},renderer,auth,
   googleClientId:config.clientId,googleCallbackUri:config.callbackUri,openExternal:async value=>{opened.push(value);}});
 const event=()=>({sender:renderer,senderFrame:renderer.mainFrame});
 const request=()=>({schemaVersion:1,requestId:randomUUID(),expectedRevision:revision,href:url(fields)});
 const capability=event();listeners.get(COSMANEURA_CHANNELS.googleCapability)(capability);assert.equal(capability.returnValue,true);
 await handlers.get(COSMANEURA_CHANNELS.open)(event(),request());assert.deepEqual(opened,[url(fields)]);
 for(const page of ['app://cosmas/index.html?foreign=1#cosmas/settings','app://other/index.html#cosmas/settings','app://cosmas:443/index.html#cosmas/settings']){
   renderer.mainFrame.url=page;const denied=event();listeners.get(COSMANEURA_CHANNELS.googleCapability)(denied);assert.equal(denied.returnValue,false);
   await assert.rejects(handlers.get(COSMANEURA_CHANNELS.open)(event(),request()));
 }
 renderer.mainFrame.url='app://cosmas/index.html#cosmas/home';
 await assert.rejects(handlers.get(COSMANEURA_CHANNELS.open)({...event(),senderFrame:{url:renderer.mainFrame.url}},request()));
 current={...state,revision:randomUUID()};await assert.rejects(handlers.get(COSMANEURA_CHANNELS.open)(event(),request()));
 assert.equal(opened.length,1);dispose();
});
