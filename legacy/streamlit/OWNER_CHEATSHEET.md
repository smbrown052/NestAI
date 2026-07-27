# NestAI Owner / Development Cheat Sheet

## Quick-Start: Owner Test Mode (Unlimited)

Owner Test Mode unlocks every NestAI feature and bypasses all product quotas.
External API calls are still gated by whether the API key is configured in
`st.secrets` — OWNER_TEST only removes NestAI's own product limits, not missing
credentials.

### Activation

**PowerShell (Windows)**
```powershell
$env:NESTAI_OWNER_MODE = "true"
python -m streamlit run legacy/streamlit/app.py
```

**Bash / macOS / Linux**
```bash
NESTAI_OWNER_MODE=true python -m streamlit run legacy/streamlit/app.py
# or export for the entire shell session:
export NESTAI_OWNER_MODE=true
python -m streamlit run legacy/streamlit/app.py
```

### What you get

| Feature | Status |
|---|---|
| Property analyses | Unlimited |
| Saved properties | Unlimited |
| Multi-property comparison | ✅ |
| Natural-language filtering | ✅ |
| Lifestyle Score | ✅ |
| AI explanations and reports | ✅ |
| Commute analysis (Google Maps) | ✅ (needs API key) |
| Walk Score / neighborhood enrichment | ✅ (needs API key) |
| AI rent negotiation | ✅ (needs OpenAI key) |
| AI chat advisor | ✅ (needs OpenAI key) |
| Exports | ✅ |

### Sidebar badge in Owner Test Mode
The sidebar shows:
```
🔑 Owner Test Mode — Unlimited
Property analyses: Unlimited
Saved properties: Unlimited
AI usage: Unlimited
Google usage: Unlimited
```

### Deactivation

**PowerShell**
```powershell
Remove-Item Env:NESTAI_OWNER_MODE
```

**Bash**
```bash
unset NESTAI_OWNER_MODE
```

---

## Development Plan Switcher

The in-app plan switcher lets you preview any plan without restarting.

### Activation

**PowerShell**
```powershell
$env:NESTAI_DEV_MODE = "true"
python -m streamlit run legacy/streamlit/app.py
```

**Bash**
```bash
NESTAI_DEV_MODE=true python -m streamlit run legacy/streamlit/app.py
```

### Usage

When `NESTAI_DEV_MODE=true`, a **"🛠 Development Plan Preview"** expander appears
in the sidebar under the plan badge.  Select any plan from the dropdown and click
**"Apply Plan"** to switch instantly.

Available selections:
- **Free** — default; 5 analyses, 1 saved property
- **Premium** — 100 analyses, 50 saved properties, all core features
- **Premium Plus** — 500 analyses, 200 saved properties, advanced features
- **Beta** — Premium capabilities with admin-configurable quotas
- **Owner Test (Unlimited)** — same as `NESTAI_OWNER_MODE=true`

> ⚠️ The switcher is hidden when neither `NESTAI_DEV_MODE` nor
> `NESTAI_OWNER_MODE` is set.  It is never shown to end users in production.

### Deactivation

**PowerShell**
```powershell
Remove-Item Env:NESTAI_DEV_MODE
```

**Bash**
```bash
unset NESTAI_DEV_MODE
```

---

## Combining Both Flags

You can use both flags together to get the dev switcher AND start in Owner Test Mode:

```powershell
$env:NESTAI_OWNER_MODE = "true"
$env:NESTAI_DEV_MODE   = "true"
python -m streamlit run legacy/streamlit/app.py
```

---

## Testing

Run the full test suite from the `legacy/streamlit` directory:

```bash
cd legacy/streamlit
python -m pytest tests/ -v
```

Run only plan-related tests:

```bash
python -m pytest tests/test_plan_ui.py -v
python -m pytest tests/test_feature_access.py -v
```

---

## Architecture Notes

- **Single source of truth for plan state:** `feature_access.py` (`nestai_plan` in `session_state`)
- `credits.py` syncs via `nestai_tier` for backwards compatibility
- `plan_ui.py` renders all pricing/plan UI; import `render_plan_sidebar`, `render_pricing_cards`, `render_upgrade_prompt`
- `OWNER_TEST` is never shown on the public pricing page
- Quota functions return `None` (not a large integer) to represent unlimited
