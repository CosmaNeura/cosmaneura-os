"""Shared production-review profile predicate (stdlib only).

One copy for the whole repo. #377 (account delete) and #381 (hosted model
endpoint) both import from this module and keep no private copy. The JS twin
is classifyAccountDeleteProfile in infra/standalone/render.mjs, held in step by
infra/standalone/account-delete-profile-matrix.json.
"""

from __future__ import annotations

STAGING_WEB_ORIGIN = "https://staging.cosmas.ai"
REVIEW_WEB_ORIGIN = "https://beta.cosmas.ai"
REVIEW_CLERK_ISSUER = "https://clerk.beta.cosmas.ai"
STAGING_SESSION_POLICY = "shared_staging"
REVIEW_SESSION_POLICY = "audience"


def classify_review_profile(
    *,
    policy: str | None,
    web_origin: str | None,
    cors: str | None,
    issuer: str | None,
) -> str | None:
    """Return 'review', 'staging', or None for a hosted profile.

    'review' requires all of: policy == 'audience'; web_origin ==
    https://beta.cosmas.ai (or, when web_origin is None, the first CORS origin
    equal to it, never mere membership); beta.cosmas.ai present and
    staging.cosmas.ai absent across web_origin and CORS; and issuer ==
    https://clerk.beta.cosmas.ai as an added condition, never the sole admit.
    'staging' is shared_staging policy or staging.cosmas.ai in the origins.
    Mixed staging and beta origins, or shared_staging with beta, return None.
    Values are compared exactly; nothing here logs or returns input values.
    """
    cors_list = [part.strip() for part in (cors or "").split(",") if part.strip()]
    origins = set(cors_list)
    if web_origin:
        origins.add(web_origin)
    has_staging = STAGING_WEB_ORIGIN in origins
    has_review = REVIEW_WEB_ORIGIN in origins
    if has_staging and has_review:
        return None
    if policy == STAGING_SESSION_POLICY and has_review:
        return None
    review_web = (
        (web_origin == REVIEW_WEB_ORIGIN)
        if web_origin is not None
        else (bool(cors_list) and cors_list[0] == REVIEW_WEB_ORIGIN)
    )
    if (
        policy == REVIEW_SESSION_POLICY
        and review_web
        and has_review
        and not has_staging
        and (issuer or "") == REVIEW_CLERK_ISSUER
    ):
        return "review"
    if policy == STAGING_SESSION_POLICY or has_staging:
        return "staging"
    return None
