import {mergeConfig,defineConfig} from 'vite';
import acceptance from './vite.ux-acceptance.config';
export default mergeConfig(acceptance,defineConfig({define:{'import.meta.env.VITE_MESSAGES_ENABLED':'"true"'},server:{port:5187},build:{outDir:'../messages-lab-dist'}}));
