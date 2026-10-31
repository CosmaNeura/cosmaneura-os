import {createHash} from 'node:crypto';
import {mkdir, readFile, writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {resolve} from 'node:path';
import {resolveBetaFeatureProfile, STANDALONE_FEATURE_PROFILE} from '../../../clients/shared/beta-feature-profile.mjs';

const fail = message => {throw new Error(`Staging workspaces: ${message}`);};
const requireValue = (value, message) => {if (!value) fail(message);};
const exact = (object, keys) => requireValue(object && typeof object === 'object' && !Array.isArray(object) && Object.keys(object).every(key => keys.includes(key)), 'unknown manifest fields');
const digest = value => createHash('sha256').update(value).digest('hex');
const uuid = value => /^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(value ?? '');
const bounded = (value, max) => typeof value === 'string' && value.length > 0 && value.length <= max && value === value.trim() && !/[\u0000-\u001f\u007f]/.test(value);
const receipt = value => /^[0-9a-f]{64}$/.test(value ?? '');
export const SECRET_NAMES = Object.freeze({DATABASE_URL:'database-url', REDIS_URL:'redis-url', WORKSPACE_ENROLLMENT_ADMISSION_SECRET:'enrollment-admission-key', DATABASE_ADMIN_URL:'database-admin-url', OWNER_MANIFEST:'owner-manifest'});

function stageOrigin(value) {
  const u = new URL(value);
  requireValue(u.protocol === 'https:' && u.origin === value && !u.username && !u.password && !u.port &&
    (u.hostname === 'staging.cosmas.ai' || u.hostname.endsWith('.staging.cosmas.ai')), 'exact owned staging origin required');
  return value;
}

function reservedBox(practice) {
  const bytes = value => Buffer.from(value.replaceAll('-', ''), 'hex');
  const hash = createHash('sha1').update(bytes('f17d7eec-39ee-5d1e-8071-0d94453d91bd')).update(practice,'utf8').digest();
  hash[6] = (hash[6] & 15) | 80; hash[8] = (hash[8] & 63) | 128;
  const hex = hash.subarray(0,16).toString('hex');
  return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
}

export function render(input) {
  exact(input, ['version','environment','synthetic_only','namespace','release_operator_object_id','foundation','account','release','practices','create_migration_jobs','create_owner_reservation_jobs','deploy_workloads','bind_domains']);
  requireValue(input.version === 1 && input.environment === 'staging' && input.synthetic_only === true && /^[a-z0-9]{6,8}$/.test(input.namespace), 'two-practice synthetic staging contract required');
  requireValue(uuid(input.release_operator_object_id), 'reviewed secret publisher principal required');
  for (const key of ['create_migration_jobs','create_owner_reservation_jobs','deploy_workloads','bind_domains']) requireValue(typeof input[key] === 'boolean', 'explicit deployment gates required');
  const f = input.foundation;
  exact(f, ['contract_version','environment','subscription_id','tenant_id','resource_group_name','location','vnet_id','container_app_environment_id','container_registry_id','registry_server','postgres_subnet_id','private_endpoint_subnet_id','vault_private_dns_zone_id']);
  requireValue(f.contract_version === 'enrollment-foundation.v1' && f.environment === 'staging' && uuid(f.subscription_id) && uuid(f.tenant_id) && ['eastus2','centralus'].includes(f.location) && /^rg-cosmabot-enrollment-staging-[a-z0-9]{6,8}$/.test(f.resource_group_name), 'independent staging foundation required');
  const scope = `/subscriptions/${f.subscription_id}/resourceGroups/${f.resource_group_name}/providers/`;
  for (const key of ['vnet_id','container_app_environment_id','container_registry_id','postgres_subnet_id','private_endpoint_subnet_id','vault_private_dns_zone_id']) requireValue(typeof f[key] === 'string' && f[key].toLowerCase().startsWith(scope.toLowerCase()), 'foundation resources must remain owned');
  requireValue(/^acrcbotenrstg[a-z0-9]{6,8}\.azurecr\.io$/.test(f.registry_server) && f.container_registry_id.endsWith('/'+f.registry_server.split('.')[0]), 'owned enrollment registry required');
  const account = input.account;
  exact(account, ['app_origin','api_origin','issuer','publishable_key']);
  stageOrigin(account.app_origin); stageOrigin(account.api_origin);
  requireValue(account.app_origin === 'https://onboarding.staging.cosmas.ai' && account.api_origin === 'https://enrollment-api.staging.cosmas.ai', 'dedicated central enrollment staging pair required');
  const issuer = new URL(account.issuer);
  requireValue(issuer.protocol === 'https:' && issuer.origin === account.issuer && !issuer.port && !issuer.username && !issuer.password && /^[a-z0-9]+(?:-[a-z0-9]+)*\.clerk\.accounts\.dev$/.test(issuer.hostname), 'selected staging Clerk development issuer required');
  requireValue(typeof account.publishable_key === 'string' && account.publishable_key.startsWith('pk_test_') && Buffer.from(account.publishable_key.slice(8),'base64').toString() === `${issuer.hostname}$`, 'matching public staging Clerk key required');
  exact(input.release, ['source_commit','api_image','job_image']);
  requireValue(/^[0-9a-f]{40}$/.test(input.release.source_commit), 'immutable release source required');
  const image = value => requireValue(typeof value === 'string' && value.startsWith(`${f.registry_server}/`) && /^[a-z0-9.]+\.azurecr\.io\/[a-z0-9./_-]+@sha256:[0-9a-f]{64}$/.test(value), 'owned digest image required');
  image(input.release.api_image);
  if (input.release.job_image !== null) image(input.release.job_image);
  if (input.create_migration_jobs || input.create_owner_reservation_jobs) requireValue(input.release.job_image !== null, 'measured private job image required before jobs');
  requireValue(Array.isArray(input.practices) && input.practices.length === 2, 'exactly two reserved practices required');
  const files = {}, practices = {};
  for (const p of input.practices) {
    exact(p, ['key','plan','owner_display_name','practice_display_name','reviewed_by','evidence_ref','web_image','secret_references','migration_receipt_sha256','reservation_receipt_sha256','dns_ownership_qualified']);
    requireValue(['a','b'].includes(p.key) && !practices[p.key], 'distinct a/b practice slots required');
    const plan = p.plan;
    exact(plan, ['practice_id','box_id','organization_id','owner_subject','issuer','api_origin','workspace_url','source_commit','image_sha256']);
    requireValue(uuid(plan.practice_id) && uuid(plan.box_id) && plan.box_id === reservedBox(plan.practice_id) && /^org_[A-Za-z0-9]+$/.test(plan.organization_id) && /^user_[A-Za-z0-9]+$/.test(plan.owner_subject), 'registry-reserved practice/Box/owner/Org required');
    requireValue(plan.issuer === account.issuer && plan.source_commit === input.release.source_commit && plan.image_sha256 === input.release.api_image.split('@sha256:')[1], 'plan must match selected issuer and API release');
    const web = new URL(plan.workspace_url);
    const webOrigin = stageOrigin(web.origin), apiOrigin = stageOrigin(plan.api_origin);
    requireValue(web.pathname === '/chief' && !web.search && !web.hash && !web.username && !web.password && !web.port && /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.staging\.cosmas\.ai$/.test(web.hostname) && ![account.app_origin,account.api_origin,'https://api.staging.cosmas.ai'].includes(webOrigin) && apiOrigin === `https://api.${web.hostname}`, 'paired independent practice Chief/API destinations required');
    for (const [key,max] of [['owner_display_name',120],['practice_display_name',120],['reviewed_by',200],['evidence_ref',255]]) requireValue(bounded(p[key],max), 'bounded owner reservation metadata required');
    if (p.web_image !== null) image(p.web_image);
    if (input.deploy_workloads) requireValue(p.web_image !== null, 'measured practice web image required before workloads');
    requireValue(typeof p.dns_ownership_qualified === 'boolean', 'DNS ownership qualification must be explicit');
    const vault = `https://kv-cews-${input.namespace}-${p.key}.vault.azure.net/`;
    exact(p.secret_references, Object.keys(SECRET_NAMES));
    for (const [name,reference] of Object.entries(p.secret_references)) requireValue(typeof reference === 'string' && new RegExp(`^${vault.replaceAll('.','\\.')}secrets/${SECRET_NAMES[name]}/[0-9a-f]{32}$`).test(reference), 'only exact per-Box versioned secret references accepted');
    const runtimeNames = ['DATABASE_URL','REDIS_URL','WORKSPACE_ENROLLMENT_ADMISSION_SECRET'];
    if (input.create_migration_jobs || input.create_owner_reservation_jobs || input.deploy_workloads) requireValue(runtimeNames.every(name => p.secret_references[name]), 'runtime secret references incomplete');
    if (input.create_migration_jobs || input.create_owner_reservation_jobs) requireValue(p.secret_references.DATABASE_ADMIN_URL, 'private job admin reference required');
    if (input.create_owner_reservation_jobs) requireValue(p.secret_references.OWNER_MANIFEST && receipt(p.migration_receipt_sha256), 'migration evidence and protected owner manifest required before reservation');
    if (input.deploy_workloads) requireValue(receipt(p.migration_receipt_sha256) && receipt(p.reservation_receipt_sha256), 'migrations and exact owner reservation must be qualified first');
    if (input.bind_domains) requireValue(input.deploy_workloads && p.dns_ownership_qualified, 'bind domains only after explicit DNS ownership qualification');
    const owner = {schema_version:'cosmas-os/d3-beta-bootstrap/v1',box_id:plan.box_id,clinic_display_name:p.practice_display_name,owner_display_name:p.owner_display_name,clerk_issuer:plan.issuer,clerk_subject:plan.owner_subject,clerk_organization_id:plan.organization_id,reviewed_by:p.reviewed_by,evidence_ref:p.evidence_ref};
    const ownerJson = JSON.stringify(owner,null,2)+'\n';
    const build = resolveBetaFeatureProfile({VITE_WORKSPACE_FEATURE_PROFILE:STANDALONE_FEATURE_PROFILE,VITE_WORKSPACE_HOSTED_CLIENT:'web',VITE_WORKSPACE_DATA_MODE:'synthetic',VITE_WORKSPACE_HOSTED_API_ORIGIN:apiOrigin,VITE_API_BASE:apiOrigin,VITE_WORKSPACE_WEB_ORIGIN:webOrigin,VITE_CLERK_PUBLISHABLE_KEY:account.publishable_key,VITE_WORKSPACE_ORGANIZATION_ID:plan.organization_id,VITE_COSMANEURA_WEB_ORIGIN:'',VITE_CAPTURE_UPLOAD_ORIGINS:'',VITE_WORKSPACE_CAPTURE_MODE:'disabled'});
    files[`owner-${p.key}.json`] = owner;
    // Missing enrollment gates retain the entry route's closed default and
    // remain compatible with the unchanged beta feature whitelist.
    files[`web-${p.key}.env.json`] = {...build.env,VITE_ENROLLMENT_API_BASE:account.api_origin};
    practices[p.key] = {...p,plan,web_origin:webOrigin,owner_manifest_sha256:digest(ownerJson),api_env:{COSMAS_ENV:'early_adopter_beta',DATA_MODE:'synthetic',AUTH_MODE:'clerk_jwt',SYNTH_SEED:'false',SYNC_WORKER:'false',BLOB_BACKEND:'azure',BETA_BOX_ID:plan.box_id,CLERK_ISSUER:plan.issuer,CLERK_JWKS_URL:`${plan.issuer}/.well-known/jwks.json`,CLERK_ORGANIZATION_ID:plan.organization_id,CLERK_SESSION_POLICY:'enrollment_default',CLERK_AUDIENCE:'',CLERK_AUTHORIZED_PARTIES:`${account.app_origin},${webOrigin}`,CORS_ALLOWED_ORIGINS:`${account.app_origin},${webOrigin}`,HUMAN_DEPLOY_EVIDENCE_REF:p.evidence_ref,WORKSPACE_ENABLED:'true',WORKSPACE_AUTHENTICATED_ENABLED:'true',WORKSPACE_HOSTED_ENABLED:'true',WORKSPACE_DRAFT_RECOVERY_REQUIRED:'true',WORKSPACE_APPLE_HOSTED_TRANSPORT_ENABLED:'false',WORKSPACE_DESKTOP_HOSTED_TRANSPORT_ENABLED:'false',WORKSPACE_ENROLLMENT_MANAGED:'true',WORKSPACE_ENROLLMENT_PRACTICE_ID:plan.practice_id,WORKSPACE_ENROLLMENT_API_ORIGIN:account.api_origin,WORKSPACE_ENROLLMENT_ACCOUNT_ORIGIN:account.app_origin,WORKSPACE_ENROLLMENT_ORIGIN_ALLOWLIST:`${account.api_origin},${account.app_origin}`,WORKSPACE_RELEASE_SOURCE_COMMIT:plan.source_commit,WORKSPACE_RELEASE_IMAGE_SHA256:plan.image_sha256}};
  }
  for (const key of ['practice_id','box_id','organization_id','api_origin','workspace_url']) requireValue(practices.a.plan[key] !== practices.b.plan[key], 'practice stores and identities must not collide');
  const releaseSchema = JSON.parse(awaitlessSchema());
  files['deployment.json'] = {...input,practices,expected_schema_revision:releaseSchema.schema_revision,rendered_only:true,deployed:false,workspace_ready:false};
  return files;
}

// Bind the deployment to the existing release-owned migration head.
import {readFileSync} from 'node:fs';
function awaitlessSchema() {return readFileSync(new URL('../../beta/environment/release-schema.json',import.meta.url),'utf8');}

async function main() {
  const args=process.argv.slice(2);
  requireValue(args.length === 4 && args[0] === '--input' && args[2] === '--output', 'use --input reviewed.json --output fresh-protected-directory');
  const files=render(JSON.parse(await readFile(resolve(args[1]),'utf8'))), output=resolve(args[3]);
  await mkdir(output,{mode:0o700});
  for (const [name,value] of Object.entries(files)) await writeFile(resolve(output,name),JSON.stringify(value,null,2)+'\n',{mode:0o600,flag:'wx'});
  process.stdout.write('Prepared two isolated synthetic workspace configurations; no deployment or readiness was granted.\n');
}
if(process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main().catch(()=>{process.stderr.write('Staging workspace preparation refused.\n');process.exitCode=1;});
