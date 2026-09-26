import {mergeConfig,defineConfig} from 'vitest/config';
import capture from '../capture/vitest.config';
export default mergeConfig(capture,defineConfig({test:{include:['recorder/**/*.test.ts']}}));
