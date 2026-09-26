import {test} from 'node:test';
import assert from 'node:assert/strict';
import {connectorApiRoute,CONNECTOR_HEADERS} from './connector-api-routes.mjs';
const id='00000000-0000-4000-8000-000000000051',base='/workspaces/'+id+'/research';
test('research uses only exact same-service methods, header and byte budgets',()=>{
 const read=connectorApiRoute('/research/catalog','GET');assert.deepEqual(read,{header:'X-Cosmas-Research-Contract',input:0,output:131072,seconds:35,strictResponse:true,errorOutput:2048});
 assert.equal(connectorApiRoute(base+'?bot='+id,'GET').output,1048576);
 for(const suffix of ['/search','/resolve','/'+id+'/save','/'+id+'/save/resolve'])assert.deepEqual(connectorApiRoute(base+suffix,'POST'),{...read,input:8192});
 assert.equal(CONNECTOR_HEADERS.filter(h=>h==='X-Cosmas-Research-Contract').length,1);
});
test('research refuses unknown methods, bare bot names, encoded separators, duplicate queries and external hosts',()=>{
 for(const [path,method] of [[base,'GET'],[base+'?bot=research','GET'],[base+'?bot='+id+'&bot='+id,'GET'],[base+'?bot='+id+'&other=1','GET'],[base+'?bot='+id.replace('0051','00af').toUpperCase(),'GET'],[base+'/search?bot='+id,'POST'],[base+'/search','GET'],[base+'/resolve','DELETE'],[base+'/'+id+'/save/more','POST'],['https://pubmed.ncbi.nlm.nih.gov/','GET'],['/research/catalog?x=1','GET'],['/research/catalog','POST'],[base.replace('/research','%2fresearch')+'/search','POST']])assert.equal(connectorApiRoute(path,method),null,method+' '+path);
});
import {permittedAuthenticatedApiPath,proxyAuthenticatedWorkspaceRequest as proxy} from './workspace-auth-proxy.mjs';
const ready={phase:'ready',revision:id,identity:{userId:'invented',sessionId:'invented',organizationId:'invented'}};
const auth=()=>({snapshot:()=>ready,getState:async()=>ready,getToken:async()=> 'invented.research.token',subscribe:()=>()=>{}});
const request=(header='1',body='{}')=>new Request('app://cosmas/api'+base+'/search',{method:'POST',headers:{'Content-Type':'application/json','X-Cosmas-Desktop-Session':id,'X-Cosmas-Research-Contract':header},body});
test('actual desktop proxy preserves fixed local destination and requires Research negotiation before credentials',async()=>{
 for(const header of ['','2','1, 1'])assert.equal((await proxy(request(header),{...auth(),getToken:()=>assert.fail('no credential')},()=>assert.fail('no dispatch'))).status,426);
 assert.equal(permittedAuthenticatedApiPath('app://cosmas/api'+base+'?bot='+id,'GET'),base+'?bot='+id);
 for(const bad of [base+'?bot='+id+'&bot='+id,base+'?bot='+id+'&other=1',base+'?bot=%30'+id.slice(1),base+'?bot='+id+'#x',base.replace('/research','/other/../research')+'?bot='+id])assert.equal(permittedAuthenticatedApiPath('app://cosmas/api'+bad,'GET'),null);
 let calls=0;const result=await proxy(request(),auth(),async(url,options)=>{calls++;assert.equal(url,'http://127.0.0.1:8046'+base+'/search');assert.equal(options.headers['X-Cosmas-Research-Contract'],'1');assert.equal(options.headers.Authorization,'Bearer invented.research.token');assert.equal(options.headers['X-Cosmas-Desktop-Session'],undefined);assert.equal(options.redirect,'error');return new Response('{}',{headers:{'Content-Type':'application/json','Cache-Control':'no-store','Set-Cookie':'never-forward'}});});
 assert.equal(result.status,200);assert.equal(calls,1);assert.equal(result.headers.get('set-cookie'),null);
});
test('actual proxy applies new request/response caps before forwarding excess Research data',async()=>{
 assert.equal((await proxy(request('1','x'.repeat(8193)),auth(),()=>assert.fail('no dispatch'))).status,503);
 assert.equal((await proxy(request(),auth(),async()=>new Response('x'.repeat(131073),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}))).status,503);
});
test('older history and saved packets retain exact GET query and separate byte bounds',async()=>{
 for(const suffix of ['', '/saved']){
  const path=base+suffix+'?bot='+id+'&before='+id,route=connectorApiRoute(path,'GET');
  assert.equal(route.input,0);assert.equal(route.output,suffix?131072:1048576);assert.equal(route.header,'X-Cosmas-Research-Contract');
  assert.equal(permittedAuthenticatedApiPath('app://cosmas/api'+path,'GET'),path);
  for(const query of ['?before='+id+'&bot='+id,'?bot='+id+'&before='+id+'&before='+id,'?bot='+id+'&before=','?bot='+id+'&before=research','?bot='+id+'&before=%30'+id.slice(1)])assert.equal(connectorApiRoute(base+suffix+query,'GET'),null);
  assert.equal(connectorApiRoute(path,'POST'),null);
 }
 let calls=0;const path=base+'/saved?bot='+id+'&before='+id;
 const result=await proxy(new Request('app://cosmas/api'+path,{headers:{'Content-Type':'application/json','X-Cosmas-Desktop-Session':id,'X-Cosmas-Research-Contract':'1'}}),auth(),async(url,options)=>{calls++;assert.equal(url,'http://127.0.0.1:8046'+path);assert.equal(options.method,'GET');assert.equal(options.body,undefined);return new Response('{}',{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});});
 assert.equal(result.status,200);assert.equal(calls,1);
});
