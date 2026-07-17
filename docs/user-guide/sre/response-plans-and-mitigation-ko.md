---
title: 대응 계획과 완화
description: FDAI가 action pipeline을 우회하지 않고 incident response plan을 작성, 사전 테스트, 승인, 라우팅하는 방법입니다.
translation_of: response-plans-and-mitigation.md
translation_source_sha: fdead9be999339ca139b5fb28539ac56967ab765
translation_revised: 2026-07-17
---

# 대응 계획과 완화

인시던트 대응 계획(Incident Response Plan, IRP)은 특정 alert class에 대한 사전 작성된
gated response입니다. Trigger, ordered response step, activation requirement, approver role,
notification channel을 선언합니다. Plan은 mitigation을 제안하고 라우팅할 수 있지만 직접
실행하지 않습니다.

## 작성 게이트

모든 plan은 draft로 시작합니다. Activation은 필요한 runbook, rollback reference, owner,
channel, approval role이 있는지 확인합니다. Readiness를 통과하지 못한 plan은 inactive
상태로 남습니다.

Pretest는 유사한 resolved incident에 대해 plan을 평가합니다. Report는 plan이 대응할 수
있는 과거 case와 필수 evidence 또는 step이 누락된 지점을 보여 줍니다. Pretest 성공은
검토 증거이며 자동 activation이 아닙니다.

## Alert 대응 흐름

1. Alert가 시간 제한이 있는 investigation을 시작합니다.
2. Investigation이 finding과 prioritized recommendation을 반환합니다.
3. Coordinator가 grounded actionable recommendation 중 우선순위가 가장 높은 항목을 선택합니다.
4. Mitigation proposal을 설정된 approval gate로 보냅니다.
5. 승인된 proposal이 typed trust 및 risk pipeline에 다시 들어갑니다.
6. Teams 또는 Slack이 governed outcome을 받습니다.

기본 approval gate는 deny합니다. Approval binding이 없거나 고장 나면 action이 발생하지
않습니다.

## 완화는 실행이 아님

Response step은 `ActionType`을 지정하며 executor를 호출하지 않습니다. 일반 pipeline이
precondition, stop condition, blast radius, rollback, mode, lock, identity, policy를 계속
검증합니다. Reject와 timeout은 감사되는 no-op으로 종료됩니다.

## 실패 동작

- Actionable finding이 없으면 proposal을 만들지 않습니다.
- Investigation timeout 또는 exception은 action 없이 audit-shaped result를 남깁니다.
- Approval reject 또는 timeout은 no-op입니다.
- Routing failure는 out-of-band API call로 전환되지 않습니다.
- Partial execution은 runbook에 선언된 failure 및 compensation branch를 따릅니다.

## 다음 단계

| 학습 대상 | 문서 |
|-----------|------|
| 증거를 수집하는 방법 | [분류와 조사](triage-and-investigation-ko.md) |
| 승인 경로를 선택하는 방법 | [온콜과 에스컬레이션](on-call-and-escalation-ko.md) |
| Typed action이 안전을 유지하는 방법 | [온톨로지 기반 자동화](../concepts/ontology-driven-automation-ko.md) |
| 운영자 절차 | [SRE runbook](../../runbooks/README-ko.md) |
