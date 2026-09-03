/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
  readonly VITE_CLERK_PUBLISHABLE_KEY?: string;
  readonly VITE_COSMAS_ENV?: "synth_os" | "early_adopter_beta";
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
