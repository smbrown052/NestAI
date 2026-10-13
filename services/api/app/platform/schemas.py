from typing import Literal
from pydantic import BaseModel, Field, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Idempotent(StrictModel):
    idempotency_key: str = Field(min_length=1, max_length=128)


class Analysis(Idempotent):
    kind: Literal["apartment", "home", "rental_home"]
    text: str = Field(min_length=1, max_length=200_000)


class SaveProperty(Idempotent):
    kind: Literal["apartment", "home", "rental_home"]
    parsed: dict
    external_id: str | None = Field(default=None, min_length=1, max_length=128)


class Profile(StrictModel):
    preferences: dict


class ProfilePatch(StrictModel):
    display_name: str = Field(max_length=120)


class Fees(StrictModel):
    parking: float | None = Field(default=None, ge=0)
    utilities: float | None = Field(default=None, ge=0)
    pet_fee: float | None = Field(default=None, ge=0)
    renters_insurance: float | None = Field(default=None, ge=0)
    other: float | None = Field(default=None, ge=0)


class PropertyPatch(StrictModel):
    fees: Fees


class Empty(StrictModel):
    pass


class NaturalRequest(StrictModel):
    request: str = Field(max_length=4000)


class Feedback(Idempotent):
    category: Literal["bug", "feature", "feedback", "general"] = "feedback"
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(min_length=1, max_length=20_000)
    actual_behavior: str | None = Field(default=None, max_length=10_000)
    expected_behavior: str | None = Field(default=None, max_length=10_000)
    route_or_screen: str | None = Field(default=None, max_length=128)
    user_contact_allowed: bool = False


class Recovery(Idempotent):
    pass


class Ranking(StrictModel):
    property_ids: list[str] = Field(default_factory=list, max_length=200)
    constraints: dict = Field(default_factory=dict)
    priorities: dict[str, float] = Field(default_factory=dict)


class PaidRequest(Idempotent):
    property_ids: list[str] = Field(min_length=1, max_length=200)
    question: str = Field(default="", max_length=4000)
    destination: str = Field(default="", max_length=500)
    mode: Literal["driving", "walking", "bicycling", "transit"] = "transit"
    priorities: dict[str, float] = Field(default_factory=dict)
    constraints: dict = Field(default_factory=dict)


class Export(StrictModel):
    property_ids: list[str] = Field(default_factory=list, max_length=200)
    format: Literal["csv", "json"] = "csv"
    scope: Literal["properties", "units"] = "properties"
    constraints: dict = Field(default_factory=dict)
    priorities: dict[str, float] = Field(default_factory=dict)
