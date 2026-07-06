---
title: 진화하는 시스템 프롬프트
translation_of: prompt-composition.md
translation_source_sha: 41dcf22b999cfee2473307f1a4ea618baa2094b9
translation_revised: 2026-07-06
---

# 진화하는 시스템 프롬프트

T2 tier와 quality gate는 하드코딩된 단일 문자열이 아니라 **조립 가능한
catalog-as-code 프롬프트**를 소비합니다. 이 문서는 설계의 원본입니다. 레이어가 어떻게
조립되고, 각 아티팩트가 어디에 살며, composition root가 어떤 seam을 배선하고, 모델이
우리가 보낸 것을 실제로 읽었는지 어떻게 측정하는지를 다룹니다.
[llm-strategy-ko.md](llm-strategy-ko.md#t2---reasoning-tier-quality-gate-required)의
LLM 계약과
[architecture.instructions.md](../../.github/instructions/architecture.instructions.md)의
trust routing을 확장합니다.

> **범위.** 업스트림은 범용 · Azure-first입니다. 웹 검색과 고객별 오버라이드는
> fork 전용 바인딩으로만 들어옵니다. 코어 저장소는 기본 비활성 fake를 배포하므로
> 포크는 명시적으로 opt-in해야 합니다
> ([generic-scope.instructions.md](../../.github/instructions/generic-scope.instructions.md)).
>
> **상태.** Wave 1 랜딩 완료 - 기본 프롬프트가 `rule-catalog/prompts/` 아래로
> 외부화되었고 composition root가 이를 로드합니다. Wave 2-5(task pack, tool /
> web search, operator memory, debate orchestrator, measurement)은 여기 문서화되어
> 있지만 아직 구현되지 않았습니다. 모든 wave는 shadow gate를 통과해야만 승격됩니다.
> [Rollout waves](#rollout-waves) 참조.

## 한눈에 보는 설계

프롬프트는 코드 안의 리터럴이 아니라 **데이터**입니다. Composition root가 부팅 시
`rule-catalog/prompts/`에서 로드하고, capability로 인덱싱한 뒤, 해석된 body를
Azure OpenAI 어댑터에 넘깁니다. 런타임 레이어(rule-catalog citation,
operator memory 항목, tool output, web snippet, debate transcript)는 모두
`trusted="false"` XML 태그로 감싸져 모델이 이를 데이터로 취급하도록 합니다.
**결정론적 verifier가 유일한 실행 authority**로 남습니다 - 추가된 역할, 툴,
레이어는 모두 그 verifier를 위한 재료를 생산할 뿐, 우회로가 아닙니다.

## Role x layer 매트릭스

프롬프트는 두 축을 가집니다. **레이어**는 조립된 프롬프트를 구성하는 콘텐츠 타입이며,
**역할**은 어떤 base / pack / tool 집합이 적용될지 결정합니다. Wave 1은 reviewer
역할만 배포하며, 나머지는 미래 wave가 안정된 seam에 슬롯인할 수 있도록 선언만 되어
있습니다.

| Layer \\ Role | Proposer | Critic | Judge |
|--------------|----------|--------|-------|
| Base (역할 스켈레톤) | `base/t2-proposer.vN.yaml` | `base/t2-critic.vN.yaml` | `base/t2-judge.vN.yaml` |
| Task Skill Pack | `packs/<capability>.proposer.vN.yaml` | `packs/<capability>.critic.vN.yaml` | (보통 proposer pack과 공유) |
| Tool Manifest | tools + 선택적 `web.search` | tools(읽기 전용) | 없음 (Judge는 툴 호출 금지) |
| Domain Context (RAG) | rule / 과거 인시던트 인용 | 동일 | 동일 |
| Web Snippets | Proposer가 가져온 경우 | 읽기 전용 | 읽기 전용 |
| Operator Memory | scope 제한 | scope 제한 | scope 제한 |
| Debate Transcript | (첫 턴엔 비어 있음) | Proposer 출력 | Proposer + Critic 출력 |

현재 reviewer 역할은 2-model cross-check로 동작합니다(Wave 2는 이를 유지). Wave 4
가 Critic을 추가하고, Wave 4.5가 Proposer / Critic / Judge orchestrator로 승격합니다.
매트릭스가 이미 각 셀을 예약해 두어 이 추가가 리팩터를 요구하지 않습니다.

## 레이어 카탈로그

각 레이어는 고정된 역할과 고정된 저장 티어를 가집니다.

- **Base** - 짧고 불변인 역할 스켈레톤 (출력 계약, verifier-as-authority 리마인드,
  JSON-only 출력 규칙). Wave 1 목표: <= 128 토큰.
- **Task Skill Pack** - capability-scoped 지시 (예: RCA grounding, 액션 제안,
  novelty 분류). 각 pack은 capability가 참조할 수 있는 rule-catalog 항목을 인용합니다.
- **Tool Manifest** - 이 역할이 호출할 수 있는 툴의 부분집합. base 프롬프트 밖에서
  선언하는 이유는 base를 짧고 캐시 친화적으로 유지하기 위함입니다.
- **Domain Context (RAG)** - 이벤트별로 선택된 rule 발췌와 과거 인시던트 참조.
  프롬프트 옆에 영구 저장하지 않고, audit에는 인용된 id와 vector-hit 점수만 기록.
- **Web Snippets** - [Web search policy](#web-search-policy) 하에서만 가져옵니다.
  `<web_snippet trusted="false" url="..." hash="...">...</web_snippet>`로 wrap.
- **Operator Memory** - operator 피드백(HIL reject, override 사유,
  ChatOps preference, PR 리뷰)에서 나온 scope 제한, HIL-승인된 노트.
  절대 global 아님. [Operator memory pipeline](#operator-memory-pipeline) 참조.
- **Debate Transcript** - 이전 역할들의 출력이 다음 역할에게 읽기 전용 컨텍스트로 전달.

## 저장

### Catalog-as-code (git 추적)

```text
rule-catalog/
  prompts/
    schema/
      prompt.schema.json          # 모든 아티팩트가 검증되는 JSON Schema
    base/
      t2-cross-check.v1.yaml      # Wave 1 (배포됨)
      t2-proposer.vN.yaml         # Wave 3 (계획됨)
      t2-critic.vN.yaml           # Wave 4 (계획됨)
      t2-judge.vN.yaml            # Wave 4.5 (계획됨)
    packs/                        # Wave 2+
    tools/                        # Wave 2.5+
    roles/                        # Wave 3+
```

### 런타임 데이터 (Postgres, hash 주소 blob)

기존 state / audit 스키마 옆에 두 개의 새 테이블이 랜딩합니다. Append-only이며 hash로
주소되므로, replay가 외부 콘텐츠를 다시 fetch 하지 않습니다.

```sql
CREATE TABLE operator_memory (
  id            uuid PRIMARY KEY,
  scope_kind    text NOT NULL,     -- 'resource-group' | 'resource' | 'vertical'
  scope_ref     text NOT NULL,
  category      text NOT NULL,
  body          text NOT NULL,     -- 주입 시 <operator_note>로 wrap
  source_event  text NOT NULL,     -- 'hil.reject' | 'override.create' | ...
  source_ref    text NOT NULL,     -- audit id / PR url / message id
  author        text NOT NULL,
  approved_by   text NOT NULL,     -- self-approval 금지
  created_at    timestamptz NOT NULL,
  superseded_by uuid,
  ttl           interval
);

CREATE TABLE agent_transcript (
  id             uuid PRIMARY KEY,
  event_id       text NOT NULL,
  round          smallint NOT NULL,
  role           text NOT NULL,    -- 'proposer' | 'critic' | 'judge'
  model_id       text NOT NULL,
  prompt_hash    text NOT NULL,
  layer_manifest jsonb NOT NULL,   -- 정렬된 layer ref + version + token 수
  tool_calls     jsonb NOT NULL,
  response_hash  text NOT NULL,
  cost_usd       numeric NOT NULL,
  latency_ms     integer NOT NULL,
  created_at     timestamptz NOT NULL
);

CREATE TABLE web_evidence (
  content_hash    text PRIMARY KEY,
  url             text NOT NULL,
  fetched_at      timestamptz NOT NULL,
  intent          text NOT NULL,
  sanitized_text  text NOT NULL,
  injection_flags jsonb NOT NULL
);
```

Global scope의 operator memory는 write 시점에 거부됩니다 - 이 설계가 상속하는
[Human Override](../../.github/instructions/architecture.instructions.md#human-override)
정책 기준으로 너무 넓기 때문입니다.

## Provider protocols (DI seam)

코어는 Protocol 뒤에 남고, Azure 어댑터가 seam당 한 구현을 제공합니다. 이 설계가
도입하는 새 seam:

| Seam | 종류 | Wave | 역할 |
|------|------|------|------|
| `PromptRegistry` | sync | 1 (배포됨) | 프롬프트 YAML 로드 / 인덱스 |
| `PromptComposer` | async | 2 | 이벤트별 Role x Layer 조립 |
| `ToolRegistry` | sync | 2.5 | Tool YAML manifest 로드 |
| `ToolExecutor` | async | 2.5 | 모델이 발행한 tool call 디스패치 |
| `OperatorMemoryStore` | async | 3 | scope-bounded 노트 읽기 / append |
| `WebSearchProvider` | async | 5 | allowlist 뒤 outbound HTTP |
| `EvidenceStore` | async | 5 | hash-addressed 웹 스냅샷 저장 |
| `AgentTranscriptStore` | async | 4.5 | append-only debate 행 |
| `DebateOrchestrator` | async | 4.5 | Proposer -> Critic -> Judge 루프 |

I/O-bound seam은
[coding-conventions.instructions.md](../../.github/instructions/coding-conventions.instructions.md#safety)
가 선언한 provider protocol의 async-by-default 규칙을 따릅니다.

## Tool use 서브시스템

툴은 rule catalog를 미러링한 catalog-as-code입니다. 각 YAML이 설명, 호출 스키마,
capability gate, allowlist, output wrapper를 선언합니다.

- **Capability별 allowlist**: capability의 `llm-registry` 엔트리가 Proposer /
  Critic이 호출할 수 있는 툴을 이름 짓습니다. tool manifest를 짧게 유지하여
  "lost in the middle" 실패 모드가 새어들지 않게 합니다.
- **Untrusted 출력**: 모든 tool 결과는 wrap되며
  (`<tool_result trusted="false" tool="..." ...>...</tool_result>`) 데이터로 취급.
  verifier와 policy 재검사가 authoritative로 남습니다.
- **Budget**: 각 툴은 `cost_budget_usd_per_call`을 선언하고, composer가 이벤트별
  상한을 강제. 초과 시 HIL로 abort.
- **Judge는 툴을 쥐지 않음**: judgment는 직무 분리입니다. 툴을 호출하는 Judge는
  두 번째 Proposer로 붕괴합니다.

## Web search 정책

Web search는 최후의 수단 툴입니다. fork별 opt-in이며 절대 grounding source가
아닙니다.

- **기본 off**: 업스트림은 no-op `WebSearchProvider`를 배포. fork가 API key와
  curated 도메인 allowlist를 제공하여 활성화합니다.
- **언제 실행 가능**: T2 케이스, novelty score가 threshold 초과, capability의
  tool allowlist가 `web.search`를 포함, 이벤트당 query / cost budget이 소진되지
  않음.
- **도메인 allowlist**: primary source만 (vendor docs, RFC, NVD, CVE 레지스트리).
  블로그, 포럼, 소셜 미디어는 금지.
- **Snippet 처리**: HTML strip. prompt-유사 패턴(`ignore previous`, `system:` 등)
  탐지 및 플래그. inject 전에 `<web_snippet trusted="false">...</web_snippet>`
  로 wrap.
- **Grounding source가 아님**: `cited_rule_ids`는 여전히 rule-catalog 항목으로
  해석되어야 합니다. 유용한 웹 발견은 rule-catalog discovery loop로 흘러가며,
  현재 이벤트의 grounding 요구를 만족시키지 않습니다.
- **Replay 결정성**: 결과는 `web_evidence`에 `(content_hash, url, fetched_at)`
  로 저장. audit 엔트리는 hash를 참조. Replay는 저장된 스냅샷을 읽으며 다시 fetch
  하지 않으므로 과거 실행이 재현 가능하게 유지됩니다.

## Debate orchestrator (Proposer / Critic / Judge)

Debate는 router가 요청할 때만 실행됩니다 - 보통 high-severity, high novelty,
또는 명시적인 operator-memory 지침. 기본 T2 경로는 여전히
[llm-strategy-ko.md](llm-strategy-ko.md)에 문서화된 2-model cross-check입니다.

```text
Proposer  -- candidate + citation + confidence
   |
   v
Critic    -- objection: [{severity, cited_rule_id, alt_action?}]
   |
   v
Judge     -- decision in {accept, revise_and_retry (<=1), escalate_hil}
   |
   +--> accept       -> 결정론적 verifier -> risk gate
   +--> revise       -> Proposer 1회 재시도 (total round <= 2)
   +--> escalate_hil -> 종료
```

이벤트당 하드 리밋: `debate.max_rounds <= 2`, `debate.max_wall_seconds`,
`debate.max_cost_usd`. 초과 시 HIL로 abort. Critic은 Proposer와 다른 publisher
모델이어야 합니다 (mixed-model distinctness 규칙 확장,
[llm-strategy-ko.md](llm-strategy-ko.md#t2---reasoning-tier-quality-gate-required)).
Judge는 더 작고 저렴한 모델이어도 됩니다.

Critic의 역할은 "다른 의견"이 아니라, 네 개의 안전 불변식(stop-condition, 롤백,
blast-radius, audit-log)에 대한 체크리스트 + citation validity + operator memory
와의 모순 여부입니다.

## Operator memory 파이프라인

Operator 피드백은 두 단계 gate를 거쳐 memory가 됩니다:

```text
HIL reject / approve reason -----\\
Override create / modify event  --+--> operator-memory 후보
ChatOps preference message      --|         |
PR review comment on rem PR     --/         v
                                     HIL 2차 승인 (self-approval 금지)
                                             |
                                             v
                                  operator_memory 행 (append-only)
```

- **Scope는 resource-group 이하여야 합니다.** 더 넓은 scope는 override가 아닌
  rule 변경이며, catalog pipeline을 통과해야 합니다.
- **주입 시 sanitize + wrap**: memory body는
  `<operator_note author="..." scope="..." trusted="false">...</operator_note>`
  태그 안으로 들어가며, base 프롬프트는 해당 태그 안의 지시를 따르는 것을
  금지합니다.
- **Discovery 신호**: 같은 rule에 대한 장기 override 또는 유사한 memory 행의 다수는
  rule-catalog discovery loop에 revision / retirement 후보로 흘러갑니다.

## 인식 측정

긴 프롬프트는 조용히 지시를 흘립니다. "모델이 우리가 보낸 것을 실제로 읽었는가"를
1급 KPI로 다루며, 프롬프트를 enforce로 승격하기 전에 gate합니다.

- **하드 토큰 예산** - composer가 조립된 프롬프트당 토큰을 추정. 초과 시 HIL로
  abort하고 `prompt.token_budget.exceeded_rate`를 증가. 우선순위가 낮은 레이어
  (가장 오래된 operator memory부터)는 감사에 보이는 이유와 함께 명시적으로 drop.
- **Canary 토큰** - composer가 태그된 레이어 마커
  (`<layer id="pack.rca.v3">...</layer>`)를 삽입. 역할들은 어느 레이어를
  인식했는지 보고. 인식되지 않은 고우선순위 레이어는 결함으로 surfacing.
- **Adherence rate** - JSON 스키마 위반, 필수 필드 누락, citation-rule-id
  validity를 매 프롬프트 버전 bump마다 고정 시나리오 세트에서 측정.
- **Position sensitivity** - 통제된 fixture가 동일한 지시를 base vs. pack
  vs. 끝에 배치하고 adherence를 비교. 특정 위치의 지속적 dip은 base 재작성
  신호.
- **Mixed-model agreement rate** - 기존 quality-gate disagreement rate를
  프롬프트 버전별로 추적하여 리그레션을 즉시 노출.
- **Debate economics** - debate orchestrator 랜딩 후
  `debate.rounds.p95`, `debate.cost_usd.p95`, `debate.timeout_to_hil_rate`,
  `critic.reversal_rate`를 추적.

승격 gate (초기값, capability별로 튜닝): `adherence >= 0.95`,
`citation_f1 >= 0.9`, `web.grounding_leak == 0`, `debate.timeout_to_hil_rate
<= 5%`, `critic.reversal_rate in [1%, 15%]`.

## 안전 불변식 (확장)

[coding-conventions.instructions.md](../../.github/instructions/coding-conventions.instructions.md#safety)
의 8개 불변식에 이 설계 랜딩과 함께 6개가 추가됩니다:

1. Web-search 출력은 **절대** `cited_rule_id`가 아님.
2. Tool 결과와 web snippet은 **항상** `trusted="false"` XML로 wrap.
3. Debate 루프는 하드 `max_rounds`, `max_wall_seconds`, `max_cost_usd`
   상한을 가지며, 초과 시 HIL로 abort.
4. Critic과 Proposer의 publisher는 **달라야** 하며, 같은 publisher 쌍은 단일
   voter로 붕괴함.
5. Judge는 툴을 호출**해서는 안 됨**. Judgment와 generation은 분리.
6. Web evidence는 hash 주소 immutable이며, replay는 스냅샷을 읽고 다시 fetch
   하지 않음.

## Rollout waves

모든 wave는 shadow first로 랜딩. 승격은 이전 wave의 승격 gate가 유지되어야 함.

| Wave | Deliverable | 배포됨 |
|------|-------------|--------|
| 1 | Base 프롬프트 catalog 외부화 + `PromptRegistry` + composition 배선 | yes |
| 2 | Task pack + Recognition probe 스캐폴드 + KPI 확장 | 계획됨 |
| 2.5 | `rule.query` / `state.query` / `audit.query`용 `ToolRegistry` + `ToolExecutor` (웹 검색 없음) | 계획됨 |
| 3 | Operator Memory 스키마 + HIL 2차 승인 파이프라인 (HIL reject reason만으로 시작) | 계획됨 |
| 4 | Critic 역할 (2-role debate: Proposer + Critic, verifier가 여전히 authoritative) | 계획됨 |
| 4.5 | Judge 역할과 `max_rounds = 1`로 시작하는 full `DebateOrchestrator` | 계획됨 |
| 5 | Fork별 web search opt-in (업스트림은 no-op provider. enforce에는 injection detection 필요) | 계획됨 |

## Wave 1 - 무엇이 배포되었나

Wave 1은 런타임 행동을 바꾸지 않은 채 seam을 도입합니다.

- `rule-catalog/prompts/schema/prompt.schema.json` - 프롬프트 아티팩트용 JSON
  Schema.
- `rule-catalog/prompts/base/t2-cross-check.v1.yaml` - 추출된 T2 base 프롬프트.
- `src/aiopspilot/core/prompts/` - `PromptRegistry` Protocol,
  `FileSystemPromptRegistry` 구현, aggregate-error 검증.
- `bind_azure_llm_bindings`가 선택적 `system_prompt`를 받아 모든 cross-check
  config에 스레딩.
- `__main__._finalize_llm_bindings`가 `FileSystemPromptRegistry`를 통해 base
  프롬프트를 로드하여 전달.
- `tests/core/prompts/test_yaml_matches_dataclass_default.py`가 배포된 YAML body를
  dataclass 기본값에 pin하여 전환 중 두 값이 drift 하지 않도록. Wave 2는
  기본값을 제거하고 이 pin을 삭제.

## 관련 문서

| 목적 | 시작 지점 |
|------|-----------|
| Tier 경계와 quality gate | [llm-strategy-ko.md](llm-strategy-ko.md) |
| Trust routing과 컨트롤 루프 | [../../.github/instructions/architecture.instructions.md](../../.github/instructions/architecture.instructions.md) |
| 이 설계가 확장하는 Human override 정책 | [../../.github/instructions/architecture.instructions.md#human-override](../../.github/instructions/architecture.instructions.md#human-override) |
| 안전 불변식과 코딩 컨벤션 | [../../.github/instructions/coding-conventions.instructions.md](../../.github/instructions/coding-conventions.instructions.md) |
| Prompt-injection 위협 모델 | [security-and-identity-ko.md](security-and-identity-ko.md) |
| Rule catalog와 provenance 규칙 | [rule-catalog-collection-ko.md](rule-catalog-collection-ko.md) |
