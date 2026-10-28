import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import {proxyAuthenticatedWorkspaceRequest as proxy} from './workspace-auth-proxy.mjs';

const revision='00000000-0000-4000-8000-000000000084';
const ready={phase:'ready',revision,identity:{userId:'invented',sessionId:'invented',organizationId:'invented'}};
const teamRoutes=[['/provider-team','GET'],['/provider-team','POST'],['/provider-team/setup','GET'],
  ['/provider-team/rehearsal','POST'],['/provider-team/resources','GET'],['/provider-team/usage','GET']];
const renderer=await readFile(new URL('../../web/src/workspace-api.ts',import.meta.url),'utf8');
const rendererVersion=renderer.match(/headers\.set\("X-Cosmas-Team-Contract","([0-9]+)"\)/)?.[1];
const request=(path,method='GET',version=rendererVersion,extra={})=>new Request('app://cosmas/api'+path,{
  method,headers:{'Content-Type':'application/json','X-Cosmas-Desktop-Session':revision,
    'X-Cosmas-Workspace-Protocol':'1','X-Cosmas-Team-Contract':version,...extra},...(method==='POST'?{body:'{}'}:{})});
const response=(body='{}')=>new Response(body,{headers:{'Content-Type':'application/json','Cache-Control':'no-store','X-Cosmas-Workspace-Protocol':'1','Content-Length':String(Buffer.byteLength(body))}});
const session=()=>({getState:async()=>ready,snapshot:()=>ready,getToken:async()=> 'invented.local.token',subscribe:()=>()=>{}});
const noAuthority={getState:()=>assert.fail('Admission must precede state acquisition'),getToken:()=>assert.fail('Admission must precede token acquisition'),subscribe:()=>assert.fail('Admission must precede subscription')};

test('the actual renderer team generation reaches only the existing six team route/method pairs',async()=>{
  assert.equal(rendererVersion,'5');
  for(const [path,method] of teamRoutes){
    let calls=0;
    const result=await proxy(request(path,method),session(),async(url,options)=>{
      calls++;assert.equal(url,'http://127.0.0.1:8046'+path);assert.equal(options.method,method);
      assert.equal(options.headers['X-Cosmas-Team-Contract'],'5');assert.equal(options.headers['X-Cosmas-Workspace-Protocol'],'1');
      assert.equal(options.headers.Authorization,'Bearer invented.local.token');
      assert.equal(options.credentials,'omit');assert.equal(options.redirect,'error');
      if(method==='POST')assert.equal(new TextDecoder().decode(options.body),'{}');
      else assert.equal(options.body,undefined);
      return response();
    });
    assert.equal(result.status,200,path);assert.equal(calls,1,path);
  }
});

test('unknown or combined team generations and wrong routes fail before native authority',async()=>{
  for(const [path,method] of teamRoutes){
    for(const version of ['6','5, 5','4, 5','']){
      assert.equal((await proxy(request(path,method,version),noAuthority,()=>assert.fail('No dispatch'))).status,426);
    }
  }
  for(const path of ['/workspaces','/practice-access']){
    const extra=path==='/practice-access'?{'X-Cosmas-Practice-Access-Contract':'1'}:{};
    assert.equal((await proxy(request(path,'GET','5',extra),noAuthority,()=>assert.fail('No dispatch'))).status,426);
  }
  for(const [path,method] of [['/provider-team/setup','POST'],['/provider-team/rehearsal','GET'],['/provider-team/resources','POST'],['/provider-team/usage','POST']]){
    assert.equal((await proxy(request(path,method,'5'),noAuthority,()=>assert.fail('No dispatch'))).status,404);
  }
});

test('identity and activity retain their exact generation two negotiation',async()=>{
  for(const path of ['/provider-team/identity','/provider-team/activity/attention']){
    const extra={'X-Cosmas-Draft-Recovery':'2',...(path.includes('/activity/')?{'X-Cosmas-Activity-Contract':'2'}:{})};
    assert.equal((await proxy(request(path,'GET','5',extra),noAuthority,()=>assert.fail('No dispatch'))).status,426);
    const result=await proxy(request(path,'GET','2',extra),session(),async(_url,options)=>{
      assert.equal(options.headers['X-Cosmas-Team-Contract'],'2');return response();
    });
    assert.equal(result.status,200);
  }
});

test('generation five retains resource byte bounds and the post-response session fence',async()=>{
  assert.equal((await proxy(request('/provider-team/resources'),session(),async()=>response('x'.repeat(16385)))).status,503);
  let current=ready;const auth={...session(),getState:async()=>current,snapshot:()=>current};
  const result=await proxy(request('/provider-team'),auth,async()=>{current={...ready,phase:'signedOut',identity:null};return response();});
  assert.equal(result.status,401);
});
