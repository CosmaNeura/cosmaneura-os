import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
import {fileURLToPath} from 'node:url';
const path=(value:string)=>fileURLToPath(new URL(value,import.meta.url));
export default defineConfig({root:path('./browser-operational-lab'),plugins:[react()],resolve:{alias:[{find:'@cosmaneura-scribe/capture-protocol',replacement:path('../clients/capture/protocol/generated.ts')},{find:/.*capture-source-factory$/,replacement:path('./browser-operational-lab/capture-source.ts')}]},server:{host:'127.0.0.1',port:5173,strictPort:true,hmr:false,watch:{ignored:['**/*']},fs:{allow:[path('..')]}}});
