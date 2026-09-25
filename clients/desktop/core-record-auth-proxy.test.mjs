import assert from 'node:assert/strict';
import test from 'node:test';
import {connectorApiRoute,CONNECTOR_HEADERS} from './connector-api-routes.mjs';
import {permittedAuthenticatedApiPath,proxyAuthenticatedWorkspaceRequest as proxy} from './workspace-auth-proxy.mjs';
const id='00000000-0000-4000-8000-000000000001',header='X-Cosmas-Record-Contract';
const path=`/workspaces/${id}/cosmaneura-record/location`;
function auth(){let state={phase:'ready',revision:id,identity:{userId:'invented',sessionId:'invented',organizationId:'invented'}};const listeners=new Set();return {
  getState:async()=>state,snapshot:()=>state,getToken:async()=>'invented.local.token',subscribe:fn=>{listeners.add(fn);return()=>listeners.delete(fn);},
  revoke(){state={phase:'signedOut',revision:id,identity:null};for(const fn of listeners)fn(state);}};}
const request=()=>new Request('app://cosmas/api'+path,{headers:{'Content-Type':'application/json','X-Cosmas-Desktop-Session':id,[header]:'1'}});
const response=(body='{}',headers={})=>new Response(body,{headers:{'Content-Type':'application/json','Cache-Control':'no-store',...headers}});
test('the location is the single strict read-only route with zero request body and bounded response',()=>{
  assert.equal(CONNECTOR_HEADERS.filter(v=>v===header).length,1);
  assert.deepEqual(connectorApiRoute(path,'GET'),{header,input:0,output:2048,seconds:35,strictResponse:true,errorOutput:2048});
  assert.equal(permittedAuthenticatedApiPath('app://cosmas/api'+path,'GET'),path);
  for(const method of ['POST','PUT','PATCH','DELETE','HEAD'])assert.equal(permittedAuthenticatedApiPath('app://cosmas/api'+path,method),null);
  for(const url of ['app://cosmas/api'+path+'?','app://cosmas/api'+path+'?next=x','app://cosmas/api'+path+'#x',
    'app://cosmas/api'+path+'/extra','https://outside.invalid'+path,'app://cosmas/api'+path.replace('/location','/%6cocation'),
    'app://cosmas/api'+path.replace('/cosmaneura-record/','/extra/../cosmaneura-record/')])assert.equal(permittedAuthenticatedApiPath(url,'GET'),null,url);
});
test('requires exact negotiation before requesting a native credential',async()=>{
  for(const value of [null,'','2','1, 1']){const req=request();if(value===null)req.headers.delete(header);else req.headers.set(header,value);
    const session=auth();session.getToken=()=>assert.fail('no token');assert.equal((await proxy(req,session,()=>assert.fail('no dispatch'))).status,426);}
});
test('forwards only the fixed local API read and strips cookies',async()=>{
  let count=0;const result=await proxy(request(),auth(),async(url,options)=>{count++;assert.equal(url,'http://127.0.0.1:8046'+path);
    assert.equal(options.method,'GET');assert.equal(options.body,undefined);assert.equal(options.headers[header],'1');
    assert.equal(options.headers.Authorization,'Bearer invented.local.token');assert.equal(options.redirect,'error');
    return response('{}',{'Set-Cookie':'invented=never-forward'});});
  assert.equal(count,1);assert.equal(result.status,200);assert.equal(result.headers.get('set-cookie'),null);
});
test('refuses oversized or encoded navigation replies',async()=>{
  assert.equal((await proxy(request(),auth(),async()=>response(' '.repeat(2049)))).status,503);
  assert.equal((await proxy(request(),auth(),async()=>response('{}',{'Content-Encoding':'identity'}))).status,502);
});
test('withdrawal during a read clears the response without repeating it',async()=>{
  const session=auth();let cancelled=0,calls=0;
  const promise=proxy(request(),session,async()=>{calls++;return response(new ReadableStream({pull(){return new Promise(()=>{});},cancel(){cancelled++;}}));});
  await new Promise(resolve=>setImmediate(resolve));session.revoke();assert.equal((await promise).status,401);assert.equal(calls,1);assert.equal(cancelled,1);
});
