import { loadEnv } from 'vite';
import { fileURLToPath } from 'node:url';
import { resolveEnrollmentBuild } from './enrollment-build-config.mjs';
try {
  resolveEnrollmentBuild(loadEnv('production', fileURLToPath(new URL('../', import.meta.url)), 'VITE_'));
} catch (error) {
  console.error(`Enrollment account build refused: ${error.message}`);
  process.exitCode = 1;
}
