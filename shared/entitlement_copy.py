"""Public plan descriptions derived from the account entitlement contract."""

from shared.entitlements import features_for, limits_for


def free_plan_summary() -> str:
    limit = limits_for("free")["properties"]
    summary = f"Free accounts can save and compare up to {limit} properties."
    features = features_for("free")
    paid_features = [
        label for feature, label in [
            ("enrichment", "Neighborhood enrichment"),
            ("commute", "commute analysis"),
        ] if not features[feature]
    ]
    if paid_features:
        summary += f" {' and '.join(paid_features)} require Premium or Premium Plus."
    return summary
