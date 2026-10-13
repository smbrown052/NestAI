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


class Ranking(StrictModel):
    property_ids: list[str] = Field(default_factory=list, max_length=200)
    constraints: dict[str, float | bool] = Field(default_factory=dict)
    priorities: dict[str, float] = Field(default_factory=dict)


class PaidRequest(Idempotent):
    property_ids: list[str] = Field(min_length=1, max_length=200)
    question: str = Field(default="", max_length=4000)
    destination: str = Field(default="", max_length=500)
    mode: Literal["driving", "walking", "bicycling", "transit"] = "transit"
    priorities: dict[str, float] = Field(default_factory=dict)
    constraints: dict[str, float | bool] = Field(default_factory=dict)


class Export(StrictModel):
    property_ids: list[str] = Field(default_factory=list, max_length=200)
    format: Literal["csv", "json"] = "csv"
    scope: Literal["properties", "units"] = "properties"
