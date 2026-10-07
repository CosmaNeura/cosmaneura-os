import assert from 'node:assert/strict';
import test from 'node:test';
import {connectorApiRoute} from './connector-api-routes.mjs';
import {permittedAuthenticatedApiPath,proxyAuthenticatedWorkspaceRequest as proxy} from './workspace-auth-proxy.mjs';
const id='00000000-0000-4000-8000-000000000001',header='X-Cosmas-Practice-Access-Contract';
const ready={phase:'ready',revision:id,identity:{userId:'invented',sessionId:'invented',organizationId:'invented'}};
const auth=()=>({getState:async()=>ready,snapshot:()=>ready,getToken:async()=> 'invented.local.token',subscribe:()=>()=>{}});
const request=(path,method='GET',headers={[header]:'1'},body)=>new Request('app://cosmas/api'+path,{method,headers:{'Content-Type':'application/json','X-Cosmas-Desktop-Session':id,...headers},...(body===undefined?{}:{body})});
const json=(body='{}',extra={})=>new Response(body,{headers:{'Content-Type':'application/json','Cache-Control':'no-store',...extra}});
test('admits exact access and quick-setup routes, without general identity administration',async()=>{
  for(const [path,method] of [['/practice-access','GET'],['/practice-access/requests','GET'],['/practice-access/setup','GET'],['/practice-access/setup/complete','POST'],['/practice-access/request','POST'],['/practice-access/cancel','POST'],['/practice-access/decide','POST'],['/practice-access/members','POST'],['/practice-access/member-change','POST']]){
    assert.equal(permittedAuthenticatedApiPath('app://cosmas/api'+path,method),path);
    assert.deepEqual(connectorApiRoute(path,method),{header,input:method==='GET'?0:4096,output:131072,seconds:15,strictResponse:true,errorOutput:2048});
    let calls=0;assert.equal((await proxy(request(path,method,undefined,method==='POST'?'{}':undefined),auth(),async(url,options)=>{
      calls++;assert.equal(url,'http://127.0.0.1:8046'+path);assert.equal(options.headers[header],'1');assert.equal(options.headers.Authorization,'Bearer invented.local.token');return json();
    })).status,200);assert.equal(calls,1);
    assert.equal(permittedAuthenticatedApiPath('app://cosmas/api'+path+'?owner=other',method),null);
    assert.equal(permittedAuthenticatedApiPath('app://cosmas/api'+path,method==='GET'?'POST':'GET'),null);
  }
  for(const path of ['/admin/identities/bind','/practice-access/approve','/practice-access/requests/other','/practice-access/'])assert.equal(permittedAuthenticatedApiPath('app://cosmas/api'+path,'POST'),null);
});
test('rejects missing or misplaced contracts and oversized input before provider transport',async()=>{
  for(const headers of [{},{[header]:'2'},{[header]:'1','X-Cosmas-Inbox-Contract':'1'}])assert.equal((await proxy(request('/practice-access','GET',headers),auth(),()=>assert.fail())).status,426);
  assert.equal((await proxy(request('/provider-team','GET',{[header]:'1'}),auth(),()=>assert.fail())).status,426);
  assert.equal((await proxy(request('/practice-access/decide','POST',undefined,'x'.repeat(4097)),auth(),()=>assert.fail())).status,503);
});
test('withholds oversized, encoded and stale-session results',async()=>{
  for(const [response,status] of [[json('x'.repeat(131073)),503],[json('{}',{'Content-Encoding':'gzip'}),502]])assert.equal((await proxy(request('/practice-access'),auth(),async()=>response)).status,status);
  const session=auth();let current=ready;session.snapshot=()=>current;session.getState=async()=>current;
  assert.equal((await proxy(request('/practice-access'),session,async()=>{current={...ready,phase:'signedOut',identity:null};return json();})).status,401);
});
