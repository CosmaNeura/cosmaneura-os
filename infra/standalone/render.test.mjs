import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdir,readFile,writeFile,mkdtemp,rm,stat,symlink} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {render,prepare,validateInput} from './render.mjs';
import {packageStagingWeb, STAGING_WEB_ORIGIN} from '../../scripts/package-staging-web.mjs';
import {validateBetaFeatureManifest} from '../../clients/shared/beta-feature-profile.mjs';

const sample=JSON.parse(await readFile(new URL('./invented-host-input.json',import.meta.url),'utf8'));
const copy=()=>structuredClone(sample);
const script=fileURLToPath(new URL('./render.mjs',import.meta.url));

test('dedicated host preparation binds every client, database, service, TLS and pending gate to one explicit instance',()=>{
  const files=render(copy()),contract=files['host-preparation.json'],env=files['api-public.json'];
  assert.equal(contract.deployment_authorized,false);assert.equal(contract.resource_ownership_verified,false);
  assert.equal(contract.state,'PREPARATION_ONLY_STARTUP_HELD');
  assert.equal(contract.database.host,'127.0.0.1');assert.equal(contract.database.port,15432);
  assert.equal(contract.database.database_create,false);assert.equal(contract.database.schema_create,false);
  assert.equal(contract.database.migration_credential_available_to_api,false);
  assert.equal(contract.database.pre_migrated_required,true);assert.equal(contract.database.initialization_service,false);
  assert.match(contract.resource_identity.database,/^cosmabot_standalone_[a-f0-9]{32}$/);
  assert.match(contract.resource_identity.database_role,/^cosmabot_runtime_[a-f0-9]{12}$/);
  for(const key of ['standalone_root','postgres_root','proxy_root','configuration_root','release_root'])
    assert.ok(contract.resource_identity[key].endsWith('/'+sample.instance_id));
  assert.equal(env.COSMAS_ENV,'standalone_clerk_synthetic');assert.equal(env.WORKSPACE_HOSTED_ENABLED,'true');
  assert.equal(env.BETA_BOX_ID,sample.box_id);
  assert.deepEqual(files['instance.json'],{schema:'cosmabot-standalone-runtime/v1',instance_id:sample.instance_id});
  assert.equal(contract.resource_identity.file_marker.mode,'0600');
  assert.equal(env.STANDALONE_JWKS_PATH,'');assert.equal(env.STANDALONE_CLERK_ISSUER_ALLOWLIST,sample.identity.frontendOrigin);
  assert.equal(env.CLERK_SESSION_POLICY,'audience');assert.equal(env.CLERK_AUDIENCE,sample.identity.audience);
  assert.equal(contract.clerk_session_proof.audience,sample.identity.audience);
  for(const client of ['desktop','apple'])assert.equal(files[`clients/${client}-identity.json`].audience,sample.identity.audience);
  assert.notEqual(sample.identity.audience,`cosmabot-standalone:${sample.instance_id}`);
  for(const audience of ['x','a'.repeat(255),`cosmabot-standalone:${sample.instance_id}`]){
    const candidate=copy();candidate.identity.audience=audience;
    const output=render(candidate);assert.equal(output['api-public.json'].CLERK_AUDIENCE,audience);
    assert.equal(output['clients/apple-identity.json'].audience,audience);
    assert.equal(output['clients/desktop-identity.json'].audience,audience);
  }
  assert.equal(env.CLERK_AUTHORIZED_PARTIES,[sample.web_origin,'app://cosmas','capacitor://localhost'].join(','));
  assert.deepEqual(contract.private_environment.exact_names,['DATABASE_URL','HUMAN_DEPLOY_EVIDENCE_REF']);
  assert.equal(Object.hasOwn(env,'DATABASE_URL'),false);
  assert.equal(Object.hasOwn(env,'HUMAN_DEPLOY_EVIDENCE_REF'),false);
  for(const [key,value] of Object.entries(env))if(key.includes('CORE_'))assert.ok(value===''||value==='false');
  assert.deepEqual(contract.external_workers,[]);assert.deepEqual(contract.platform_connections,[]);
  for(const client of ['web','desktop','apple']){
    const manifest=files['clients/standalone-profile.json'].clients[client];
    validateBetaFeatureManifest(manifest);
    assert.equal(manifest.profile,'standalone-practice-v1');assert.equal(manifest.coreWebOrigin,'');
    assert.equal(manifest.captureMode,'disabled');assert.equal(manifest.dataMode,'synthetic');
    assert.equal(manifest.apiOrigin,sample.api_origin);
  }
  for(const [name,value] of Object.entries(files))if(name.endsWith('.service')){
    assert.match(value,/^ExecStart=\/bin\/sh .*\/STARTUP-HELD\.sh$/m);
    assert.doesNotMatch(value,/^\[Install\]$/m);assert.doesNotMatch(value,/^ExecStart=.*(?:uvicorn|postgres|nginx)/m);
  }
  const network=files['network-requirements.json'];
  assert.equal(network.configuration_is_not_a_firewall,true);assert.equal(network.default_policy,'deny');
  assert.equal(network.api_egress.length,1);assert.equal(network.api_egress[0].hostname,'identity.standalone.example.com');
  assert.equal(network.api_egress[0].redirects_allowed,false);assert.ok(network.deny.includes('*.cosmaneura.com'));
  assert.match(files['https.review.conf'],/microphone=\(\)/);assert.match(files['https.review.conf'],/default_server/);
  assert.match(files['postgresql.review.conf'],/listen_addresses = '127\.0\.0\.1'/);
  assert.match(files['postgresql.review.conf'],/unix_socket_directories = ''/);
  assert.equal(contract.tls.private_key_permissions.group,contract.resource_identity.proxy_user);
  assert.equal(contract.tls.private_key_permissions.api_user_access,false);
  assert.doesNotMatch(files['pg_hba.review.conf'],/\btrust\b/);
});

test('staging session policy must be explicitly matched to existing development client identity; live readiness stays unqualified',()=>{
  const candidate=copy();candidate.identity_policy='shared_staging';
  candidate.identity.profile='operational-staging-v1';candidate.identity.audience='';
  candidate.identity.frontendOrigin='https://invented-own-practice.clerk.accounts.dev';
  candidate.identity.publishableKey='pk_test_'+Buffer.from('invented-own-practice.clerk.accounts.dev$').toString('base64');
  const files=render(candidate);assert.equal(files['api-public.json'].CLERK_SESSION_POLICY,'shared_staging');
  assert.equal(files['api-public.json'].CLERK_AUDIENCE,'');
  assert.equal(files['clients/desktop-identity.json'].profile,'operational-staging-v1');
  assert.equal(files['host-preparation.json'].clerk_session_proof.default_session_token_required,true);
  assert.equal(files['host-preparation.json'].clerk_session_proof.named_jwt_template_is_not_a_substitute,true);
  assert.equal(files['host-preparation.json'].live_readiness.requires_identity_policy,'audience');
  assert.equal(files['host-preparation.json'].live_readiness.qualified,false);
  const wrongAudience=structuredClone(candidate);wrongAudience.identity.audience='invented-cosmabot-application-api';
  assert.throws(()=>render(wrongAudience));
  delete candidate.identity_policy;assert.throws(()=>render(candidate));
});

test('shared platform resources, identity ambiguity, plaintext origins and configuration injection are rejected before rendering',()=>{
  const changes=[
    item=>{item.resource_scope='existing-platform-host';},item=>{item.instance_id='not-an-instance';},
    item=>{item.box_id=item.instance_id;},item=>{delete item.box_id;},
    item=>{item.api_origin='https://app.cosmaneura.com';item.identity.apiOrigin=item.api_origin;},
    item=>{item.web_origin='https://beta.cosmas.ai';},
    item=>{item.web_origin='https://cosmas.ai';},
    item=>{item.web_origin='https://www.cosmas.ai';},
    item=>{item.web_origin='https://app.cosmas.ai';},
    item=>{item.web_origin='https://foo.cosmaneura.com';},
    item=>{item.web_origin='https://api.staging.cosmas.ai';},
    item=>{item.identity.frontendOrigin='https://clerk.cosmaneura.com';},
    item=>{item.identity.frontendOrigin='https://offline.cosmabot.invalid';},
    item=>{item.web_origin='http://own.example.invalid';},item=>{item.web_origin+='/?credentials=x';},
    item=>{item.api_origin='https://127.0.0.1';},item=>{item.identity_policy='shared_staging';},
    item=>{item.identity.audience='';},item=>{delete item.identity.audience;},
    ...[null,['api'],'a'.repeat(256),'contains space','tab\tvalue','line\nbreak','a\u007f','nonascii-\u00e9'].map(audience=>item=>{item.identity.audience=audience;}),
    item=>{item.identity.organizationId='';},
    item=>{item.identity.publishableKey='pk_live_mismatched';},item=>{item.ports.postgres=item.ports.api;},
    item=>{item.ports.api=443;},item=>{item.ports.api='18443\nExecStart=/bin/sh';},
    item=>{item.tls.hostnames=['*.example.invalid','api.standalone.example.invalid'];},
    item=>{item.tls.certificate_sha256='unverified';},item=>{item.database_url='postgresql://platform';},
    item=>{item.artifacts.postgres_major=15;},item=>{item.artifacts.api_archive_sha256='latest';},
    item=>{item.artifacts.schema_revision='revision; migrate';},item=>{item.core_origin='https://app.cosmaneura.com';},
    item=>{item.runtime_environment={CORE_CAPTURE_ORIGIN:'https://app.cosmaneura.com'};},
    item=>{item.secret='DO_NOT_LOG_THIS_SECRET';}
  ];
  for(const change of changes){const candidate=copy();change(candidate);assert.throws(()=>validateInput(candidate));}
});

test('CLI writes a fresh bounded public package, refuses duplicate keys and symlinks, and cannot overwrite or start services',async t=>{
  const root=await mkdtemp(join(tmpdir(),'cosmabot-standalone-host-'));t.after(()=>rm(root,{recursive:true,force:true}));
  const input=join(root,'public.json');await writeFile(input,JSON.stringify(sample));
  const output=join(root,'candidate');const receipt=await prepare({input,output});
  assert.equal(receipt.startup_held,true);assert.equal(receipt.deployment_authorized,false);
  await assert.rejects(()=>stat(join(output,'.incomplete')),{code:'ENOENT'});
  const held=spawnSync('/bin/sh',[join(output,'STARTUP-HELD.sh')],{encoding:'utf8'});
  assert.equal(held.status,78);assert.match(held.stderr,/not authorized or qualified/);
  const retained=await readFile(join(output,'render-receipt.json'),'utf8');
  await assert.rejects(()=>prepare({input,output}));assert.equal(await readFile(join(output,'render-receipt.json'),'utf8'),retained);
  const duplicate=join(root,'duplicate.json');await writeFile(duplicate,JSON.stringify(sample).replace('"version":1','"version":1,"version":1'));
  const rejected=join(root,'rejected');await assert.rejects(()=>prepare({input:duplicate,output:rejected}));
  await assert.rejects(()=>stat(rejected),{code:'ENOENT'});
  const aliased=join(root,'symlink.json');await symlink(input,aliased);await assert.rejects(()=>prepare({input:aliased,output:rejected}));
  const bad=join(root,'secret.json');await writeFile(bad,JSON.stringify({...sample,password:'DO_NOT_LOG_THIS_SECRET'}));
  const denied=spawnSync(process.execPath,[script,'--input',bad,'--output',rejected],{encoding:'utf8'});
  assert.notEqual(denied.status,0);assert.doesNotMatch(denied.stdout+denied.stderr,/DO_NOT_LOG_THIS_SECRET/);
  const good=spawnSync(process.execPath,[script,'--input',input,'--output',join(root,'cli-good')],{encoding:'utf8'});
  assert.equal(good.status,0,good.stderr);assert.equal(JSON.parse(good.stdout).startup_held,true);
});

test('the web packager accepts beta.cosmas.ai and still refuses other hosts and real-data switches',async t=>{
  const root=await mkdtemp(join(tmpdir(),'beta-web-package-'));t.after(()=>rm(root,{recursive:true,force:true}));
  const dist=join(root,'dist');await mkdir(dist);
  const commit='0123456789abcdef0123456789abcdef01234567';
  await writeFile(join(dist,'version.json'),`${JSON.stringify({commit,built_at:'2026-10-30T17:48:00Z'})}\n`);
  const beta=packageStagingWeb({distDir:dist,outputDir:join(root,'beta'),argv:['--target','https://beta.cosmas.ai']});
  assert.equal(beta.target,'https://beta.cosmas.ai');
  assert.equal(beta.production,false);assert.equal(beta.deployed,false);assert.equal(beta.pushed,false);
  const staging=packageStagingWeb({distDir:dist,outputDir:join(root,'staging'),argv:['--dist',dist,'--output',join(root,'staging')]});
  assert.equal(staging.target,STAGING_WEB_ORIGIN);assert.equal(staging.production,false);
  const refused=[
    ['--target','https://app.cosmaneura.com'],['--target','https://cosmas.ai'],['--target','https://www.cosmas.ai'],
    ['--target','https://app.cosmas.ai'],['--target','https://foo.cosmaneura.com'],['--target','https://random.example.invalid'],
    ['authorized_beta'],['--data-mode','authorized_beta'],
  ];
  for(const [index,argv] of refused.entries())assert.throws(()=>packageStagingWeb({distDir:dist,outputDir:join(root,`refused-${index}`),argv}),/staging_web_package_refused/);
});
