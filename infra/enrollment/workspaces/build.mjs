import {execFileSync} from 'node:child_process';
import {cp, lstat, mkdir, readFile, readdir, writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {render} from './render.mjs';

const root = fileURLToPath(new URL('../../../', import.meta.url));
const here = fileURLToPath(new URL('./', import.meta.url));
const fail = () => {throw new Error('Qualified public build input required');};

async function regularTree(path) {
  const info = await lstat(path);
  if (info.isSymbolicLink() || (!info.isDirectory() && !info.isFile())) fail();
  if (info.isDirectory()) for (const name of await readdir(path)) await regularTree(resolve(path,name));
}

async function main() {
  if (Number(process.versions.node.split('.')[0]) < 24) fail();
  const args = process.argv.slice(2);
  if (args.length !== 6 || args[0] !== '--input' || args[2] !== '--practice' || args[4] !== '--output' || !['a','b','job'].includes(args[3])) fail();
  const input = JSON.parse(await readFile(resolve(args[1]),'utf8'));
  const files = render(input), slot=args[3], output=resolve(args[5]);
  if (output === root || output.startsWith(root+'/')) fail();
  const source = execFileSync('git',['rev-parse','HEAD'],{cwd:root,encoding:'utf8'}).trim();
  if (source !== input.release.source_commit || execFileSync('git',['status','--porcelain'],{cwd:root,encoding:'utf8'}).trim()) fail();
  if (slot === 'job') {
    await mkdir(output,{mode:0o700});
    await cp(resolve(here,'Dockerfile.job'),resolve(output,'Dockerfile'));
    await cp(resolve(here,'job.py'),resolve(output,'job.py'));
  } else {
    // Keep unrelated local Vite settings out of a released public bundle.
    if ((await readdir(resolve(root,'web'))).some(name=>/^\.env(?:$|\.local$|\.production(?:\.local)?$)$/.test(name))) fail();
    const env = Object.fromEntries(Object.entries(process.env).filter(([name])=>!name.startsWith('VITE_')));
    Object.assign(env, files[`web-${slot}.env.json`], {VITE_BUILD_SHA:source,COREPACK_ENABLE_NETWORK:'0'});
    execFileSync('corepack',['pnpm@9.15.9','--dir','web','run','build'],{cwd:root,env,stdio:'inherit'});
    const dist = resolve(root,'web/dist');
    await regularTree(dist);
    const version = JSON.parse(await readFile(resolve(dist,'version.json'),'utf8'));
    const binding = JSON.parse(await readFile(resolve(dist,'cosmas-workspace-build.json'),'utf8'));
    const features = JSON.parse(await readFile(resolve(dist,'cosmas-beta-features.json'),'utf8'));
    const plan = input.practices.find(p=>p.key===slot).plan;
    if (version.commit !== source || binding.apiOrigin !== plan.api_origin || binding.dataMode !== 'synthetic' || features.organizationId !== plan.organization_id || features.profile !== 'standalone-practice-v1' || features.platformAccess !== 'disabled' || features.captureMode !== 'disabled') fail();
    await mkdir(output,{mode:0o700});
    await cp(dist,resolve(output,'dist'),{recursive:true});
    await cp(resolve(here,'Dockerfile.web'),resolve(output,'Dockerfile'));
    await cp(resolve(here,'serve_web.py'),resolve(output,'serve_web.py'));
    await writeFile(resolve(output,'build-receipt.json'),JSON.stringify({source_commit:source,practice_id:plan.practice_id,box_id:plan.box_id,organization_id:plan.organization_id,api_origin:plan.api_origin,workspace_url:plan.workspace_url,image_digest_measured:false,deployed:false})+'\n',{mode:0o600,flag:'wx'});
  }
  process.stdout.write('Prepared a minimal public image context; build/push and readiness are separate operator steps.\n');
}
main().catch(()=>{process.stderr.write('Staging workspace build preparation refused.\n');process.exitCode=1;});
