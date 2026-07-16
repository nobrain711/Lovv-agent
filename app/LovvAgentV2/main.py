"""AgentCore Runtime app for LovvAgentV2."""

from __future__ import annotations

from pathlib import Path

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from dotenv import load_dotenv

# agentcore dev does not inject agentcore.json envVars into the local process.
# The V2 env file is absent from the deployed CodeZip, and override=False
# preserves variables explicitly supplied by the environment.
APP_DIR = Path(__file__).resolve().parent

for env_path in (
    APP_DIR / ".env.v2.local",
    *(parent / ".env.v2.local" for parent in APP_DIR.parents),
):
    load_dotenv(env_path, override=False)

from lovv_agent_v2.agentcore_entrypoint import handle_v2_invocation
from lovv_agent_v2.common.runtime_logging import configure_runtime_logging
from lovv_agent_v2.common.telemetry import init_telemetry

configure_runtime_logging()
init_telemetry()

# Activate ADOT LangChain instrumentation manually.
# When the runtime process is NOT launched via `opentelemetry-instrument` CLI,
# the distro's instrumentors are not auto-loaded. We explicitly instrument
# LangChain so that ADOT's callback handler creates invoke_agent/chain/llm
# spans that AgentCore observability can display.
try:
    from amazon.opentelemetry.distro.instrumentation.langchain import LangChainInstrumentor
    LangChainInstrumentor().instrument()
    import json as _json
    print(_json.dumps({"logType": "LANGCHAIN_INSTRUMENTOR", "status": "success"}))
except Exception as _instr_err:  # noqa: BLE001
    import json as _json
    print(_json.dumps({"logType": "LANGCHAIN_INSTRUMENTOR", "status": "failed", "error": str(_instr_err)}))

app = BedrockAgentCoreApp()


@app.entrypoint
async def invoke(payload, context):
    """Invoke the Lovv V2 recommendation graph inside AgentCore Runtime."""
    import os
    if not os.getenv("ORS_API_KEY"):
        try:
            import boto3, json as _j
            sm = boto3.client("secretsmanager", region_name="us-east-1")
            secret = sm.get_secret_value(
                SecretId="bedrock-agentcore-identity!default/apikey/ors_service_key-95fa23b5"
            )
            secret_data = _j.loads(secret["SecretString"])
            # Token Vault stores the key as {"api_key_value": "..."}
            api_key = (
                secret_data.get("api_key_value")
                or secret_data.get("apiKey")
                or secret_data.get("api_key")
                or (secret_data if isinstance(secret_data, str) else None)
            )
            if api_key:
                os.environ["ORS_API_KEY"] = str(api_key)
        except Exception:  # noqa: BLE001
            pass

    return handle_v2_invocation(payload, context)


if __name__ == "__main__":
    app.run()
