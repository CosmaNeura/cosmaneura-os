import assert from 'node:assert/strict';
import test from 'node:test';
import {connectorApiRoute,CONNECTOR_HEADERS} from './connector-api-routes.mjs';
import {permittedAuthenticatedApiPath,proxyAuthenticatedWorkspaceRequest as proxy} from './workspace-auth-proxy.mjs';

const id='00000000-0000-4000-8000-000000000001',header='X-Cosmas-Membership-Contract';
const base=`/workspaces/${id}/membership-work`,path=base+`/${id}/results/${id}/finance-evidence`;
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const request=(target=path,extra={},signal,method='GET')=>new Request('app://cosmas/api'+target,{method,headers:{'Content-Type':'application/json','X-Cosmas-Desktop-Session':id,[header]:'1',...extra},signal});
const json=(body='{}',extra={})=>new Response(body,{headers:{'Content-Type':'application/json','Cache-Control':'no-store',...extra}});
const sized=n=>'"'+'x'.repeat(n-2)+'"';
function auth(){let state={phase:'ready',revision:id,identity:{userId:'invented',sessionId:'invented',organizationId:'invented'}},tokens=0,states=0;const listeners=new Set();return {getState:async()=>{states++;return state;},snapshot:()=>state,getToken:async()=>{tokens++;return 'invented.local.token';},counts:()=>({tokens,states}),subscribe:fn=>{listeners.add(fn);return()=>listeners.delete(fn);},revoke(){state={phase:'signedOut',revision:id,identity:null};for(const fn of listeners)fn(state);}};}

test('saved finance evidence admits only exact GET with no input, 64 KiB output and 15-second deadline',()=>{
 assert.deepEqual(connectorApiRoute(path,'GET'),{header,input:0,output:65536,seconds:15});assert.equal(permittedAuthenticatedApiPath('app://cosmas/api'+path,'GET'),path);assert.equal(CONNECTOR_HEADERS.filter(v=>v===header).length,1);
 assert.deepEqual(connectorApiRoute(base+'/retire','POST'),{header,input:16384,output:8192,seconds:15});assert.deepEqual(connectorApiRoute(base+'/'+id,'GET'),{header,input:0,output:32768,seconds:15});
});
test('new route denies commands, query selection, malformed IDs, aliases and alternate origins',()=>{
 for(const method of ['POST','PUT','PATCH','DELETE','HEAD','OPTIONS','get'])assert.equal(connectorApiRoute(path,method),null,method);
 for(const target of [path+'/',path+'/extra',path+'?',path+'?finance_ticket='+id,path+'?cursor=x',path.replace('/results/','/result/'),path.replace('/finance-evidence','/pdf'),path.replace('/results/'+id,'/results'),path.replace(id,'INVALID'),path.replace(id,id.toUpperCase().replace('00000000','ABCDEF00')),path.replace('/results/','/%72esults/'),base+'/results/'+id+'/finance-evidence'])assert.equal(connectorApiRoute(target,'GET'),null,target);
 for(const target of ['https://outside.invalid'+path,'app://other/api'+path,'app://user@cosmas/api'+path,'app://cosmas:8046/api'+path,'app://cosmas/api'+path+'#fragment'])assert.equal(permittedAuthenticatedApiPath(target,'GET'),null,target);
});
test('only exact membership negotiation reaches native credentials',async()=>{
 for(const value of [undefined,'','0','2','1, 1']){const r=request();if(value===undefined)r.headers.delete(header);else r.headers.set(header,value);const session=auth();assert.equal((await proxy(r,session,()=>assert.fail('no request'))).status,426);assert.deepEqual(session.counts(),{tokens:0,states:0});}
 for(const other of CONNECTOR_HEADERS.filter(v=>v!==header)){const session=auth();assert.equal((await proxy(request(path,{[other]:'1'}),session,()=>assert.fail('mixed family'))).status,426);assert.equal(session.counts().tokens,0);}
});
test('GET uses fresh native authority and the fixed OS target with no body or renderer headers',async()=>{
 let calls=0;const result=await proxy(request(path,{'X-Renderer-Endpoint':'https://outside.invalid'}),auth(),async(url,options)=>{calls++;assert.equal(url,'http://127.0.0.1:8046'+path);assert.equal(options.method,'GET');assert.equal(options.body,undefined);assert.equal(options.headers[header],'1');assert.equal(options.headers.Authorization,'Bearer invented.local.token');assert.equal(options.headers['X-Cosmas-Desktop-Session'],undefined);assert.equal(options.headers['X-Renderer-Endpoint'],undefined);assert.equal(options.redirect,'error');assert.equal(options.credentials,'omit');return json('{}',{'Set-Cookie':'invented=withheld'});});
 assert.equal(result.status,200);assert.equal(calls,1);assert.equal(result.headers.get('set-cookie'),null);
});
test('64 KiB is an exact UTF-8 response cap; public and HTML responses fail closed',async()=>{
 for(const body of [sized(65536),'"'+'é'.repeat(32767)+'"']){const r=await proxy(request(),auth(),async()=>json(body));assert.equal(r.status,200);assert.equal((await r.arrayBuffer()).byteLength,65536);}
 for(const body of [sized(65537),'"'+'é'.repeat(32768)+'"'])assert.equal((await proxy(request(),auth(),async()=>json(body))).status,503);
 // Existing connector GET transport preserves bytes; the shared membership validator parses closed JSON.
 assert.equal(await (await proxy(request(),auth(),async()=>json('{'))).text(),'{');
 for(const extra of [{'Content-Type':'text/html'},{'Cache-Control':'public'}])assert.equal((await proxy(request(),auth(),async()=>json('{}',extra))).status,502);
});
test('renderer credentials and artifact authority are rejected before credential or socket access',async()=>{
 for(const name of ['Authorization','Cookie','X-Box-Id','X-Actor-Principal-Id','Content-Encoding']){const session=auth();assert.equal((await proxy(request(path,{[name]:'invented'}),session,()=>assert.fail('renderer authority'))).status,401);assert.deepEqual(session.counts(),{tokens:0,states:0});}
 assert.equal((await proxy(request(path,{'X-Cosmas-Artifact-Write-Key':'invented-key'}),auth(),()=>assert.fail('not an upload'))).status,400);
});
test('unchanged 15-second budget includes held native credentials and withholds their late result',async t=>{
 t.mock.timers.enable({apis:['setTimeout']});let release,calls=0;const session=auth();session.getToken=()=>new Promise(resolve=>{release=resolve;});const pending=proxy(request(),session,async()=>{calls++;return json();});await tick();t.mock.timers.tick(15000);assert.equal((await pending).status,401);release('invented.local.token');await tick();assert.equal(calls,0);
});
test('deadline and sign-out discard held evidence streams without partial disclosure or retry',async t=>{
 t.mock.timers.enable({apis:['setTimeout']});let cancelled=0,calls=0;const stream=()=>new ReadableStream({pull(){return new Promise(()=>{});},cancel(){cancelled++;}});
 let pending=proxy(request(),auth(),async()=>{calls++;return json(stream());});await tick();t.mock.timers.tick(15000);assert.equal((await pending).status,401);assert.equal(cancelled,1);assert.equal(calls,1);
 const session=auth();pending=proxy(request(),session,async()=>{calls++;return json(stream());});await tick();session.revoke();assert.equal((await pending).status,401);assert.equal(cancelled,2);assert.equal(calls,2);
});
