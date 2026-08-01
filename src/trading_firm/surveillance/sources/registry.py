"""The versioned source registry (§30.8) — one file, one loader, no add().

Modeled on the specialist bench: the registry is exposed as a frozen mapping
precisely so a session cannot extend it at runtime. Registering a source is a
config change under version control; approving one for production is an owner
action carried by an approval record, because an unapproved free source must
not silently become production-critical (§30.8).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

REGISTRY_PATH = (
    Path(__file__).resolve().parents[4] / "config" / "registries" / "sources.yaml"
)
CONTEXT_INSTRUMENTS_PATH = (
    Path(__file__).resolve().parents[4]
    / "config"
    / "registries"
    / "market_context_instruments.yaml"
)

# Same shape rule as the bench's reproducible ids: lowercase dotted words,
# never prose — a source id appears in immutable events and health records.
_SOURCE_ID = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$")
_INSTRUMENT_ID = re.compile(r"^[A-Z][A-Z0-9]*(_[A-Z0-9]+)*$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceRecord(_Strict):
    """§30.8 registry entry for one approved external intelligence source."""

    source_id: str
    source_type: Literal["broker", "official", "calendar", "news", "market_data", "derived"]
    provider_name: str
    base_url_or_connector_reference: str | None = None
    assets_or_currencies: list[str]
    auth_required: bool
    polling_policy: str
    rate_limit_policy: str
    freshness_sla_seconds: int | None = Field(default=None, gt=0)
    priority: int = Field(ge=1)
    reliability_tier: int = Field(ge=1, le=5)
    license_or_usage_notes: str
    production_approved: bool
    fail_closed_when_unavailable: bool
    approval_record_id: str | None = None
    research_only: bool = False

    @field_validator("source_id")
    @classmethod
    def _reproducible_id(cls, value: str) -> str:
        if not _SOURCE_ID.match(value):
            raise ValueError(
                f"source_id {value!r} is not a reproducible identifier: lowercase "
                f"dotted words only, because it appears in immutable events (§30.8)"
            )
        return value

    @model_validator(mode="after")
    def _production_needs_an_owner(self) -> SourceRecord:
        if self.production_approved and not self.approval_record_id:
            raise ValueError(
                f"{self.source_id}: production_approved requires approval_record_id — "
                f"do not allow an unapproved free source to silently become "
                f"production-critical (§30.8)"
            )
        if self.production_approved and self.research_only:
            raise ValueError(
                f"{self.source_id}: research_only and production_approved contradict; "
                f"a source suitable only for research is marked accordingly (§30.8)"
            )
        return self


class SourceRegistry(_Strict):
    version: str
    sources: list[SourceRecord]

    @model_validator(mode="after")
    def _ids_unique(self) -> SourceRegistry:
        seen: set[str] = set()
        for record in self.sources:
            if record.source_id in seen:
                raise ValueError(f"duplicate source_id {record.source_id!r} (§30.8)")
            seen.add(record.source_id)
        return self

    @property
    def by_id(self) -> Mapping[str, SourceRecord]:
        """Frozen view — the registry has no add(); registration is a config
        change under version control, never a runtime call (§30.8)."""
        return MappingProxyType({record.source_id: record for record in self.sources})

    def require(self, source_id: str) -> SourceRecord:
        record = self.by_id.get(source_id)
        if record is None:
            raise KeyError(
                f"source {source_id!r} is not in the registry; adapters refuse "
                f"unregistered sources (§30.8)"
            )
        return record


def load_source_registry(path: str | Path = REGISTRY_PATH) -> SourceRegistry:
    raw = yaml.safe_load(Path(path).read_text())
    if not isinstance(raw, dict) or set(raw) != {"source_registry"}:
        raise ValueError(f"{path}: expected a single top-level 'source_registry' key (§30.8)")
    return SourceRegistry.model_validate(raw["source_registry"])


def load_context_instruments(path: str | Path = CONTEXT_INSTRUMENTS_PATH) -> tuple[str, ...]:
    """Approved cross-market context instruments (§30.3.G). Empty until the
    Cross-Market Monitor's domain is enabled and instruments are ratified."""
    raw = yaml.safe_load(Path(path).read_text())
    if not isinstance(raw, dict) or set(raw) != {"context_instruments"}:
        raise ValueError(
            f"{path}: expected a single top-level 'context_instruments' key (§30.8)"
        )
    instruments = raw["context_instruments"] or []
    bad = [i for i in instruments if not _INSTRUMENT_ID.match(str(i))]
    if bad:
        raise ValueError(
            f"context instruments {bad} are not instrument ids; the Cross-Market "
            f"Monitor tracks approved contextual instruments only (§30.3)"
        )
    return tuple(instruments)
