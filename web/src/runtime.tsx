import { ClerkProvider } from "@clerk/react";
import { Component, type ErrorInfo, type ReactNode } from "react";
import {
  App,
  ClerkBetaApp,
  StatusScreen,
  resolveRuntimeMode,
  type AppRuntimeMode,
} from "./App";

type BetaFrontendConfiguration =
  | { configured: true; publishableKey: string }
  | {
      configured: false;
      reason: "missing_clerk_key" | "invalid_clerk_key" | "missing_api_base" | "invalid_api_base";
    };

export function resolveBetaFrontendConfiguration(
  publishableKey: string | undefined,
  apiBase: string | undefined,
): BetaFrontendConfiguration {
  const key = publishableKey?.trim();
  if (!key) return { configured: false, reason: "missing_clerk_key" };
  if (!/^pk_(?:test|live)_\S+$/.test(key)) {
    return { configured: false, reason: "invalid_clerk_key" };
  }

  const base = apiBase?.trim();
  if (!base) return { configured: false, reason: "missing_api_base" };
  try {
    const parsed = new URL(base);
    if (
      parsed.protocol !== "https:" ||
      parsed.username ||
      parsed.password ||
      parsed.search ||
      parsed.hash
    ) {
      return { configured: false, reason: "invalid_api_base" };
    }
  } catch {
    return { configured: false, reason: "invalid_api_base" };
  }

  return { configured: true, publishableKey: key };
}

class BetaRuntimeErrorBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError(_error: unknown) {
    return { failed: true };
  }

  componentDidCatch(_error: unknown, _info: ErrorInfo) {
    // Do not render or persist identity-provider error details.
  }

  render() {
    if (this.state.failed) {
      return (
        <StatusScreen
          title="Beta login is unavailable"
          detail="No work has been loaded. Try again later or contact the beta administrator."
        />
      );
    }
    return this.props.children;
  }
}

const configuredRuntimeMode = resolveRuntimeMode(
  import.meta.env.VITE_COSMAS_ENV,
  import.meta.env.DEV,
);

type RuntimeAppProps = {
  runtimeMode?: AppRuntimeMode;
  clerkPublishableKey?: string;
  apiBase?: string;
};

export function RuntimeApp({
  runtimeMode = configuredRuntimeMode,
  clerkPublishableKey = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY,
  apiBase = import.meta.env.VITE_API_BASE,
}: RuntimeAppProps) {
  if (runtimeMode !== "early_adopter_beta") {
    return <App runtimeMode={runtimeMode} />;
  }

  const configuration = resolveBetaFrontendConfiguration(clerkPublishableKey, apiBase);
  if (!configuration.configured) {
    return (
      <StatusScreen
        title="Beta login is not configured"
        detail="This build is intentionally offline. It will not contact Clerk or the API until the approved beta configuration is installed."
      />
    );
  }

  return (
    <BetaRuntimeErrorBoundary>
      <ClerkProvider publishableKey={configuration.publishableKey}>
        <ClerkBetaApp />
      </ClerkProvider>
    </BetaRuntimeErrorBoundary>
  );
}
