import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
import {fileURLToPath} from 'node:url';
const path=(value:string)=>fileURLToPath(new URL(value,import.meta.url));
export default defineConfig({
  root:path('./visit-prep-lab'),publicDir:path('./public'),plugins:[react()],
  resolve:{alias:[{find:'./visit-prep-api',replacement:path('./visit-prep-lab/core.ts')},
    {find:'./core-connection-api',replacement:path('./visit-prep-lab/core.ts')},
    {find:'@cosmaneura-scribe/capture-protocol',replacement:path('../clients/capture/protocol/generated.ts')},
    {find:'@cosmaneura-scribe/capacitor-ios-pcm',replacement:path('../clients/capture/plugins/ios-pcm/index.ts')},
    {find:'@cosmaneura-scribe/capacitor-secure-queue',replacement:path('../clients/capture/plugins/secure-queue/index.ts')}]},
  server:{host:'127.0.0.1',port:5197,strictPort:true,fs:{allow:[path('..')]}},
});
