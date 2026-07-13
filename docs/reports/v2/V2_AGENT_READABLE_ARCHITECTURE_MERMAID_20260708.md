# Lovv Agent V2 Readable Architecture Mermaid

작성일: 2026-07-08

이 문서는 발표/공유용으로 읽히는 Agent V2 아키텍처다. 세부 node를 전부 펼치기보다, 먼저 경계와 책임이 보이도록 5개 Mermaid로 나눴다.

## 1. Runtime Boundary

```mermaid
flowchart LR
  subgraph Caller["Caller"]
    Client["Client / Backend"]
  end

  subgraph AgentCore["AWS AgentCore Runtime"]
    Endpoint["DEFAULT endpoint\nREADY / liveVersion 3"]
    Runtime["LovvAgentCore_LovvAgentV2-cy3tYk7nV4\nPython 3.12 / VPC"]
    Entrypoint["opentelemetry-instrument main.py\nBedrockAgentCoreApp"]
  end

  subgraph App["Deployable CodeZip: app/LovvAgentV2"]
    Handler["handle_v2_invocation"]
    Harness["build_live_harness"]
    Graph["LangGraph V2"]
  end

  subgraph AWS["AWS Dependencies"]
    Bedrock["Bedrock Runtime\nIntent / Explanation LLM"]
    Embed["Titan Embedding"]
    S3V["S3 Vectors\nlovv-vector-dev / kr-tour-domain-v2"]
    DDB["DynamoDB\nTourKoreaDomainDataV2"]
    ProfileDDB["DynamoDB\nLovvAgentCore-LovvUserProfile"]
    Memory["AgentCore Memory\nLovv_agent_v2_checkpointer"]
    RDS["RDS MySQL\nlovv-dev-mysql / lovvdev"]
    ORS["AgentCore Credential\nors_service_key"]
  end

  Client --> Endpoint --> Runtime --> Entrypoint --> Handler --> Harness --> Graph
  Harness --> Bedrock
  Harness --> Embed
  Harness --> S3V
  Harness --> DDB
  Harness --> ProfileDDB
  Harness --> Memory
  Harness --> RDS
  Harness --> ORS
```

## 2. Supervisor Spine

```mermaid
flowchart TD
  Request["Request\ncreate / clarify / modify / confirm"] --> Intent["Intent Agent\n요청 정규화"]
  Intent --> Supervisor["Supervisor Router\nrouting.next_node 결정"]

  Supervisor --> Profile["Profile\n개인화 weight / confirmation update"]
  Profile --> Supervisor

  Supervisor --> Festival["Festival Verifier\n축제 조건 gate"]
  Festival --> Supervisor

  Supervisor --> City["City Select\n도시/seed 후보 선택"]
  City --> Supervisor

  Supervisor --> Planner["Planner\n장소 검색 / day route / itinerary 조립"]
  Planner --> Supervisor

  Supervisor --> Explain["Explain Itinerary\n상세 설명 보강"]
  Explain --> Supervisor

  Supervisor --> Weather["Weather Alternative\n날씨 리스크 / 대체 옵션"]
  Weather --> Supervisor

  Supervisor --> Response["Response Packager\n최종 payload 또는 interrupt"]
  Response --> Supervisor

  Supervisor --> End["END"]

  Response -. "END_WAIT_USER" .-> Interrupt["LangGraph interrupt\n사용자 선택 대기"]
  Interrupt -. "Command(resume=...)" .-> Intent
```

## 3. Agent Responsibility Map

```mermaid
flowchart LR
  subgraph Input["Input Layer"]
    Intent["Intent\nentry_type 판별\ncity_select_input 생성\nLLM 보조 modify_intent 생성"]
    Profile["Profile\nsaved_trip_count\ntheme_weights\nprofile_update"]
  end

  subgraph Discovery["Discovery Layer"]
    Festival["Festival Verifier\nfestival candidates 검증"]
    City["City Select\nvector search\nDynamo hydrate\ncity scoring"]
  end

  subgraph Planning["Planning Layer"]
    Planner["Planner\nretrieve_places\nroute_days\nassemble_itinerary\napply_edit"]
    Explain["Explain Itinerary\nrecord hydration\nLLM 설명 생성"]
    Weather["Weather Alternative\nweather_audit\nuser_notice"]
  end

  subgraph Output["Output Layer"]
    Response["Response Packager\nresponse_payload\nclarification options\ninterrupt"]
  end

  Intent --> Profile --> Festival --> City --> Planner --> Explain --> Weather --> Response
```

## 4. Planner Internal Flow

```mermaid
flowchart TD
  Entry{"Planner entry"} -->|"일반 생성"| Retrieve["retrieve_places"]
  Entry -->|"slot_replace / day_regenerate"| ApplyEdit["apply_edit"]

  Retrieve --> Search["DestinationSearch + Embedding"]
  Search --> Places["candidate places"]
  Places --> Route["route_days\nanchor / nearest-neighbor / trim / repair"]
  Route --> Travel["ORS travel time\nfallback Haversine"]
  Travel --> Assemble["assemble_itinerary"]

  Assemble --> Retry{"대체 도시 retry 필요?"}
  Retry -->|"yes"| RetryCity["retry_alternative_city"]
  RetryCity --> Retrieve
  Retry -->|"no"| Weather["weather_alternative"]

  ApplyEdit --> Weather
  Weather --> Output["planner_output\nvalidation_result\nweather_risk"]
```

## 5. Request Lifecycle

```mermaid
sequenceDiagram
  participant C as Client/Backend
  participant AC as AgentCore Runtime
  participant H as handle_v2_invocation
  participant G as LangGraph V2
  participant S as Supervisor
  participant A as Worker Agents
  participant R as Response Packager

  C->>AC: invoke payload
  AC->>H: main.py entrypoint
  H->>H: request_id / thread_id / actor_id / resume 추출
  H->>G: graph.invoke(payload, config)
  G->>S: intent 이후 supervisor 진입

  loop until response or end
    S->>A: routing.next_node
    A->>S: state update
  end

  S->>R: response_packager
  alt final response
    R->>H: response_payload
    H->>AC: dict response
    AC->>C: result
  else clarification needed
    R->>G: interrupt(response_payload)
    G->>H: END_WAIT_USER
    H->>AC: clarification payload
    AC->>C: user choice required
    C->>AC: resume payload
    AC->>H: Command(resume=...)
  end
```

## Key Notes

- 현재 live V2 runtime은 `LovvAgentCore_LovvAgentV2-cy3tYk7nV4`이고 `READY`, `liveVersion=3`이다.
- 실제 배포 기준 코드는 `app/LovvAgentV2/`이다. `src/lovv_agent_v2/`는 개발 소스지만 AgentCore CodeZip 기준 truth surface는 아니다.
- Supervisor는 전체 worker를 직접 실행하는 agent가 아니라 deterministic router다. 핵심 출력은 `routing.next_node`다.
- 일반 생성 흐름은 `Intent -> Profile -> Festival -> City Select -> Planner -> Explain -> Weather -> Response`로 읽으면 된다.
- `Response Packager`만 사용자 대기를 만들 수 있다. 이때 LangGraph `interrupt`가 발생하고 다음 호출은 `Command(resume=...)`로 이어진다.
- live AWS는 VPC 배포다. 로컬 `agentcore/agentcore.json`의 `networkMode=PUBLIC`과 현재 live 상태가 다르다.
