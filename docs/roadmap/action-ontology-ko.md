---
title: Action 온톨로지
translation_of: action-ontology.md
translation_source_sha: 9beea478c66467ba755f28112bd8f916c1dd39f7
translation_revised: 2026-07-06
---

# Action 온톨로지

AIOpsPilot 의 모든 액션 - 룰이 발화시킨 remediation 이든 오퍼레이터가
요청한 ops task 든 - 는 shipped 온톨로지의 **`ActionType`** entry 하나의
instance 이다. 이 문서는 스키마, 트리거 축 (`rule_violation` vs
`operator_request`), tier 및 role 상한, live-probe 참조, 그리고 `core/`
편집 없이 고객이 재정의 가능하게 하는 **fork-override seam** 을 권위적으로
정의한다.

이 온톨로지의 소비자:

- T0Engine + ActionBuilder ([phase-1](phases/phase-1-rule-catalog-t0-ko.md))
  는 룰이 발화시킨 액션을 빌드할 때 `rollback_contract`,
  `preconditions`, `stop_conditions`, `blast_radius` 를 read.
- 통합 RiskGate + Executor ([execution-model.md](execution-model-ko.md))
  는 실행 **여부** 와 **방법** 을 결정할 때 tier 상한, min-role,
  live-probe 참조, execution path 를 read.
- 오퍼레이터 콘솔 narrator ([operator-console.md](operator-console-ko.md))
  는 ops-flavoured tool call 을 제안하거나 실행할 때 `trigger_kind`,
  `description`, `argument_schema` 를 read.

단일 온톨로지가 세 곳 모두를 feed 하기 때문에, 새 remediation 또는 새 ops
verb 추가는 YAML 파일 하나 - 엔진에 branching 없음, 새 executor 없음.

> 고객-무관: 아래의 모든 ActionType 이름, 파라미터, blast-radius 값은
> placeholder 또는 예시. Fork 가 config 로 entry 추가/재정의
> ([generic-scope.instructions.md](../../.github/instructions/generic-scope.instructions.md)).

## 1. 하나의 온톨로지, 두 트리거

기존 shipped 15개 ActionType 은 모두 룰이 발화시킨 remediation
(`remediate.tag-add`, `remediate.disable-public-access`, ...). 오퍼레이터
콘솔 pull-방향 ([operator-console.md](operator-console-ko.md) §4) 는 룰
발화가 아니라 **오퍼레이터의 chat 요청** 으로 트리거되는 액션이 필요:
"이 pod 재시작", "scale out", "cache flush". 이들은 같은 safety envelope
를 공유하지만 다른 trigger surface 를 가진다.

온톨로지는 둘 다 **하나의 스키마 + 하나의 축** 으로 처리:

```yaml
trigger_kind:
  - rule_violation      # T0/T1/T2 엔진이 룰 매치 → 자동 proposal
  - operator_request    # 콘솔의 사람 → 명시적 ops
  - both                # 어느 경로든 사용 가능한 동일 ActionType
```

- **`rule_violation`** - ControlLoop 이 매치된 룰 + finding 로부터 액션을
  construct. 트리거는 T0/T1/T2 판정.
- **`operator_request`** - 오퍼레이터-콘솔 narrator 가 이 ActionType 을
  대상으로 하는 tool_call 을 emit. 트리거는 콘솔 세션 + principal +
  arguments.
- **`both`** - 일부 액션은 두 surface 모두에 속함. 예: `ops.restart-service`
  는 오퍼레이터가 트리거 ("restart this") 하거나 룰이 트리거 (health-probe
  fail 룰) MAY. 온톨로지 entry 는 합집합을 declare; runtime 이 path 선택.

이 축을 제외하고 스키마의 어느 것도 trigger-specific 이 아니다; executor,
RiskGate, audit 계약은 둘 다 동일.

## 2. 스키마

```yaml
schema_version: "1.0.0"
id: string                              # 전역 unique, snake+dot: "ops.restart-service"
name: string                            # human-readable
version: semver
category:                               # 최상위 bucket
  - remediation                         # 룰 발화, config-drift 스타일
  - ops                                 # 오퍼레이터 요청 runtime 액션
  - governance                          # 정책 / 예외 / promotion 변경
description: string                     # <= 200 자, 영어, 마케팅 없음

# --- 트리거 축 (§1) ------------------------------------------------------
trigger_kind:                           # rule_violation | operator_request | both 중 하나
  kind: enum
  restrict_to_scenarios: [string, ...]  # 옵션; 어느 시나리오가 이걸 fire MAY 인지 narrow

# --- Autonomy + safety (기존, phase-1 그대로 유지) -----------------------
default_mode: shadow                    # 신규 ActionType 은 shadow MUST
promotion_gate:
  min_shadow_days: int
  min_samples: int
  min_accuracy: float
  max_policy_escapes: int

# --- Execution path (execution-model.md 상세) ----------------------------
execution_path: pr_native | direct_api | pr_manual
                                        # pr_native → shipped GitOpsPrAdapter (기본)
                                        # direct_api → ops-fast-path (Azure ARM call)
                                        # pr_manual → hil label PR, auto-merge 없음

# --- Rollback contract (기존) --------------------------------------------
rollback_contract: pr_revert | scripted | pitr | snapshot_restore | state_forward_only
irreversible: bool                       # true 면 tier 무관 HIL 필수

# --- Preconditions + stop conditions (기존) -----------------------------
preconditions:
  - kind: graph_fresh_within_seconds
    value: int
  - kind: resource_tag_present
    tag: string
  - ...                                  # 기존 카탈로그 재사용

stop_conditions:
  - kind: provider_api_error_streak
    count: int
  - kind: time_box_exceeded_seconds
    seconds: int
  - ...

# --- Blast radius (기존 static + 신규 live) -----------------------------
blast_radius:
  computation: static_enum | graph_derived
  static_bucket: resource | subnet | subscription
  max_affected_resources: int            # graph_derived 만

  # 신규: live-blast probe pointer (Month 1+; §6 참조)
  live_probe_ref: string                 # 옵션; 예: "probes/vm_traffic_last_5m"

# --- 신규: tier × role 상한 (execution-model.md §3) ---------------------
ceiling_by_tier:
  t0:
    max_autonomy: enforce_auto | enforce_hil | shadow_only
    min_role: reader | contributor | approver | owner | breakglass
  t1:
    max_autonomy: enforce_hil | shadow_only
    min_role: contributor | approver | owner
  t2:
    max_autonomy: shadow_only            # T2 는 shadow-only 기본; raise 는 명시적 fork override
    min_role: approver | owner

# --- 신규: prod-vs-non-prod downgrade -----------------------------------
prod_downgrade:
  mode: enforce_hil | shadow_only        # "prod" 가 collapse 되는 값
  detection_ref: string                  # 예: "env_detectors/tag_env_eq_prod"

# --- Arguments (operator_request 또는 both 만) --------------------------
argument_schema:                         # JSON Schema; 콘솔이 렌더 + 검증
  type: object
  properties: {...}
  required: [...]

# --- Provenance (기존) ---------------------------------------------------
provenance:
  source_url: string
  resolved_ref: string                   # git sha / registry version
  content_hash: string                   # sha256
  license: string
  retrieved_at: RFC3339
```

기존 shipped ActionType 은 **자동 마이그레이션**:

- `trigger_kind.kind = rule_violation`
- `category = remediation`
- `ceiling_by_tier` 는 현 implicit default 로 채워짐 (T0 → medium/high
  severity 는 `enforce_hil`, low 는 `enforce_auto`; T1/T2 → `shadow_only`)
- 스키마-깨는 rename 없음; 로더는 누락된 신규 field 를 가장 safe 한 값으로
  취급.

## 3. Category 카탈로그

세 최상위 category. 신규 category 는 doc PR + 도메인 어휘를 flat 하게
유지하기 위해
[architecture.instructions.md](../../.github/instructions/architecture.instructions.md)
에 short-form entry 필요.

### 3.1 `remediation.*`

룰 발화, config-drift 스타일. 현재 shipping:

- `remediate.tag-add`
- `remediate.disable-public-access`
- `remediate.right-size`
- `remediate.rotate-secret`
- `remediate.enable-tde`
- `remediate.enable-encryption`
- `remediate.enable-diagnostic-settings`
- `remediate.enable-backup-protection`
- `remediate.enable-zone-redundancy`
- `remediate.enable-rbac`
- `remediate.restrict-network-access`
- `remediate.remove-orphan-resource`
- `remediate.set-tls-policy`
- `remediate.enable-purge-protection`
- `remediate.set-retention-policy`
- `remediate.assign-identity`

기본 `execution_path: pr_native` (GitOps). Fork 는 API 변경이 하나의
idempotent call 인 액션 별로 `direct_api` 로 override MAY.

### 3.2 `ops.*`

오퍼레이터 요청 runtime 액션. Day 1 shipping:

- `ops.restart-service` - AKS pod 재시작, App Service 재시작, Container App revision 재시작.
- `ops.scale-out` - replica / instance count 증가.
- `ops.scale-in` - replica count 감소 (Approver + live probe).
- `ops.flush-cache` - Redis / CDN cache flush.
- `ops.drain-connection` - load balancer backend 의 connection drain.
- `ops.rotate-cert` - TLS cert 회전 (App Gateway / Front Door).
- `ops.failover-primary` - 복제 리소스에서 failover 트리거.

기본 `execution_path: direct_api` (ops 는 latency-sensitive; PR overhead
는 목적을 defeat). Fork 는 모든 runtime change 가 reviewable diff 로
landing 해야 하는 compliance-heavy 환경에서 `pr_manual` 을 강제 MAY.

### 3.3 `governance.*`

온톨로지 / 카탈로그 / 예외 / promotion 변경. Day 1 shipping:

- `governance.promote-action-type` - 하나의 ActionType 의 `default_mode`
  를 shadow → enforce 로 flip (해당 ActionType 의 `promotion_gate` 로
  bounded).
- `governance.retire-rule` - enforce 집합에서 룰 제거 (shadow-only 또는
  full retire).
- `governance.grant-exemption` - time-boxed 예외 생성
  ([rule-governance.md](rule-governance-ko.md)).
- `governance.override-ceiling` - 특정 resource / tag 스코프에 대한 tier
  ceiling 의 operator-측 override (fork extension).

Governance 액션은 항상 `execution_path: pr_native` 사용 - catalog-as-code
변경이고 reviewed diff 로 landing MUST.

## 4. 트리거 surface

### 4.1 `rule_violation` (동작 변경 없음)

```
Event → EventIngest → TrustRouter → T0/T1/T2 → Finding →
  ActionBuilder(finding, rule, action_type) → Action → RiskGate → Executor
```

- 룰은 `remediates: <action_type_id>` (기존 field) 로 ActionType 을
  declare.
- `ActionBuilder` 는 룰의 `parameters` 블록으로부터 Action 의 `params`
  populate.
- 트리거 surface 는 event bus.

### 4.2 `operator_request` (신규)

```
Chat turn → Narrator → tool_call(action_type_id, args) →
  Coordinator argument_schema 대비 args validate →
  RiskGate → Executor
```

- 오퍼레이터는 narrator 가 tool_call 로 translate 한 자연어 turn 을
  통해 ActionType pick.
- ActionType 의 `argument_schema` (JSON Schema) 는 coordinator 경계에서
  args 를 validate ([operator-console.md § 5.2](operator-console-ko.md#52-consoletool)) -
  콘솔은 잘못된 형태의 액션을 executor 에 절대 dispatch 안 함.
- 트리거 surface 는 오퍼레이터-콘솔 세션.

Note: 두 surface 는 RiskGate 에서 만남 (execution-model.md §3).
ActionType 은 자신의 invocation 을 어느 트리거가 생성했는지 모름 - 오직
`trigger_kind` scoping (§1) 만 제약.

## 5. Argument 스키마 (`operator_request` 만)

룰-발화 ActionType 은 params 를 룰의 `parameters` 블록에서 받음; 오퍼레이터
-요청 ActionType 은 params 를 오퍼레이터의 tool_call arguments 에서 받고
`argument_schema` JSON Schema 를 declare MUST → 콘솔이:

1. `list_tools()` 에서 machine-readable shape 로 tool 렌더.
2. 액션 호출 전 coordinator 경계에서 arguments validate
   ([operator-console.md § 5.2](operator-console-ko.md#52-consoletool)).
3. 감사-write 경계에서 sensitive field (`x-aiopspilot-redact: true` mark)
   redact.

### 5.1 예시 - `ops.restart-service`

```yaml
argument_schema:
  type: object
  additionalProperties: false
  required: [target_resource_ref, restart_reason]
  properties:
    target_resource_ref:
      type: string
      description: CSP-중립 리소스 id, 예 "example-rg/aks/cluster/pod-name".
    restart_reason:
      type: string
      minLength: 10
      maxLength: 200
      description: Human-readable justification; audit trail 에 기록.
    grace_period_seconds:
      type: integer
      default: 30
      minimum: 0
      maximum: 300
```

### 5.2 Redaction 힌트

오퍼레이터가 type MAY 하는 secret 또는 PII 를 carry MAY 하는 field (예:
tool-call 중 password, `restart_reason` 안의 email) 는 redactor 가 audit
write 전 strip 하도록 `x-aiopspilot-redact` 를 carry SHOULD:

```yaml
properties:
  temp_admin_password:
    type: string
    x-aiopspilot-redact: true    # verbatim 저장 절대 안 됨
```

## 6. Live blast probe (execution-model.md §6, Month 1+)

Static `blast_radius` 만으로는 coarse - 같은 "delete storage account"
mutation 이 dead 리소스에서는 사소하지만 live 리소스에서는 catastrophic.
Month 1 은 ActionType 에 **`live_probe_ref`** field 를 추가하므로 RiskGate
가 결정 전에 probe 를 consult 가능.

```yaml
live_probe_ref: probes/vm_traffic_last_5m
```

- Probe 는 [`rule-catalog/probes/`](../../rule-catalog/probes/) 아래
  YAML 로 declare - probe id 당 하나의 파일.
- 각 probe 는 input (target resource ref), query (Azure Monitor KQL /
  Metric API / ARG), interpretation 함수 (`quiet | active | overloaded`)
  를 declare.
- `RiskGate` 는 probe 를 호출하고 answer 를 static ceiling 과 결합 (see
  [execution-model.md § 4](execution-model-ko.md#4-live-blast-probe)).

Probe 는 ActionType 및 환경 별로 opt-in. Fork 가 자체 probe 를 ship;
upstream 카탈로그는 small starter set 을 ship (VM traffic, storage
access log, load-balancer backend health).

## 7. Fork override seam

위의 모든 것은 데이터. Fork 는 `core/` 또는 upstream YAML 을 편집하지
않고 어느 축이든 재정의 MUST 가능해야 함. 온톨로지는 네 override 채널을
노출한다.

### 7.1 파일 기반 overlay

- Upstream 은 `rule-catalog/action-types/<id>.yaml` ship.
- Fork 는 `rule-catalog/action-types-overrides/<id>.yaml` 을 override
  할 field 의 strict subset 으로 배치.
- 로더는 startup 시 upstream + overrides 를 **key-by-key 우선순위**
  로 merge (overrides 승리). 누락된 upstream id 는 fork-only 추가;
  누락된 overrides field 는 upstream 으로 fallback.
- 매 merge 는 audit entry
  (`action_kind=catalog.load.action_type_overlay`) 를 write → 승격된
  override 는 traceable.

```yaml
# 예시: fork 가 prod 에서 tag-add 를 tighten
# path: rule-catalog/action-types-overrides/remediate.tag-add.yaml
id: remediate.tag-add
ceiling_by_tier:
  t0:
    max_autonomy: enforce_hil      # upstream 은 enforce_auto; fork downgrade
prod_downgrade:
  mode: shadow_only
```

### 7.2 Policy-as-code overlay

- `policies/action_types/` 아래 Rego 정책이 per-invocation override 를
  compute MAY, 예: "금요일 오후에 모든 enforce_auto 를 enforce_hil 로
  downgrade" (change freeze).
- RiskGate 는 파일 overlay 후 정책 evaluate - 둘 다 같은 축에 대해
  something 을 express 하면 Rego 승리.

### 7.3 Config-driven overlay

- Coarse switch (feature-flag 스타일) 를 위한 env-var toggle:
  `AIOPSPILOT_OVERRIDE_ACTION_TYPE_<id>_MAX_AUTONOMY=shadow_only`.
- Rare; Rego re-deploy 가 너무 느린 emergency downgrade 를 위해 문서화.

### 7.4 Runtime override (chat)

- 오퍼레이터 콘솔의 Approver / Owner 가 bounded scope
  (`resource_group=X, until=YYYY-MM-DDT..Z`) 로
  `governance.override-ceiling` 호출 MAY. 이는 `pr_native` 로 (감사됨)
  `policies/action_types/` 아래 Rego 정책 fragment 를 write.
- Time-boxed; 자동 만료는 기존 exemption workflow 와 함께 ship
  ([rule-governance.md](rule-governance-ko.md)).

### 7.5 우선순위

여러 overlay 가 같은 축에 대해 speak 하면 우선순위는:

1. Runtime override (Rego fragment, chat-authored, time-boxed) - 가장
   specific, 가장 recent.
2. Rego 정책 (`policies/action_types/`) - operator-authored steady state.
3. 파일 overlay (`rule-catalog/action-types-overrides/`) - fork
   compile-time.
4. Upstream YAML (`rule-catalog/action-types/`) - repository default.

RiskGate 는 항상 그 순서로 resolve 하고 winning overlay layer 를 audit
entry 에 기록.

## 8. 로더 + 검증

- 로더 ([`rule_catalog/schema/action_type.py`](../../src/aiopspilot/rule_catalog/schema/action_type.py))
  는 startup 시 upstream + overrides + Rego reference 를 load.
- Cross-check (기존 shipping):
  - 모든 룰의 `remediates:` 는 로딩된 ActionType 을 pointing.
  - 모든 `check_logic.reference` 는 `policies/` 아래 실제 파일로 resolve.
- 신규 Day-1 cross-check:
  - `trigger_kind = rule_violation | both` → 적어도 하나의 shipped 룰이
    reference, 그렇지 않으면 로더는 "dangling remediation-only ActionType"
    warning 로그 (fatal 아님 - fork 가 나중에 enable MAY).
  - `trigger_kind = operator_request | both` → `argument_schema` 는
    non-empty MUST. 누락된 스키마는 fatal load error.
  - `ceiling_by_tier.t2.max_autonomy != shadow_only` → `policies/action_types/`
    의 Rego 정책이 ActionType 을 명시적으로 name 하지 않는 한 fatal
    (T2 raise 는 operator-authored 정책으로 defend MUST).
  - `live_probe_ref` → 참조된 probe 는 `rule-catalog/probes/` 아래 (또는
    fork-only path 아래) 존재 MUST. 누락된 probe 는 fatal.

## 9. 감사 계약

매 액션 dispatch (룰-발화든 오퍼레이터-발화든) 는 ActionType metadata 를
attach 한 audit entry 를 write:

```json
{
  "action_kind": "action.dispatch",
  "action_type_id": "ops.restart-service",
  "trigger_kind": "operator_request",
  "principal": {...},
  "arguments": {...},
  "arguments_redacted": [...],
  "resolved_ceiling": {
    "tier": "T0",
    "max_autonomy": "enforce_hil",
    "min_role": "contributor",
    "prod_downgrade_applied": false,
    "live_probe_result": "active",
    "winning_overlay_layer": "rego"
  },
  "risk_decision": "hil",
  "mode": "enforce",
  "execution_path": "direct_api",
  "started_at": "...",
  ...
}
```

`resolved_ceiling` 블록은 tier + role + prod + probe + overlay 가 결정에
도달하도록 combine 된 방식의 readable proof. 향후 overlay 변경은 dispatch
시점에 in effect 였던 ceiling 이 verbatim 기록되므로 과거 audit entry 를
절대 break 하지 않음.

## 10. Migration 계획

온톨로지 변경은 세 단계로 landing; 각 단계는 reviewed catalog-as-code PR
(see [rule-governance.md](rule-governance-ko.md)):

1. **스키마 확장** - 로더가 신규 field 를 safe default 로 학습. 모든
   15개 shipped ActionType 이 여전히 validate.
2. **Backfill** - `trigger_kind = rule_violation` 이 모든 기존 entry 에
   set; `ceiling_by_tier` 는 pre-existing implicit ceiling (`default_mode`,
   `promotion_gate.max_policy_escapes`) 로부터 populate.
3. **Ops 카탈로그** - shipped ops.* 집합 (§3.2) 이 `argument_schema`,
   `direct_api` path, appropriate ceiling 과 함께 landing.

오퍼레이터 콘솔은 3단계 완료 전에 `trigger_kind = operator_request`
ActionType 을 소비하지 않음; 이전 단계들은 ControlLoop 에 strictly
non-breaking.

## 11. Testability

- **스키마** - 매 YAML 로드에서 JSON Schema 검증 (기존).
- **Overlay 우선순위** - 모든 축 + layer 조합에 대한 table-driven test
  (§7.5).
- **Argument 스키마** - property test: 스키마 밖의 어느 입력이든 dispatch
  전 reject; redact 된 field 는 audit payload 에 절대 등장 안 함.
- **Live-probe hook** - fake `LiveBlastProbe` 가 `quiet / active /
  overloaded` 각각 반환; ceiling adjustment table-driven.
- **Rego overlay** - 금요일에 downgrade 하는 정책을 exercise 하는 통합
  test; time frozen; audit entry 가 overlay layer 를 name 함을 assert.
- **Cross-check 로드 error** - `operator_request` 에 `argument_schema`
  누락한 fixture ActionType 가 특정 error 로 로드 실패.

## 12. 관련 문서

- [execution-model.md](execution-model-ko.md) - 이 온톨로지를 소비;
  RiskGate + Executor + live-probe combinator.
- [operator-console.md](operator-console-ko.md) - operator-request
  트리거 surface; tool 스키마는 `argument_schema`.
- [rule-governance.md](rule-governance-ko.md) - ActionType promotion,
  retirement, override 가 catalog PR 파이프라인을 통해 flow 하는 방식.
- [phase-1-rule-catalog-t0.md](phases/phase-1-rule-catalog-t0-ko.md) -
  원본 ActionType 도입과 rule → ActionType dispatch.
- [security-and-identity.md](security-and-identity-ko.md) - 모든 액션이
  상속하는 safety invariant 와 identity 계약.
