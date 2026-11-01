// The account host is a separate staging build, never the existing beta workspace.
export function resolveEnrollmentBuild(env) {
  const requireValue = (condition, message) => { if (!condition) throw new Error(message); };
  requireValue(env.VITE_ENROLLMENT_ENABLED === 'true' && env.VITE_ENROLLMENT_ACCOUNT_ONLY === 'true',
    'The account build needs explicit enabled and account-only routing.');
  requireValue(env.VITE_ENROLLMENT_ACCOUNT_ORIGIN === 'https://onboarding.staging.cosmas.ai' &&
    env.VITE_ENROLLMENT_API_BASE === 'https://enrollment-api.staging.cosmas.ai',
    'The staging account build requires its exact owned account/API origins.');
  const publicNames = new Set(['VITE_ENROLLMENT_ENABLED', 'VITE_ENROLLMENT_ACCOUNT_ONLY',
    'VITE_ENROLLMENT_ACCOUNT_ORIGIN', 'VITE_ENROLLMENT_API_BASE', 'VITE_ENROLLMENT_CLERK_ISSUER',
    'VITE_ENROLLMENT_CLERK_PUBLISHABLE_KEY', 'VITE_BUILD_SHA']);
  requireValue(Object.entries(env).every(([name, value]) => !name.startsWith('VITE_') ||
    publicNames.has(name) || value === ''),
    'An account image cannot inherit workspace, runtime, native, provider or beta Clerk settings.');
  const issuer = new URL(env.VITE_ENROLLMENT_CLERK_ISSUER);
  requireValue(issuer.protocol === 'https:' && issuer.origin === env.VITE_ENROLLMENT_CLERK_ISSUER &&
    !issuer.port && !issuer.username && !issuer.password &&
    (issuer.hostname === 'clerk.staging.cosmas.ai' || /^[a-z0-9]+(?:-[a-z0-9]+)*\.clerk\.accounts\.dev$/.test(issuer.hostname)),
    'The staging account build needs the selected Development Clerk issuer.');
  const key = env.VITE_ENROLLMENT_CLERK_PUBLISHABLE_KEY;
  requireValue(typeof key === 'string' && /^pk_test_[A-Za-z0-9+/=_-]+$/.test(key) &&
    Buffer.from(key.slice('pk_test_'.length), 'base64').toString('utf8') === `${issuer.hostname}$`,
    'The public Development Clerk key must match the selected issuer.');
  requireValue(/^[0-9a-f]{40}$/.test(env.VITE_BUILD_SHA ?? ''), 'Bind the account image to its exact source commit.');
  return { version: 1, kind: 'enrollment-account', environment: 'staging', source_commit: env.VITE_BUILD_SHA,
    application_origin: env.VITE_ENROLLMENT_ACCOUNT_ORIGIN, enrollment_api_origin: env.VITE_ENROLLMENT_API_BASE,
    clerk_issuer: issuer.origin, account_only: true, clinical_workspace: false };
}
