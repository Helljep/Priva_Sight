"""Request / response shapes for the planner API."""
from typing import Literal, Optional

from pydantic import BaseModel, Field


class PlanRequest(BaseModel):
    goal: str
    history: list[str] = Field(default_factory=list)
    url: str = ""
    title: str = ""
    elements: list[dict] = Field(default_factory=list)
    visibleText: list[str] = Field(default_factory=list)
    scroll: dict = Field(default_factory=dict)
    screenshot: Optional[str] = None  # data URL of the SANITISED screenshot


class Action(BaseModel):
    type: Literal["click", "type", "select", "scroll", "navigate", "wait", "done", "fail"]
    id: Optional[int] = None
    text: Optional[str] = None          # may contain tokens such as [EMAIL_1] or {PASSWORD}
    direction: Optional[Literal["up", "down"]] = None
    url: Optional[str] = None
    submit: bool = False
    answer: Optional[str] = None
    reason: Optional[str] = None


class PlanResponse(BaseModel):
    action: Action
    thought: str = ""
    backend: str = ""
