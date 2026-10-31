import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { resolve, dirname } from 'node:path';

export function renderEnrollmentNginx(template, manifest) {
  if (manifest.kind !== 'enrollment-account' || manifest.account_only !== true ||
    manifest.clinical_workspace !== false || manifest.environment !== 'staging' ||
    manifest.application_origin !== 'https://onboarding.staging.cosmas.ai' ||
    manifest.enrollment_api_origin !== 'https://enrollment-api.staging.cosmas.ai' ||
    !/^[0-9a-f]{40}$/.test(manifest.source_commit ?? '')) throw new Error('Invalid account build manifest');
  if (!template.includes('listen 8080;') || !template.includes('location = /healthz') ||
    !template.includes('try_files $uri $uri/ /index.html;') ||
    template.split('Permissions-Policy').length !== 2 ||
    !template.includes('Permissions-Policy "camera=(), geolocation=(), microphone=(), payment=()"')) {
    throw new Error('Unexpected account hosting policy template');
  }
  return template;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.argv.length !== 2) throw new Error('The account policy generator takes no arguments');
  const root = fileURLToPath(new URL('../', import.meta.url));
  const manifest = JSON.parse(await readFile(resolve(root, 'dist/cosmas-enrollment-build.json'), 'utf8'));
  const output = resolve(root, '.beta/nginx.conf');
  await mkdir(dirname(output), { recursive: true });
  await writeFile(output, renderEnrollmentNginx(await readFile(resolve(root, 'nginx.conf'), 'utf8'), manifest));
}
