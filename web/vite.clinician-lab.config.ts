import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
import {fileURLToPath} from 'node:url';
const path=(value:string)=>fileURLToPath(new URL(value,import.meta.url));
export default defineConfig({
  root:path('./clinician-lab'),publicDir:path('./public'),plugins:[react()],
  resolve:{alias:[{find:'./session-prep-api',replacement:path('./clinician-lab/prep.ts')},
    {find:'./capture-api',replacement:path('./clinician-lab/capture.ts')},
    {find:'./capture-runtime',replacement:path('./clinician-lab/capture.ts')},
    {find:'./VendorWorkMount',replacement:path('./clinician-lab/unsupported.tsx')},
    {find:'@cosmaneura-scribe/capture-protocol',replacement:path('../clients/capture/protocol/generated.ts')},
    {find:'@cosmaneura-scribe/capacitor-ios-pcm',replacement:path('../clients/capture/plugins/ios-pcm/index.ts')},
    {find:'@cosmaneura-scribe/capacitor-secure-queue',replacement:path('../clients/capture/plugins/secure-queue/index.ts')}]},
  define:Object.fromEntries(Object.entries({VITE_COSMAS_ENV:'synth_os',VITE_WORKSPACE_ENABLED:'true',
    VITE_WORKSPACE_AUTHENTICATED_ENABLED:'true',VITE_WORKSPACE_CAPTURE_ENABLED:'true',VITE_WORKSPACE_PREP_ENABLED:'true',
    VITE_WORKSPACE_CAPTURE_NOTES_ENABLED:'false'}).map(([key,value])=>[`import.meta.env.${key}`,JSON.stringify(value)])),
  server:{host:'127.0.0.1',port:5188,strictPort:true,fs:{allow:[path('..')]}},
  build:{outDir:path('./clinician-lab-dist'),emptyOutDir:true},
});
