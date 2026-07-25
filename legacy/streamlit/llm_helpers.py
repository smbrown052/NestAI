import json
import streamlit as st
from openai import OpenAI


PREFERENCE_SCHEMA = {
    "name": "apartment_preferences",
    "schema": {
        "type": "object",
        "properties": {
            "must_haves": {
                "type": "object",
                "properties": {
                    "max_price": {"type": ["integer", "null"]},
                    "min_sqft": {"type": ["integer", "null"]},
                    "beds": {"type": ["number", "null"]},
                    "baths": {"type": ["number", "null"]},
                    "availability": {
                        "type": ["string", "null"],
                        "enum": [None, "now", "within_7_days", "within_30_days"]
                    }
                },
                "required": ["max_price", "min_sqft", "beds", "baths", "availability"],
                "additionalProperties": False
            },
            "nice_to_haves": {
                "type": "object",
                "properties": {
                    "low_price": {"type": "number"},
                    "large_space": {"type": "number"},
                    "soon_available": {"type": "number"}
                },
                "required": ["low_price", "large_space", "soon_available"],
                "additionalProperties": False
            },
            "user_summary": {"type": "string"}
        },
        "required": ["must_haves", "nice_to_haves", "user_summary"],
        "additionalProperties": False
    }
}


def get_openai_client():
    api_key = st.secrets.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("Missing OPENAI_API_KEY in Streamlit secrets.")
    return OpenAI(api_key=api_key)


def parse_preferences_with_llm(user_query: str) -> dict:
    client = get_openai_client()

    response = client.responses.create(
        model="gpt-5-mini",
        input=[
            {
                "role": "system",
                "content": (
                    "Extract apartment preferences from the user's request. "
                    "Only use fields in the schema. "
                    "If the user does not specify something, return null for must_haves "
                    "and reasonable weights from 0.0 to 1.0 for nice_to_haves."
                )
            },
            {
                "role": "user",
                "content": user_query
            }
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": PREFERENCE_SCHEMA["name"],
                "schema": PREFERENCE_SCHEMA["schema"],
                "strict": True
            }
        }
    )

    return json.loads(response.output_text)


def generate_rationale_with_llm(user_query: str, prefs: dict, top_results: list[dict]) -> str:
    client = get_openai_client()

    response = client.responses.create(
        model="gpt-5-mini",
        input=[
            {
                "role": "system",
                "content": (
                    "You explain apartment ranking results. "
                    "Be concise, specific, and do not invent facts. "
                    "Use only the data provided."
                )
            },
            {
                "role": "user",
                "content": (
                    f"User request:\n{user_query}\n\n"
                    f"Parsed preferences:\n{json.dumps(prefs, indent=2)}\n\n"
                    f"Top ranked options:\n{json.dumps(top_results, indent=2)}\n\n"
                    "Write 3 short bullets, one per option, explaining why each ranked well and mention any tradeoff."
                )
            }
        ]
    )

    return response.output_text.strip()


# ── AI Rent Negotiator ────────────────────────────────────────────────────────

def generate_negotiation_script(unit: dict, comparables: list[dict]) -> str:
    """
    Generate a negotiation email, talking points, and concession requests
    for a specific unit, using nearby comparable listings for leverage.
    """
    client = get_openai_client()

    unit_summary = {
        k: unit.get(k)
        for k in [
            "property", "unit", "price", "price_num",
            "beds", "baths", "sqft", "availability", "address",
        ]
    }
    comp_summary = [
        {k: c.get(k) for k in ["property", "unit", "price", "price_num", "beds", "sqft"]}
        for c in comparables
    ]

    response = client.responses.create(
        model="gpt-5-mini",
        input=[
            {
                "role": "system",
                "content": (
                    "You are an expert apartment negotiator helping a renter secure the best deal. "
                    "Write a professional, specific negotiation email and talking points. "
                    "Be concise, cite only the data provided, and do not invent facts."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Target apartment:\n{json.dumps(unit_summary, indent=2)}\n\n"
                    f"Comparable listings (for leverage):\n{json.dumps(comp_summary, indent=2)}\n\n"
                    "Please produce:\n"
                    "### Negotiation Email\n"
                    "A concise, professional email to the property manager.\n\n"
                    "### Talking Points\n"
                    "Three specific points to raise in conversation.\n\n"
                    "### Concessions to Request\n"
                    "Two realistic concessions (e.g., one month free, waived parking fee).\n"
                ),
            },
        ],
    )
    return response.output_text.strip()


# ── AI Apartment Advisor ──────────────────────────────────────────────────────

def advisor_chat_response(
    user_message: str,
    history: list[dict],
    units_context: list[dict],
) -> str:
    """
    Return an AI advisor reply given the full conversation history and saved units.

    history: list of {"role": "user"|"assistant", "content": str} dicts.
    units_context: list of unit dicts from the comparison DataFrame.
    """
    client = get_openai_client()

    keep_keys = [
        "property", "unit", "price_num", "sqft_num",
        "beds_num", "baths_num", "floor", "availability",
        "nearest_metro", "metro_min",
        "walk_score", "safety_score",
        "commute_driving_min", "commute_transit_min",
        "commute_display", "lifestyle_summary",
        "address",
    ]
    units_json = json.dumps(
        [{k: u.get(k) for k in keep_keys} for u in units_context],
        indent=2,
    )

    system_prompt = (
        "You are a personal AI apartment advisor. "
        "Help the user find the best apartment for their specific lifestyle, commute, and budget. "
        "When recommending, explain why and surface any tradeoffs. "
        "When advising someone to skip an option, say clearly why. "
        "Answer natural language questions like 'which has the fastest commute for both of us?' "
        "Be conversational, specific, and concise. Use only the data provided.\n\n"
        f"Available apartments:\n{units_json}"
    )

    messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_message})

    response = client.responses.create(
        model="gpt-5-mini",
        input=messages,
    )
    return response.output_text.strip()
