import {loadEnv} from 'vite';
import {fileURLToPath} from 'node:url';
import {resolveBetaFeatureProfile} from '../../clients/shared/beta-feature-profile.mjs';
import {accountPublicUrlPassThrough} from '../../clients/shared/account-public-url.mjs';
try {
  const env = loadEnv('production', fileURLToPath(new URL('../', import.meta.url)), 'VITE_');
  accountPublicUrlPassThrough(env);
  resolveBetaFeatureProfile(env);
} catch (error) {
  console.error(`Beta web build refused: ${error.message}`);
  process.exit(1);
}
