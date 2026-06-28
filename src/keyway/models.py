"""Pydantic request schemas for the LLM admin API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LLMGroupCreateRequest(BaseModel):
    group_id: str = Field(..., min_length=1, max_length=64, pattern=r".*[a-zA-Z0-9].*")
    name: str = Field(..., min_length=1, max_length=128)
    note: str = Field(default="", max_length=512)


class LLMGroupUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    enabled: bool | None = None
    note: str | None = Field(default=None, max_length=512)


class LLMGroupCopyRequest(BaseModel):
    new_name: str = Field(..., min_length=1, max_length=128)
    new_group_id: str | None = Field(default=None, max_length=64, pattern=r".*[a-zA-Z0-9].*")


class LLMProviderCreateRequest(BaseModel):
    provider_id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=128)
    base_url: str = Field(..., min_length=1, max_length=512)
    api_key: str = Field(..., min_length=1, max_length=4096)
    protocol: str = Field(default="openai", max_length=16)
    note: str = Field(default="", max_length=512)


class LLMProviderUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    base_url: str | None = Field(default=None, max_length=512)
    api_key: str | None = Field(default=None, max_length=4096)
    protocol: str | None = Field(default=None, max_length=16)
    enabled: bool | None = None
    note: str | None = Field(default=None, max_length=512)


class LLMRouteCreateRequest(BaseModel):
    alias: str = Field(..., min_length=1, max_length=128)
    provider_id: str = Field(..., min_length=1, max_length=64)
    upstream_model: str = Field(..., min_length=1, max_length=256)
    upstream_path: str = Field(default="", max_length=256)
    mode: str = Field(default="direct", max_length=16)
    adapter_config: str = Field(default="{}", max_length=4096)
    fusion_config: str = Field(default="{}", max_length=4096)
    note: str = Field(default="", max_length=512)


class LLMRouteUpdateRequest(BaseModel):
    alias: str | None = Field(default=None, max_length=128)
    provider_id: str | None = Field(default=None, max_length=64)
    upstream_model: str | None = Field(default=None, max_length=256)
    upstream_path: str | None = Field(default=None, max_length=256)
    mode: str | None = Field(default=None, max_length=16)
    adapter_config: str | None = Field(default=None, max_length=4096)
    fusion_config: str | None = Field(default=None, max_length=4096)
    enabled: bool | None = None
    note: str | None = Field(default=None, max_length=512)


class LLMRouteProviderCreateRequest(BaseModel):
    provider_id: str = Field(..., min_length=1, max_length=64)
    upstream_model: str = Field(..., min_length=1, max_length=256)
    priority: int = Field(default=0)
    enabled: bool = Field(default=True)


class LLMRouteProviderUpdateRequest(BaseModel):
    priority: int | None = None
    enabled: bool | None = None
    upstream_model: str | None = Field(default=None, max_length=256)


class LLMKeyCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    expires_at: str | None = Field(default=None, max_length=64)
    owner_user_id: str | None = Field(default=None, max_length=64)


class LLMKeyUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    enabled: bool | None = None
    expires_at: str | None = Field(default=None, max_length=64)


class LLMToolProviderCreateRequest(BaseModel):
    tool_id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=128)
    api_key: str = Field(..., min_length=1, max_length=4096)
    config: str = Field(default="{}", max_length=4096)


class LLMToolProviderUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    api_key: str | None = Field(default=None, max_length=4096)
    config: str | None = Field(default=None, max_length=4096)
    enabled: bool | None = None


class LLMTestRequest(BaseModel):
    """Admin-only LLM connectivity probe. Exactly one of provider_id / alias must be set."""
    provider_id: str | None = Field(default=None, max_length=64)
    alias: str | None = Field(default=None, max_length=128)


class AdminLoginRequest(BaseModel):
    token: str = Field(..., min_length=1, max_length=256)
