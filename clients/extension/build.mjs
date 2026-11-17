import {build} from 'esbuild';
import {mkdir, readFile, writeFile, copyFile} from 'node:fs/promises';
import {resolveBuild} from './build-config.mjs';

// Read only the explicitly selected local env file; never discover another app's keys.
if (process.env.COSMABOT_EXTENSION_ENV_FILE) process.loadEnvFile(process.env.COSMABOT_EXTENSION_ENV_FILE);
const config = resolveBuild(process.env, process.argv.includes('--unconfigured'));
const manifest = JSON.parse(await readFile(new URL('./manifest.json', import.meta.url)));
if (config.issuer) manifest.content_security_policy.extension_pages =
  manifest.content_security_policy.extension_pages.replace('; base-uri', ` ${config.issuer}; base-uri`);
await mkdir(new URL('./dist/', import.meta.url), {recursive: true});
const application = await build({absWorkingDir: import.meta.dirname, entryPoints: ['src/worker.mjs', 'src/panel.mjs'],
  outdir: 'dist', bundle: true, platform: 'browser', format: 'esm', target: 'chrome120',
  minify: true, sourcemap: false, metafile: true, define: {'__CLERK_CONFIG__': JSON.stringify(config), 'process.env.NODE_ENV': '"production"'}});
const content = await build({absWorkingDir: import.meta.dirname, entryPoints: ['src/content.mjs'],
  outfile: 'dist/content.js', bundle: true, platform: 'browser', format: 'iife', target: 'chrome120', minify: true, metafile: true});
// Every import must be folded into local bundles; no external runtime modules.
for (const result of [application, content])
  if (Object.values(result.metafile.outputs).some(output => output.imports.length))
    throw new Error('Extension bundle contains an unbundled runtime import');
await writeFile(new URL('./dist/bundle-audit.json', import.meta.url), JSON.stringify({
  bundled: true, externalImports: [], inputs: Object.keys(application.metafile.inputs)
}, null, 2) + '\n');
for (const file of ['panel.html', 'panel.css']) await copyFile(new URL(`./${file}`, import.meta.url), new URL(`./dist/${file}`, import.meta.url));
await writeFile(new URL('./dist/manifest.json', import.meta.url), JSON.stringify(manifest, null, 2) + '\n');
console.log(config.publishableKey ? 'Built local development proof' : 'Built unconfigured inspection artifact (sign-in disabled)');
