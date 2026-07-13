from __future__ import annotations

import os
from typing import Protocol, TypedDict

from botocore.exceptions import BotoCoreError, ClientError
from lovv_agent_v2.infra.aws_clients import create_boto3_client_factory

DEFAULT_CREDENTIAL_ENV_VAR = "CREDENTIAL_ORS_SERVICE_KEY_NAME"
DEFAULT_REGION = "us-east-1"
DEFAULT_USER_ID = "lovv-runtime"


class WorkloadTokenResponse(TypedDict):
    workloadAccessToken: str


class ApiKeyResponse(TypedDict):
    apiKey: str


class AgentCoreIdentityClient(Protocol):
    def get_workload_access_token_for_user_id(
        self,
        *,
        workloadName: str,
        userId: str,
    ) -> WorkloadTokenResponse: ...

    def get_resource_api_key(
        self,
        *,
        workloadIdentityToken: str,
        resourceCredentialProviderName: str,
    ) -> ApiKeyResponse: ...


def resolve_agentcore_api_key(
    credential_env_var: str = DEFAULT_CREDENTIAL_ENV_VAR,
    client: AgentCoreIdentityClient | None = None,
) -> str | None:
    provider_name = _env_text(credential_env_var)
    workload_name = _env_text("LOVV_AGENTCORE_WORKLOAD_NAME")
    if provider_name is None or workload_name is None:
        return None
    user_id = _env_text("LOVV_AGENTCORE_USER_ID") or DEFAULT_USER_ID
    try:
        identity_client = client or _agentcore_client()
        token = identity_client.get_workload_access_token_for_user_id(
            workloadName=workload_name,
            userId=user_id,
        )["workloadAccessToken"]
        return identity_client.get_resource_api_key(
            workloadIdentityToken=token,
            resourceCredentialProviderName=provider_name,
        )["apiKey"]
    except (BotoCoreError, ClientError, KeyError):
        return None


def _agentcore_client() -> AgentCoreIdentityClient:
    client_factory = create_boto3_client_factory()
    return client_factory("bedrock-agentcore", region_name=_region())


def _region() -> str:
    return _env_text("LOVV_AWS_REGION") or os.getenv("AWS_REGION") or DEFAULT_REGION


def _env_text(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


__all__ = [
    "DEFAULT_CREDENTIAL_ENV_VAR",
    "resolve_agentcore_api_key",
]
