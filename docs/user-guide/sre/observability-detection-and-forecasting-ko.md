---
title: 관측성, 감지, 예측
description: FDAI가 두 번째 실행 경로를 만들지 않고 이벤트와 telemetry를 연계된 설명 가능한 finding으로 바꾸는 방법입니다.
translation_of: observability-detection-and-forecasting.md
translation_source_sha: 63246b9386c0dfffb8dd977b50380cab14cb69d9
translation_revised: 2026-07-17
---

# 관측성, 감지, 예측

FDAI는 관측성을 실행 surface가 아니라 증거 생성으로 다룹니다. 이벤트, 메트릭, 로그,
트레이스, 이상, 예측은 정규화된 finding이 되어 다른 모든 이벤트와 동일한 trust 및
risk pipeline에 다시 들어갑니다.

> 이벤트 상관관계, 결정론적 이상 감지, 예측은 upstream에 구현되어 있습니다. 실제
> 워크로드를 관찰하려면 배포 환경에서 metric, log, trace provider를 연결해야 합니다.

## 이 가이드에서 다루는 내용

- 원시 신호, finding, incident, action의 차이.
- 결정론적 상관관계가 데이터를 버리지 않고 알림 노이즈를 줄이는 방법.
- 이상 및 예측 detector가 설명 가능성과 shadow-first를 유지하는 방법.
- 감지 결과를 신뢰하기 전에 운영자가 확인할 증거.

## 신호 모델

| 레코드 | 의미 | 실행 가능 여부 |
|--------|------|----------------|
| 원시 신호 | provider 이벤트, metric sample, log, trace 하나 | 불가 |
| Finding | 정규화된 anomaly, forecast, policy observation | 불가 |
| Incident | 관련 event와 finding의 안정적인 그룹 | 불가 |
| RCA hypothesis | 인용이 있는 incident 설명 | 불가 |
| Action proposal | 안전 계약을 가진 typed change | 일반 gate 통과 후에만 가능 |

Finding 자체는 변경 권한을 부여하지 않습니다. `ActionType`에 매핑되고, 검증 및 scope
검사를 통과하고, resource lock을 획득하며, policy가 요구하는 risk verdict를 받아야
합니다.

## 판단 전에 연계

상관관계는 정규화 및 중복 제거 이후에 실행됩니다. Resource, deployment, trace,
causal parent, 제한된 time window 같은 안정적인 key로 신호를 그룹화합니다. 늦게 도착한
member는 열린 incident에 합류할 수 있으며, 설정된 window를 지난 event는 연결된 후속
incident를 생성합니다.

상관관계는 레코드가 서로 관련됐음을 나타낼 뿐, 하나가 다른 하나의 원인이라고 주장하지
않습니다. 인과관계 판단은 근본 원인 분석이 담당합니다.

예시: deployment가 변경 event 하나를 생성하고 네 service에서 error 발생 -> 공유된
deployment 및 resource graph가 incident 하나를 생성 -> 원시 레코드 다섯 개는 member로
모두 유지 -> RCA가 원인을 별도로 평가.

## 설명 가능한 이상 감지

결정론적 detector는 metric을 설정된 rolling 또는 seasonal baseline과 비교합니다.
Finding은 baseline, observed value, deviation, direction, window, severity를 기록하므로
운영자가 발생 이유를 재현할 수 있습니다.

- **Cold start**: 이력이 부족하면 추측하지 않고 abstain합니다.
- **Flat baseline**: 분산이 0인 경우를 명시적으로 처리해 0 나눗셈이나 무한 severity를
  만들지 않습니다.
- **Seasonality**: pooled 24x7 평균이 아니라 같은 시간대 또는 주간 phase와 비교합니다.
- **Composite degradation**: 여러 metric finding이 quorum을 충족해야 compound anomaly를
  생성할 수 있습니다.
- **Change awareness**: maintenance 및 진행 중인 change는 예상된 deviation을 주석 처리하거나
  억제합니다.

## 임계값 위반 예측

Forecast detector는 측정된 추세가 제한된 horizon 안에서 설정된 threshold를 넘을지
추정합니다. 각 결과는 예상 위반 시각, fit quality, uncertainty band를 포함합니다. Fit이
약하거나 crossing이 불확실하면 abstain합니다.

일반적인 대상은 capacity exhaustion, RPO limit에 가까워지는 replication lag,
certificate expiry, budget run rate, backup-retention drift입니다.

Forecast는 결정론적 사실이 아닙니다. Finding을 생성하고 예방적 remediation pull request를
제안할 수 있지만, 제안은 계속 trust-router, verifier, risk-gate, 일반 승인 정책을
통과해야 합니다.

## 운영자 워크플로

1. Provider, resource, time window, data freshness를 확인합니다.
2. Baseline, threshold, deviation, cold-start 상태를 검사합니다.
3. Incident membership과 deployment 또는 maintenance window가 신호를 설명하는지 확인합니다.
4. Correlation ID를 따라 RCA, verdict, action proposal, audit row를 확인합니다.
5. 누락된 증거는 unavailable로 처리합니다. 0이나 정상 상태로 추론하지 마세요.

## 증거와 보호 지표

Detector fire rate, cold-start abstention, false-positive rate, false-negative rate,
forecast precision 및 recall, forecast lead time, incident-to-raw-signal ratio를
추적합니다. 승격에는 고정된 scenario set에서 측정한 증거가 필요하며, 회귀가 발생하면
detector를 shadow로 되돌립니다.

## 상세 레퍼런스

구현 계약, detector 알고리즘, control-loop wiring은
[관측성과 감지](../../roadmap/rules-and-detection/observability-and-detection-ko.md)에
정의되어 있습니다.

## 다음 단계

| 학습 대상 | 문서 |
|-----------|------|
| Finding이 incident가 되는 방법 | [인시던트 관리](incident-management-ko.md) |
| 워크로드 영향이 우선순위를 바꾸는 방법 | [SLO와 오류 예산](slos-and-error-budgets-ko.md) |
| 원인이 상관관계와 다른 이유 | [근본 원인 분석](root-cause-analysis-ko.md) |
| 최종 증거를 검사하는 방법 | [감사 로그 읽기](../guides/read-audit-log-ko.md) |
