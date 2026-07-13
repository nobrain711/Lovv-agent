# Lovv Agent V2 Agent/Supervisor and Tool Graph

작성일: 2026-07-08

이 문서는 두 가지 관점만 담는다.

1. 전체 구조도: Agent와 Supervisor만 보이게 단순화한다.
2. Tool 구조도: 각 Agent가 사용하는 tool/runtime 의존성을 LangGraph처럼 연결한다.

## 1. Agent + Supervisor 전체 구조도

```mermaid
flowchart TD
  Start["Request\ncreate / clarify / modify / confirm"] --> Intent["Intent Agent"]
  Intent --> Supervisor["Supervisor Router"]

  Supervisor -->|"profile"| Profile["Profile Agent"]
  Profile --> Supervisor

  Supervisor -->|"festival_verifier"| Festival["Festival Verifier Agent"]
  Festival --> Supervisor

  Supervisor -->|"city_select"| City["City Select Agent"]
  City --> Supervisor

  Supervisor -->|"planner"| Planner["Planner Agent"]
  Planner --> Supervisor

  Supervisor -->|"explain_itinerary"| Explain["Explain Itinerary Agent"]
  Explain --> Supervisor

  Supervisor -->|"weather_alternative"| Weather["Weather Alternative Agent"]
  Weather --> Supervisor

  Supervisor -->|"response_packager"| Response["Response Packager Agent"]
  Response --> Supervisor

  Supervisor -->|"end"| End["END"]

  Response -. "END_WAIT_USER / interrupt" .-> UserWait["User Wait"]
  UserWait -. "Command(resume=...)" .-> Intent
```

## 2. Agent Tool Graph

```mermaid
flowchart LR
  subgraph Graph["LangGraph V2 Runtime"]
    Intent["Intent Agent"]
    Supervisor["Supervisor Router"]
    Profile["Profile Agent"]
    Festival["Festival Verifier Agent"]
    City["City Select Agent"]
    Planner["Planner Agent"]
    Explain["Explain Itinerary Agent"]
    Weather["Weather Alternative Agent"]
    Response["Response Packager Agent"]
  end

  subgraph Tools["Injected Tools / Runtime Containers"]
    IntentRuntime["IntentPromptRuntime"]
    CityTools["CitySelectTools"]
    CityScoring["CitySelectScoringTools"]
    FestivalTools["FestivalVerifierTools"]
    PlannerTools["PlannerRuntimeTools"]
    TravelTime["TravelTimeProvider"]
    ExplainRuntime["ItineraryExplanationRuntime"]
    WeatherIndex["WeatherRiskIndex"]
    Checkpointer["AgentCoreMemorySaver"]
  end

  subgraph AWS["AWS / External Services"]
    BedrockLLM["Bedrock Converse\nopenai.gpt-oss-120b-1:0"]
    TitanEmbedding["Bedrock Embedding\namazon.titan-embed-text-v2:0"]
    S3Vectors["S3 Vectors\nlovv-vector-dev / kr-tour-domain-v2"]
    DomainDDB["DynamoDB\nTourKoreaDomainDataV2"]
    ProfileDDB["DynamoDB\nLovvAgentCore-LovvUserProfile"]
    RDS["RDS MySQL\nlovv-dev-mysql / lovvdev"]
    ORS["OpenRouteService\nors_service_key"]
    Memory["AgentCore Memory\nLovv_agent_v2_checkpointer"]
  end

  Intent --> IntentRuntime --> BedrockLLM
  BedrockLLM -. "create extraction\nmodify intent assist" .-> Intent

  Profile --> ProfileDDB
  Profile -. "saved itinerary evidence" .-> RDS

  Festival --> FestivalTools --> DomainDDB

  City --> CityTools
  City --> CityScoring
  CityTools --> TitanEmbedding
  CityTools --> S3Vectors
  CityTools --> DomainDDB
  CityScoring --> DomainDDB

  Planner --> PlannerTools
  Planner --> TravelTime
  PlannerTools --> TitanEmbedding
  PlannerTools --> S3Vectors
  PlannerTools --> DomainDDB
  TravelTime --> ORS

  Explain --> ExplainRuntime
  ExplainRuntime --> BedrockLLM
  ExplainRuntime --> DomainDDB

  Weather --> WeatherIndex

  Response -. "interrupt / resume" .-> Checkpointer --> Memory

  Supervisor -. "routes only\nno direct external tool" .-> Intent
  Supervisor -. "routes only\nno direct external tool" .-> Profile
  Supervisor -. "routes only\nno direct external tool" .-> Festival
  Supervisor -. "routes only\nno direct external tool" .-> City
  Supervisor -. "routes only\nno direct external tool" .-> Planner
  Supervisor -. "routes only\nno direct external tool" .-> Explain
  Supervisor -. "routes only\nno direct external tool" .-> Weather
  Supervisor -. "routes only\nno direct external tool" .-> Response
```

## Notes

- `Supervisor Router`는 tool을 직접 호출하지 않고 `routing.next_node`만 결정한다.
- 실제 배포 기준 코드는 `app/LovvAgentV2/`이다.
- AgentCore runtime은 `LovvAgentCore_LovvAgentV2-cy3tYk7nV4`, live version `3`, status `READY` 기준이다.
