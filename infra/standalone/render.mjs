/** Offline preparation for a dedicated CosmaBot host. Never installs or starts services. */
import {readFile,writeFile,mkdir,lstat,unlink} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {resolve,join} from 'node:path';
import {workspaceIdentityInputs} from '../../scripts/prepare-workspace-identity.mjs';

export class Refused extends Error {}
const refuse=code=>{throw new Refused(code);};
const hash=value=>createHash('sha256').update(value).digest('hex');
const object=(value,keys,code)=>{
  if(!value||typeof value!=='object'||Array.isArray(value)||
    Object.keys(value).length!==keys.length||keys.some(key=>!Object.hasOwn(value,key)))refuse(code);
};
// Keep equal to cosmas_os.workspace_llm.DEPLOYMENT (Data Zone Standard US).
const WORKSPACE_LLM_DEPLOYMENT='gpt-4.1-dzus';
// Synthetic web addresses, and the matching api.<host> names. Every other
// cosmas.ai or cosmaneura.com hostname stays refused.
const syntheticWebHosts=['staging.cosmas.ai','beta.cosmas.ai'];
const ownedSyntheticHosts=new Set(syntheticWebHosts.flatMap(host=>[host,`api.${host}`]));
const platformHosts=new Set(['cosmas.ai','www.cosmas.ai','app.cosmas.ai','api.cosmas.ai','bot.cosmas.ai',...ownedSyntheticHosts]);
function origin(value,ownedStaging=false){
  let url;try{url=new URL(value);}catch{refuse('exact_https_origin_required');}
  if(typeof value!=='string'||url.origin!==value||url.protocol!=='https:'||url.port||
    !/^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}$/.test(url.hostname)||
    url.hostname==='cosmaneura.com'||url.hostname.endsWith('.cosmaneura.com')||
    platformHosts.has(url.hostname)&&!(ownedStaging&&ownedSyntheticHosts.has(url.hostname)))
    refuse('dedicated_https_origin_required');
  return url.hostname;
}

function betaFeatures(value){
  if(value.beta_features===undefined)return {profile:'standalone-practice-v1',model:null,google:null};
  const features=value.beta_features;object(features,['model','google'],'public_beta_features_shape');
  if(features.model!==null){
    object(features.model,['origin','endpoint','deployment'],'public_model_shape');
    const model=features.model;
    if(typeof model.origin!=='string'||model.origin!==model.origin.trim()||
      !/^https:\/\/[a-z0-9][a-z0-9-]{1,62}\.(?:openai\.azure\.com|services\.ai\.azure\.com)$/.test(model.origin)||
      model.endpoint!==model.origin+'/openai/v1'||model.deployment!==WORKSPACE_LLM_DEPLOYMENT)refuse('exact_owned_model_selection_required');
  }
  if(features.google!==null){
    object(features.google,['client_id','callback_uri','return_origin'],'public_google_shape');
    if(typeof features.google.client_id!=='string'||features.google.client_id!==features.google.client_id.trim()||
      !/^[A-Za-z0-9_-]{1,200}\.apps\.googleusercontent\.com$/.test(features.google.client_id)||
      features.google.callback_uri!==value.api_origin+'/connections/google/callback'||
      features.google.return_origin!==value.web_origin)refuse('matching_google_public_contract_required');
  }
  return {...features,profile:features.google?'independent-beta-v1':'standalone-practice-v1'};
}

export function validateInput(value){
  const keys=['version','resource_scope','instance_id','box_id','source_commit','web_origin','api_origin',
    'identity_policy','identity','ports','artifacts','tls'];
  if(value&&Object.hasOwn(value,'beta_features'))keys.push('beta_features');
  object(value,keys,'input_shape');
  const ownedVm=value.resource_scope==='owned-cosmabot-vm-instance';
  if(value.version!==1||!['dedicated-new-cosmabot-host','owned-cosmabot-vm-instance'].includes(value.resource_scope))refuse('dedicated_host_required');
  const features=betaFeatures(value);
  const ownedPair=syntheticWebHosts.some(host=>value.web_origin===`https://${host}`&&value.api_origin===`https://api.${host}`);
  if(ownedVm&&(features.profile!=='independent-beta-v1'||!ownedPair))refuse('exact_owned_cosmabot_routes_required');
  if(typeof value.instance_id!=='string'||!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(value.instance_id))refuse('instance_uuid_required');
  if(typeof value.box_id!=='string'||!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(value.box_id)||value.box_id===value.instance_id)refuse('distinct_fresh_box_uuid_required');
  if(!/^[0-9a-f]{40}$/.test(value.source_commit))refuse('source_commit_required');
  const web=origin(value.web_origin,ownedVm),api=origin(value.api_origin,ownedVm);
  if(web===api)refuse('separate_api_and_web_origins_required');
  const issuer=origin(value.identity?.frontendOrigin);
  if(issuer.endsWith('.invalid')||issuer.endsWith('.localhost')||[web,api].includes(issuer))refuse('separate_explicit_clerk_issuer_required');
  const staging=value.identity_policy==='shared_staging';
  const audience=value.identity?.audience;
  if(!['audience','shared_staging'].includes(value.identity_policy)||
    value.identity?.profile!==(staging?'operational-staging-v1':'operational-beta-v1')||
    value.identity?.apiOrigin!==value.api_origin||
    typeof audience!=='string'||(staging?audience!=='':!/^[\x21-\x7e]{1,255}$/.test(audience)))refuse('explicit_matching_identity_policy_required');
  // Audience identifies the reviewed receiving application. The exact issuer,
  // organization and Box bind the practice; storage remains instance-specific.
  // This existing generator owns public identity validation and every client flag.
  workspaceIdentityInputs(value.identity,{webOrigin:value.web_origin,coreWebOrigin:'',captureUploadOrigins:[],
    dataMode:'synthetic',featureProfile:features.profile});
  object(value.ports,['api','postgres'],'ports_shape');
  if(Object.values(value.ports).some(port=>!Number.isInteger(port)||port<1024||port>65535)||
    value.ports.api===value.ports.postgres)refuse('distinct_unprivileged_loopback_ports_required');
  object(value.artifacts,['api_archive_sha256','web_archive_sha256','postgres_major','schema_revision'],'artifacts_shape');
  if(![value.artifacts.api_archive_sha256,value.artifacts.web_archive_sha256].every(item=>typeof item==='string'&&/^[0-9a-f]{64}$/.test(item))||
    value.artifacts.postgres_major!==16||!/^[a-z0-9]{1,32}$/.test(value.artifacts.schema_revision))refuse('explicit_artifact_contract_required');
  object(value.tls,['certificate_sha256','hostnames'],'tls_shape');
  if(!/^[0-9a-f]{64}$/.test(value.tls.certificate_sha256)||!Array.isArray(value.tls.hostnames)||
    value.tls.hostnames.length!==2||[...value.tls.hostnames].sort().join(',')!==[api,web].sort().join(','))refuse('exact_public_tls_certificate_required');
  return value;
}

const disabledFlags=`WORKSPACE_TEAM_SETUP_ENABLED WORKSPACE_AI_ACTIVITY_ENABLED WORKSPACE_RESEARCH_ENABLED
WORKSPACE_RESEARCH_IO_ENABLED WORKSPACE_NATIVE_SYNTHETIC_ENABLED WORKSPACE_APPLE_LOCAL_TRANSPORT_ENABLED
WORKSPACE_DESKTOP_LOCAL_TRANSPORT_ENABLED WORKSPACE_CAPTURE_NOTES_ENABLED WORKSPACE_CORE_RECORD_ENABLED
WORKSPACE_CORE_CONNECTION_ENABLED WORKSPACE_ATHENA_CONNECTION_ENABLED WORKSPACE_ATHENA_VISIT_LINK_ENABLED
WORKSPACE_CORE_APPOINTMENT_SETUP_ENABLED WORKSPACE_PREP_ENABLED WORKSPACE_PREP_WORK_ENABLED
WORKSPACE_SCHEDULING_ENABLED WORKSPACE_SCHEDULING_LOGIN_ENABLED WORKSPACE_SCHEDULING_ENROLLMENT_ENABLED
WORKSPACE_SCHEDULING_PATIENT_SETUP_ENABLED WORKSPACE_GOOGLE_CONNECTION_ENABLED WORKSPACE_GOOGLE_MESSAGE_ENABLED
WORKSPACE_MICROSOFT_MESSAGE_ENABLED WORKSPACE_GOOGLE_CALENDAR_ENABLED WORKSPACE_CALENDAR_IMPORT_ENABLED
WORKSPACE_EHR_READ_ENABLED WORKSPACE_ELATION_SANDBOX_ENABLED WORKSPACE_ELATION_PROBLEMS_ENABLED
WORKSPACE_ELATION_MEDICATIONS_ENABLED WORKSPACE_ELATION_LABS_ENABLED WORKSPACE_TEBRA_FHIR_ENABLED
WORKSPACE_ATHENA_ALLERGIES_ENABLED WORKSPACE_ATHENA_MEDICATIONS_ENABLED WORKSPACE_MICROSOFT_CONNECTION_ENABLED
WORKSPACE_APPOINTMENTS_ENABLED VENDOR_WORK_ENABLED VENDOR_IO_ENABLED VENDOR_EVENTS_ENABLED VENDOR_SETUP_ENABLED
FAX_INBOUND_ENABLED FAX_INBOUND_SOURCE_ENABLED EFAX_INBOUND_ENABLED EFAX_INBOUND_SOURCE_ENABLED
PORTAL_SETUP_ENABLED PORTAL_WORK_ENABLED PORTAL_IO_ENABLED FINANCE_WORK_ENABLED FINANCE_SETUP_ENABLED
MEMBERSHIP_WORK_ENABLED INBOX_WORK_ENABLED INBOX_HANDOFF_ENABLED FINANCE_IO_ENABLED FINANCE_EVENTS_ENABLED
WORKSPACE_ROUTINES_ENABLED WORKSPACE_CAPTURE_CORRECTIONS_ENABLED WORKSPACE_CAPTURE_RECOVERY_ENABLED
WORKSPACE_CAPTURE_SOURCE_ENABLED WORKSPACE_CAPTURE_LONG_VISITS_ENABLED WORKSPACE_SESSION_PREP_ENABLED
WORKSPACE_AGENT_TOOLS_ENABLED`.split(/\s+/);

function service({name,user,config,release,intended,writePaths,environment=false,https=false}){
  return `[Unit]\nDescription=${name} (review only; startup held)\n\n[Service]\nType=exec\nUser=${user}\nGroup=${user}\nWorkingDirectory=${release}\n${environment?`EnvironmentFile=${config}/api-public.env\nEnvironmentFile=${config}/api-private.env\n`:''}ExecStart=/bin/sh ${release}/STARTUP-HELD.sh\n# Intended command for a separately qualified release only:\n# ${intended}\nRestart=no\nUMask=0077\nNoNewPrivileges=true\nPrivateTmp=true\nProtectSystem=strict\nProtectHome=true\nReadWritePaths=${writePaths.join(' ')}\nCapabilityBoundingSet=${https?'CAP_NET_BIND_SERVICE':''}\n${https?'AmbientCapabilities=CAP_NET_BIND_SERVICE\n':''}RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6\n\n# No Install section: this review unit cannot be enabled as a release.\n`;
}

export function render(input){
  const value=validateInput(input),id=value.instance_id,short=id.replaceAll('-','').slice(0,12);
  const features=betaFeatures(value),ownedVm=value.resource_scope==='owned-cosmabot-vm-instance';
  const parent=`/var/lib/cosmabot/standalone/${id}`;
  const root=ownedVm?parent+'/app':`/var/lib/cosmabot-standalone/${id}`,postgres=ownedVm?parent+'/postgres':`/var/lib/cosmabot-postgres/${id}`;
  const config=ownedVm?parent+'/config':`/etc/cosmabot-standalone/${id}`,release=ownedVm?parent+'/release':`/opt/cosmabot-standalone/${id}`,proxyRoot=ownedVm?parent+'/proxy':`/var/lib/cosmabot-https/${id}`;
  const apiUser=`cosmabot-api-${short}`,pgUser=`cosmabot-pg-${short}`,proxyUser=`cosmabot-web-${short}`;
  const dbName=`cosmabot_standalone_${id.replaceAll('-','')}`,dbRole=`cosmabot_runtime_${short}`;
  const files=workspaceIdentityInputs(value.identity,{webOrigin:value.web_origin,coreWebOrigin:'',captureUploadOrigins:[],
    dataMode:'synthetic',featureProfile:features.profile});
  const parties=[value.web_origin,'app://cosmas','capacitor://localhost'].join(',');
  const environment={...Object.fromEntries(disabledFlags.map(name=>[name,'false'])),
    COSMAS_ENV:'standalone_clerk_synthetic',DATA_MODE:'synthetic',AUTH_MODE:'clerk_jwt',BETA_BOX_ID:value.box_id,
    STANDALONE_INSTANCE_ID:id,STANDALONE_ROOT:root,STANDALONE_JWKS_PATH:'',
    STANDALONE_CLERK_ISSUER_ALLOWLIST:value.identity.frontendOrigin,
    BLOB_BACKEND:'local',BLOB_ROOT:root+'/blobs',REDIS_URL:'',SYNTH_SEED:'false',SYNC_WORKER:'false',
    EXECUTION_BACKEND:'celery',WORKSPACE_ENABLED:'true',WORKSPACE_AUTHENTICATED_ENABLED:'true',
    WORKSPACE_HOSTED_ENABLED:'true',WORKSPACE_DRAFT_RECOVERY_REQUIRED:'true',
    WORKSPACE_APPLE_HOSTED_TRANSPORT_ENABLED:'true',WORKSPACE_DESKTOP_HOSTED_TRANSPORT_ENABLED:'true',
    WORKSPACE_CAPTURE_BACKEND:'disabled',WORKSPACE_LLM_BACKEND:'disabled',WORKSPACE_LLM_ENDPOINT:'',
    CORE_WEB_ORIGIN:'',CORE_CONNECTION_TENANT_REF:'',CORE_CAPTURE_ORIGIN:'',CORE_CAPTURE_SCOPE:'',
    CORE_CAPTURE_MANAGED_IDENTITY_CLIENT_ID:'',CORE_SESSION_PREP_SCOPE:'',CORE_SESSION_PREP_MANAGED_IDENTITY_CLIENT_ID:'',
    CLERK_SESSION_POLICY:value.identity_policy,CLERK_ISSUER:value.identity.frontendOrigin,
    CLERK_JWKS_URL:value.identity.frontendOrigin+'/.well-known/jwks.json',
    CLERK_AUDIENCE:value.identity.audience,CLERK_ORGANIZATION_ID:value.identity.organizationId,
    CLERK_AUTHORIZED_PARTIES:parties,CORS_ALLOWED_ORIGINS:parties};
  if(features.model)Object.assign(environment,{WORKSPACE_LLM_BACKEND:'azure_gpt41',WORKSPACE_LLM_ENDPOINT:features.model.endpoint,
    WORKSPACE_LLM_DEPLOYMENT:features.model.deployment,STANDALONE_MODEL_ORIGIN_ALLOWLIST:features.model.origin});
  if(features.google)Object.assign(environment,{WORKSPACE_GOOGLE_CONNECTION_ENABLED:'true',WORKSPACE_GOOGLE_MESSAGE_ENABLED:'true',
    WORKSPACE_GOOGLE_CALENDAR_ENABLED:'true',GOOGLE_CONNECTION_CLIENT_ID:features.google.client_id,
    GOOGLE_CONNECTION_CALLBACK_URI:features.google.callback_uri,GOOGLE_CONNECTION_RETURN_ORIGIN:features.google.return_origin});
  const contract={schema:'cosmabot-standalone-host-preparation/v1',state:'PREPARATION_ONLY_STARTUP_HELD',
    instance_id:id,box_id:value.box_id,source_commit:value.source_commit,resource_scope:value.resource_scope,
    deployment_authorized:false,resource_ownership_verified:false,account_mapping_verified:false,
    identity_policy:value.identity_policy,synthetic_only:true,
    live_readiness:{requires_identity_policy:'audience',qualified:false},
    resource_identity:{host_name:`cosmabot-standalone-${short}`,api_user:apiUser,postgres_user:pgUser,proxy_user:proxyUser,standalone_root:root,
      postgres_root:postgres,proxy_root:proxyRoot,configuration_root:config,release_root:release,
      database:dbName,database_role:dbRole,database_marker:`cosmabot-standalone:${id}`,
      file_marker:{source:'instance.json',destination:root+'/instance.json',owner:apiUser,mode:'0600'}},
    database:{host:'127.0.0.1',port:value.ports.postgres,name:dbName,role:dbRole,
      pre_migrated_required:true,schema_revision:value.artifacts.schema_revision,
      superuser:false,create_database:false,create_role:false,replication:false,bypass_rls:false,
      schema_create:false,database_create:false,temporary:false,
      migration_credential_available_to_api:false,initialization_service:false,
      startup_guard:'Existing backend validates exact owned database marker, runtime role and schema before readiness.',
      transport:'Dedicated host loopback only; no remote PostgreSQL URL or TLS-query contract is introduced.'},
    private_environment:{file:config+'/api-private.env',expected_owner:'root',mode:'0600',values_in_package:false,
      exact_names:['DATABASE_URL','HUMAN_DEPLOY_EVIDENCE_REF'],
      database_url_structure:`postgresql+psycopg://${dbRole}:<external password>@127.0.0.1:${value.ports.postgres}/${dbName}`},
    clerk_session_proof:{required:true,named_jwt_template_is_not_a_substitute:true,default_session_token_required:true,
      issuer:value.identity.frontendOrigin,organization:value.identity.organizationId,audience:value.identity.audience,
      audience_source:'Explicit reviewed identity input; never inferred from the instance UUID or changed in Clerk by this renderer.',
      tenant_binding:'Exact issuer and organization plus the separately reserved local Box and human identity.',
      authorized_parties:parties.split(','),real_user_session_verified:false,identity_instance_ownership_verified:false},
    directories:[{path:root,owner:apiUser,mode:'0700'},{path:root+'/blobs',owner:apiUser,mode:'0700'},
      {path:root+'/keys',owner:apiUser,mode:'0700',local_jwks_file_forbidden:true},
      {path:postgres,owner:pgUser,mode:'0700',pre_existing_pgdata_required:true},
      {path:proxyRoot,owner:proxyUser,mode:'0700'},
      {path:config,owner:'root',mode:'0755',public_configuration_files_mode:'0644',private_environment_mode:'0600'},
      {path:release,owner:'root',mode:'0755',writable_by_runtime:false,dotenv_file_forbidden:true}],
    artifacts:value.artifacts,tls:{...value.tls,certificate:config+'/tls/server.crt',private_key:config+'/tls/server.key',
      protected_directory:{path:config+'/tls',owner:'root',group:proxyUser,mode:'0750'},
      private_key_permissions:{owner:'root',group:proxyUser,mode:'0640',api_user_access:false},
      key_in_package:false,certificate_matches_key_and_hosts_verified:false,automatic_certificate_requests:false},
    required_evidence:['Dedicated CosmaBot host and users owned independently of the Cosmaneura platform',
      'Source and package hashes, dependency provenance and exact schema match',
      'New database, restricted role, instance marker and explicit separate migration receipt',
      'Empty or explicitly approved invented data; no platform database, storage or account import',
      'Default Clerk session issuer, organization, audience policy and authorized-party checks for web and native',
      'Private environment exact names, protected permissions and no inherited credentials or .env file',
      'Manual TLS certificate, private key match, hostname coverage and DNS ownership',
      'Host firewall and DNS qualification: only declared Clerk JWKS egress, no metadata or other providers',
      'Backup and restore proof for this exact deployment, independent of local synthetic lab proof',
      'Separate release review replacing the startup hold; no activation tool is provided'],
    external_workers:[],platform_connections:[],automatic_migrations:false,automatic_seed:false};
  if(value.beta_features!==undefined){
    contract.feature_profile=features.profile;
    contract.optional_runtime_features={model:!!features.model,google:!!features.google,live_provider_acceptance:false,
      secrets_in_package:false,practice_records:'invented synthetic records',google_content:'actual consenting account content; never relabelled as invented'};
    if(features.model)contract.private_environment.exact_names.push('WORKSPACE_LLM_API_KEY');
    if(features.google)contract.private_environment.exact_names.push('GOOGLE_CONNECTION_CLIENT_SECRET','GOOGLE_CONNECTION_ENCRYPTION_KEY');
  }
  if(ownedVm){
    contract.resource_identity.host_name='vm-cosmabot-staging-eus2-lab01';
    contract.private_environment.file=config+'/private/api-private.json';
    contract.private_environment.mode='0400';contract.private_environment.expected_owner=apiUser;
    contract.existing_proxy={retain_ports:[80,443],new_tls_listener_forbidden:true,
      exact_routes:[value.web_origin,value.api_origin],old_services_and_data_retained:true,cutover_and_rollback_qualified:false};
    contract.required_evidence.push('Exact existing VM machine/container/image/UID/port bindings and reviewed proxy-only cutover plus rollback');
  }
  const firewall={schema:'cosmabot-standalone-host-network-requirements/v1',state:'NOT_INSTALLED_OR_VERIFIED',
    dedicated_host_required:true,target_host:`cosmabot-standalone-${short}`,default_policy:'deny',configuration_is_not_a_firewall:true,
    inbound:[{service:'manual HTTPS proxy',tcp_port:443,hostnames:value.tls.hostnames}],
    local_only:[{service:'PostgreSQL',address:'127.0.0.1',tcp_port:value.ports.postgres},
      {service:'CosmaBot API',address:'127.0.0.1',tcp_port:value.ports.api}],
    api_egress:[{protocol:'https',hostname:new URL(value.identity.frontendOrigin).hostname,tcp_port:443,
      path:'/.well-known/jwks.json',redirects_allowed:false}],
    request_contract:'Exact JWKS path and redirect refusal require separate HTTP-client verification; a host firewall cannot enforce HTTPS paths.',
    dns:'A separately reviewed resolver policy must permit resolution of the exact Clerk issuer only.',
    deny:['All other external destinations','169.254.0.0/16 metadata and link-local','fe80::/10 and cloud metadata IPv6',
      '*.cosmaneura.com',...platformHosts],
    network_namespace:'Dedicated host; never the main platform host or its network/deployment identity',
    qualification:'Service configuration alone does not enforce destination allowlisting; demonstrate host egress policy before release.'};
  if(features.model)firewall.api_egress.push({protocol:'https',hostname:new URL(features.model.origin).hostname,tcp_port:443,
    path:'/openai/v1/chat/completions',redirects_allowed:false});
  if(features.google){
    for(const hostname of ['oauth2.googleapis.com','openidconnect.googleapis.com','gmail.googleapis.com','www.googleapis.com'])
      firewall.api_egress.push({protocol:'https',hostname,tcp_port:443,redirects_allowed:false});
    firewall.browser_oauth_origins=['https://accounts.google.com'];
  }
  if(value.beta_features!==undefined){
    firewall.dns='Only the exact configured Clerk/model and documented Google API hostnames; qualify resolver enforcement separately.';
    contract.required_evidence=contract.required_evidence.map(item=>item.startsWith('Host firewall and DNS')?
      'Host firewall and DNS qualification: only declared Clerk, optional own model and Google API egress; no metadata or other providers':item);
  }
  if(ownedVm){
    firewall.dedicated_host_required=false;firewall.existing_owned_cosmabot_host_required=true;
    firewall.target_host=contract.resource_identity.host_name;
    firewall.network_namespace='Existing dedicated CosmaBot VM, with separately owned instance users/data and retained old CosmaBot rollback services';
    firewall.inbound=[{service:'existing CosmaBot HTTPS proxy only',tcp_port:443,hostnames:value.tls.hostnames}];
  }
  const proxy=`# Review only. The matching service has an unconditional startup hold.\n# Manual certificate only; no ACME or provider discovery.\npid ${proxyRoot}/nginx.pid;\nerror_log ${proxyRoot}/error.log warn;\nevents { worker_connections 256; }\nhttp {\n  include /etc/nginx/mime.types;\n  access_log off;\n  server_tokens off;\n  client_body_temp_path ${proxyRoot}/body;\n  proxy_temp_path ${proxyRoot}/proxy;\n  ssl_certificate ${config}/tls/server.crt;\n  ssl_certificate_key ${config}/tls/server.key;\n  ssl_protocols TLSv1.2 TLSv1.3;\n  add_header X-Content-Type-Options "nosniff" always;\n  add_header Referrer-Policy "no-referrer" always;\n  add_header X-Frame-Options "DENY" always;\n  add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;\n  add_header Permissions-Policy "camera=(), geolocation=(), microphone=(), payment=()" always;\n  server { listen 443 ssl default_server; server_name _; return 444; }\n  server {\n    listen 443 ssl;\n    server_name ${new URL(value.api_origin).hostname};\n    client_max_body_size 8m;\n    location / {\n      proxy_pass http://127.0.0.1:${value.ports.api};\n      proxy_set_header Host $host;\n      proxy_set_header X-Forwarded-Proto https;\n      proxy_set_header X-Forwarded-For $remote_addr;\n    }\n  }\n  server {\n    listen 443 ssl;\n    server_name ${new URL(value.web_origin).hostname};\n    root ${release}/web;\n    location ~ \\.mjs$ { types { application/javascript mjs; } try_files $uri =404; expires 1y; }\n    location /assets/ { try_files $uri =404; expires 1y; }\n    location / { try_files $uri $uri/ /index.html; expires -1; }\n  }\n}\n`;
  const output={...Object.fromEntries(Object.entries(files).map(([name,data])=>['clients/'+name,data])),
    'host-input.json':value,'host-preparation.json':contract,'api-public.json':environment,
    'instance.json':{schema:'cosmabot-standalone-runtime/v1',instance_id:id},
    'api-public.env':Object.entries(environment).map(([key,item])=>`${key}=${JSON.stringify(item)}`).join('\n')+'\n',
    'network-requirements.json':firewall,'https.review.conf':proxy,
    'postgresql.review.conf':`# Use only an existing owned PostgreSQL16 data directory. Never initdb here.\n# TCP loopback only; no system PostgreSQL socket or lock directory is shared.\n# Administrative access needs a separate reviewed maintenance procedure.\nlisten_addresses = '127.0.0.1'\nunix_socket_directories = ''\nport = ${value.ports.postgres}\npassword_encryption = 'scram-sha-256'\n`,
    'pg_hba.review.conf':`# Runtime role only; migration/admin access must be a separate reviewed local procedure.\nhost ${dbName} ${dbRole} 127.0.0.1/32 scram-sha-256\nhost all all 0.0.0.0/0 reject\nhost all all ::0/0 reject\n`,
    'cosmabot-api.review.service':service({name:'CosmaBot standalone API',user:apiUser,root,config,release,writePaths:[root],environment:true,
      intended:`${release}/api/bin/uvicorn cosmas_os.api.app:app --host 127.0.0.1 --port ${value.ports.api} --workers 1`}),
    'cosmabot-postgres.review.service':service({name:'CosmaBot owned PostgreSQL',user:pgUser,root,config,release,writePaths:[postgres],
      intended:`/usr/lib/postgresql/16/bin/postgres -D ${postgres} -c config_file=${config}/postgresql.conf -c hba_file=${config}/pg_hba.conf`}),
    'cosmabot-https.review.service':service({name:'CosmaBot HTTPS proxy',user:proxyUser,config,release,writePaths:[proxyRoot],https:true,
      intended:`/usr/sbin/nginx -c ${config}/https.conf -g 'daemon off;'`}),
    'STARTUP-HELD.sh':'#!/bin/sh\nprintf "%s\\n" "CosmaBot preparation only: deployment and startup are not authorized or qualified." >&2\nexit 78\n'};
  if(ownedVm){
    // Existing Caddy owns TLS. Do not even emit a second 443 listener candidate.
    delete output['https.review.conf'];delete output['cosmabot-https.review.service'];
  }
  return output;
}

function parseJson(raw){
  // Inputs are public and bounded; reject duplicate keys rather than silently choosing one.
  let cursor=0;
  const space=()=>{while(/\s/.test(raw[cursor]??'')&&cursor<raw.length)cursor++;};
  const string=()=>{const start=cursor++;while(cursor<raw.length){const next=raw[cursor++];if(next==='\\'){cursor++;continue;}if(next==='"')return JSON.parse(raw.slice(start,cursor));}refuse('invalid_json');};
  const value=()=>{space();if(raw[cursor]==='"')return string();if(raw[cursor]==='{'){cursor++;const result=Object.create(null);space();if(raw[cursor]==='}'){cursor++;return result;}
    while(cursor<raw.length){space();if(raw[cursor]!=='"')refuse('invalid_json');const key=string();if(Object.hasOwn(result,key))refuse('duplicate_json_key');space();if(raw[cursor++]!==':')refuse('invalid_json');result[key]=value();space();const next=raw[cursor++];if(next==='}')return result;if(next!==',')refuse('invalid_json');}refuse('invalid_json');}
    if(raw[cursor]==='['){cursor++;const result=[];space();if(raw[cursor]===']'){cursor++;return result;}while(cursor<raw.length){result.push(value());space();const next=raw[cursor++];if(next===']')return result;if(next!==',')refuse('invalid_json');}refuse('invalid_json');}
    const match=/^(?:true|false|null|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)/.exec(raw.slice(cursor));if(!match)refuse('invalid_json');cursor+=match[0].length;return JSON.parse(match[0]);};
  const parsed=value();space();if(cursor!==raw.length)refuse('invalid_json');return parsed;
}

export async function prepare({input,output}){
  const info=await lstat(input);if(!info.isFile()||info.isSymbolicLink()||info.size>16384)refuse('bounded_public_input_required');
  const files=render(parseJson(await readFile(input,'utf8')));
  await mkdir(output,{mode:0o700});await writeFile(join(output,'.incomplete'),'Preparation incomplete\n',{flag:'wx'});
  await mkdir(join(output,'clients'),{mode:0o700});
  const receipt={schema:'cosmabot-standalone-render-receipt/v1',startup_held:true,deployment_authorized:false,files:{}};
  for(const [name,value] of Object.entries(files)){
    const raw=typeof value==='string'?value:JSON.stringify(value,null,2)+'\n';
    await writeFile(join(output,name),raw,{flag:'wx',mode:0o600});receipt.files[name]=hash(raw);
  }
  await writeFile(join(output,'render-receipt.json'),JSON.stringify(receipt,null,2)+'\n',{flag:'wx',mode:0o600});
  await unlink(join(output,'.incomplete'));return receipt;
}

if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  try{
    const args=process.argv.slice(2);if(args.length!==4||args[0]!=='--input'||args[2]!=='--output'||!args[1]||!args[3])refuse('exact_input_output_arguments_required');
    const receipt=await prepare({input:args[1],output:args[3]});
    console.log(JSON.stringify({startup_held:receipt.startup_held,deployment_authorized:false,files:Object.keys(receipt.files).length}));
  }catch{console.error('Standalone host preparation refused. Use explicit public inputs and a new output directory.');process.exitCode=1;}
}
