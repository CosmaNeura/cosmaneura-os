import assert from 'node:assert/strict';
import test from 'node:test';
import {connectorApiRoute} from './connector-api-routes.mjs';
import {proxyAuthenticatedWorkspaceRequest as proxy} from './workspace-auth-proxy.mjs';
const id='00000000-0000-4000-8000-000000000001';
const state={phase:'ready',revision:id,identity:{userId:'invented',sessionId:'invented',organizationId:'invented'}};
const auth=()=>({getState:async()=>state,snapshot:()=>state,getToken:async()=>'invented.local.token',subscribe:()=>()=>{}});
const request=(path,value)=>new Request('app://cosmas/api'+path,{headers:{'Content-Type':'application/json','X-Cosmas-Desktop-Session':id,'X-Cosmas-Connection-Contract':value}});
const json=content=>new Response(content,{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
test('catalog alone accepts exact v2, forwards it and retains v1',async()=>{
  for(const version of ['1','2']){
    const result=await proxy(request('/connections/catalog',version),auth(),async(_url,options)=>{
      assert.equal(options.headers['X-Cosmas-Connection-Contract'],version);return json(JSON.stringify({padding:'x'.repeat(version==='2'?5000:100)}));});
    assert.equal(result.status,200);assert.equal((await result.json()).padding.length,version==='2'?5000:100);
  }
  for(const [path,value] of [['/connections/plugins','2'],['/connections/catalog','2, 2'],['/connections/catalog','3'],['/connections/catalog?provider=x','2']])
    assert.notEqual((await proxy(request(path,value),auth(),()=>assert.fail('invalid negotiation dispatched'))).status,200);
});
test('v2 catalog stays within the dedicated response byte budget',async()=>{
  assert.equal(connectorApiRoute('/connections/catalog','GET').output,32768);
  const result=await proxy(request('/connections/catalog','2'),auth(),async()=>json('x'.repeat(32769)));
  assert.equal(result.status,503);
});
