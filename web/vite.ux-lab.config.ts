import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
import {fileURLToPath} from 'node:url';
const path=(value:string)=>fileURLToPath(new URL(value,import.meta.url));
export default defineConfig({
  root:path('./ux-lab'),plugins:[react()],
  resolve:{alias:[{find:'./connection-catalog-api',replacement:path('./ux-lab/fixtures.ts')},{find:'./connection-summary',replacement:path('./ux-lab/fixtures.ts')}]},
  server:{host:'127.0.0.1',port:5187,strictPort:true,fs:{allow:[path('..')]}},
  build:{outDir:path('./ux-lab-dist'),emptyOutDir:true},
});
