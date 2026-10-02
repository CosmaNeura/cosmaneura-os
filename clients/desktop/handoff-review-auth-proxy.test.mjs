import assert from 'node:assert/strict';
import test from 'node:test';
import {permittedAuthenticatedApiPath,proxyAuthenticatedWorkspaceRequest} from './workspace-auth-proxy.mjs';
import {proxyWorkspaceRequest} from './api-proxy.mjs';
const id='00000000-0000-4000-8000-000000000001';
const ready={phase:'ready',revision:id,identity:{userId:'invented',sessionId:'invented',organizationId:'invented'}};
const auth=()=>({getState:async()=>ready,snapshot:()=>ready,getToken:async()=> 'invented.synthetic.token',subscribe:()=>()=>{}});
const path=action=>`/workspaces/${id}/handoffs/${id}/${action}`;
const request=(action,headers={},body='{}')=>new Request('app://cosmas/api'+path(action),{method:'POST',body,headers:{'Content-Type':'application/json','X-Cosmas-Desktop-Session':id,'X-Cosmas-Model-Contract':'1','X-Cosmas-Handoff-Review':'1',...headers}});
for(const action of ['review','revision']) {
 test(`native ${action} forwards only exact negotiated route and fresh token`,async()=>{
  assert.equal(permittedAuthenticatedApiPath('app://cosmas/api'+path(action),'POST'),path(action));
  for(const suffix of ['?owner='+id,'/send','/execute','#fragment'])assert.equal(permittedAuthenticatedApiPath('app://cosmas/api'+path(action)+suffix,'POST'),null);
  assert.equal(permittedAuthenticatedApiPath('app://cosmas/api'+path(action),'GET'),null);
  const response=await proxyAuthenticatedWorkspaceRequest(request(action),auth(),async(url,options)=>{
   assert.equal(url,'http://127.0.0.1:8046'+path(action));
   assert.equal(options.headers['X-Cosmas-Handoff-Review'],'1');assert.equal(options.headers['X-Cosmas-Model-Contract'],'1');
   assert.equal(options.headers.Authorization,'Bearer invented.synthetic.token');
   return Response.json({workspace:{text:'x'.repeat(20000)}},{headers:{'Cache-Control':'no-store'}});
  });assert.equal(response.status,200);
 });
 test(`native ${action} refuses incompatible contracts before credentials`,async()=>{
  for(const headers of [{'X-Cosmas-Handoff-Review':'2'},{'X-Cosmas-Model-Contract':'2'}]){
   const response=await proxyAuthenticatedWorkspaceRequest(request(action,headers),auth(),()=>assert.fail('no upstream'));
   assert.equal(response.status,426);
  }
  const response=await proxyAuthenticatedWorkspaceRequest(request(action,{},'x'.repeat(12289)),auth(),()=>assert.fail('no oversized upstream'));
  assert.equal(response.status,503);
 });
 test(`synthetic desktop ${action} retains review contract`,async()=>{
  const response=await proxyWorkspaceRequest(new Request('app://cosmas/api'+path(action),{method:'POST',body:'{}',headers:{'Content-Type':'application/json','X-Box-Id':id,'X-Actor-Principal-Id':id,'X-Cosmas-Model-Contract':'1','X-Cosmas-Handoff-Review':'1'}}),async(_url,options)=>{
   assert.equal(options.headers.get('X-Cosmas-Handoff-Review'),'1');assert.equal(options.headers.get('X-Cosmas-Model-Contract'),'1');
   return Response.json({ok:true});
  });assert.equal(response.status,200);
 });
}
test('review header cannot be attached to arbitrary commands',async()=>{
 const response=await proxyAuthenticatedWorkspaceRequest(new Request('app://cosmas/api/provider-team',{headers:{'Content-Type':'application/json','X-Cosmas-Desktop-Session':id,'X-Cosmas-Handoff-Review':'1'}}),auth(),()=>assert.fail('no upstream'));
 assert.equal(response.status,426);
});
