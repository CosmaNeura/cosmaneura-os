import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, readFile, writeFile, realpath, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {validateOperationalNativeIdentity, validateOperationalNativeDataMode, operationalNativeAuthSettings, operationalNativeBundle} from './native-identity-config.mjs';
import {prepareDesktopState} from './installation-state.mjs';

const identity = {version:1,profile:'operational-beta-v1',client:'desktop',apiOrigin:'https://api.example.invalid',
  frontendOrigin:'https://clerk.example.invalid',publishableKey:'pk_live_'+btoa('clerk.example.invalid$'),
  organizationId:'org_invented_beta',audience:'cosmas-os-beta'};
const config = {mode:'hosted-beta-authenticated',dataMode:'authorized_beta',apiOrigin:identity.apiOrigin,nativeIdentity:identity,
  installation:{version:1,profile:'beta',bundleIdentifier:'com.cosmasos.beta.desktop',storageGeneration:1,
    electronVersion:'43.4.1',rendererPartition:'persist:cosmasos-operational-beta',authHelperBundleIdentifier:'com.cosmasos.beta.desktop.auth'}};

const stagingIdentity = {...identity, profile:'operational-staging-v1', audience:'',
  frontendOrigin:'https://invented.clerk.accounts.dev', publishableKey:'pk_test_'+btoa('invented.clerk.accounts.dev$')};
const dedicatedStagingKey = 'pk_live_Y2xlcmsuc3RhZ2luZy5jb3NtYXMuYWkk';
const productionClerkKey = 'pk_live_Y2xlcmsuY29zbWFuZXVyYS5jb20k';
const liveKey = host => 'pk_live_'+btoa(host+'$');

test('explicit staging identity uses the development issuer without accepting it as production',()=>{
  for (const client of ['desktop','apple']) {
    const value={...stagingIdentity,client};
    assert.deepEqual(validateOperationalNativeIdentity(value,client,value.apiOrigin),value);
    assert.equal(operationalNativeAuthSettings(value).profile,'operational-staging-v1');
    assert.equal(validateOperationalNativeDataMode('synthetic',value),'synthetic');
    assert.throws(()=>validateOperationalNativeDataMode('authorized_beta',value));
    for (const changed of [{profile:'operational-beta-v1'}, {profile:'unknown'}, {audience:'other-api'}, {audience:null},
      {publishableKey:'pk_live_'+btoa('invented.clerk.accounts.dev$')},
      {frontendOrigin:'https://other.clerk.accounts.dev'},
      {frontendOrigin:identity.frontendOrigin,publishableKey:'pk_test_'+btoa('clerk.example.invalid$')}])
      assert.throws(()=>validateOperationalNativeIdentity({...value,...changed},client,value.apiOrigin));
  }
});

test('staging profile accepts its own Clerk instance and rejects other live hosts',()=>{
  for (const client of ['apple','desktop']) {
    const value={...identity,profile:'operational-staging-v1',client,
      frontendOrigin:'https://clerk.staging.cosmas.ai',publishableKey:dedicatedStagingKey,audience:'cosmas-os-beta-api'};
    assert.deepEqual(validateOperationalNativeIdentity(value,client,value.apiOrigin),value);
    const auth=operationalNativeAuthSettings(value);
    assert.equal(auth.profile,'operational-staging-v1');
    assert.equal(auth.frontendOrigin,'https://clerk.staging.cosmas.ai');
    assert.equal(auth.publishableKey,dedicatedStagingKey);
    assert.equal(auth.audience,'cosmas-os-beta-api');
    assert.equal(validateOperationalNativeDataMode('synthetic',value),'synthetic');
    assert.throws(()=>validateOperationalNativeDataMode('authorized_beta',value));
    const otherAudience={...value,audience:'invented-staging-audience'};
    assert.deepEqual(validateOperationalNativeIdentity(otherAudience,client,otherAudience.apiOrigin),otherAudience);
    const beta={...value,profile:'operational-beta-v1'};
    assert.deepEqual(validateOperationalNativeIdentity(beta,client,beta.apiOrigin),beta);
    assert.equal(validateOperationalNativeDataMode('authorized_beta',beta),'authorized_beta');
    for (const changed of [
      {frontendOrigin:'https://clerk.cosmaneura.com',publishableKey:productionClerkKey},
      {frontendOrigin:identity.frontendOrigin,publishableKey:identity.publishableKey},
      {frontendOrigin:'https://clerk.invented.example',publishableKey:liveKey('clerk.invented.example')},
      {publishableKey:productionClerkKey},
      {publishableKey:liveKey('clerk.other.example')},
      {frontendOrigin:'https://clerk.other.example',publishableKey:dedicatedStagingKey},
      {audience:''},{audience:null},{audience:'has space'},
      {publishableKey:'pk_test_'+btoa('clerk.staging.cosmas.ai$')},
      {frontendOrigin:'https://clerk.staging.cosmas.ai.example',publishableKey:liveKey('clerk.staging.cosmas.ai.example')},
      {frontendOrigin:'https://preview.clerk.staging.cosmas.ai',publishableKey:liveKey('preview.clerk.staging.cosmas.ai')},
    ]) assert.throws(()=>validateOperationalNativeIdentity({...value,...changed},client,value.apiOrigin),
      /Operational native identity/,JSON.stringify(changed));
  }
  const production={...identity,client:'apple',frontendOrigin:'https://clerk.cosmaneura.com',
    publishableKey:productionClerkKey,audience:'cosmas-os-beta-api'};
  assert.deepEqual(validateOperationalNativeIdentity(production,'apple',production.apiOrigin),production);
  assert.throws(()=>validateOperationalNativeIdentity({...production,profile:'operational-staging-v1'},'apple',production.apiOrigin));
});

test('staging launch cannot authorize real data or silently replace an installed identity',async t=>{
  const base=await realpath(await mkdtemp(join(tmpdir(),'cosmas-shared-staging-')));
  t.after(()=>rm(base,{recursive:true,force:true}));
  const prior={...config,dataMode:'synthetic'};
  const directory=await prepareDesktopState(prior,base,'43.4.1');
  await writeFile(join(directory,'retained-draft'),'invented encrypted draft');
  const marker=await readFile(join(directory,'cosmas-installation.json'));
  await assert.rejects(prepareDesktopState({...prior,nativeIdentity:stagingIdentity},base,'43.4.1'));
  await assert.rejects(prepareDesktopState({...config,nativeIdentity:stagingIdentity},base,'43.4.1'));
  assert.deepEqual(await readFile(join(directory,'cosmas-installation.json')),marker);
  assert.equal(await readFile(join(directory,'retained-draft'),'utf8'),'invented encrypted draft');
  const fresh=join(base,'fresh');
  assert.ok(await prepareDesktopState({...prior,nativeIdentity:stagingIdentity},fresh,'43.4.1'));
});

test('operational identity binds the decoded production frontend, client and API',()=>{
  assert.deepEqual(validateOperationalNativeIdentity(identity,'desktop',identity.apiOrigin),identity);
  assert.equal(operationalNativeBundle('desktop'),'com.cosmasos.beta.desktop.auth');
  assert.equal(operationalNativeBundle('apple'),'com.cosmasos.beta.ios');
  assert.equal(operationalNativeAuthSettings(identity).enabled,true);
  for (const changed of [
    {...identity,client:'apple'}, {...identity,apiOrigin:'https://other.example.invalid'},
    {...identity,publishableKey:'pk_test_'+btoa('clerk.example.invalid$')},
    {...identity,frontendOrigin:'https://other.example.invalid'},
    {...identity,frontendOrigin:'https://clerk.example.invalid:443'},
    {...identity,publishableKey:'pk_live_'+btoa('invented.clerk.accounts.dev$'),frontendOrigin:'https://invented.clerk.accounts.dev'},
    {...identity,publishableKey:identity.publishableKey+' '}, {...identity,audience:'with spaces'},
    {...identity,organizationId:''}, {...identity,secret:'forbidden'}, {...identity,version:true},
  ]) assert.throws(()=>validateOperationalNativeIdentity(changed,'desktop',identity.apiOrigin));
});

test('stable operational installation preserves data and refuses changed account/backend or synthetic storage',async()=>{
  const base = await realpath(await mkdtemp(join(tmpdir(),'cosmas-native-identity-')));
  const dir = await prepareDesktopState(config,base,'43.4.1');
  assert.equal(dir,join(base,'CosmasOS Beta','com.cosmasos.beta.desktop'));
  await writeFile(join(dir,'retained-encrypted-draft'), 'invented ciphertext');
  const marker = await readFile(join(dir,'cosmas-installation.json'),'utf8');
  assert.equal(await prepareDesktopState({...config,appVersion:'0.9.0'},base,'43.4.1'),dir);
  for (const changed of [
    {...config,nativeIdentity:{...identity,organizationId:'org_other'}},
    {...config,apiOrigin:'https://other.example.invalid',nativeIdentity:{...identity,apiOrigin:'https://other.example.invalid'}},
    {...config,dataMode:'synthetic'}, {...config,installationRoot:base},
    {...config,installation:{...config.installation,bundleIdentifier:'com.cosmasos.synthetic.desktop.w60'}},
    {...config,installation:{...config.installation,rendererPartition:'persist:cosmasos-authenticated-local'}},
    {...config,nativeIdentity:undefined},
  ]) await assert.rejects(prepareDesktopState(changed,base,'43.4.1'));
  assert.equal(await readFile(join(dir,'cosmas-installation.json'),'utf8'),marker);
  assert.equal(await readFile(join(dir,'retained-encrypted-draft'),'utf8'),'invented ciphertext');
});

test('synthetic data with operational identity preserves custody and rejects mode/account changes',async t=>{
  const base=await realpath(await mkdtemp(join(tmpdir(),'cosmas-operational-synthetic-')));
  t.after(()=>rm(base,{recursive:true,force:true}));
  const synthetic={...config,dataMode:'synthetic'};
  const directory=await prepareDesktopState(synthetic,base,'43.4.1');
  const marker=await readFile(join(directory,'cosmas-installation.json'),'utf8');
  assert.equal(JSON.parse(marker).dataMode,'synthetic');
  assert.match(JSON.parse(marker).identityBinding,/^[0-9a-f]{64}$/);
  await writeFile(join(directory,'retained-draft'),'invented private draft');
  assert.equal(await prepareDesktopState(synthetic,base,'43.4.1'),directory);
  for(const changed of [
    {...synthetic,dataMode:'authorized_beta'}, {...synthetic,dataMode:undefined},
    {...synthetic,nativeIdentity:undefined}, {...synthetic,nativeIdentity:null},
    {...synthetic,nativeIdentity:{...identity,organizationId:'org_other'}},
    {...synthetic,nativeIdentity:{...identity,apiOrigin:'https://other.example.invalid'}},
    {...synthetic,nativeIdentity:{...identity,publishableKey:'pk_test_invented'}},
  ]) await assert.rejects(prepareDesktopState(changed,base,'43.4.1'));
  assert.equal(await readFile(join(directory,'cosmas-installation.json'),'utf8'),marker);
  assert.equal(await readFile(join(directory,'retained-draft'),'utf8'),'invented private draft');
});
