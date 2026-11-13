/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Independent enrollment service; never inherit the clinical API/Org configuration. */
  readonly VITE_ENROLLMENT_ENABLED?: string;
  /** Only the dedicated central account build replaces its root with enrollment. */
  readonly VITE_ENROLLMENT_ACCOUNT_ONLY?: string;
  readonly VITE_ENROLLMENT_API_BASE?: string;
  readonly VITE_ENROLLMENT_CLERK_PUBLISHABLE_KEY?: string;
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
  /** Opt-in: show Create custom bot and capability restrictions (hidden by default in beta). */
  readonly VITE_CUSTOM_BOTS_ENABLED?: string;
  /** Opt-in: show Coming soon connection cards (hidden by default in beta). */
  readonly VITE_COMING_SOON_CONNECTIONS_ENABLED?: string;
  /**
   * Public Privacy Policy URL shown on the Account screen (App Store 5.1.1(i)).
   * Placeholder default is https://cosmas.ai/privacy until John publishes the final URL.
   */
  readonly VITE_PRIVACY_POLICY_URL?: string;
  /**
   * Public Support URL shown on the Account screen.
   * Placeholder default is https://cosmas.ai/support until John publishes the final URL.
   */
  readonly VITE_SUPPORT_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
