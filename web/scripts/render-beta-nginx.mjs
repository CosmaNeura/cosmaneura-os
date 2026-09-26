import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {resolve,dirname} from 'node:path';
import {validateBetaFeatureManifest} from '../../clients/shared/beta-feature-profile.mjs';

export function renderBetaNginx(template, candidate) {
  const manifest=validateBetaFeatureManifest(candidate);
  if(manifest.client!=='web')throw new Error('Hosted web policy requires a web client build');
  const baseline='Permissions-Policy "camera=(), geolocation=(), microphone=(), payment=()"';
  if(template.split('Permissions-Policy').length!==2 || !template.includes(baseline)) {
    throw new Error('Unexpected hosted permissions policy template');
  }
  return manifest.captureMode==='browser_microphone'
    ? template.replace(baseline,baseline.replace('microphone=()','microphone=(self)'))
    : template;
}

if(process.argv[1] && resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
  if(process.argv.length!==2)throw new Error('The web build policy generator takes no arguments');
  const root=fileURLToPath(new URL('../',import.meta.url));
  const manifest=JSON.parse(await readFile(resolve(root,'dist/cosmas-beta-features.json'),'utf8'));
  const template=await readFile(resolve(root,'nginx.conf'),'utf8');
  const output=resolve(root,'.beta/nginx.conf');
  const result=renderBetaNginx(template,manifest);
  await mkdir(dirname(output),{recursive:true});
  await writeFile(output,result);
  console.log(`Hosted web capture policy: ${manifest.captureMode}; microphone ${manifest.captureMode==='browser_microphone'?'self only':'denied'}`);
}
