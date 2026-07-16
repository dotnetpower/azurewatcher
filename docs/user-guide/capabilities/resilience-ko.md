---
title: 회복탄력성
description: FDAI가 필요해지기 전에 복구를 증명하는 방법 - 예약된 DR 훈련, 범위가 제한된 카오스 실험, 알려진 실패 패턴에 대한 자가 치유.
translation_of: resilience.md
translation_source_sha: 3d5800248f2bf611ad74922e8775c4d3d91811ac
translation_revised: 2026-07-17
---

# 회복탄력성

FDAI는 여러분의 워크로드를 복구 가능한 상태로 유지하고, 장애 중이 아니라 정해진
일정에 그것을 증명합니다. 재해 복구를 리허설하고, 데이터베이스를 복구 목표에 대해
연습하며, blast-radius가 제한된 카오스 실험을 실행하고, 이전에 본 실패 패턴을 자가
치유합니다 - 그래서 복구 경로가 처음 실행되는 순간이 결코 실제 장애가 아닙니다.

## 무엇을 얻나요

- **예약된 DR 훈련.** 재해 복구 리허설이 임시가 아니라 정의된 연습 창(window)에서
  실행되고 결과를 기록합니다.
- **복구 목표 검증.** 데이터베이스 연습이 여러분의 목표 RPO와 RTO에 대해 복원하고,
  중요해지기 전에 갭(예: point-in-time-restore 갭)을 플래그합니다.
- **범위가 제한된 카오스 실험.** 실패는 엄격한 blast-radius 한도 안에서 주입되므로,
  실험이 선언된 범위를 결코 초과할 수 없습니다.
- **알려진 패턴에 대한 자가 치유.** 해소된 인시던트와 일치하는 실패는 자동
  교정되고, 새로운 소수는 여러분에게 에스컬레이션됩니다.

## FDAI가 복구를 증명하는 방법

<!-- fdai:steps -->

1. **갭 찾기.** 예약된 작업이 회복탄력성 갭 - 예컨대 중요 데이터베이스의
   point-in-time-restore 갭 - 을 감지하고 finding을 올립니다.
2. **훈련 예약.** 에이전트가 정의된 연습 창 안에 짝지어진 복원 훈련을 예약하며,
   결코 라이브 트래픽에 무제한으로 실행하지 않습니다.
3. **blast radius 안에서 실행.** 연습은 범위, 배치, 속도 한도 아래에서 실행됩니다 -
   모든 자율 액션이 담는 동일한 안전 불변식.
4. **목표 대비 검증.** 복원은 목표 RPO와 RTO에 대해 확인되고, 성공과 실패가 모두
   기록됩니다.
5. **증거 감사.** 결과는 복구 경로가 작동한다는 증거로서 추가 전용(append-only)
   감사 로그에 들어갑니다.

## 약속이 아니라 증거

회복탄력성은 단언하지 않고 베이스라인 대비 측정합니다(
[목표와 메트릭](../../roadmap/architecture/goals-and-metrics-ko.md) 참조):

- **MTTR** - 평균 해소 시간, 평균과 함께 중앙값과 p90으로 보고 - 은 단축 지향
  목표입니다.
- **자동 해소율** - 사람 개입 0이고 롤백 없이 해소된 이벤트 - 은 높이는 방향의
  목표입니다.
- **롤백률**과 **거짓 음성률(false-negative rate)**은 가드 메트릭입니다: 둘 다
  베이스라인 임계값을 넘어 악화되면 안 됩니다.

모든 훈련과 자가 치유는 먼저 [shadow 모드](../concepts/shadow-then-enforce-ko.md)로
출시되고, 측정된 정확도가 유지된 뒤에만 승격됩니다.

## 관련 문서

<!-- fdai:cards -->

- [SRE 기초](../concepts/sre-foundations-ko.md) - FDAI가 인코딩하는 SRE 실천.
- [에이전트와 자가 치유](../concepts/agents-and-self-healing-ko.md) - 에이전트 조직이 실패를 해소하는 방식.
- [리스크 티어](../concepts/risk-tiers-ko.md) - 복구 액션이 auto, HIL, deny로 라우팅되는 방식.
- [운영 준비성 검토](../../roadmap/operations/operational-readiness-ko.md) - dev에서 ops로의 준비성 게이트.
- [배포와 온보딩](../../roadmap/deployment/deploy-and-onboard-ko.md) - FDAI를 여러분의 환경에 도입하기.
