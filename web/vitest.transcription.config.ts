import {defineConfig} from 'vitest/config';
import {fileURLToPath} from 'node:url';
const path=(v:string)=>fileURLToPath(new URL(v,import.meta.url));
export default defineConfig({resolve:{alias:{
  '@cosmaneura-scribe/capture-protocol':path('../clients/capture/protocol/generated.ts'),
  '@cosmaneura-scribe/capture-preview-domain':path('../clients/capture/test-fixtures/preview-constants.ts'),
  '@cosmaneura-scribe/capacitor-ios-pcm':path('../clients/capture/plugins/ios-pcm/index.ts'),
  '@cosmaneura-scribe/capacitor-secure-queue':path('../clients/capture/plugins/secure-queue/index.ts'),
}},test:{environment:'node',include:['flow-checks/*.test.ts']}});
