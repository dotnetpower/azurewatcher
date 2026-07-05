---
title: AIOpsPilot 시작하기
description: AIOpsPilot 5분 오리엔테이션 — 무엇인지, 언제 적합한지, 다음으로 어디를 볼지.
translation_of: get-started.md
translation_source_sha: d35e776779d675c9f47dd288ee3c21cf95a1dbaf
translation_revised: 2026-07-05
---

# AIOpsPilot 시작하기

AIOpsPilot 은 자율 클라우드 운영 제어 평면입니다. 운영 이벤트 중 **반복 가능한 다수**를
규칙 · 정책 · 타입 있는 액션으로 결정론적으로 해소하고, 결정론 게이트를 통과한 **애매한
소수**만 LLM 추론으로 넘깁니다. 모든 자율 액션은 리스크 분류를 거치며, 안전 임계값을
넘는 것은 반드시 HIL(human-in-the-loop) 승인 대기로 넘어갑니다.

레퍼런스 구현 대상은 **Azure** 입니다. 다른 CSP 를 추가할 수 있도록 클라우드 중립 시맨틱
을 유지하지만, 지금 시점에 비-Azure 어댑터는 없습니다.

## 세 도메인, 하나의 제어 평면

AIOpsPilot 은 초기 세 버티컬을 하나의 이벤트 기반 코어에서 다룹니다:

- **Change Safety** — 규칙 카탈로그 기반 정책 게이트, remediation PR, shadow → enforce
  롤아웃.
- **Resilience** — 스케줄된 회복력 훈련, DB DR 훈련, blast-radius 제한 카오스 실험.
- **Cost Governance** — 비용 이상 탐지, 라이트사이징 PR, 리소스 그룹별 예산 가드레일.

각 도메인은 고유한 규칙과 액션을 로드하지만 동일한 제어 루프, 관측성, 감사 로그, 리스크
게이트를 공유합니다.

## 여기서 "자율"이란?

AIOpsPilot 은 운영자를 LLM 으로 대체하는 것이 아닙니다. 모든 이벤트를 세 티어로 분류하고
적절히 라우팅합니다:

- **T0 (결정론, 목표 ~70–80% 커버리지)** — policy-as-code 결정. 모델 호출 없음, 애매함
  없음.
- **T1 (경량, ~15–20%)** — 감사 로그 이력 위의 패턴 매칭 · 임베딩 유사도 · 소형 모델
  분류기. 저렴하고 빠르며 감사 가능.
- **T2 (심층 추론, ~5–10%)** — mixed-model 교차 검증 · 결정론 verifier · grounding
  검사를 거친 frontier 모델. LLM 은 **제안**하고, 실행 자격은 verifier 가 부여합니다.
  모델 자체가 아닙니다.

trust-router 는 이벤트를 결정할 수 있는 가장 낮은 티어를 고릅니다. risk-gate 는 결과
액션이 자동 실행되는지 승인 대기로 넘어가는지를 판단합니다.

## AIOpsPilot 이 적합한 경우

**모두 참** 일 때 잘 맞습니다:

- 운영자가 반복적으로 승인 · 롤백하는 클라우드 설정 이벤트(드리프트, 비용 회귀, 정책
  위반)에 실제 시간을 쓰고 있다.
- 인프라가 IaC 와 policy-as-code 로 표현되어 있다(또는 그 방향으로 가고 있다).
- 자율성 이득을 재기 위한 **기준선(baseline)** 이 있거나 만들 수 있다. AIOpsPilot 은
  측정된 짝 없이 배수를 주장하지 않습니다.
- 컴플라이언스가 저위험 변경의 자동 실행을 허용한다 — 단, 모든 액션에 stop-condition,
  롤백 경로, blast-radius 제한, 감사 로그가 있어야 합니다.

## 아직 적합하지 않은 경우

- IaC 도 policy-as-code 도 없는 환경 — 결정론 티어가 실행할 대상이 없습니다.
- 일회성, 비반복 인시던트. AIOpsPilot 의 이득은 반복 가능한 다수를 자동화하는 데 있고,
  나머지 신규 소수는 인간이 계속 루프 안에 남습니다.
- Azure 이외의 CSP. 추상화는 중립적으로 설계되어 있지만, Azure 어댑터만 제공됩니다.

## 다음 단계

- **개념(Concepts)** — [결정론 우선](../concepts/deterministic-first/),
  [리스크 티어](../concepts/risk-tiers/),
  [Shadow, then enforce](../concepts/shadow-then-enforce/) — 어떤 도입에서든
  깨지지 않아야 할 불변식을 이해합니다.
- **가이드(Guides)** — 일상 운영자 흐름의 태스크 가이드:
  [변경 승인](../guides/approve-change/),
  [감사 로그 읽기](../guides/read-audit-log/),
  [규칙 override](../guides/override-a-rule/).
- **레퍼런스(Reference)** — 단계별 산출물, KPI, 규칙 카탈로그 스키마, 배포 토폴로지가
  담긴 엔지니어링 [로드맵](../reference/roadmap/).
