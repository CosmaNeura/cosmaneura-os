import {readFile,writeFile,mkdir,lstat} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {resolve,join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {validateOperationalNativeIdentity} from '../clients/desktop/native-identity-config.mjs';
import {resolveBetaFeatureProfile} from '../clients/shared/beta-feature-profile.mjs';

// OpenTofu jsonencode orders object keys and escapes these five characters.
export function identityDigest(identity) {
  const value=JSON.stringify(Object.fromEntries(Object.entries(identity).sort(([a],[b])=>a<b?-1:a>b?1:0)))
    .replace(/[<>&\u2028\u2029]/g,char=>'\\u'+char.charCodeAt(0).toString(16).padStart(4,'0'));
  return createHash('sha256').update(value).digest('hex');
}

/** Reuse the existing native schema; all output values are public configuration. */
export function workspaceIdentityInputs(candidate,{webOrigin,coreWebOrigin,captureUploadOrigins}) {
  const desktop=validateOperationalNativeIdentity(candidate,'desktop',candidate?.apiOrigin);
  const apple=validateOperationalNativeIdentity({...desktop,client:'apple'},'apple',desktop.apiOrigin);
  if(!Array.isArray(captureUploadOrigins))throw new Error('Explicit upload origins required');
  const builds={};
  for(const client of ['web','desktop','apple']) {
    builds[client]=resolveBetaFeatureProfile({
      VITE_WORKSPACE_FEATURE_PROFILE:'operational-beta-v1',
      VITE_WORKSPACE_HOSTED_CLIENT:client,VITE_WORKSPACE_DATA_MODE:'authorized_beta',
      VITE_WORKSPACE_HOSTED_API_ORIGIN:desktop.apiOrigin,
      VITE_API_BASE:client==='desktop'?'app://cosmas/api':desktop.apiOrigin,
      VITE_WORKSPACE_WEB_ORIGIN:client==='web'?webOrigin:'',
      VITE_CLERK_PUBLISHABLE_KEY:desktop.publishableKey,
      VITE_COSMANEURA_WEB_ORIGIN:coreWebOrigin,
      VITE_CAPTURE_UPLOAD_ORIGINS:captureUploadOrigins.join(','),
      VITE_WORKSPACE_CAPTURE_MODE:client==='apple'?'ios_native':'browser_microphone',
    });
  }
  const digest=identityDigest(desktop);
  const webArgs=Object.fromEntries(['VITE_CLERK_PUBLISHABLE_KEY','VITE_WORKSPACE_HOSTED_API_ORIGIN',
    'VITE_WORKSPACE_WEB_ORIGIN','VITE_WORKSPACE_DATA_MODE','VITE_COSMANEURA_WEB_ORIGIN',
    'VITE_CAPTURE_UPLOAD_ORIGINS','VITE_WORKSPACE_CAPTURE_MODE'].map(key=>[key,builds.web.env[key]]));
  return {
    'desktop-identity.json':desktop,
    'apple-identity.json':apple,
    'web-build-arguments.json':webArgs,
    ...Object.fromEntries(Object.entries(builds).map(([client,value])=>[client+'-build-env.json',value.env])),
    'os.identity.tfvars.json':{
      clerk_org_id:desktop.organizationId,clerk_issuer_url:desktop.frontendOrigin,
      clerk_jwks_url:desktop.frontendOrigin+'/.well-known/jwks.json',
      clerk_audience:desktop.audience,web_origin:webOrigin,workspace_operational_identity:desktop,
    },
    'identity-bindings.json':{
      version:1,profile:'operational-beta-v1',identity_sha256:digest,
      api_origin:desktop.apiOrigin,web_origin:webOrigin,core_web_origin:coreWebOrigin,
      native_origins:{desktop:'app://cosmas',apple:'capacitor://localhost'},
      native_bundles:{desktop:'com.cosmasos.beta.desktop',desktop_auth:'com.cosmasos.beta.desktop.auth',apple:'com.cosmasos.beta.ios'},
      actual_account_or_device_acceptance:false,activation_authorized:false,
      native_release_evidence_generated:false,
    },
  };
}

export async function prepareWorkspaceIdentity({identityPath,webOrigin,coreWebOrigin,captureUploadOrigins,output}) {
  const info=await lstat(identityPath);
  if(!info.isFile()||info.isSymbolicLink()||info.size>8192)throw new Error('Use one bounded public native identity file');
  const raw=await readFile(identityPath,'utf8');
  // Native identity values are flat primitives. Reject duplicate keys even when
  // JSON.parse would silently keep only the final copy.
  const candidate=JSON.parse(raw);
  const names=[...raw.matchAll(/"(?:[^"\\]|\\.)*"/g)]
    .filter(match=>raw.slice(match.index+match[0].length).trimStart().startsWith(':'))
    .map(match=>JSON.parse(match[0]));
  if(new Set(names).size!==names.length)throw new Error('Duplicate identity field');
  const files=workspaceIdentityInputs(candidate,{webOrigin,coreWebOrigin,captureUploadOrigins});
  await mkdir(output,{mode:0o700});
  const incomplete=join(output,'.incomplete');
  await writeFile(incomplete,'Public identity preparation incomplete\n',{flag:'wx'});
  for(const [name,value] of Object.entries(files))await writeFile(join(output,name),JSON.stringify(value,null,2)+'\n',{flag:'wx'});
  const {unlink}=await import('node:fs/promises');
  await unlink(incomplete);
  return files['identity-bindings.json'];
}

if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
  try {
    const args=process.argv.slice(2),known=new Set(['--identity','--web-origin','--core-web-origin','--capture-upload-origin','--output']);
    const values={};
    for(let i=0;i<args.length;i+=2){
      const key=args[i],value=args[i+1];
      if(!known.has(key)||!value||value.startsWith('--')||(key!=='--capture-upload-origin'&&values[key]))throw new Error('Invalid public identity arguments');
      if(key==='--capture-upload-origin')(values[key]??=[]).push(value);else values[key]=value;
    }
    if([...known].some(key=>!values[key]))throw new Error('All public identity arguments are required');
    console.log(JSON.stringify(await prepareWorkspaceIdentity({identityPath:values['--identity'],webOrigin:values['--web-origin'],
      coreWebOrigin:values['--core-web-origin'],captureUploadOrigins:values['--capture-upload-origin'],output:values['--output']})));
  } catch {
    console.error('Public identity preparation refused; inspect the explicit inputs or choose a new output directory.');
    process.exitCode=1;
  }
}
