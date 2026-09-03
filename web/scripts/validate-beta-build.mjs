function fail(message) {
  console.error(`Beta web build refused: ${message}`);
  process.exit(1);
}
if (process.env.VITE_COSMAS_ENV !== "early_adopter_beta") {
  fail("VITE_COSMAS_ENV must be early_adopter_beta");
}

const publishableKey = process.env.VITE_CLERK_PUBLISHABLE_KEY?.trim();
if (!publishableKey || !/^pk_live_\S+$/.test(publishableKey)) {
  fail("a production Clerk publishable key (pk_live_...) is required");
}

const apiBase = process.env.VITE_API_BASE?.trim();
if (!apiBase) fail("VITE_API_BASE is required");

let parsedApiBase;
try {
  parsedApiBase = new URL(apiBase);
} catch {
  fail("VITE_API_BASE must be a valid URL");
}

if (
  parsedApiBase.protocol !== "https:" ||
  parsedApiBase.username ||
  parsedApiBase.password ||
  parsedApiBase.pathname !== "/" ||
  parsedApiBase.search ||
  parsedApiBase.hash ||
  parsedApiBase.origin !== apiBase
) {
  fail("VITE_API_BASE must be one exact credential-free HTTPS origin");
}
