# NestAI Property Platform

## Overview

NestAI is expanding from an apartment-only tool into a multi-property-type comparison platform. The application currently supports:

| Property Type | Supported | Workflow |
|---|---|---|
| Apartments (`APARTMENT_BUILDING` / `APARTMENT_UNIT`) | ✅ | Existing Apartments tab |
| Rental Homes (`RENTAL_HOME`) | ✅ | Homes tab |
| Homes for Sale (`HOME_FOR_SALE`) | ✅ | Homes tab |
| Rental Homes (separate tab) | 🔜 Coming soon | — |
| Condos | 🔜 Coming soon | — |
| Townhomes | 🔜 Coming soon | — |
| New Construction | 🔜 Coming soon | — |

---

## Application Structure

```
legacy/streamlit/
├── app.py                  # Main Streamlit entrypoint
├── homes_tab.py            # Homes tab UI (all homes workflow)
├── home_storage.py         # SQLite persistence for saved homes
├── feature_access.py       # Centralized plan/capability/quota service
├── parser/
│   ├── home_listing.py     # Zillow pasted-text parser
│   └── apartment_listing.py
├── text_parser.py          # Apartment parser (unchanged)
├── data/
│   ├── home_example_1.txt  # Canonical Zillow fixture 1 (Valley Dr)
│   └── home_example_2.txt  # Canonical Zillow fixture 2 (Martha Custis Dr)
└── tests/
    ├── test_home_parser.py
    ├── test_feature_access.py
    └── test_home_storage.py

services/api/app/db/models/
├── property.py             # Generic Property model
├── home_details.py         # HomeDetails model
└── usage_event.py          # UsageEvent model

services/api/alembic/versions/
├── 0001_initial_schema.py
└── 0002_property_platform.py
```

---

## Running the Application

```bash
cd legacy/streamlit
streamlit run app.py
```

---

## Running Tests

```bash
cd legacy/streamlit
python -m pytest tests/ -v
```

---

## Homes Tab Workflow

1. Open the **Homes** tab at the top of the application.
2. Click a fixture button (e.g., **3624 Valley Dr**) or paste Zillow listing text.
3. Click **🔍 Analyze Home**.
4. Review the parsed summary: price, beds, baths, sq ft, scores, facts, features.
5. Click **💾 Save Home** to persist the home locally.
6. View all saved homes in the **My Saved Homes** section below.
7. Use the **Filter & Sort** controls to narrow and rank your saved homes.
8. Premium users can view the **Side-by-Side Comparison** table.

---

## Adding New Property Types

1. Add a `property_type` constant to `feature_access.py` (e.g., `"CONDO"`).
2. Create a dedicated parser in `legacy/streamlit/parser/`.
3. Add tests in `legacy/streamlit/tests/`.
4. Create a new tab rendering function following the `render_homes_tab()` pattern.
5. Register the tab in `app.py` alongside the Apartments and Homes tabs.
6. Add a `Condo` detail model in `services/api/app/db/models/` if needed.
7. Add the table to a new Alembic migration.
