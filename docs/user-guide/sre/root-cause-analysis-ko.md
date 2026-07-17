---
title: 근본 원인 분석
description: FDAI가 티어별 인용 가능한 근본 원인 가설을 만들고 증거가 부족할 때 abstain하는 방법입니다.
translation_of: root-cause-analysis.md
translation_source_sha: 0cefa911944a974f4888c08e556e87ad46797ca8
translation_revised: 2026-07-17
---

# 근본 원인 분석

근본 원인 분석(Root-Cause Analysis, RCA)은 인시던트가 발생했을 수 있는 이유를
설명합니다. FDAI는 RCA를 citation, confidence, tier, grounding state가 있는 hypothesis로
저장합니다. RCA는 판단을 위한 증거이며 변경 실행 권한이 아닙니다.

## Trust tier별 RCA

| 티어 | 역할 | 일반적인 증거 |
|------|------|---------------|
| T0 | 직접적인 결정론적 원인 | 일치한 rule, 위반된 control, 선언된 remediation |
| T1 | 과거 incident 재사용 또는 결정론적 causal chain | 해결된 incident, 순서가 있는 change 및 symptom event, resource dependency |
| T2 | 신규 또는 모호한 사례의 grounded reasoning | 검증된 telemetry, event, rule, knowledge chunk, scenario evidence |

T1 reuse는 과거 원인과 learned action이 현재 증거에도 적용되는지 다시 검증합니다. T1
causal chain은 선행 change를 root로 요구합니다. Symptom만 있는 window는 원인을 만들지
않고 abstain합니다.

## Grounding gate

모든 citation은 reasoner에 제공된 evidence set에서 나와야 합니다. Malformed response,
fabricated citation, unsupported claim, 설정 threshold 미만 confidence는 abstained
hypothesis가 되어 사람 검토로 이동합니다.

Telemetry와 operator document는 untrusted input입니다. Model text는 policy, what-if 결과,
deterministic verifier를 덮어쓸 수 없습니다.

## Causal chain

Structured T1 chain은 root 및 failure event ID와 ordered hop을 보존합니다. 각 hop은 cause
및 effect reference, lead time, relationship, confidence를 기록합니다. Resource dependency
data가 있으면 관련 경로를 강화하고 무관한 연결을 차단합니다.

시간 순서만으로 확실한 원인이 되지 않습니다. Confidence는 제한되며 여러 root가 비슷하게
failure를 설명하면 낮아지고, 가장 약한 supported link를 기준으로 결정됩니다.

## RCA dossier 읽기

다음 요소를 함께 확인하세요.

1. Incident 및 correlation ID.
2. Tier, outcome, confidence, grounding state.
3. Citation과 evidence freshness.
4. Alternative 또는 ambiguous hypothesis.
5. 존재하는 경우 structured causal hop.
6. 연결된 response plan, verdict, mode, rollback reference.

Chain data나 evidence가 없으면 unavailable로 표시합니다. Browser는 audit record보다 더
확신도 높은 설명을 재구성하지 않습니다.

## 다음 단계

| 학습 대상 | 문서 |
|-----------|------|
| 증거 범위를 제한하는 방법 | [분류와 조사](triage-and-investigation-ko.md) |
| Mitigation을 제안하는 방법 | [대응 계획과 완화](response-plans-and-mitigation-ko.md) |
| 판단을 감사하는 방법 | [감사 로그 읽기](../guides/read-audit-log-ko.md) |
| 상세 RCA 계약 | [관측성과 감지](../../roadmap/rules-and-detection/observability-and-detection-ko.md) |
