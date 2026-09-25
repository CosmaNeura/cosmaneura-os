import assert from 'node:assert/strict';
import test from 'node:test';
import {connectorApiRoute,CONNECTOR_HEADERS} from './connector-api-routes.mjs';
import {permittedAuthenticatedApiPath,proxyAuthenticatedWorkspaceRequest as proxy} from './workspace-auth-proxy.mjs';

const id='00000000-0000-4000-8000-000000000001',header='X-Cosmas-Membership-Contract';
const base=`/workspaces/${id}/membership-work`,path=base+'/retire',tick=()=>new Promise(resolve=>setImmediate(resolve));
const request=(target=path,body='{}',extra={},signal)=>new Request('app://cosmas/api'+target,{method:'POST',headers:{'Content-Type':'application/json','X-Cosmas-Desktop-Session':id,[header]:'1',...extra},body,duplex:'half',signal});
const json=(body='{}',extra={})=>new Response(body,{headers:{'Content-Type':'application/json','Cache-Control':'no-store',...extra}});
const sized=n=>'"'+'x'.repeat(n-2)+'"';
function auth(){
  let state={phase:'ready',revision:id,identity:{userId:'invented',sessionId:'invented',organizationId:'invented'}},tokens=0,states=0;
  const listeners=new Set();
  return {getState:async()=>{states++;return state;},snapshot:()=>state,getToken:async()=>{tokens++;return 'invented.local.token';},counts:()=>({tokens,states}),subscribe:fn=>{listeners.add(fn);return()=>listeners.delete(fn);},revoke(){state={phase:'signedOut',revision:id,identity:null};for(const fn of listeners)fn(state);}};
}

test('only the root retirement POST gains a 16KiB wrapper budget, with existing membership negotiation and 15s deadline',()=>{
  assert.deepEqual(connectorApiRoute(path,'POST'),{header,input:16384,output:8192,seconds:15});
  assert.equal(permittedAuthenticatedApiPath('app://cosmas/api'+path,'POST'),path);
  assert.equal(CONNECTOR_HEADERS.filter(v=>v===header).length,1);
  for(const target of [base,base+'/resolve',base+'/'+id+'/decide',base+'/'+id+'/result',base+'/'+id+'/verify',base+'/'+id+'/withdraw'])
    assert.deepEqual(connectorApiRoute(target,'POST'),{header,input:8192,output:8192,seconds:15});
});

test('retirement denies other methods, ticket-addressed actions, malformed IDs, query data and alternate destinations',()=>{
  for(const method of ['GET','PUT','PATCH','DELETE','HEAD','OPTIONS','post'])assert.equal(connectorApiRoute(path,method),null,method);
  for(const target of [path+'/',path+'/extra',path+'?',path+'?cursor=x',path+'?owner='+id,base+'/'+id+'/retire',base+'/retire/'+id,base+'/retirement',base+'/%72etire',base+'//retire',path.replace(id,'ABCDEF00-0000-4000-8000-000000000001'),path.replace(id,'invalid')]){
    assert.equal(connectorApiRoute(target,'POST'),null,target);
  }
  for(const target of ['https://outside.invalid'+path,'app://other/api'+path,'app://user@cosmas/api'+path,'app://cosmas:8046/api'+path,'app://cosmas/api'+path+'#fragment'])assert.equal(permittedAuthenticatedApiPath(target,'POST'),null,target);
});

test('retirement negotiates only its exact family before any native credentials are read',async()=>{
  for(const value of [undefined,'','0','2','1, 1']){
    const req=request();if(value===undefined)req.headers.delete(header);else req.headers.set(header,value);
    const session=auth();assert.equal((await proxy(req,session,()=>assert.fail('no dispatch'))).status,426);assert.deepEqual(session.counts(),{tokens:0,states:0});
  }
  for(const other of CONNECTOR_HEADERS.filter(v=>v!==header)){
    const session=auth();assert.equal((await proxy(request(path,'{}',{[other]:'1'}),session,()=>assert.fail('no mixed family'))).status,426);assert.equal(session.counts().tokens,0);
  }
});

test('wrapper bytes use fresh native credentials and fixed destination without renderer authority or cookies',async()=>{
  const body=' {"command_kind":"verify","request":{"invented":"transport-only"},"request_sha256":"'+'a'.repeat(64)+'"} ';
  let calls=0;const response=await proxy(request(path,body,{'X-Renderer-Endpoint':'https://outside.invalid'}),auth(),async(url,options)=>{
    calls++;assert.equal(url,'http://127.0.0.1:8046'+path);assert.equal(options.method,'POST');assert.deepEqual(options.body,new TextEncoder().encode(body));
    assert.equal(options.headers[header],'1');assert.equal(options.headers.Authorization,'Bearer invented.local.token');assert.equal(options.headers['X-Renderer-Endpoint'],undefined);assert.equal(options.headers['X-Cosmas-Desktop-Session'],undefined);
    assert.equal(options.credentials,'omit');assert.equal(options.redirect,'error');assert.equal(options.cache,'no-store');return json('{}',{'Set-Cookie':'invented=withheld'});
  });
  assert.equal(response.status,200);assert.equal(calls,1);assert.equal(response.headers.get('set-cookie'),null);
});

test('16KiB retirement wrapper is exact in UTF-8 bytes; existing original commands remain capped at 8 KiB',async()=>{
  for(const body of [sized(16384),'"'+'é'.repeat(8191)+'"'])assert.equal((await proxy(request(path,body),auth(),async()=>json())).status,200);
  for(const body of [sized(16385),'"'+'é'.repeat(8192)+'"','{']){
    const session=auth();assert.equal((await proxy(request(path,body),session,()=>assert.fail('oversize or malformed'))).status,503);assert.equal(session.counts().tokens,0);
  }
  for(const target of [base,base+'/resolve',base+'/'+id+'/verify'])assert.equal((await proxy(request(target,sized(8193)),auth(),()=>assert.fail('original cap unchanged'))).status,503);
});

test('response never exceeds 8 KiB or admits HTML/public caching and renderer credentials remain denied',async()=>{
  const response=await proxy(request(),auth(),async()=>json(sized(8192)));assert.equal(response.status,200);assert.equal((await response.arrayBuffer()).byteLength,8192);
  assert.equal((await proxy(request(),auth(),async()=>json(sized(8193)))).status,503);
  for(const extra of [{'Content-Type':'text/html'},{'Cache-Control':'public'}])assert.equal((await proxy(request(),auth(),async()=>json('{}',extra))).status,502);
  for(const name of ['Authorization','Cookie','X-Box-Id','X-Actor-Principal-Id','Content-Encoding']){
    const session=auth();assert.equal((await proxy(request(path,'{}',{[name]:'invented'}),session,()=>assert.fail('renderer authority'))).status,401);assert.deepEqual(session.counts(),{tokens:0,states:0});
  }
  assert.equal((await proxy(request(path,'{}',{'Content-Type':'application/pdf'}),auth(),()=>assert.fail('JSON only'))).status,400);
  assert.equal((await proxy(request(path,'{}',{'X-Cosmas-Artifact-Write-Key':'invented-key'}),auth(),()=>assert.fail('no artifact key'))).status,400);
});

test('15-second whole-request deadline includes stalled credentials and never dispatches their late result',async t=>{
  t.mock.timers.enable({apis:['setTimeout']});let release,calls=0;const session=auth();session.getToken=()=>new Promise(resolve=>{release=resolve;});
  const pending=proxy(request(),session,async()=>{calls++;return json();});await tick();t.mock.timers.tick(15000);assert.equal((await pending).status,401);
  release('invented.local.token');await tick();assert.equal(calls,0);
});

test('stalled wrapper and response streams are cancelled within the same deadline without partial dispatch or disclosure',async t=>{
  t.mock.timers.enable({apis:['setTimeout']});let cancelled=0;const stream=()=>new ReadableStream({pull(){return new Promise(()=>{});},cancel(){cancelled++;}});
  const session=auth();let pending=proxy(request(path,stream()),session,()=>assert.fail('no partial wrapper'));await tick();t.mock.timers.tick(15000);assert.equal((await pending).status,401);assert.equal(session.counts().tokens,0);assert.equal(cancelled,1);
  pending=proxy(request(),auth(),async()=>json(stream()));await tick();t.mock.timers.tick(15000);assert.equal((await pending).status,401);assert.equal(cancelled,2);
});

test('sign-out withholds a pending retirement receipt without retry',async()=>{
  const session=auth();let cancelled=0,calls=0;const body=new ReadableStream({pull(){return new Promise(()=>{});},cancel(){cancelled++;}});
  const pending=proxy(request(),session,async()=>{calls++;return json(body);});await tick();session.revoke();assert.equal((await pending).status,401);assert.equal(cancelled,1);assert.equal(calls,1);
});
