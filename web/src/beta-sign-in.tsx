import { SignIn } from "@clerk/react";

/** Clerk hash route for the built-in password reset step (SignIn routing="hash"). */
export const CLERK_FORGOT_PASSWORD_HASH = "#/forgot-password";

/**
 * Invite-only Cosmas Beta sign-in: Clerk password reset only.
 * Never mounts SignUp or enables sign-in-or-up / transferable signup.
 */
export function BetaSignIn() {
  return (
    <div className="beta-sign-in" data-testid="beta-sign-in">
      <SignIn routing="hash" withSignUp={false} transferable={false} />
      <p className="beta-sign-in-help">
        <button
          type="button"
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
