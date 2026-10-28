/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_WORKSPACE_SCHEDULING_ENROLLMENT_ENABLED?: string;
  readonly VITE_ATHENA_VISIT_LINK_ENABLED?: string;
  readonly VITE_COSMANEURA_RECORD_ENABLED?: string;
  readonly VITE_COSMANEURA_WEB_ORIGIN?: string;
  readonly VITE_API_BASE?: string;
  readonly VITE_CLERK_PUBLISHABLE_KEY?: string;
  readonly VITE_WORKSPACE_ORGANIZATION_ID?: string;
  readonly VITE_COSMAS_ENV?: "synth_os" | "early_adopter_beta";
  readonly VITE_VENDOR_SETUP_ENABLED?: string;
  readonly VITE_EFAX_INBOUND_ENABLED?: string;
  readonly VITE_FAX_INBOUND_ENABLED?: string;
  readonly VITE_FAX_INBOUND_SOURCE_ENABLED?: string;
  readonly VITE_EFAX_INBOUND_SOURCE_ENABLED?: string;
  readonly VITE_INBOX_ENABLED?: string;
  readonly VITE_INBOX_HANDOFF_ENABLED?: string;
  /** Short git SHA baked in at build time for Settings/footer. */
  readonly VITE_BUILD_SHA?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
