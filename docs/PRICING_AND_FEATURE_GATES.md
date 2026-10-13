# NestAI Pricing and Feature Gates

## Plans

| Plan | Price | Monthly Analyses | Saved Properties | Paid APIs |
|---|---|---|---|---|
| **Free** | $0 | 5 | 2 active, shared across apartments/houses | ❌ None |
| **Premium** | Verify approved Stripe price; existing prices conflict | 100 | 50 | ✅ Entitled integrations |
| **Premium Plus** | Verify approved Stripe price; existing prices conflict | 500 | 200 | ✅ Entitled integrations |
| **Beta** | Admin-granted | 50 (configurable) | 10 (configurable) | ✅ All |

Roles (separate from plans):

| Role | Description |
|---|---|
| `USER` | Default application user |
| `ADMIN` | Platform operator — bypasses all capability checks |

---

## Feature Gate Map

| Feature | Free | Premium | Premium Plus | Beta |
|---|---|---|---|---|
| Analyze property | ✅ | ✅ | ✅ | ✅ |
| Save property | ✅ (2 max) | ✅ | ✅ | ✅ |
| Basic filters | ✅ | ✅ | ✅ | ✅ |
| Basic comparison of saved properties | ✅ | ✅ | ✅ | ✅ |
| Restore archived property | ❌ | ✅ | ✅ | ✅ |
| AI chat | ❌ | ✅ | ✅ | ✅ |
| AI explanations | ❌ | ✅ | ✅ | ✅ |
| Generate AI reports | ❌ | ✅ | ✅ | ✅ |
| AI negotiation | ❌ | ✅ | ✅ | ✅ |
| Natural language filtering | ❌ | ✅ | ✅ | ✅ |
| Lifestyle score | ❌ | ✅ | ✅ | ✅ |
| Google Maps API | ❌ | ✅ | ✅ | ✅ |
| Walk Score API | ❌ | ✅ | ✅ | ✅ |
| Commute analysis | ❌ | ✅ | ✅ | ✅ |
| Neighborhood enrichment | ❌ | ✅ | ✅ | ✅ |
| Export | ❌ | ✅ | ✅ | ✅ |

---

## Authoritative Entitlements

The shared typed contract is `shared/entitlements.py`. FastAPI enforces account
ownership, operation limits and paid access. Streamlit visibility is not an
authorization boundary. Its `feature_access.py` module is a compatibility
adapter, not an independent entitlement source.

```python
from feature_access import capability, require_capability

# Boolean check
if capability("can_use_google_apis"):
    # make the API call

# Structured check — prevents paid calls for Free users even if UI button is reachable
if prompt := require_capability("can_use_google_apis"):
    st.warning(prompt.message)
    return
# safe to proceed
```

Disabled UI buttons alone are not sufficient. Every paid backend route checks
the authenticated account; frontend preview state must never grant access.
Native table CSV downloads must also be disabled for Free.

---

## Account-Level Property Rule

Free users may have at most **2 active** saved properties in total.
An apartment building counts once, not once per unit. House listings count
once each; apartment and house limits are shared.

When a Free user tries to save a third property:

1. The backend rejects the addition without changing existing records.
2. Updating an existing property does not consume another slot.
3. The user can explicitly remove/archive a property or upgrade.
4. Downgrades retain data and prohibit further additions while over limit.

---

## Monthly Quotas and Legacy Data

Monthly quotas are account-level, shared across apartments and houses, with
calendar-month boundaries in UTC. They are not session counters. Plus has a
finite 500 analyses/month and must not advertise Unlimited.

Separate configurable Premium/Plus starting limits:

- AI operations: 100 / 500.
- Enrichment: 50 / 200.
- Commute: 100 / 400.
- Reports: 20 / 100.

Backend overrides use `NESTAI_QUOTA_<PLAN>_<METRIC>` (for example,
`NESTAI_QUOTA_PREMIUM_AI`). Successful idempotent retries use the existing
account receipt; failed operations do not consume successful-operation quota.
Retain legitimate legacy balances and grants separately without automatic
conversion. Back up SQLite and preserve unassigned legacy homes: random session
identifiers alone do not establish authenticated ownership.

---

## Blocking Paid API Calls for Free Users

The legacy provider modules are retained for compatibility; operational paid
requests go through authenticated backend platform routes. Credentials must
be configured in that service's environment.

| Module | API | Gate |
|---|---|---|
| `enrichment.py` | Google Maps, Walk Score | `can_use_google_apis`, `can_use_walk_score_api`, `can_use_commute_analysis` |
| `llm_helpers.py` | OpenAI | `can_use_ai_chat`, `can_use_ai_explanations`, `can_generate_ai_reports` |

The Homes parser (`parser/home_listing.py`) is deterministic and makes no
external calls. Common numeric natural-language constraints are also
deterministic; unavailable AI must not silently ignore them.

Premium reports and Plus detailed reports require actual downloadable
artifacts. Plus adds cost/space data, contributions and sensitivity analysis,
not decorative explanatory copy. Referrals, priority support and unsupported
early-access promises are outside this MVP; existing records remain preserved.
