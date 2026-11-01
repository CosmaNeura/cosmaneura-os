import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {constants} from 'node:fs';
import {cp, lstat, mkdir, open, readFile, readdir, writeFile} from 'node:fs/promises';
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
  const operator = args.length === 10 && args[6] === '--job-operator-source' && args[8] === '--base-api-receipt';
  if ((!operator && args.length !== 6) || args[0] !== '--input' || args[2] !== '--practice' || args[4] !== '--output' || !['a','b','job'].includes(args[3]) || (operator && args[3] !== 'job')) fail();
  const input = JSON.parse(await readFile(resolve(args[1]),'utf8'));
  const files = render(input), slot=args[3], output=resolve(args[5]);
  if (output === root || output.startsWith(root+'/')) fail();
  const source = execFileSync('git',['rev-parse','HEAD'],{cwd:root,encoding:'utf8'}).trim();
  if (source !== (operator ? args[7] : input.release.source_commit) || execFileSync('git',['status','--porcelain'],{cwd:root,encoding:'utf8'}).trim()) fail();
  if (slot === 'job') {
    if (operator) {
      const baseSource = input.release.source_commit;
      if ([source,baseSource].some(value=>typeof value !== 'string' || value.length !== 40 || /[^0-9a-f]/.test(value))) fail();
      const committed = (revision,path) => execFileSync('git',['show',`${revision}:${path}`],{cwd:root,maxBuffer:2_000_000});
      const hash = data => createHash('sha256').update(data).digest('hex');
      const job = committed(baseSource,'infra/enrollment/workspaces/job.py');
      // The operator layer may replace only the preparer, never the job's
      // practice/Box/schema/owner binding or the selected release renderer.
      if (!job.equals(committed(source,'infra/enrollment/workspaces/job.py')) || !committed(baseSource,'infra/enrollment/workspaces/render.mjs').equals(await readFile(resolve(here,'render.mjs')))) fail();
      const receiptFile = await open(resolve(args[9]),constants.O_RDONLY | constants.O_NOFOLLOW);
      let raw;
      try {
        const info = await receiptFile.stat();
        if (!info.isFile() || info.uid !== process.getuid() || (info.mode & 0o777) !== 0o600 || info.size > 65_536) fail();
        raw = await receiptFile.readFile();
      } finally { await receiptFile.close(); }
      const api = JSON.parse(raw);
      if (api.contract_version !== 'workspace-image-receipt.v1' || api.kind !== 'workspace-api' || api.source_commit !== baseSource || api.image !== input.release.api_image || api.status !== 'Succeeded' || !['buildkit','image_validation_passed','trivy_passed','pushed_verified','tag_and_digest_locked'].every(name=>api[name] === true)) fail();
      const preparer = committed(source,'src/cosmas_os/application/database_preparation.py');
      const dockerfile = Buffer.concat([committed(baseSource,'infra/enrollment/workspaces/Dockerfile.job'),Buffer.from(`\n# Operator-only preparer overlay on the selected immutable application image.\nCOPY --chown=10001:10001 database_preparation.py /app/src/cosmas_os/application/database_preparation.py\nLABEL org.opencontainers.image.revision="${source}" com.cosmaneura.cosmas-os.workspace-release-source="${baseSource}" com.cosmaneura.cosmas-os.base-api-source="${baseSource}" com.cosmaneura.cosmas-os.operator-source="${source}"\n`)]);
      await mkdir(output,{mode:0o700});
      for (const [name,data] of [['Dockerfile',dockerfile],['job.py',job],['database_preparation.py',preparer]]) await writeFile(resolve(output,name),data,{mode:0o600,flag:'wx'});
      await writeFile(resolve(output,'build-receipt.json'),JSON.stringify({contract_version:'workspace-job-context.v1',source_commit:source,operator_source_commit:source,workspace_source_commit:baseSource,base_application_source_commit:baseSource,base_application_image:api.image,application_receipt_sha256:hash(raw),job_py_sha256:hash(job),operator_preparer_sha256:hash(preparer),dockerfile_sha256:hash(dockerfile),image_digest_measured:false,queued:false,pushed:false,deployed:false,workspace_runtime_qualified:false})+'\n',{mode:0o600,flag:'wx'});
    } else {
      await mkdir(output,{mode:0o700});
      await cp(resolve(here,'Dockerfile.job'),resolve(output,'Dockerfile'));
      await cp(resolve(here,'job.py'),resolve(output,'job.py'));
    }
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
