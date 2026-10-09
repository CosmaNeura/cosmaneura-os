import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
import {fileURLToPath} from 'node:url';
const path=(v:string)=>fileURLToPath(new URL(v,import.meta.url));
export default defineConfig({root:path('./transcription-lab'),plugins:[react()],resolve:{alias:[
  {find:/^\.\/creator-review-api$/,replacement:path('./transcription-lab/review-adapter.ts')},
  {find:'./capture-notes-api',replacement:path('./transcription-lab/services.ts')},
  {find:'./saved-recording-runtime',replacement:path('./transcription-lab/services.ts')},
  {find:'@cosmaneura-scribe/capture-protocol',replacement:path('../clients/capture/protocol/generated.ts')},
  {find:'@cosmaneura-scribe/capacitor-ios-pcm',replacement:path('../clients/capture/plugins/ios-pcm/index.ts')},
  {find:'@cosmaneura-scribe/capacitor-secure-queue',replacement:path('../clients/capture/plugins/secure-queue/index.ts')},
 ]},server:{host:'127.0.0.1',port:5191,strictPort:true,fs:{allow:[path('..')]}},
 define:{'import.meta.env.VITE_API_BASE':JSON.stringify('http://127.0.0.1:5191'),'import.meta.env.VITE_DESKTOP_SYNTHETIC_ENABLED':JSON.stringify('true'),'import.meta.env.VITE_WORKSPACE_APPLE_LOCAL_TRANSPORT_ENABLED':JSON.stringify('true')},
 build:{outDir:path('./transcription-lab-dist'),emptyOutDir:true}});
