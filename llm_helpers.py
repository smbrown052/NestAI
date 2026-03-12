import json
from openai import OpenAI

client = OpenAI()


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
    },
    "strict": True
}


def parse_preferences_with_llm(user_query: str) -> dict:
    response = client.responses.create(
        model="gpt-5-mini",
        input=[
            {
                "role": "system",
                "content": (
                    "Extract apartment preferences from the user's request. "
                    "Only use fields in the schema. "
                    "If the user does not specify something, return null for must_haves "
                    "and a reasonable default weight from 0.0 to 1.0 for nice_to_haves."
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
                    "Write 3 short bullets, one per option, explaining why each ranked well "
                    "and mention any tradeoff."
                )
            }
        ]
    )

    return response.output_text.strip()