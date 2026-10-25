import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
import {fileURLToPath} from 'node:url';
const path=(value:string)=>fileURLToPath(new URL(value,import.meta.url));
export default defineConfig({
  root:path('./ux-lab'),plugins:[react()],
  resolve:{alias:[{find:'./connection-catalog-api',replacement:path('./ux-lab/fixtures.ts')},{find:'./connection-summary',replacement:path('./ux-lab/fixtures.ts')},
    {find:'./microsoft-connection-api',replacement:path('./ux-lab/provider-fixtures.ts')},
    {find:'./core-connection-api',replacement:path('./ux-lab/provider-fixtures.ts')},
    {find:'@cosmaneura-scribe/capture-protocol',replacement:path('../clients/capture/protocol/generated.ts')},
    {find:'@cosmaneura-scribe/capacitor-ios-pcm',replacement:path('../clients/capture/plugins/ios-pcm/index.ts')},
    {find:'@cosmaneura-scribe/capacitor-secure-queue',replacement:path('../clients/capture/plugins/secure-queue/index.ts')}]},
  server:{host:'127.0.0.1',port:5187,strictPort:true,fs:{allow:[path('..')]}},
  build:{outDir:path('./ux-lab-dist'),emptyOutDir:true},
});
