import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
import {fileURLToPath} from 'node:url';

const path = (value: string) => fileURLToPath(new URL(value, import.meta.url));
const disabled = ['AI_ACTIVITY', 'ATHENA_CONNECTION', 'ATHENA_VISIT_LINK', 'CONNECTION_ONBOARDING',
  'CORE_APPOINTMENT_SETUP', 'CORE_CONNECTION', 'COSMANEURA_RECORD', 'FINANCE_SETUP', 'FINANCE_WORK',
  'INBOX', 'INBOX_HANDOFF', 'MEMBERSHIP_WORK', 'PORTAL_SETUP', 'PORTAL_WORK', 'VENDOR_SETUP',
  'WORKSPACE_APPLE_LOCAL_TRANSPORT', 'WORKSPACE_APPOINTMENTS', 'WORKSPACE_CAPTURE_CORRECTIONS',
  'WORKSPACE_CAPTURE', 'WORKSPACE_CAPTURE_LONG_VISITS', 'WORKSPACE_CAPTURE_NOTES', 'WORKSPACE_CAPTURE_RECOVERY',
  'WORKSPACE_CAPTURE_SOURCE', 'WORKSPACE_DESKTOP_AUTH', 'WORKSPACE_GOOGLE_CONNECTION', 'WORKSPACE_HOSTED',
  'WORKSPACE_MICROSOFT_CONNECTION', 'WORKSPACE_NATIVE_AUTH', 'WORKSPACE_PREP', 'WORKSPACE_PREP_WORK',
  'WORKSPACE_ROUTINES', 'WORKSPACE_SCHEDULING', 'WORKSPACE_SCHEDULING_ENROLLMENT', 'WORKSPACE_SCHEDULING_LOGIN'];

export default defineConfig({
  root: path('./clinician-live-lab'), publicDir: path('./public'), envDir: false, plugins: [react()],
  resolve: {alias: {
    '@cosmaneura-scribe/capture-protocol': path('../clients/capture/protocol/generated.ts'),
    '@cosmaneura-scribe/capacitor-ios-pcm': path('../clients/capture/plugins/ios-pcm/index.ts'),
    '@cosmaneura-scribe/capacitor-secure-queue': path('../clients/capture/plugins/secure-queue/index.ts'),
  }},
  define: Object.fromEntries(Object.entries({
    ...Object.fromEntries(disabled.map(key => [`VITE_${key}_ENABLED`, 'false'])),
    VITE_COSMAS_ENV: 'synth_os', VITE_WORKSPACE_ENABLED: 'true', VITE_WORKSPACE_AUTHENTICATED_ENABLED: 'true',
    VITE_DESKTOP_SYNTHETIC_ENABLED: 'true', VITE_API_BASE: 'http://127.0.0.1:5194/unavailable',
  }).map(([key, value]) => [`import.meta.env.${key}`, JSON.stringify(value)])),
  server: {
    host: '127.0.0.1', port: 5194, strictPort: true, fs: {allow: [path('..')]},
    proxy: {'/lab-api': {target: 'http://127.0.0.1:5195', changeOrigin: false, timeout: 180_000, proxyTimeout: 180_000}},
  },
  build: {outDir: path('./clinician-live-lab-dist'), emptyOutDir: true},
});
