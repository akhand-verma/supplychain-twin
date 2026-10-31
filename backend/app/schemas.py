from pydantic import BaseModel, ConfigDict, Field, field_validator

from .catalog import POLICY_KEYS, SCENARIO_KEYS


def check_policy(v: str) -> str:
    if v not in POLICY_KEYS:
        raise ValueError(f"policy must be one of {POLICY_KEYS}")
    return v


def check_scenario(v: str) -> str:
    if v not in SCENARIO_KEYS:
        raise ValueError(f"scenario must be one of {SCENARIO_KEYS}")
    return v


class SimulateRequest(BaseModel):
    policy: str
    scenario: str = "baseline"
    seed: int = Field(0, ge=0)

    @field_validator("policy")
    @classmethod
    def validate_policy(cls, v: str) -> str:
        return check_policy(v)

    @field_validator("scenario")
    @classmethod
    def validate_scenario(cls, v: str) -> str:
        return check_scenario(v)


class MonteCarloRequest(BaseModel):
    policies: list[str] = Field(min_length=1)
    scenario: str = "baseline"
    n_runs: int = Field(100, ge=10, le=500)

    @field_validator("policies")
    @classmethod
    def validate_policies(cls, v: list[str]) -> list[str]:
        for p in v:
            check_policy(p)
        return v

    @field_validator("scenario")
    @classmethod
    def validate_scenario(cls, v: str) -> str:
        return check_scenario(v)


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: str
    status: str
    params: dict
    result: dict | None = None
    error: str | None = None