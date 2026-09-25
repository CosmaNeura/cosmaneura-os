/** Adapted from W90's renderer builder; compiles web assets only, never native apps. */
import {createHash} from 'node:crypto';
import {createRequire} from 'node:module';
import {lstat, mkdir, readFile, realpath, unlink, writeFile} from 'node:fs/promises';
import {basename, dirname, join, relative, resolve, sep} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {isDeepStrictEqual} from 'node:util';
import {resolveBetaFeatureProfile} from '../clients/shared/beta-feature-profile.mjs';
import {resolveHostedWorkspace} from '../clients/shared/hosted-workspace-config.mjs';
import {validateOperationalNativeIdentity} from '../clients/desktop/native-identity-config.mjs';

const source = fileURLToPath(new URL('../', import.meta.url));
const digest = value => createHash('sha256').update(value).digest('hex');
const within = (parent, child) => {
  const path = relative(parent, child);
  return path === '' || path !== '..' && !path.startsWith('..' + sep);
};
const overlap = (a, b) => within(a, b) || within(b, a);

async function absent(path) {
  try { await lstat(path); }
  catch (error) { if (error.code === 'ENOENT') return; throw error; }
  throw new Error('Use a fresh output and complete retained client inputs');
}

async function flatJson(path) {
  const info = await lstat(path);
  if (!info.isFile() || info.isSymbolicLink() || info.size > 16384) {
    throw new Error('Retained client input must be a bounded regular JSON file');
  }
  const raw = await readFile(path);
  let value, names;
  try {
    const text = new TextDecoder('utf-8', {fatal: true}).decode(raw);
    value = JSON.parse(text);
    names = [...text.matchAll(/"(?:[^"\\]|\\.)*"/g)]
      .filter(match => text.slice(match.index + match[0].length).trimStart().startsWith(':'))
      .map(match => JSON.parse(match[0]));
  } catch { throw new Error('Retained client input is not valid JSON'); }
  if (!value || typeof value !== 'object' || Array.isArray(value) ||
      Object.values(value).some(item => item !== null && typeof item === 'object') ||
      new Set(names).size !== names.length) {
    throw new Error('Retained client inputs must have unique flat fields');
  }
  return {value, raw};
}

export function nativeRendererArguments(args) {
  const values = {}, names = new Set(['--inputs', '--client', '--output']);
  for (let i = 0; i < args.length; i += 2) {
    const key = args[i], value = args[i + 1];
    if (!names.has(key) || !value || value.startsWith('--') || Object.hasOwn(values, key)) {
      throw new Error('Specify --inputs, --client desktop|apple, and --output exactly once');
    }
    values[key] = value;
  }
  if (Object.keys(values).length !== names.size) throw new Error('All native renderer arguments are required');
  return {inputs: values['--inputs'], client: values['--client'], output: values['--output']};
}

export async function buildNativeRenderer({inputs, client, output}, {build} = {}) {
  if (!['desktop', 'apple'].includes(client)) throw new Error('Select the desktop or apple renderer');
  if (Object.keys(process.env).some(key => key.startsWith('VITE_'))) {
    throw new Error('Remove ambient VITE settings; select the retained public client inputs explicitly');
  }
  const inputRoot = await realpath(resolve(inputs));
  const sourceRoot = await realpath(source);
  const outputPath = join(await realpath(dirname(resolve(output))), basename(resolve(output)));
  if (overlap(sourceRoot, outputPath) || overlap(inputRoot, outputPath)) {
    throw new Error('Keep native renderer output separate from source and retained inputs');
  }
  await absent(outputPath);
  await absent(join(inputRoot, '.incomplete'));
  const identityName = client + '-identity.json', envName = client + '-build-env.json';
  const identityInput = await flatJson(join(inputRoot, identityName));
  const envInput = await flatJson(join(inputRoot, envName));
  const identity = validateOperationalNativeIdentity(identityInput.value, client, identityInput.value.apiOrigin);
  const env = envInput.value;
  const profile = resolveBetaFeatureProfile({
    VITE_WORKSPACE_FEATURE_PROFILE: identity.profile,
    VITE_WORKSPACE_HOSTED_CLIENT: client, VITE_WORKSPACE_DATA_MODE: 'authorized_beta',
    VITE_WORKSPACE_HOSTED_API_ORIGIN: identity.apiOrigin,
    VITE_API_BASE: client === 'desktop' ? 'app://cosmas/api' : identity.apiOrigin,
    VITE_WORKSPACE_WEB_ORIGIN: '', VITE_CLERK_PUBLISHABLE_KEY: identity.publishableKey,
    VITE_COSMANEURA_WEB_ORIGIN: env.VITE_COSMANEURA_WEB_ORIGIN,
    VITE_CAPTURE_UPLOAD_ORIGINS: env.VITE_CAPTURE_UPLOAD_ORIGINS,
    VITE_WORKSPACE_CAPTURE_MODE: env.VITE_WORKSPACE_CAPTURE_MODE,
  });
  if (!isDeepStrictEqual(env, profile.env)) {
    throw new Error('Retained native environment differs from the complete current identity/profile');
  }
  await mkdir(outputPath, {mode: 0o700});
  const incomplete = join(outputPath, '.incomplete');
  await writeFile(incomplete, 'Native renderer compilation incomplete\n', {flag: 'wx'});
  const previousNodeEnv = process.env.NODE_ENV;
  Object.assign(process.env, profile.env, {NODE_ENV: 'production'});
  try {
    if (!build) {
      const require = createRequire(join(sourceRoot, 'web/package.json'));
      ({build} = await import(pathToFileURL(require.resolve('vite'))));
    }
    const dist = join(outputPath, 'dist');
    await build({root: join(sourceRoot, 'web'), configFile: join(sourceRoot, 'web/vite.config.ts'),
      configLoader: 'runner', envDir: false, cacheDir: join(outputPath, '.vite-cache'), mode: 'production',
      build: {outDir: dist, emptyOutDir: false}});
    const actual = JSON.parse(await readFile(join(dist, 'cosmas-beta-features.json'), 'utf8'));
    const transport = JSON.parse(await readFile(join(dist, 'cosmas-workspace-build.json'), 'utf8'));
    if (!isDeepStrictEqual(actual, profile.manifest) ||
        !isDeepStrictEqual(transport, {version: 1, ...resolveHostedWorkspace(profile.env)})) {
      throw new Error('Compiled native renderer manifests differ from the retained inputs');
    }
    await absent(join(inputRoot, '.incomplete'));
    const inputsSha256 = {};
    for (const [name, original] of [[identityName, identityInput], [envName, envInput]]) {
      const current = await flatJson(join(inputRoot, name));
      if (!current.raw.equals(original.raw)) throw new Error('Retained native inputs changed during compilation');
      inputsSha256[name] = digest(original.raw);
    }
    const receipt = {version: 1, client, inputsSha256, profile: actual,
      nativeCompiled: false, packaged: false, launched: false};
    await writeFile(join(outputPath, 'native-renderer-build.json'), JSON.stringify(receipt, null, 2) + '\n', {flag: 'wx'});
    await unlink(incomplete);
    return {dist, ...receipt};
  } finally {
    for (const key of Object.keys(profile.env)) delete process.env[key];
    if (previousNodeEnv === undefined) delete process.env.NODE_ENV;
    else process.env.NODE_ENV = previousNodeEnv;
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const result = await buildNativeRenderer(nativeRendererArguments(process.argv.slice(2)));
    console.log(`Built ${result.client} renderer: ${result.dist}; web assets only`);
  } catch (error) {
    console.error(`Native renderer build refused: ${error.message}`);
    process.exitCode = 1;
  }
}
