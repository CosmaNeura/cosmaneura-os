import assert from 'node:assert/strict';
import test from 'node:test';
import {connectorApiRoute} from './connector-api-routes.mjs';
import {permittedAuthenticatedApiPath,proxyAuthenticatedWorkspaceRequest as proxy} from './workspace-auth-proxy.mjs';
import {fetchLocalAuthenticatedWorkspace as local} from './local-auth-http.mjs';

const id='00000000-0000-4000-8000-000000000001',root=`/workspaces/${id}`;
const ready={phase:'ready',revision:id,identity:{userId:'invented',sessionId:'invented',organizationId:'invented'}};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function auth(){let state=ready;const listeners=new Set();return {getState:async()=>state,snapshot:()=>state,getToken:async()=> 'invented.local.token',subscribe:fn=>{listeners.add(fn);return()=>listeners.delete(fn);},revoke(){state={phase:'signedOut',revision:id,identity:null};for(const fn of listeners)fn(state);}};}
const request=(path,method='GET',headers={},body)=>new Request('app://cosmas/api'+path,{method,headers:{'Content-Type':'application/json','X-Cosmas-Desktop-Session':id,...headers},...(body===undefined?{}:{body,duplex:'half'})});
const json=(body='{}',status=200)=>new Response(body,{status,headers:{'Content-Type':'application/json','Cache-Control':'no-store','Set-Cookie':'must-not-escape'}});
const vendor={'X-Cosmas-Vendor-Contract':'1'};

test('admits only the concrete connector routes and opaque cursor pages',()=>{
  assert.equal(permittedAuthenticatedApiPath('app://cosmas/api'+root+'/vendor-preparations/retire','POST'),root+'/vendor-preparations/retire');
  for(const [path,method] of [[root+'/vendor-preparations/retire','GET'],[root+'/vendor-preparations/retire?owner='+id,'POST'],[root+'/vendor-preparations','POST'],[root+`/vendor-preparations/${id}/retire`,'POST']]) assert.equal(permittedAuthenticatedApiPath('app://cosmas/api'+path,method),null);
  for(const [path,method] of [[root+'/vendor-work/options','GET'],[root+'/vendor-work','POST'],[root+`/vendor-work/${id}/retire`,'POST'],[root+`/vendor-artifacts/${id}/content`,'PUT'],[root+`/vendor-artifacts/${id}/content`,'GET'],[root+'/finance-work/options','GET'],[root+`/finance-work/${id}/submit`,'POST'],['/portal-setup','GET'],['/portal-setup/activate','POST'],[`/practice-work/${id}/result`,'POST']]) assert.equal(permittedAuthenticatedApiPath('app://cosmas/api'+path,method),path);
  const path=root+'/vendor-work?cursor='+encodeURIComponent('opaque:value/+==');
  assert.equal(permittedAuthenticatedApiPath('app://cosmas/api'+path,'GET'),path);
  for(const [path,method] of [[root+'/vendor-work?owner='+id,'GET'],[root+'/vendor-work?cursor=x&cursor=y','GET'],[root+'/vendor-work?cursor=has+space','GET'],[root+'/vendor-work?cursor=x','POST'],[root+'/vendor-work/'+id+'/retire','GET'],[root+'/vendor-artifacts/'+id+'/content','POST'],['/portal-setup/activate','GET'],['/portal-setup?cursor=x','GET'],[root+'/finance-work/'+id+'/charge','POST'],['/vendor-events/spruce/'+id,'POST']]) assert.equal(permittedAuthenticatedApiPath('app://cosmas/api'+path,method),null);
});

test('invited Scheduling connection carries the bounded catalog through its exact route',async()=>{
  const path='/connections/scheduling/session',headers={'X-Cosmas-Scheduling-Login':'1'};
  const payload=JSON.stringify({action:'enrollment_review',padding:'x'.repeat(1400)});
  const result=await proxy(request(path,'POST',headers,payload),auth(),async(_url,options)=>{
    assert.equal(options.body.length,new TextEncoder().encode(payload).length);
    assert.equal(options.headers['X-Cosmas-Scheduling-Login'],'1');return json(JSON.stringify({catalog:'x'.repeat(65000)}));
  });
  assert.equal(result.status,200);assert.equal((await result.json()).catalog.length,65000);
  assert.equal((await proxy(request(path,'POST',headers,'x'.repeat(2049)),auth(),()=>assert.fail('oversized request dispatched'))).status,503);
  assert.equal((await proxy(request(path,'POST',headers,'{}'),auth(),async()=>json('x'.repeat(69633)))).status,503);
});

test('forwards exactly one negotiated family and refuses misplaced headers before credentials',async()=>{
  for(const [path,header] of [[root+'/vendor-work/options','X-Cosmas-Vendor-Contract'],[root+'/finance-work/options','X-Cosmas-Finance-Contract'],['/portal-setup','X-Cosmas-Portal-Contract']]){
    assert.equal((await proxy(request(path),auth(),()=>assert.fail('no upstream'))).status,426);
    let calls=0;const result=await proxy(request(path,'GET',{[header]:'1'}),auth(),async(url,options)=>{calls++;assert.equal(url,'http://127.0.0.1:8046'+path);assert.equal(options.headers[header],'1');assert.equal(options.headers.Authorization,'Bearer invented.local.token');assert.equal(options.headers['X-Cosmas-Desktop-Session'],undefined);return json();});
    assert.equal(result.status,200);assert.equal(calls,1);assert.equal(result.headers.get('set-cookie'),null);
    assert.equal((await proxy(request(path,'GET',{[header]:'1, 1'}),auth(),()=>assert.fail('no upstream'))).status,426);
  }
  assert.equal((await proxy(request('/provider-team','GET',vendor),auth(),()=>assert.fail('no upstream'))).status,426);
  assert.equal((await proxy(request(root+'/vendor-work/options','GET',{...vendor,'X-Cosmas-Finance-Contract':'1'}),auth(),()=>assert.fail('no upstream'))).status,426);
});

test('passes bounded private PDF bytes and exact write key, never through JSON parsing',async()=>{
  const path=root+`/vendor-artifacts/${id}/content`,bytes=new TextEncoder().encode('%PDF-1.7\nInvented private document\n%%EOF');
  const result=await proxy(request(path,'PUT',{...vendor,'Content-Type':'application/pdf','X-Cosmas-Artifact-Write-Key':'invented-pdf-key'},bytes),auth(),async(_url,options)=>{assert.equal(options.method,'PUT');assert.equal(options.headers['Content-Type'],'application/pdf');assert.equal(options.headers['X-Cosmas-Artifact-Write-Key'],'invented-pdf-key');assert.deepEqual(options.body,bytes);return json();});
  assert.equal(result.status,200);
  assert.equal((await proxy(request(path,'PUT',{...vendor,'Content-Type':'application/pdf'},bytes),auth(),()=>assert.fail('no upstream'))).status,400);
  assert.equal((await proxy(request(root+'/vendor-work/options','GET',{...vendor,'X-Cosmas-Artifact-Write-Key':'invented-pdf-key'}),auth(),()=>assert.fail('no upstream'))).status,400);
  const preview=await proxy(request(path,'GET',vendor),auth(),async()=>new Response(bytes,{headers:{'Content-Type':'application/pdf','Cache-Control':'no-store'}}));
  assert.equal(preview.headers.get('Content-Type'),'application/pdf');assert.deepEqual(new Uint8Array(await preview.arrayBuffer()),bytes);
  assert.equal((await proxy(request(path,'GET',vendor),auth(),async()=>json())).status,502);
  assert.equal((await proxy(request(path,'GET',vendor),auth(),async()=>json('{"error":"unavailable"}',409))).status,409);
});

test('enforces JSON and PDF byte ceilings without releasing oversized private content',async()=>{
  for(const [path,limit] of [[root+`/vendor-work/${id}/retire`,4096],[root+'/vendor-preparations/retire',33792]]){
    const body='"'+'x'.repeat(limit-2)+'"';
    assert.equal((await proxy(request(path,'POST',vendor,body),auth(),async()=>json())).status,200);
    assert.equal((await proxy(request(path,'POST',vendor,body+' '),auth(),()=>assert.fail('no upstream'))).status,503);
  }
  assert.equal((await proxy(request(root+'/vendor-work/options','GET',vendor),auth(),async()=>json('x'.repeat(65537)))).status,503);
  const pdf=root+`/vendor-artifacts/${id}/content`,headers={...vendor,'Content-Type':'application/pdf','X-Cosmas-Artifact-Write-Key':'invented-pdf-key'};
  assert.equal((await proxy(request(pdf,'PUT',headers,new Uint8Array(8388609)),auth(),()=>assert.fail('no upstream'))).status,503);
  assert.equal((await proxy(request(pdf,'GET',vendor),auth(),async()=>new Response(new Uint8Array(8388609),{headers:{'Content-Type':'application/pdf','Cache-Control':'no-store'}}))).status,503);
});

test('session loss while a PDF is being read prevents token acquisition and dispatch',async()=>{
  const session=auth();let reads=0,tokens=0;session.getToken=async()=>{tokens++;return 'invented.local.token';};
  const stream=new ReadableStream({pull(){reads++;return new Promise(()=>{});}});
  const pending=proxy(request(root+`/vendor-artifacts/${id}/content`,'PUT',{...vendor,'Content-Type':'application/pdf','X-Cosmas-Artifact-Write-Key':'invented-pdf-key'},stream),session,()=>assert.fail('no upstream'));
  await tick();assert.ok(reads);session.revoke();assert.equal((await pending).status,401);assert.equal(tokens,0);
});

test('connector deadlines include credential acquisition and cannot dispatch after expiry',async t=>{
  t.mock.timers.enable({apis:['setTimeout']});let release;
  const session=auth();session.getToken=()=>new Promise(resolve=>{release=resolve;});
  const pending=proxy(request('/portal-setup','GET',{'X-Cosmas-Portal-Contract':'1'}),session,()=>assert.fail('no late upstream'));
  await tick();t.mock.timers.tick(15000);assert.equal((await pending).status,401);release('invented.local.token');await tick();
});

test('direct socket transport does not allow arbitrary queries, PUT paths or destinations',async()=>{
  const options={method:'PUT',headers:vendor,body:new Uint8Array()};
  for(const url of ['http://127.0.0.1:8046/workspaces','http://127.0.0.1:8046'+root+'/vendor-work?cursor=x','http://localhost:8046'+root+`/vendor-artifacts/${id}/content`]) await assert.rejects(local(url,options,()=>assert.fail('no socket')));
  await assert.rejects(local('http://127.0.0.1:8046'+root+'/vendor-work?owner=x',{method:'GET',headers:vendor},()=>assert.fail('no socket')));
  assert.equal(connectorApiRoute(root+`/vendor-work/${id}/retire`,'POST').input,4096);
});

test('portal actions use their own closed route family and one whole-pipeline deadline',async t=>{
  const headers={'X-Cosmas-Portal-Work-Contract':'1'},path=root+`/portal-work/${id}/submit`;
  for(const [p,method] of [[root+'/portal-work','GET'],[root+'/portal-work','POST'],[root+'/portal-work/resolve','POST'],[root+`/portal-work/${id}`,'GET'],[root+`/portal-work/${id}/observations`,'GET'],[path,'POST']]) assert.equal(permittedAuthenticatedApiPath('app://cosmas/api'+p,method),p);
  for(const [p,method] of [[root+'/portal-work?cursor=x','GET'],[root+'/portal-work/options','GET'],[root+`/portal-work/${id}/submit`,'GET'],[root+`/portal-work/${id}/observations`,'POST'],[root+`/portal-work/${id}/reconcile`,'POST']]) assert.equal(permittedAuthenticatedApiPath('app://cosmas/api'+p,method),null);
  assert.equal((await proxy(request(path,'POST',{'X-Cosmas-Portal-Contract':'1'},'{}'),auth(),()=>assert.fail('wrong family'))).status,426);
  let calls=0;
  const response=await proxy(request(path,'POST',headers,'{}'),auth(),async(_url,options)=>{calls++;assert.equal(options.headers['X-Cosmas-Portal-Work-Contract'],'1');return json();});
  assert.equal(response.status,200);assert.equal(calls,1);
  assert.equal((await proxy(request(path,'POST',headers,' '.repeat(16385)),auth(),()=>assert.fail('oversized'))).status,503);
  t.mock.timers.enable({apis:['setTimeout']});let release;
  const session=auth();session.getToken=()=>new Promise(resolve=>{release=resolve;});
  const pending=proxy(request(path,'POST',headers,'{}'),session,()=>assert.fail('expired portal action'));
  await tick();t.mock.timers.tick(45000);assert.equal((await pending).status,401);release('invented.local.token');await tick();
});
