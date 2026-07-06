---
title: Execution 모델
translation_of: execution-model.md
translation_source_sha: 22e356af93dd6317468bff9f642d63e6c84a6da9
translation_revised: 2026-07-06
---

# Execution 모델

AIOpsPilot 이 액션 실행 **여부** 와 **방법** 을 결정하는 방식. 이 문서는
통합 RiskGate, 5-axis execution-authority 매트릭스, 3개의 executor
경로 (PR-native / direct API / PR-manual), live-blast probe combinator,
그리고 live 변경이 만족해야 하는 safety invariant 를 권위적으로 정의한다.

이 모델의 소비자:

- ControlLoop 과 오퍼레이터-콘솔 coordinator 는 액션 dispatch 전에
  RiskGate 에 ask.
- 각 executor 경로는 액션의 ActionType 이 선언한 safety envelope 를 구현
  ([action-ontology.md](action-ontology-ko.md)).
- 오퍼레이터 콘솔은 `resolved_ceiling` 을 surface → 오퍼레이터가 시스템
  이 auto / HIL / deny 를 결정한 이유를 정확히 볼 수 있음.

> 고객-무관: 아래의 모든 ceiling default, probe expression, role assignment
> 는 placeholder. Fork 는
> [action-ontology.md § 7](action-ontology-ko.md#7-fork-override-seam)
> 에 문서화된 override seam 으로 tune.

## 1. 여기서 "execute" 의 의미

이 문서 이전까지, AIOpsPilot 이 하는 모든 것은 **shadow** 였음 - judge
하고 log, mutate 절대 안 함. Execute 는 모든 gate 통과 후 executor 가
mutation surface (git PR merge, Azure ARM API, scripted rollback runner)
를 실제로 호출하는 것. Shadow mode 는 모든 신규 액션의 기본으로 여전히
유지; execution 은 promoted state, per-action, measured evidence 로
gated, 매 dispatch 에서 re-check.

3개의 실 실행 경로 (§5):

- **PR-native** - 변경이 merge policy 가 auto-accept 하는 git PR 로
  landing (또는 사람이 accept). 감사 + rollback 은 git 으로부터.
- **Direct API** - executor 가 substrate API 를 직접 호출 (Azure ARM,
  kubectl, Redis). 감사는 audit log 에, rollback 은 ActionType 의
  `rollback_contract` 에.
- **PR-manual** - 변경이 `hil` label 을 carry 하는 PR 로 landing; auto-
  merge 없음, approver 가 accept MUST. 자동화된 검증이 부족한 high-risk
  액션에 사용.

단일 ActionType 이 어느 경로를 사용하는지 declare; fork 는 환경별
온톨로지 overlay 를 통해 override.

## 2. 5-axis authority 매트릭스

RiskGate 는 **5개 직교 axis** 를 하나의 결정으로 collapse. 각 axis 는
독립적으로 autonomy 를 낮춤; 최종 결정은 각 axis 가 permit 하는 것의
**minimum**. 여기서 어느 것도 autonomy 를 raise 하지 않음 - upgrade 는
promotion 파이프라인
([phase-2-quality-and-t1.md § Promotion](phases/phase-2-quality-and-t1-ko.md#promotion-shadow--enforce))
을 통해, dispatch time 의 RiskGate 가 아님.

```
authority = min(
  A_tier          # T0 | T1 | T2
  A_ceiling       # ActionType.ceiling_by_tier[tier]
  A_static_blast  # ActionType.blast_radius (선언됨)
  A_live_blast    # live probe → quiet | active | overloaded (Month 1+)
  A_role          # min_role vs principal role (RBAC)
  A_env           # prod → ActionType.prod_downgrade 별 downgrade
)
```

각 axis 는 다음 중 하나 반환:

- `enforce_auto` - HIL 없이 실행 허용.
- `enforce_hil` - 실행 허용하되 사람 승인 필수.
- `shadow_only` - judge 하고 log; mutation 없음.
- `deny` - 진행 안 함; 결정은 hard stop.

최종 RiskGate 출력은 winning minimum + audit consumer 가 reasoning 을
render 할 수 있도록 각 axis 의 기여를 name 하는 `resolved_ceiling`
breakdown (§8) 을 carry 하는 **`RiskDecision`**.

### 2.1 Axis A - Tier

Trust router 로부터.

| Tier | 기본 posture |
|------|-----------------|
| T0 (deterministic) | `enforce_auto` 허용 - T0 판정은 policy-as-code pass |
| T1 (lightweight similarity) | Upstream 은 `enforce_hil` 이상 절대 안 됨; fork 가 ActionType 별로 raise MAY |
| T2 (frontier reasoning) | Upstream 은 `shadow_only` 이상 절대 안 됨; fork 가 raise MAY 하지만 ActionType 을 명시적으로 naming 하는 Rego 정책 하에서만 (action-ontology §7.1) |

### 2.2 Axis B - ActionType ceiling

ActionType 의 `ceiling_by_tier` 로부터
([action-ontology.md § 2](action-ontology-ko.md#2-스키마)).

### 2.3 Axis C - Static blast radius

ActionType 의 `blast_radius` 블록. 두 계산 mode:

- `static_enum` - `resource | subnet | subscription` 중 하나. Bucket 이
  넓을수록 이 axis 는 낮은 값 반환:
  - `resource` → 자체적으로 autonomy 를 낮추지 않음.
  - `subnet` → `enforce_hil` 에 cap.
  - `subscription` → `enforce_hil` 에 cap 하고 ceiling 을 `wide-blast`
    marking → downstream analytics 가 flag.
- `graph_derived` - dispatch time 에 inventory 그래프로부터 computed.
  `max_affected_resources` 초과 값은 다른 axis 와 관계없이 `enforce_hil`
  에 cap.

### 2.4 Axis D - Live blast probe (Month 1+)

`ActionType.live_probe_ref` 가 probe 를 name. Probe 는 세 level 중
하나 반환 (§4). Mapping:

| Probe 결과 | Ceiling 에 대한 효과 |
|--------------|-------------------|
| `quiet` | 변경 없음 - static ceiling 승리 |
| `active` | `enforce_hil` 에 cap (사람 approve) |
| `overloaded` | `shadow_only` 에 cap (defer; 지금은 너무 risky) |

`live_probe_ref` 가 unset 이면 axis 는 "no opinion" 반환 - 자체적으로
autonomy 를 낮추지 않음.

### 2.5 Axis E - Role (RBAC)

`ActionType.ceiling_by_tier[tier].min_role` vs 호출 principal 의
resolved role ([user-rbac-and-identity.md](user-rbac-and-identity-ko.md)
로부터):

- Principal 이 `min_role` 이상 → axis 가 tier default 반환.
- Principal 이 `min_role` 미달 → axis 가 `deny` 반환.
- BreakGlass principal → axis 가 `enforce_hil` 반환 (`_auto` 절대 아님;
  BreakGlass 는 HIL 을 절대 우회 안 함, reviewer 가 eligible 하게 만들
  뿐).

룰-발화 액션의 경우 "principal" 은 executor identity (시스템 MI); 그
role 은 composition time 에 fixed
([composition.py](../../src/aiopspilot/composition.py)).

### 2.6 Axis F - Environment (prod downgrade)

`ActionType.prod_downgrade` 가 env-detector reference 를 name. Detector
가 target 리소스에 대해 "prod" 반환 시, axis 는 `prod_downgrade.mode`
(전형적으로 `enforce_hil` 또는 `shadow_only`) 에 cap. `prod_downgrade`
블록 누락은 이 ActionType 에 대해 axis 가 비활성 (dev-only 액션은 이거
없이 ship).

### 2.7 결합

각 axis 는 위 4 level 중 하나 반환; RiskGate 는 순서
`enforce_auto > enforce_hil > shadow_only > deny` 에서 **minimum** 을
취함. 어느 axis 의 `deny` 든 hard stop; executor 는 절대 호출 안 됨.

## 3. 통합 RiskGate

RiskGate 는
[`src/aiopspilot/core/risk_gate/`](../../src/aiopspilot/core/risk_gate/)
에 살고 **두** trigger surface (룰-발화와 오퍼레이터-요청; see
[action-ontology.md § 4](action-ontology-ko.md#4-트리거-surface))
의 단일 결정 지점.

계약:

```python
class RiskGate(Protocol):
    async def evaluate(
        self,
        *,
        action_type: OntologyActionType,
        action: Action,
        trigger_kind: TriggerKind,
        tier: TrustTier,
        principal: Principal,
        env: EnvClassification,
        promotion_state: ActionModeRecord,
    ) -> RiskDecision: ...

@dataclass(frozen=True)
class RiskDecision:
    decision: Literal["auto", "hil", "abstain", "deny"]
    mode: Literal["shadow", "enforce"]
    execution_path: ExecutionPath          # ActionType 로부터 inherit, lower 강제 MAY
    resolved_ceiling: ResolvedCeiling      # audit-friendly breakdown (§8)
    hil_queue_id: str | None               # decision == "hil" 시 populated
```

- `promotion_state` 는 기존
  [`ActionPromotionRegistry`](../../src/aiopspilot/core/risk_gate/gate.py)
  로부터 read - shadow-mode ActionType 은 axis 가 permit 하는 것과 관계
  없이 `mode` 를 `shadow` 로 clamp.
- `execution_path` 는 ActionType 기본이나 axis (전형적으로 role 또는
  env axis) 가 downgrade 강제 시 (예: compliance-heavy fork 가 prod 의
  모든 direct-API ActionType 에 `pr_manual` 강제).
- RiskGate 는 **dispatch attempt 당 한 번** 호출. Retry 의 re-check 는
  fresh dispatch (fresh audit entry).

### 3.1 오퍼레이터-콘솔 verifier 와의 상호작용

콘솔의 coordinator 는 매 write-class tool call 에서 RiskGate 를 재실행
([operator-console.md § 7.2](operator-console-ko.md#72-chat-특화-3-invariant),
invariant 5). 콘솔은 이 경로를 절대 우회하지 않음; "trusted narrator
shortcut" 없음.

### 3.2 `ActionPromotionRegistry` 와의 상호작용

Promotion 은 RiskGate 와 직교:

- `ActionPromotionRegistry.mode_of(action_type)` 는 ActionType 이
  enforce-eligible 인지 결정.
- RiskGate 는 그것을 upper bound 로 취하고 5 axis 와 결합. 승격된
  ActionType 이 여전히 axis 에 의해 `hil` 로 gate MAY; promotion state
  가 `auto` 를 강제하지 않음.

## 4. Live blast probe

Static `blast_radius` 는 "이 ActionType 은 subnet 까지 영향 MAY" 말함;
live probe 는 "이 특정 리소스는 지난 5분 트래픽 0, 그러므로 실제 영향
없음" 말함. Static + live 결합은 "실행 중인 NSG rule 변경은 아무도
호출하지 않을 때 저-영향" 이라는 직관 뒤의 mechanism.

### 4.1 Probe 선언

Probe 는 [`rule-catalog/probes/`](../../rule-catalog/probes/) 아래 살음:

```yaml
schema_version: "1.0.0"
id: vm_traffic_last_5m
description: "지난 5분 VM 네트워크 throughput 기반 quiet/active/overloaded 반환."
adapter_ref: probe-adapters/azure-monitor       # DI seam id
kql: |
  AzureMetrics
  | where ResourceId == '{{ target_ref }}'
  | where MetricName == 'Network In Total'
  | where TimeGenerated > ago(5m)
  | summarize p = percentile(Total, 95)
interpretation:
  quiet:      p < 1000000            # <1 MB/5min
  active:     p < 100000000          # <100 MB/5min
  overloaded: p >= 100000000
timeout_seconds: 5
cache_ttl_seconds: 60
```

### 4.2 Runtime 형태

RiskGate 는 probe 를 **오직** 다음 시에만 호출:

- `ActionType.live_probe_ref` 가 set.
- 다른 axis 가 아직 `shadow_only` 또는 `deny` 로 강제하지 않음
  (probe cost 는 결정을 실제로 변경 가능할 때만 지불).
- Probe 캐시가 target 에 대해 fresh answer 없음.

Probe 실패 (timeout, adapter error) 는 `active` 로 default - safer
interpretation. Rolling window 를 가로지르는 반복 실패는 `probe.degraded`
audit entry 트리거 → 오퍼레이터가 inspect; 전체 loop 를 fail-close 하지
않음.

### 4.3 Probe adapter seam

```python
class LiveBlastProbe(Protocol):
    async def measure(
        self,
        *,
        probe_id: str,
        target_ref: str,
        deadline_seconds: float,
    ) -> ProbeResult: ...
```

Upstream Day-1 는 fake `NoOpBlastProbe` (returns "no opinion") ship;
Month-1 은 `AzureMonitorBlastProbe` 추가. Fork 는 Protocol 을 구현하는
어떤 adapter 든 bind MAY.

## 5. Executor 경로

3 경로가 모든 액션 cover; ActionType 이 어느 것을 사용하는지 name 하고
RiskGate 는 `pr_manual` 로 downgrade MAY (upgrade 절대 안 함).

### 5.1 PR-native (`pr_native`)

- Executor 가
  [`GitOpsPrAdapter`](../../src/aiopspilot/delivery/gitops_pr/adapter.py)
  로 PR 빌드.
- `auto` 결정 시, PR 은 `hil` label 을 carry 안 함 → branch 의
  auto-merge 정책이 accept.
- `hil` 결정 시, PR 은 `hil` label 을 carry → approver 가 콘솔로 merge.
- 감사 + rollback 은 git 에 lean: revert commit 이 rollback path.

Best for: configuration 변경, IaC patch, 카탈로그 업데이트, governance
변경.

### 5.2 Direct API (`direct_api`)

- Executor 가 substrate API 를 직접 호출 (Azure ARM, kubectl,
  `src/aiopspilot/delivery/` 아래 해당 delivery adapter 를 통한 Redis).
- `auto` 결정 시, call 이 HIL 없이 진행; ActionType 의 `stop_conditions`
  와 `preconditions` 가 call 전후로 executor 에 의해 enforce.
- `hil` 결정 시, executor 가 HIL item 을 enqueue (PR-manual 큐와 동일
  하지만 item 에 `mutation_target=direct` 로); approver 가 콘솔로
  accept; 그 후 executor 가 dispatch.
- Rollback 은 ActionType 의 `rollback_contract` 로부터 (`scripted`,
  `pitr`, `snapshot_restore`).
- **Idempotency invariant** - 매 direct-API call 은 액션의 안정된
  idempotency key 사용 (기존 invariant
  [coding-conventions.instructions.md](../../.github/instructions/coding-conventions.instructions.md));
  retry 된 call 이 double-apply MUST NOT.

Best for: latency 가 중요한 ops 액션 (재시작, scale, cache flush).

### 5.3 PR-manual (`pr_manual`)

- PR-native 와 동일하지만 이 PR 에 대해 auto-merge 정책 비활성 (label
  `hil` + 명시적 `merge-not-eligible`).
- Axis 와 관계없이 사람 review 필수; 모든 axis 에서 `enforce_auto` 라도
  여전히 manual-merge PR 로 landing.
- 매우 high-risk 액션 또는 자동화와 관계없이 모든 mutation 이
  reviewable diff MUST 인 compliance-heavy 환경에 사용.

Best for: scripted rollback 있는 irreversible 변경, fork 가 자동화와
관계없이 두 번째 pair of eyes 를 원하는 governance 변경.

### 5.4 Dispatch 시 executor selection

```
requested_path = ActionType.execution_path
forced_path = RiskGate.resolved_ceiling.forced_execution_path  # 옵션 axis 출력
final_path = strictest(requested_path, forced_path)
                # 엄격 순서: pr_manual > pr_native > direct_api
```

Fork 는 env axis 를 통해 prod 의 모든 dispatch 를 `pr_manual` 로 강제
가능. Upstream 은 절대 아래로부터 강제 안 함 (`pr_manual` 을 속도 위해
`direct_api` 로 lift 안 함).

## 6. 안전 invariant (변경 없음 + 하나 확장)

모든 executed 액션은 이미
[coding-conventions.instructions.md § Safety](../../.github/instructions/coding-conventions.instructions.md#safety)
의 4 autonomy invariant (stop-condition, rollback, blast-radius limit,
audit) 를 carry. 이 문서는 하나 추가:

5. **매 dispatch 는 `resolved_ceiling` 을 write.** Audit entry 는
   결정을 생성한 완전한 5-axis breakdown 을 carry MUST → 향후 overlay
   변경이 과거 결정의 재현성을 절대 break 안 함.

다른 invariant 는 정확히 이전과 같이 적용 - chat-specific carve-out
없음, direct-API relaxation 없음.

### 6.1 오퍼레이터-콘솔 invariant 와의 상호작용

Chat-특화 invariant ([operator-console.md § 7.2](operator-console-ko.md#72-chat-특화-3-invariant))
는 additive:

- **Chat invariant 5 (verifier re-check)** = "매 write-class tool call
  에서 RiskGate 실행". 이 문서가 해당 RiskGate 의 정의; 콘솔은 그저
  호출.
- **Chat invariant 6 (no self-approval)** = RiskGate 의 role axis
  (Axis E) 가 caller 의 Entra `oid` 가 큐잉된 item 의 requester 와
  매치할 때 `approve_hil` refuse.
- **Chat invariant 7 (BreakGlass time-boxed)** = Axis E 의 BreakGlass
  동작 (§2.5): BreakGlass 는 approval 을 위한 eligible role 을 raise
  하지만 HIL 을 절대 우회 안 함.

## 7. 결정론성 + 감사성

- 동일한 5-axis 입력이 주어지면 RiskGate 는 동일한 `RiskDecision`
  반환. 어떤 stochastic 구성요소 (moving window 를 query 하는 probe)
  든 probe 의 `cache_ttl_seconds` 로 bounded → TTL 내 replay 가
  identical 결정 yield.
- `resolved_ceiling` 블록은 결정의 완전한 self-explanation - dispatch
  시점에 in effect 였던 ceiling 이 record of truth 이므로 향후 overlay
  변경이 과거 audit entry 를 절대 invalidate 안 함.

## 8. `resolved_ceiling` audit 블록

매 dispatch 는 write:

```json
{
  "resolved_ceiling": {
    "tier": "T0",
    "action_type_id": "ops.restart-service",
    "axes": {
      "tier":           {"level": "enforce_auto", "reason": "shadow-promoted ActionType 의 T0 판정"},
      "ceiling":        {"level": "enforce_hil",  "reason": "ceiling_by_tier.t0.max_autonomy"},
      "static_blast":   {"level": "enforce_auto", "reason": "static_bucket=resource"},
      "live_blast":     {"level": "enforce_hil",  "reason": "probe=vm_traffic_last_5m returned active", "probe_result": "active"},
      "role":           {"level": "enforce_hil",  "reason": "principal=contributor >= min_role=contributor"},
      "env":            {"level": "enforce_auto", "reason": "not-prod"}
    },
    "winning_axis": "ceiling",
    "final_level":  "enforce_hil",
    "final_path":   "direct_api",
    "overlay_layers_applied": ["upstream", "rego"]
  }
}
```

## 9. 단계별 rollout

Execution 모델은 데이터 + 정책 변경; 어떤 서브시스템의 tier upgrade 도
요구하지 않음. Rollout 은
[action-ontology.md § 10](action-ontology-ko.md#10-migration-계획) 의
ActionType 마이그레이션에 매치.

### Day 1

- 스키마 확장만. 로더가 신규 field 학습; 모든 기존 ActionType 이 validate.
  RiskGate 는 오늘처럼 계속 동작 (shadow-only) - `promotion_state` 가
  모든 entry 에 대해 shadow 이기 때문.
- **Exit gate**: 5-axis min-combination 에 대한 property test; 모든
  기존 shipped 룰이 변경 전과 동일한 shadow-only outcome 을 여전히
  produce.

### Week 1

- 온톨로지 backfill landing (action-ontology.md § 10 step 2 참조).
- ControlLoop 이 매 dispatch 에서 통합 RiskGate 로 routing 시작 (이전
  stub 이었음); ActionType 이 promote 안 됐으므로 execution 은 shadow-
  only 유지.
- 오퍼레이터-콘솔 pull-방향이 argument-schema-validated dispatch path
  (§3.1) 와 함께 ship.
- **Exit gate**: `resolved_ceiling` audit 블록이 매 dispatch 에 등장;
  룰-발화 + 오퍼레이터-발화 경로가 동일한 RiskGate 를 통해 동일한
  executor 에 도달함을 커버하는 end-to-end test.

### Week 2

- 첫 `ops.*` ActionType 이 `execution_path=direct_api` 와
  `ceiling_by_tier.t0.max_autonomy=enforce_auto` 로 landing. RiskGate
  는 이제 Reader-visible 리소스의 non-prod 에 대해 `auto` 를 produce.
- **Exit gate**: 콘솔을 통한 Contributor 가 live-probe fake (`quiet`)
  하에 non-prod 리소스에서 `ops.restart-service` 실행; executor 가
  (mocked) ARM API 호출; audit entry 가 `direct_api` path 를 carry.

### Month 1

- 실 `AzureMonitorBlastProbe` bind; live probe 가 opt in 한 ActionType
  에서 live 로 감.
- `governance.override-ceiling` landing → Owner 가 콘솔로부터 ceiling
  downgrade 를 time-box 가능 (action-ontology §7.4).
- **Exit gate**: 최소 하나의 live probe 가 production shadow 측정에서
  최소 한 번 autonomy 를 reduce; 그 dispatch 의 audit entry 가
  `winning_axis=live_blast` 를 표시.

## 10. Testability

- **5-axis 매트릭스** - determinate 결과를 가진 모든
  (tier × ceiling × static_blast × live_blast × role × env) 조합에
  대한 table-driven property test; `min()` semantics assert.
- **Overlay 우선순위 + resolved_ceiling** - 동일 axis 에 모든 네 overlay
  layer 가 active 인 fixture; higher-precedence layer 승리 및
  `overlay_layers_applied` 아래 이름 등장 assert.
- **Live-probe fake** - `NoOpBlastProbe` 가 `quiet / active /
  overloaded` 각각 반환; RiskGate 출력이 예상대로 변경.
- **Executor path selection** - table-driven: ActionType.default vs
  forced_path; strict-order winner assert.
- **Direct-API idempotency** - executor 의 dispatch 가 동일한
  idempotency key 로 두 번 호출; substrate adapter 가 정확히 하나의
  mutation 기록.
- **PR-native + PR-manual auto-merge 정책** - adapter 가 emit 하는
  label set 에 대한 contract test; label 매트릭스 assert.
- **RiskDecision 은 authority 를 upgrade 할 수 없음** - property test:
  ActionType 의 `promotion_state=shadow` → RiskDecision.mode 는 다른
  모든 axis 와 관계없이 항상 `shadow`.

## 11. 실패 모드

- **Probe timeout / error** → default `active` (§4.2); `probe.degraded`
  로그; fail-close 안 함.
- **Overlay 로드 error** (Rego syntax error, missing file overlay
  target) → 로더가 upstream default 로 fallback 하고 `overlay.load_failed`
  audit write; RiskGate 는 `overlay_layers_applied` 를 그에 맞게 mark.
  Overlay 가 applied 인 척 silently 하지 않음.
- **Executor path 도달 불가** (direct_api adapter down) → 그 dispatch
  에 대해 `pr_manual` 로 fallback; `executor.path.degraded` write;
  오퍼레이터는 audit entry 의 resolved_ceiling 에서 fallback 을 봄.
- **RiskGate 자체 unavailable** (일어나면 안 됨 - 입력의 pure function)
  → fail-close: dispatch 없음, `deny` audit, operational lane 페이지.

## 12. 관련 문서

- [action-ontology.md](action-ontology-ko.md) - 이 문서가 소비하는
  ActionType 스키마 + fork 가 매트릭스를 tune 하는 override seam.
- [operator-console.md](operator-console-ko.md) - RiskGate 는 콘솔의
  chat invariant 가 매 write-class tool call 에 요구하는 verifier.
- [phase-2-quality-and-t1.md](phases/phase-2-quality-and-t1-ko.md) -
  ActionType 을 shadow 에서 enforce 로 flip 하는 promotion 파이프라인.
- [risk-classification.md](risk-classification-ko.md) - 이 axis
  매트릭스가 확장하는 초기 auto / HIL / deny 룰 표.
- [security-and-identity.md](security-and-identity-ko.md) - 4 autonomy
  invariant + executor identity 계약.
- [architecture.instructions.md](../../.github/instructions/architecture.instructions.md) -
  trust routing, verifier authority.
