"""Advisory selection strength; never an output-validation gate."""

STAGING_CANDIDATE_POLICIES = ("optional", "prefer_matched")


def validate_staging_candidate_policy(value: str) -> None:
    if value not in STAGING_CANDIDATE_POLICIES:
        raise ValueError("staging_candidate_policy must be optional or prefer_matched")
