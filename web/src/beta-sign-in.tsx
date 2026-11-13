import { SignIn } from "@clerk/react";
import { AccountPublicLinks } from "./AccountPublicLinks";
import {useState} from 'react';
import {nativeAppleSignInAvailable} from '../../clients/capture/src/native/apple-sign-in-plugin';
import {NativeAppleSignIn} from './NativeAppleSignIn';

/** Clerk hash route for the built-in password reset step (SignIn routing="hash"). */
export const CLERK_FORGOT_PASSWORD_HASH = "#/forgot-password";

/**
 * Invite-only Cosmas Beta sign-in: Clerk password reset only.
 * Never mounts SignUp or enables sign-in-or-up / transferable signup.
 */
export function BetaSignIn() {
  const [appleEnabled, setAppleEnabled] = useState(false);
  const [appleBusy, setAppleBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);
  return (
    <div className="beta-sign-in" data-testid="beta-sign-in">
      {nativeAppleSignInAvailable() && <NativeAppleSignIn onBusy={setAppleBusy} onEnabled={setAppleEnabled}
        onReset={() => { window.location.hash = ''; setAttempt(value => value + 1); }} />}
      <div style={{display: 'contents'}} inert={appleBusy || undefined}>
        <SignIn key={attempt} routing="hash" withSignUp={false} transferable={false}
          {...(appleEnabled ? {appearance: {elements: {socialButtonsBlockButton__apple: {display: 'none'}}}} : {})} />
      </div>
      <AccountPublicLinks />
      <p className="beta-sign-in-help">
        <button
          type="button"
          disabled={appleBusy}
          className="beta-forgot-password"
          onClick={() => {
            window.location.hash = CLERK_FORGOT_PASSWORD_HASH;
          }}
        >
          Forgot password?
        </button>
        {" "}
        Uses Clerk reset for invited accounts only — Cosmas does not offer open signup.
      </p>
    </div>
  );
}
