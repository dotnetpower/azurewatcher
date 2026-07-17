---
title: SLO와 오류 예산
description: FDAI가 워크로드 목표를 평가하고 burn-rate 증거를 governed incident signal로 바꾸는 방법입니다.
translation_of: slos-and-error-budgets.md
translation_source_sha: d3ce258b9ced3870828ede988fc0ddede033cd20
translation_revised: 2026-07-17
---

# SLO와 오류 예산

서비스 수준 목표(Service Level Objective, SLO)는 기술 신호를 사용자 영향과 연결합니다.
FDAI는 워크로드 대상 service level indicator(SLI), 목표, 오류 예산, 다중 window burn
rate를 평가해 인시던트 우선순위와 변경 판단에 측정된 신뢰성 증거를 사용합니다.

> Upstream SLO registry, evaluator, event runner는 구현되어 있습니다. 실제 평가는
> 배포 환경에서 실제 `MetricProvider`를 연결하고 runner를 예약할 때까지 Partial입니다.
> 워크로드 SLO는 FDAI control-plane health objective와 구분됩니다.

## 목표 정의

SLO entry는 workload 및 scope, SLI kind, target, measurement window, burn-rate alert
window를 식별합니다. 정의는 catalog-as-code로 관리하고 로드 시점에 검증합니다.

| 요소 | 예시 의미 |
|------|-----------|
| SLI | 성공한 request를 유효 request로 나눈 비율 |
| Objective | 30일 동안 99.9% |
| Error budget | 해당 window에서 허용되는 실패 비율 |
| Burn rate | 남은 budget이 소비되는 속도 |

## Burn rate 평가

FDAI는 짧은 window와 긴 window를 함께 사용합니다. 짧은 spike만 보면 noise일 수 있고,
긴 window breach만 보면 대응이 늦을 수 있습니다. 다중 window 평가는 설정된 조합이
지속적이거나 긴급한 budget 소비를 나타낼 때만 finding을 생성합니다.

결과는 objective, attainment, remaining budget, evaluated window, threshold, source
freshness를 기록합니다. Metric data가 없거나 오래되면 fail closed하며 정상 값으로
처리하지 않습니다.

## 위반에서 대응까지

1. Metric provider가 범위와 timestamp가 있는 sample을 반환합니다.
2. Burn-rate evaluator가 설정된 window를 계산합니다.
3. `SloBurnRunner`가 `slo.error_budget_burn` event를 게시합니다.
4. Event ingest가 event를 중복 제거하고 진행 중인 change 또는 incident와 연계합니다.
5. Trust-router와 risk-gate가 관찰, 알림, 승인 요청, typed mitigation 중 경로를 정합니다.

SLO breach는 finding이며 rollback이나 scale 권한이 아닙니다. 대응에는 계속 `ActionType`,
검증, blast-radius 제한, rollback, 필요한 verdict가 있어야 합니다.

## 운영자 확인 사항

- SLI가 편리한 infrastructure proxy가 아니라 user impact를 측정하는지 확인합니다.
- Metric source, freshness, missing-data policy, measurement window를 확인합니다.
- 짧은 window와 긴 window의 burn rate를 함께 검토합니다.
- Burn을 deployment, maintenance window, active incident와 연계합니다.
- Browser 계산만으로 위험한 change를 freeze하지 말고 governed policy를 사용합니다.

## 다음 단계

| 학습 대상 | 문서 |
|-----------|------|
| Telemetry가 finding이 되는 방법 | [관측성, 감지, 예측](observability-detection-and-forecasting-ko.md) |
| Breach가 incident에 합류하는 방법 | [인시던트 관리](incident-management-ko.md) |
| Capacity 증거가 SLO를 보완하는 방법 | [용량과 성능](capacity-and-performance-ko.md) |
| 표준 outcome metric | [목표와 메트릭](../../roadmap/architecture/goals-and-metrics-ko.md) |
