"""Thin LLM boundary for the judge.

Same shape as the boundary inside the system under test: one function, structured
output, retries, and no raw model text anywhere else in the codebase. Judges get
held to the reliability standard they are measuring.

Temperature is pinned to 0. A judge that disagrees with itself on reruns adds
variance to the very number the gate is trying to read.
"""
from __future__ import annotations

from typing import Type, TypeVar

from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential

from .config import judge_model, require_api_key

T = TypeVar("T", bound=BaseModel)

_clients: dict[str, object] = {}


def _client(model: str):
    if model not in _clients:
        from langchain_openai import ChatOpenAI

        _clients[model] = ChatOpenAI(
            model=model, api_key=require_api_key(), temperature=0,
        )
    return _clients[model]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
def structured(prompt: str, schema: Type[T], *, model: str | None = None) -> T:
    """Invoke the judge model and return a validated `schema` instance."""
    llm = _client(model or judge_model()).with_structured_output(schema)
    return llm.invoke(prompt)  # type: ignore[return-value]
