import assert from 'node:assert/strict';
import test from 'node:test';
import {connectorApiRoute,CONNECTOR_HEADERS} from './connector-api-routes.mjs';
import {permittedAuthenticatedApiPath,proxyAuthenticatedWorkspaceRequest as proxy} from './workspace-auth-proxy.mjs';

const id='00000000-0000-4000-8000-000000000001',header='X-Cosmas-Vendor-Setup-Contract';
const commands=['propose_account','propose_recipient','activate','disable','revoke','resolve'];
const routes=[['/vendor-settings','GET',0,131072],[`/vendor-settings/${id}`,'GET',0,32768],[`/vendor-settings/${id}/history`,'GET',0,1048576],...commands.map(kind=>['/vendor-settings/'+kind,'POST',8192,8192])];
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function auth(){let state={phase:'ready',revision:id,identity:{userId:'invented',sessionId:'invented',organizationId:'invented'}};const listeners=new Set();let tokens=0,states=0;return {getState:async()=>{states++;return state;},snapshot:()=>state,getToken:async()=>{tokens++;return 'invented.local.token';},counts:()=>({tokens,states}),subscribe:fn=>{listeners.add(fn);return()=>listeners.delete(fn);},revoke(){state={phase:'signedOut',revision:id,identity:null};for(const fn of listeners)fn(state);}};}
const request=(path,method='GET',extra={},body)=>new Request('app://cosmas/api'+path,{method,headers:{'Content-Type':'application/json','X-Cosmas-Desktop-Session':id,[header]:'1',...extra},...(body===undefined?{}:{body,duplex:'half'})});
const json=(body='{}',status=200,headers={})=>new Response(body,{status,headers:{'Content-Type':'application/json','Cache-Control':'no-store',...headers}});
const sized=n=>'"'+'x'.repeat(n-2)+'"';

test('vendor settings routes match the exact backend methods, family, byte caps and 15-second budget',()=>{
  assert.equal(CONNECTOR_HEADERS.filter(value=>value===header).length,1);
  for(const [path,method,input,output] of routes){assert.deepEqual(connectorApiRoute(path,method),{header,input,output,seconds:15});assert.equal(permittedAuthenticatedApiPath('app://cosmas/api'+path,method),path);}
});

test('rejects unsupported settings methods, identifiers, queries, suffixes and external destinations',()=>{
  for(const [path,allowed] of routes)for(const method of ['GET','POST','PUT','DELETE','PATCH','HEAD','OPTIONS','get'])if(method!==allowed)assert.equal(connectorApiRoute(path,method),null,method+' '+path);
  for(const path of ['/vendor-settings/','/vendor-settings/propose','/vendor-settings/options','/vendor-settings/propose_customer','/vendor-settings/send','/vendor-settings/submit','/vendor-settings/credentials','/vendor-settings/charge','/vendor-settings/'+id+'/activate','/vendor-settings/'+id+'/history/extra','/vendor-settings/not-a-uuid','/vendor-settings/'+id.toUpperCase().replace('000000000001','ABCDEF000001'),'/vendor-settings?cursor=x','/vendor-settings?owner='+id,'/vendor-settings?endpoint=https%3A%2F%2Foutside.invalid','/vendor-settings?','/vendor-settings/activate?x=1','/vendor-settings/activate?x=1&x=2','/vendor-settings/%61ctivate','/vendor-settings//activate','https://outside.invalid/vendor-settings'])for(const method of ['GET','POST'])assert.equal(connectorApiRoute(path,method),null,path);
  for(const url of ['https://outside.invalid/vendor-settings','app://outside/api/vendor-settings','app://name:secret@cosmas/api/vendor-settings','app://cosmas:8000/api/vendor-settings','app://cosmas/api/vendor-settings#fragment'])assert.equal(permittedAuthenticatedApiPath(url,'GET'),null,url);
});

test('requires only the exact negotiated settings family before any native credential access',async()=>{
  for(const wrong of [undefined,'','0','2','1, 1']){const req=request('/vendor-settings');if(wrong===undefined)req.headers.delete(header);else req.headers.set(header,wrong);const session=auth();assert.equal((await proxy(req,session,()=>assert.fail('not dispatched'))).status,426);assert.deepEqual(session.counts(),{tokens:0,states:0});}
  for(const other of CONNECTOR_HEADERS.filter(value=>value!==header)){const session=auth();assert.equal((await proxy(request('/vendor-settings','GET',{[other]:'1'}),session,()=>assert.fail('not dispatched'))).status,426);assert.deepEqual(session.counts(),{tokens:0,states:0});}
  assert.equal((await proxy(request('/provider-team'),auth(),()=>assert.fail('misplaced header'))).status,426);
});

test('forwards exact settings paths and bytes with native credentials, stripping renderer identity and upstream cookies',async()=>{
  for(const [path,method] of routes){let calls=0;const body=method==='POST'?' {"invented":"settings command"} ':undefined;const result=await proxy(request(path,method,{'X-Renderer-Endpoint':'https://outside.invalid'},body),auth(),async(url,options)=>{calls++;assert.equal(url,'http://127.0.0.1:8046'+path);assert.equal(options.method,method);assert.equal(options.headers[header],'1');assert.equal(options.headers.Authorization,'Bearer invented.local.token');assert.equal(options.headers['X-Cosmas-Desktop-Session'],undefined);assert.equal(options.headers['X-Renderer-Endpoint'],undefined);assert.equal(options.headers['X-Cosmas-Vendor-Contract'],undefined);assert.deepEqual(options.body,body===undefined?undefined:new TextEncoder().encode(body));assert.equal(options.redirect,'error');assert.equal(options.credentials,'omit');assert.equal(options.cache,'no-store');return json('{}',200,{'Set-Cookie':'invented=never-forwarded'});});assert.equal(result.status,200);assert.equal(calls,1);assert.equal(result.headers.get('set-cookie'),null);assert.equal(result.headers.get('cache-control'),'no-store');}
});

test('refuses renderer credentials, encoding, binary content and artifact write keys for settings',async()=>{
  for(const forbidden of ['Authorization','X-Box-Id','X-Actor-Principal-Id','Cookie','Content-Encoding']){const session=auth();assert.equal((await proxy(request('/vendor-settings/activate','POST',{[forbidden]:'invented'},'{}'),session,()=>assert.fail('no credentials forwarded'))).status,401);assert.deepEqual(session.counts(),{tokens:0,states:0});}
  assert.equal((await proxy(request('/vendor-settings/activate','POST',{'Content-Type':'application/pdf'},'{}'),auth(),()=>assert.fail('no binary settings'))).status,400);
  assert.equal((await proxy(request('/vendor-settings/activate','POST',{'X-Cosmas-Artifact-Write-Key':'invented-key'},'{}'),auth(),()=>assert.fail('no artifact key'))).status,400);
});

test('enforces the 8KiB request cap before native token acquisition or dispatch',async()=>{
  let calls=0;assert.equal((await proxy(request('/vendor-settings/propose_account','POST',{},sized(8192)),auth(),async()=>{calls++;return json();})).status,200);assert.equal(calls,1);
  const session=auth();assert.equal((await proxy(request('/vendor-settings/propose_account','POST',{},sized(8193)),session,()=>assert.fail('oversized'))).status,503);assert.equal(session.counts().tokens,0);
  assert.equal((await proxy(request('/vendor-settings/propose_recipient','POST',{},'{'),auth(),()=>assert.fail('malformed JSON'))).status,503);
});

test('bounds each settings response before disclosing bytes and preserves required JSON/no-store policy',async()=>{
  for(const [path,method,,maximum] of routes){const body=method==='POST'?'{}':undefined;const good=await proxy(request(path,method,{},body),auth(),async()=>json(sized(maximum)));assert.equal(good.status,200);assert.equal((await good.arrayBuffer()).byteLength,maximum);assert.equal((await proxy(request(path,method,{},body),auth(),async()=>json(sized(maximum+1)))).status,503);}
  assert.equal((await proxy(request('/vendor-settings'),auth(),async()=>json('{}',200,{'Content-Type':'text/html'}))).status,502);
  assert.equal((await proxy(request('/vendor-settings'),auth(),async()=>json('{}',200,{'Cache-Control':'public'}))).status,502);
});

test('a 15-second deadline includes stalled credentials and forbids late dispatch',async t=>{
  t.mock.timers.enable({apis:['setTimeout']});let release;const session=auth();session.getToken=()=>new Promise(resolve=>{release=resolve;});let finished=false,calls=0;
  const pending=proxy(request('/vendor-settings'),session,async()=>{calls++;return json();});void pending.then(()=>{finished=true;});await tick();t.mock.timers.tick(14999);await tick();assert.equal(finished,false);t.mock.timers.tick(1);assert.equal((await pending).status,401);release('invented.local.token');await tick();assert.equal(calls,0);
});

test('the same deadline bounds a stalled request stream before token acquisition',async t=>{
  t.mock.timers.enable({apis:['setTimeout']});const session=auth();let cancelled=0;const body=new ReadableStream({pull(){return new Promise(()=>{});},cancel(){cancelled++;}});
  const pending=proxy(request('/vendor-settings/propose_recipient','POST',{},body),session,()=>assert.fail('no partial body dispatch'));await tick();t.mock.timers.tick(15000);assert.equal((await pending).status,401);assert.equal(session.counts().tokens,0);assert.equal(cancelled,1);
});

test('the same deadline bounds a stalled private response without retries or late disclosure',async t=>{
  t.mock.timers.enable({apis:['setTimeout']});let calls=0,cancelled=0;const body=new ReadableStream({pull(){return new Promise(()=>{});},cancel(){cancelled++;}});
  const pending=proxy(request('/vendor-settings'),auth(),async()=>{calls++;return json(body);});await tick();t.mock.timers.tick(15000);assert.equal((await pending).status,401);assert.equal(calls,1);assert.equal(cancelled,1);
});

test('sign-out while settings bytes are pending prevents private disclosure',async()=>{
  const session=auth();let cancelled=0;const body=new ReadableStream({pull(){return new Promise(()=>{});},cancel(){cancelled++;}});
  const pending=proxy(request(`/vendor-settings/${id}`),session,async()=>json(body));await tick();session.revoke();assert.equal((await pending).status,401);assert.equal(cancelled,1);
});
