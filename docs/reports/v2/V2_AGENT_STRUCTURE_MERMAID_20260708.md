# Lovv Agent V2 구조 Mermaid

작성일: 2026-07-08

이 문서는 현재 코드와 live AWS 배포 상태를 함께 기준으로 만든 Agent V2 구조도이다.

- 코드 기준: `agentcore/agentcore.json`의 `codeLocation=app/LovvAgentV2/`
- 배포 기준: AWS AgentCore runtime `LovvAgentCore_LovvAgentV2-cy3tYk7nV4`
- 상태: `READY`, live endpoint `DEFAULT`, live version `3`
- 런타임: `PYTHON_3_12`, entrypoint `opentelemetry-instrument main.py`
- 네트워크: live AWS는 `VPC`, 로컬 `agentcore/agentcore.json`은 `PUBLIC`으로 남아 있어 현재 배포 상태와 로컬 설정 파일이 다르다.

## 근거 파일과 live 리소스

### 코드 근거

- `app/LovvAgentV2/main.py`: `BedrockAgentCoreApp` entrypoint에서 `handle_v2_invocation` 호출
- `app/LovvAgentV2/lovv_agent_v2/agentcore_entrypoint.py`: request/thread/actor/resume 추출, profile evidence 주입, graph invoke
- `app/LovvAgentV2/lovv_agent_v2/harness.py`: live runtime 도구 조립, checkpointer 생성, graph compile
- `app/LovvAgentV2/lovv_agent_v2/core/graph.py`: LangGraph V2 node와 supervisor conditional route 구성
- `app/LovvAgentV2/lovv_agent_v2/agents/supervisor/router.py`: `routing.next_node` 결정 규칙
- `app/LovvAgentV2/lovv_agent_v2/agents/*`: 각 agent node와 subgraph 구현

### live AWS 근거

- AgentCore runtime: `arn:aws:bedrock-agentcore:us-east-1:925273580929:runtime/LovvAgentCore_LovvAgentV2-cy3tYk7nV4`
- Runtime version: `3`
- Runtime status: `READY`
- Endpoint: `DEFAULT`, `READY`, `liveVersion=3`
- Code artifact: `s3://cdk-hnb659fds-assets-925273580929-us-east-1/cae5386e060ec1dc42147f4923f6812e9e9e629abbfe2dab643689c4628c2bff.zip`
- AgentCore Memory: `Lovv_agent_v2_checkpointer-OUxTJ7HuIM`, `ACTIVE`, `eventExpiryDuration=7`
- DynamoDB domain table: `TourKoreaDomainDataV2`, `ACTIVE`, `ItemCount=10482`
- DynamoDB profile table: `LovvAgentCore-LovvUserProfile`, `ACTIVE`, `ItemCount=0`
- S3 Vector index: `lovv-vector-dev/kr-tour-domain-v2`, `float32`, dimension `1024`, cosine
- RDS: `lovv-dev-mysql`, MySQL, `available`, port `3306`

## 1. 큰 틀: AgentCore Runtime과 Supervisor Route

```mermaid
flowchart TD
  Client["Client / Backend 호출"] --> Endpoint["AgentCore DEFAULT endpoint\nLovvAgentCore_LovvAgentV2-cy3tYk7nV4\nREADY, liveVersion=3"]
  Endpoint --> Main["app/LovvAgentV2/main.py\nBedrockAgentCoreApp.entrypoint"]
  Main --> Entry["handle_v2_invocation"]

  Entry --> IO["request_id / thread_id / actor_id / resume 추출"]
  IO --> ProfileEvidence["profile evidence 주입\n새 요청일 때만"]
  ProfileEvidence --> Harness["cached live harness"]
  IO --> Harness

  Harness --> Runtime["live graph runtime 조립"]
  Runtime --> Bedrock["Bedrock Runtime\nintent / itinerary explanation LLM"]
  Runtime --> Embed["Titan embedding\namazon.titan-embed-text-v2:0"]
  Runtime --> Vectors["S3 Vectors\nlovv-vector-dev / kr-tour-domain-v2"]
  Runtime --> DomainDdb["DynamoDB\nTourKoreaDomainDataV2"]
  Runtime --> ProfileDdb["DynamoDB\nLovvAgentCore-LovvUserProfile"]
  Runtime --> Rds["RDS MySQL\nlovv-dev-mysql / lovvdev"]
  Runtime --> Ors["AgentCore credential\nors_service_key"]
  Runtime --> Memory["AgentCore Memory checkpointer\nLovv_agent_v2_checkpointer"]

  Harness --> Graph["LangGraph V2\ncompile_v2_graph(checkpointer)"]
  Graph --> Intent["intent"]
  Intent --> Supervisor["supervisor"]

  Supervisor -->|"profile"| Profile["profile"]
  Supervisor -->|"festival_verifier"| Festival["festival_verifier"]
  Supervisor -->|"city_select"| CitySelect["city_select subgraph"]
  Supervisor -->|"planner"| Planner["planner subgraph"]
  Supervisor -->|"explain_itinerary"| Explain["explain_itinerary"]
  Supervisor -->|"weather_alternative"| Weather["weather_alternative"]
  Supervisor -->|"response_packager"| Response["response_packager"]
  Supervisor -->|"end"| End["END"]

  Profile --> Supervisor
  Festival --> Supervisor
  CitySelect --> Supervisor
  Planner --> Supervisor
  Explain --> Supervisor
  Weather --> Supervisor
  Response --> Supervisor

  Response -->|"END_WAIT_USER"| Interrupt["LangGraph interrupt\n사용자 clarify/resume 대기"]
  Interrupt --> Entry
  Response -->|"response_payload"| Client
```

## 2. Supervisor Routing 상세

`supervisor_node`는 매번 `routing.next_node`를 갱신한다. 그래프 자체는 모든 worker를 supervisor로 되돌리고, `_route_from_supervisor`가 `routing.next_node`를 다음 LangGraph node로 매핑한다.

```mermaid
flowchart TD
  Start["supervisor_node(state)"] --> Reason["clarification_reason_code 계산"]
  Reason --> Confirm{"itinerary confirmation state?"}

  Confirm -->|"yes + profile_update 있음"| End["end"]
  Confirm -->|"yes + profile_update 없음"| Profile["profile"]

  Confirm -->|"no"| ModifyPayload{"현재 modify response_payload 있음?"}
  ModifyPayload -->|"yes"| End
  ModifyPayload -->|"no"| SlotFail{"slot_replace_failed?"}
  SlotFail -->|"yes"| Response["response_packager"]
  SlotFail -->|"no"| SlotPlanner{"slot_replace planner route?"}
  SlotPlanner -->|"yes"| Planner["planner"]
  SlotPlanner -->|"no"| DirectAnchor{"direct anchor planner route?"}
  DirectAnchor -->|"yes"| Planner
  DirectAnchor -->|"no"| ModifyResponse{"modify intent가 응답 필요?"}
  ModifyResponse -->|"yes"| Response

  ModifyResponse -->|"no"| ModifyPlannerOutput{"modify + planner_output 있음?"}
  ModifyPlannerOutput -->|"yes + explanation 없음"| Explain["explain_itinerary"]
  ModifyPlannerOutput -->|"yes + post explain weather 없음"| Weather["weather_alternative"]
  ModifyPlannerOutput -->|"yes + weather 완료"| Response

  ModifyPlannerOutput -->|"no"| HasResponse{"response_payload 있음?"}
  HasResponse -->|"yes"| End
  HasResponse -->|"no"| Clarify{"clarification reason 있음?"}
  Clarify -->|"yes"| Response
  Clarify -->|"no"| HasProfile{"profile audit 있음?"}

  HasProfile -->|"no"| Profile
  HasProfile -->|"yes"| FestivalNeeded{"festival_gate 미완료\nand include_festivals?"}
  FestivalNeeded -->|"yes"| Festival["festival_verifier"]
  FestivalNeeded -->|"no"| CityResponse{"city_select status가 terminal error?"}
  CityResponse -->|"yes"| Response
  CityResponse -->|"no"| PlannerOutput{"planner_output 있음?"}

  PlannerOutput -->|"no + direct anchor 가능"| Planner
  PlannerOutput -->|"no + city_selection 없음"| City["city_select"]
  PlannerOutput -->|"no + city_selection 있음"| Planner
  PlannerOutput -->|"yes + explanation 없음"| Explain
  PlannerOutput -->|"yes + post explain weather 없음"| Weather
  PlannerOutput -->|"yes + weather 완료"| Response
```

## 3. Intent Agent

역할: 입력을 `create | clarify | modify | confirm`로 정규화하고, `city_select_input` 또는 `modify_intent`를 만든다.

```mermaid
flowchart TD
  In["state.request + 기존 state.intent"] --> EntryType{"entry_type(request)"}
  EntryType -->|"clarify + create fields 없음"| Clarify["build_clarify_intent"]
  EntryType -->|"modify"| Modify["resolve_modify_intent"]
  EntryType -->|"confirm"| Confirm["confirm intent\nthread/recommendation/revision"]
  EntryType -->|"create 또는 clarify create"| Create["fresh create"]

  Create --> Prompt{"기존 city_select_input 있음?"}
  Prompt -->|"없음"| PromptRuntime["IntentPromptRuntime\nBedrock Converse 가능"]
  Prompt -->|"있음"| Reuse["기존 city_select_input 재사용"]
  Modify --> PromptRuntime
  PromptRuntime --> ModifyUpdate["modify_state_update"]
  PromptRuntime --> Parse["CitySelectInput.from_mapping"]
  Reuse --> Parse
  Parse --> Normalize["destination identity 보강\nquery/theme 정규화\nunsupported region clarification"]
  Normalize --> Reset["fresh create면 festival_gate/city_select/planner/response/routing 초기화"]

  Clarify --> Out["intent update"]
  ModifyUpdate --> Out
  Confirm --> Out
  Reset --> Out
```

## 4. Profile Agent

역할: 사용자 profile과 saved itinerary evidence를 바탕으로 theme weight를 계산하고, confirmation이면 profile update payload를 기록한다.

```mermaid
flowchart TD
  In["state.intent + state.profile"] --> Confirm{"itinerary confirmation intent?"}
  Confirm -->|"yes"| Update["saved_trip_count + 1\nprofile_update reason=itinerary_confirmed"]
  Confirm -->|"no"| CityInput["CitySelectInput 정규화"]

  CityInput --> ProfileSource["profile.lovv_user_profile\nor mock_profile\nor profile_record.lovv_user_profile"]
  ProfileSource --> Weights["build_profile_theme_weights"]
  Weights --> Active{"profile weights active?"}
  Active -->|"yes"| Inject["intent.city_select_input.theme_weights 주입"]
  Active -->|"no"| Remove["theme_weights 제거"]
  Inject --> Audit["profile audit\nsaved_trip_count\nprofile_theme_weights\neffective_theme_weights\napplied_persona_id"]
  Remove --> Audit
  Update --> Out["intent + profile 반환"]
  Audit --> Out
```

## 5. Festival Verifier Agent

역할: 요청 또는 기존 festival candidates를 받아 선택 도시/테마/월 기준으로 festival gate를 검증한다.

```mermaid
flowchart TD
  In["state.intent.city_select_input\nstate.festival_gate 또는 state.request"] --> Input["FestivalVerifierInput"]
  Input --> Candidates{"festival candidates 위치"}
  Candidates -->|"state.festival_gate.candidates"| CandidateState["state candidates"]
  Candidates -->|"request.festival_candidates"| CandidateRequest["request candidates"]
  Candidates -->|"없음"| Empty["empty candidates"]

  CandidateState --> Tools["FestivalVerifierTools"]
  CandidateRequest --> Tools
  Empty --> Tools
  Tools --> Dynamo["DynamoLookupTool\nTourKoreaDomainDataV2"]
  Dynamo --> Agent["FestivalVerifierAgent.run"]
  Agent --> Policy["theme/date/city gate 검증"]
  Policy --> Out["festival_gate.result 또는 clarification/audit"]
```

## 6. City Select Agent

역할: S3 Vectors로 후보 도시/장소를 검색하고 DynamoDB detail을 보강한 뒤 도시를 선택한다.

```mermaid
flowchart TD
  In["intent.city_select_input"] --> Retrieval["retrieval node"]
  Retrieval --> Embed["BedrockEmbeddingAdapter\nTitan text embedding v2"]
  Retrieval --> VectorSearch["DestinationSearchTool\nS3 Vectors kr-tour-domain-v2"]
  Retrieval --> Dynamo["DynamoLookupTool\nTourKoreaDomainDataV2"]
  VectorSearch --> Candidates["raw / soft / per-theme candidates"]
  Dynamo --> Candidates

  Candidates --> Scoring["scoring_and_selection node"]
  Scoring --> ProfileWeights["theme_weights 반영"]
  Scoring --> GeoScore["distance / city / province / theme scoring"]
  Scoring --> Select["selected_city + seeds + planner_hints"]
  Select --> Out["city_select.city_selection_result"]
```

## 7. Planner Agent

역할: 선택 도시 안에서 실제 itinerary 후보를 만들고 route/day 배치를 수행한다. modify 요청 중 `slot_replace` 또는 `day_regenerate`는 `apply_edit` 경로로 들어간다.

```mermaid
flowchart TD
  In["state.intent + city_select result + planner scratch"] --> Entry{"modify_intent routing_hint"}
  Entry -->|"planner_apply_edit\nslot_replace/day_regenerate"| ApplyEdit["apply_edit"]
  Entry -->|"기본"| RetrievePlaces["retrieve_places"]

  RetrievePlaces --> PlannerRuntime["PlannerRuntimeTools\nDestinationSearch + Embedding"]
  PlannerRuntime --> PlacePool["selected city 장소 후보"]
  PlacePool --> RouteDays["route_days"]
  RouteDays --> TravelTime["ORS travel time provider\nfallback Haversine"]
  TravelTime --> Assemble["assemble_itinerary"]

  ApplyEdit --> Weather["weather_alternative"]
  Assemble --> Retry{"should_retry_alternative_city?"}
  Retry -->|"yes"| RetryCity["retry_alternative_city"]
  RetryCity --> RetrievePlaces
  Retry -->|"no"| Weather
  Weather --> Out["planner.planner_output\nvalidation_result\nweather_risk"]
```

## 8. Explain Itinerary Agent

역할: planner output의 장소별 설명과 사용자-facing itinerary 설명을 보강한다.

```mermaid
flowchart TD
  In["planner.planner_output"] --> Input["ItineraryExplanationInput"]
  Input --> Runtime["ItineraryExplanationRuntime"]
  Runtime --> Dynamo["DynamoLookupTool\n상세 record hydration"]
  Runtime --> Bedrock["Bedrock Converse\nLOVV_EXPLANATION_LLM_MODEL_ID"]
  Dynamo --> Explain["일정 item 설명/복사문 생성"]
  Bedrock --> Explain
  Explain --> Out["planner.validation_result에\nexplanation audit 추가"]
```

## 9. Weather Alternative Agent

역할: 완성된 itinerary의 실내/실외 노출과 도시/월별 weather risk를 비교해 날씨 안내 또는 대체 일정 옵션을 만든다.

```mermaid
flowchart TD
  In["planner.planner_output.itinerary"] --> Empty{"itinerary 비어 있음?"}
  Empty -->|"yes"| Unavailable["weather_audit.status=unavailable"]
  Empty -->|"no"| Exposure["summarize_exposure"]
  Exposure --> CityMonth["city_id + travel_month 추출"]
  CityMonth --> RiskIndex["city_monthly_weather_risks.json\nor runtime weather_risk_index"]
  RiskIndex --> Policy["WeatherDecisionPolicy\ndecide_weather"]
  Policy --> Notice{"notice 있음?"}
  Notice -->|"yes"| AddNotice["planner_output.user_notice 추가"]
  Notice -->|"no"| AuditOnly["weather_audit만 추가"]
  AddNotice --> Out["planner.weather_risk + validation_result"]
  AuditOnly --> Out
  Unavailable --> Out
```

## 10. Response Packager Agent

역할: 최종 응답 payload를 만들거나, clarify/대체 일정/후보 부족 상황이면 LangGraph interrupt로 사용자 선택을 기다린다.

```mermaid
flowchart TD
  In["request + planner_output + selected_city + festival_verifications + clarification"] --> PackagerInput["ResponsePackagerInput"]
  PackagerInput --> Clarification{"clarification 필요?"}
  Clarification -->|"generation_insufficient_candidates"| GenOptions["테마 완화 / 다른 도시 검색 옵션"]
  Clarification -->|"weather_alternative_available"| WeatherOptions["날씨 대체 일정 보기 / 현재 유지 옵션"]
  Clarification -->|"slot replace failed"| EditOptions["조건 확장 / 현재 장소 유지 옵션"]
  Clarification -->|"없음"| Final["ResponsePackagerAgent.run\nresponse_payload 생성"]

  GenOptions --> Wait["response_status=END_WAIT_USER"]
  WeatherOptions --> Wait
  EditOptions --> Wait
  Wait --> Interrupt["interrupt(response_payload)"]
  Interrupt --> Resume["response_resume_update\n다음 invocation에서 Command(resume=...)"]
  Final --> Out["state.response.response_payload"]
```

## 11. 배포 런타임과 코드 설정 차이

```mermaid
flowchart LR
  Local["agentcore/agentcore.json\nname LovvAgentV2\ncodeLocation app/LovvAgentV2\nruntime PYTHON_3_12\nnetworkMode PUBLIC"] --> Deploy["배포 패키지\nCodeZip"]
  Deploy --> Aws["live AWS AgentCore\nLovvAgentCore_LovvAgentV2-cy3tYk7nV4\nversion 3, READY"]

  Aws --> LiveNetwork["networkMode VPC\nsg-0c50468427a3239ac\nsubnet-0b3d1d99edd282504\nsubnet-0e04f80cfb58e0f35"]
  Aws --> LiveEntry["entryPoint\nopentelemetry-instrument main.py"]
  Aws --> LiveEnv["env vars\nLOVV_MEMORY_ENABLED=true\nLOVV_PROFILE_ENABLED=true\nLOVV_DYNAMODB_TABLE=TourKoreaDomainDataV2\nLOVV_S3_VECTOR_INDEX=kr-tour-domain-v2\nMYSQL_HOST=lovv-dev-mysql..."]
  Aws --> LiveMemory["AgentCore Memory ACTIVE\nLovv_agent_v2_checkpointer"]
```

## 12. 요약

- 현재 배포된 Agent는 V2이며, live runtime id는 `LovvAgentCore_LovvAgentV2-cy3tYk7nV4`이다.
- 실제 배포 코드는 `app/LovvAgentV2/`가 기준이다. `src/lovv_agent_v2/`는 개발 소스이지만 AgentCore `CodeZip` 기준 truth surface는 아니다.
- Supervisor는 LLM supervisor가 아니라 deterministic router다. `routing.next_node`를 계산하고, LangGraph conditional edge가 그 값을 실제 node로 라우팅한다.
- 기본 생성 흐름은 `intent -> supervisor -> profile -> supervisor -> festival_verifier -> supervisor -> city_select -> supervisor -> planner -> supervisor -> explain_itinerary -> supervisor -> weather_alternative -> supervisor -> response_packager`이다.
- modify/clarify/confirm은 `intent`와 `supervisor`에서 분기된다. `response_packager`는 사용자 입력이 더 필요하면 `interrupt`로 멈추고 다음 호출에서 `Command(resume=...)`로 이어진다.
- live AWS는 VPC 네트워크로 배포되어 있고, 로컬 `agentcore/agentcore.json`의 `networkMode=PUBLIC`과 다르다.
