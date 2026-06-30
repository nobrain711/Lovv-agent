"""AgentCore Runtime app for LovvAgentV2."""

from __future__ import annotations

from pathlib import Path

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from dotenv import load_dotenv

# agentcore dev does not inject agentcore.json envVars into the local process.
# The repository-level .env.local is absent from the deployed CodeZip, and
# override=False preserves variables explicitly supplied by the environment.
load_dotenv(Path(__file__).resolve().parents[2] / ".env.local", override=False)

from lovv_agent_v2.agentcore_entrypoint import handle_v2_invocation
from lovv_agent_v2.common.telemetry import init_telemetry

init_telemetry()
app = BedrockAgentCoreApp()


@app.entrypoint
async def invoke(payload, context):
    """Invoke the Lovv V2 recommendation graph inside AgentCore Runtime."""

    return handle_v2_invocation(payload, context)


if __name__ == "__main__":
    app.run()
