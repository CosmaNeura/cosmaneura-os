export function resolveBuild(env, unconfigured = false) {
  if (unconfigured) return {publishableKey: null, organization: null, issuer: null};
  try {
    const publishableKey = env.COSMABOT_EXTENSION_CLERK_PUBLISHABLE_KEY;
    const issuer = env.COSMABOT_EXTENSION_CLERK_ISSUER;
    const organization = env.COSMABOT_EXTENSION_CLERK_ORGANIZATION_ID;
    if (!publishableKey?.startsWith('pk_test_')) throw new Error();
    const host = Buffer.from(publishableKey.slice(8), 'base64').toString('utf8');
    if (!/^[a-z0-9-]+\.clerk\.accounts\.dev\$$/.test(host)
        || issuer !== `https://${host.slice(0, -1)}`
        || !/^org_[a-zA-Z0-9_]{1,251}$/.test(organization ?? '')) throw new Error();
    return {publishableKey, organization, issuer};
  } catch { throw new Error('CosmaBot development Clerk configuration required'); }
}
