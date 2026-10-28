import assert from 'node:assert/strict';
import test from 'node:test';
import {exactHostedOrigin, resolveHostedWorkspace, permittedHostedWorkspace} from './hosted-workspace-config.mjs';

const base = {VITE_COSMAS_ENV:'early_adopter_beta',VITE_WORKSPACE_ENABLED:'true',VITE_WORKSPACE_AUTHENTICATED_ENABLED:'true',
  VITE_WORKSPACE_HOSTED_ENABLED:'true',VITE_WORKSPACE_HOSTED_CLIENT:'web',VITE_WORKSPACE_DATA_MODE:'synthetic',
  VITE_API_BASE:'https://api.example.invalid',VITE_WORKSPACE_HOSTED_API_ORIGIN:'https://api.example.invalid',
  VITE_WORKSPACE_WEB_ORIGIN:'https://workspace.example.invalid'};

test('a hosted browser is bound to its API and page before credentials', () => {
  const config=resolveHostedWorkspace(base); assert.ok(config);
  assert.equal(permittedHostedWorkspace(config,base.VITE_API_BASE,'https://workspace.example.invalid/visit',true),true);
  for(const [api,page] of [['https://other.example.invalid','https://workspace.example.invalid'],
    [base.VITE_API_BASE,'https://unrelated.example.invalid'],[base.VITE_API_BASE,'http://localhost:5173'],
    [base.VITE_API_BASE,'https://user@workspace.example.invalid']]) assert.equal(permittedHostedWorkspace(config,api,page,true),false);
});

test('native profiles select their own auth and transport without local fallback', () => {
  for(const client of ['apple','desktop']) {
    const env={...base,VITE_WORKSPACE_HOSTED_CLIENT:client,VITE_WORKSPACE_WEB_ORIGIN:'',
      VITE_WORKSPACE_NATIVE_AUTH_ENABLED:client==='apple'?'true':'false',VITE_WORKSPACE_DESKTOP_AUTH_ENABLED:client==='desktop'?'true':'false',
      VITE_API_BASE:client==='desktop'?'app://cosmas/api':base.VITE_API_BASE};
    const config=resolveHostedWorkspace(env);assert.ok(config);
    assert.equal(permittedHostedWorkspace(config,env.VITE_API_BASE,client==='desktop'?'app://cosmas/index.html':'capacitor://localhost/index.html'),true);
    if(client==='desktop') assert.equal(permittedHostedWorkspace(config,env.VITE_API_BASE,'app://cosmas/index.html',true),false);
    assert.equal(resolveHostedWorkspace({...env,VITE_DESKTOP_SYNTHETIC_ENABLED:'true'}),null);
    assert.equal(resolveHostedWorkspace({...env,VITE_WORKSPACE_DATA_MODE:'authorized_beta'}).dataMode,'authorized_beta');
  }
});

test('an incomplete or unpinned hosted build fails closed', () => {
  for(const key of ['VITE_COSMAS_ENV','VITE_WORKSPACE_ENABLED','VITE_WORKSPACE_AUTHENTICATED_ENABLED',
    'VITE_WORKSPACE_HOSTED_ENABLED','VITE_WORKSPACE_HOSTED_API_ORIGIN','VITE_WORKSPACE_WEB_ORIGIN','VITE_WORKSPACE_HOSTED_CLIENT','VITE_WORKSPACE_DATA_MODE'])
    assert.equal(resolveHostedWorkspace({...base,[key]:''}),null,key);
  for(const origin of ['http://api.example.invalid','https://api.example.invalid/','https://api.example.invalid:443',
    'https://127.0.0.1','https://api.localhost','https://user:secret@api.example.invalid','https://api.example.invalid/a',
    'https://api.example.invalid?q=1','https://api.example.invalid#x','https://API.example.invalid','https://api.example.invalid:444'])
    assert.equal(exactHostedOrigin(origin),false,origin);
});

test('desktop hash navigation retains only the exact packaged document and proxy transport', () => {
  const env={...base,VITE_WORKSPACE_HOSTED_CLIENT:'desktop',VITE_WORKSPACE_WEB_ORIGIN:'',
    VITE_WORKSPACE_NATIVE_AUTH_ENABLED:'false',VITE_WORKSPACE_DESKTOP_AUTH_ENABLED:'true',VITE_API_BASE:'app://cosmas/api'};
  const config=resolveHostedWorkspace(env);assert.ok(config);
  for(const fragment of ['#cosmas/home','#cosmas/messages/chief?details=1']) {
    const page='app://cosmas/index.html'+fragment;
    assert.equal(permittedHostedWorkspace(config,env.VITE_API_BASE,page),true);
    assert.equal(permittedHostedWorkspace(config,env.VITE_API_BASE,page,true),false);
    assert.equal(permittedHostedWorkspace(config,base.VITE_API_BASE,page),false);
  }
  for(const page of ['app://cosmas/index.html?redirect=1#cosmas/home','app://cosmas/other.html#cosmas/home',
    'app://user@cosmas/index.html#cosmas/home','app://cosmas:80/index.html#cosmas/home',
    'app://cosmas/a/../index.html#cosmas/home','app://cosmas/%69ndex.html#cosmas/home',
    'app://COSMAS/index.html#cosmas/home','https://cosmas/index.html#cosmas/home'])
    assert.equal(permittedHostedWorkspace(config,env.VITE_API_BASE,page),false,page);
});
