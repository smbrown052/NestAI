# NestAI Pricing and Feature Gates

## Plans

| Plan | Price | Monthly Analyses | Saved Properties | Paid APIs |
|---|---|---|---|---|
| **Free** | $0 | 5 | 1 active | ❌ None |
| **Premium** | $24.99/mo | 100 | 50 | ✅ All |
| **Premium Plus** | TBD | 500 | 200 | ✅ All |
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
| Save property | ✅ (1 max) | ✅ | ✅ | ✅ |
| Basic filters | ✅ | ✅ | ✅ | ✅ |
| Compare multiple properties | ❌ | ✅ | ✅ | ✅ |
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

## How Capability Checks Work

All capability checks go through `feature_access.py`:

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

**`require_capability()` is required at every paid API entrypoint.**  
Disabled UI buttons alone are not sufficient — enforce at the function level.

---

## Free-Plan One-Active-Property Rule

Free users may have at most **1 active** saved property.

When a Free user tries to save a second property:

1. The UI shows a replacement prompt.
2. If confirmed, the existing active property is archived (never deleted).
3. The new property is saved as the active one.
4. The archived property is recoverable after a plan upgrade.

---

## NOTE: Local / Session-Based Enforcement

Plan state and quota tracking are currently **session-scoped** (Streamlit session state + local SQLite).

This means:

- Plan state does not persist across browser sessions.
- Quota reset on session refresh.
- Ownership is identified by a randomly generated `session_id`, not a verified account.

These controls are intentionally local for the current phase.  
All capability checks are behind clean interfaces (`feature_access.py`, `home_storage.py`) so the backing store can be replaced by an API-driven identity/quota service without changing call sites.

---

## Blocking Paid API Calls for Free Users

External API call sites are in:

| Module | API | Gate |
|---|---|---|
| `enrichment.py` | Google Maps, Walk Score | `can_use_google_apis`, `can_use_walk_score_api`, `can_use_commute_analysis` |
| `llm_helpers.py` | OpenAI | `can_use_ai_chat`, `can_use_ai_explanations`, `can_generate_ai_reports` |

Each function at these sites must call `require_capability(...)` before making the external request.  
The Homes parser (`parser/home_listing.py`) is **deterministic** and makes no external calls.
