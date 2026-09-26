import {loadEnv} from 'vite';
import {fileURLToPath} from 'node:url';
import {resolveBetaFeatureProfile} from '../../clients/shared/beta-feature-profile.mjs';
try {
  resolveBetaFeatureProfile(loadEnv('production', fileURLToPath(new URL('../', import.meta.url)), 'VITE_'));
} catch (error) {
  console.error(`Beta web build refused: ${error.message}`);
  process.exit(1);
}
