import test from 'node:test';
import assert from 'node:assert/strict';
import {connectorApiRoute,CONNECTOR_HEADERS} from './connector-api-routes.mjs';
import {permittedAuthenticatedApiPath,proxyAuthenticatedWorkspaceRequest as proxy} from './workspace-auth-proxy.mjs';
test('permits only the bounded explicit Visit Prep read',()=>{
  const path='/provider-team/visit-prep/read';
  assert.equal(permittedAuthenticatedApiPath('app://cosmas/api'+path,'POST'),path);
  assert.equal(connectorApiRoute(path,'POST').output,262144);
  assert.ok(CONNECTOR_HEADERS.includes(connectorApiRoute(path,'POST').header));
  for(const ending of ['/','?prep=anything','/send'])assert.equal(connectorApiRoute(path+ending,'POST'),null);
  for(const method of ['GET','PUT','DELETE'])assert.equal(connectorApiRoute(path,method),null);
});
test('desktop forwards the patient package without credentials, cookies or referrer leakage',async()=>{
  const id='00000000-0000-4000-8000-000000000001',state={phase:'ready',revision:id,identity:{userId:'invented',sessionId:'invented',organizationId:'invented'}};
  const auth={getState:async()=>state,snapshot:()=>state,getToken:async()=>'invented.local.token',subscribe:()=>()=>{}};
  const result=await proxy(new Request('app://cosmas/api/provider-team/visit-prep/read',{method:'POST',body:'{}',
    headers:{'Content-Type':'application/json','X-Cosmas-Desktop-Session':id,'X-Cosmas-Visit-Prep-Contract':'1'}}),auth,
    async(_url,options)=>{assert.equal(options.headers['X-Cosmas-Visit-Prep-Contract'],'1');
      return new Response('{}',{headers:{'Content-Type':'application/json','Cache-Control':'no-store','Set-Cookie':'discard'}});});
  assert.equal(result.status,200);assert.equal(result.headers.get('Referrer-Policy'),'no-referrer');
  assert.equal(result.headers.get('Set-Cookie'),null);
});
