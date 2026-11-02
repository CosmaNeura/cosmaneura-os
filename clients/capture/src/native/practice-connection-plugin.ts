import { Capacitor, registerPlugin, type PluginListenerHandle } from "@capacitor/core";

/**
 * Explicit account/practice connection in the owned native host. The host owns
 * its pinned account service, nonce, registry lookup and profile activation.
 * Renderer input never selects an issuer, organization, Box or destination URL.
 * Account authentication alone is not workspace access.
 */
export interface NativePracticeConnectionPlugin {
  capabilities(): Promise<unknown>;
  accountStatus(): Promise<unknown>;
  beginAccountSignIn(): Promise<unknown>;
  accountToken(options: { expectedRevision: string }): Promise<unknown>;
  enrollmentRequest(options: {
    expectedRevision: string;
    operation: "config" | "status" | "practices" | "selectPractice" | "profile" | "practice" |
      "join" | "document" | "accept" | "receipt" | "quote" | "checkout" | "recover" |
      "confirmWorkspace" | "invitation" | "portal";
    body?: unknown;
    idempotencyKey?: string;
  }): Promise<unknown>;
  openCheckout(options: { expectedRevision: string; checkoutSessionId: string }): Promise<unknown>;
  openEnrollmentDestination(options: {
    expectedRevision: string;
    destination: "checkout" | "portal";
  }): Promise<unknown>;
  activatePracticeOrganization(options: { expectedRevision: string }): Promise<unknown>;
  activateRegisteredPractice(options: { expectedRevision: string }): Promise<unknown>;
  returnToBeta(options: { expectedRevision: string }): Promise<unknown>;
  signOut(options: { expectedRevision: string }): Promise<unknown>;
  addListener(event: "accountStateChanged", listener: (state: unknown) => void): Promise<PluginListenerHandle>;
}

export const NativePracticeConnection = registerPlugin<NativePracticeConnectionPlugin>(
  "CosmasNativePracticeConnection",
);

/** Availability is a UI hint; the native host and server still authorize work. */
export const nativePracticeConnectionAvailable = () => Capacitor.getPlatform() === "ios" &&
  Capacitor.isPluginAvailable("CosmasNativePracticeConnection");
