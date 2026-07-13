"""AWS runtime client injection boundary.

This module intentionally does not import ``boto3``. The application or future
AgentCore harness must inject a runtime client factory at the outer boundary so
unit tests and package imports never require AWS credentials or network access.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from lovv_agent_v2.infra.config import RuntimeConfig, default_runtime_config

ADAPTER_NAME = "AwsClientFactory"

RESPONSIBILITY = "Create AWS clients lazily from injected runtime config."


# Protocol을 사용해 패키지가 구체적인 boto3 타입에 묶이지 않게 한다.
class AwsClientConfigurationError(RuntimeError):
    """Raised when an AWS client is requested without an injected factory."""


class AwsClientFactory(Protocol):
    """Callable boundary for runtime-owned AWS client construction."""

    def __call__(
        self,
        service_name: str,
        *,
        region_name: str,
    ) -> Any:
        """Return a client for ``service_name`` in ``region_name``."""


@dataclass(frozen=True, slots=True)
class AwsRuntimeClients:
    """Concrete client set passed into repositories at runtime."""

    s3_vectors: Any
    dynamodb: Any
    bedrock_runtime: Any


@dataclass(frozen=True, slots=True)
class AwsClientProvider:
    """Lazy AWS client provider with no global singleton behavior."""

    config: RuntimeConfig
    client_factory: AwsClientFactory | None = None

    @classmethod
    def from_factory(
        cls,
        client_factory: AwsClientFactory,
        config: RuntimeConfig | None = None,
    ) -> "AwsClientProvider":
        """Build a provider from an injected client factory."""

        return cls(
            config=default_runtime_config() if config is None else config,
            client_factory=client_factory,
        )

    def create_s3_vectors_client(self) -> Any:
        """Create the S3 Vector runtime client on demand."""

        return self._create_client("s3vectors")

    def create_dynamodb_client(self) -> Any:
        """Create the DynamoDB runtime client on demand."""

        return self._create_client("dynamodb")

    def create_bedrock_runtime_client(self) -> Any:
        """Create the Bedrock Runtime client on demand."""

        return self._create_client("bedrock-runtime")

    def create_agentcore_identity_client(self) -> Any:
        return self._create_client("bedrock-agentcore")

    def create_runtime_clients(self) -> AwsRuntimeClients:
        """Create runtime clients used by AWS-backed graph adapters."""

        # credential, region, service 이름이 잘못된 경우 repository wiring 단계에서
        # 일찍 실패하도록 런타임 client 묶음을 한 번에 생성한다.
        return AwsRuntimeClients(
            s3_vectors=self.create_s3_vectors_client(),
            dynamodb=self.create_dynamodb_client(),
            bedrock_runtime=self.create_bedrock_runtime_client(),
        )

    def _create_client(self, service_name: str) -> Any:
        """Invoke the injected factory with non-secret runtime routing config."""

        if self.client_factory is None:
            raise AwsClientConfigurationError(
                "AWS clients require an injected client_factory",
            )
        return self.client_factory(
            service_name,
            region_name=self.config.aws.region,
        )


def create_client_provider(
    *,
    config: RuntimeConfig | None = None,
    client_factory: AwsClientFactory | None = None,
) -> AwsClientProvider:
    """Return a provider without creating any AWS clients."""

    return AwsClientProvider(
        config=default_runtime_config() if config is None else config,
        client_factory=client_factory,
    )





# ==================== Boto3 Live Client Factory ====================

"""Lazy boto3 client factory for live AWS runtime execution.

This module is the only adapter boundary that knows how to create boto3
sessions. Importing it does not import boto3 or create clients; the dependency
is loaded only when the returned factory is invoked by a harness or app entry.
"""

from dataclasses import dataclass
from importlib import import_module
from typing import Any


from lovv_agent_v2.infra.config import RuntimeConfig, default_runtime_config

ADAPTER_NAME = "Boto3ClientFactory"

RESPONSIBILITY = "Create live AWS service clients from RuntimeConfig at the harness boundary."


class Boto3ClientFactoryError(RuntimeError):
    """Raised when live boto3 client construction cannot be configured."""


@dataclass(frozen=True, slots=True)
class Boto3ClientFactory:
    """Create boto3 clients without leaking credentials into project config."""

    profile_name: str | None = None
    boto3_module: Any | None = None

    def __call__(self, service_name: str, *, region_name: str) -> Any:
        """Return a boto3 client for one AWS service."""

        module = self.boto3_module
        if module is None:
            # live가 아닌 테스트에서 boto3 설치/설정 없이 패키지를 import할 수 있도록
            # boto3는 실제 client 생성 시점에만 import한다.
            try:
                module = import_module("boto3")
            except ModuleNotFoundError as exc:
                raise Boto3ClientFactoryError(
                    "boto3 is required for live AWS runtime clients",
                ) from exc

        session = (
            module.Session(profile_name=self.profile_name)
            if self.profile_name
            else module.Session()
        )
        return session.client(service_name, region_name=region_name)


def create_boto3_client_factory(
    *,
    profile_name: str | None = None,
    boto3_module: Any | None = None,
) -> AwsClientFactory:
    """Build a live AWS client factory without creating clients immediately."""

    return Boto3ClientFactory(
        profile_name=profile_name,
        boto3_module=boto3_module,
    )


def create_boto3_client_provider(
    *,
    config: RuntimeConfig | None = None,
    boto3_module: Any | None = None,
) -> AwsClientProvider:
    """Build an AwsClientProvider backed by lazy boto3 session creation."""

    resolved_config = default_runtime_config() if config is None else config
    return AwsClientProvider.from_factory(
        create_boto3_client_factory(
            profile_name=resolved_config.aws.profile_name,
            boto3_module=boto3_module,
        ),
        config=resolved_config,
    )





__all__ = [
    "ADAPTER_NAME",
    "RESPONSIBILITY",
    "AwsClientConfigurationError",
    "AwsClientFactory",
    "AwsClientProvider",
    "AwsRuntimeClients",
    "create_client_provider",
    "Boto3ClientFactory",
    "Boto3ClientFactoryError",
    "create_boto3_client_factory",
    "create_boto3_client_provider",
]
