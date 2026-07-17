---
title: 온콜과 에스컬레이션
description: FDAI가 accountable responder를 선택하고 pending decision을 에스컬레이션하며 paging integration이 없을 때 fail closed하는 방법입니다.
translation_of: on-call-and-escalation.md
translation_source_sha: a4b85ffdb35e0cf2574f0626340b7eaa246032b2
translation_revised: 2026-07-17
---

# 온콜과 에스컬레이션

온콜 라우팅은 notification channel에 실행 권한을 주지 않으면서 인시던트를 책임 있는
사람과 연결합니다. FDAI는 현재 responder를 확인하고 설정된 escalation ladder를 적용하며,
모든 timeout, reroute, approval, no-op을 기록합니다.

> Upstream on-call schedule seam과 fail-safe resolver는 구현되어 있습니다. PagerDuty 또는
> Opsgenie adapter와 channel별 DM targeting은 배포 또는 fork binding으로 남아 있습니다.
> Status-page broadcast는 Deferred입니다.

## 대응자 확인

Resolver는 시간 범위가 있는 schedule을 읽고 현재 shift의 principal을 반환합니다.
Schedule이 없거나 오래됐거나 unavailable이면 FDAI는 설정된 fail-safe route를 사용하고
degraded routing을 기록합니다. Identity를 추측하지 않습니다.

Approval과 execution은 서로 다른 principal로 유지됩니다. On-call responder는 RBAC와 policy
범위에서만 검토 또는 승인할 수 있으며, shift 중이라는 이유로 executor credential을 받지
않습니다.

## 에스컬레이션 단계

Escalation ladder는 level, wait period, channel, role, stop condition을 정의합니다. Pending
decision은 scope와 severity에 따라 primary on-call에서 secondary, incident commander,
owner로 이동할 수 있습니다.

느린 supervisory loop는 기저 risk verdict를 변경하지 않습니다. 책임 있는 approver를 찾거나
request를 expire할 수 있지만, `deny`를 `auto`로 바꾸거나 사람 대신 승인할 수 없습니다.

## 운영자 확인 사항

1. Schedule freshness, timezone, handoff boundary를 확인합니다.
2. Incident scope와 severity가 예상 ladder를 선택하는지 확인합니다.
3. 필요한 경우 approver가 executor 및 requester와 다른지 검증합니다.
4. Notification delivery와 durable retry state를 확인합니다.
5. Expiration을 감사되는 no-op으로 처리합니다.

## 커뮤니케이션

Operational alert, approval request, incident lifecycle notice는 서로 다른 message class와
RBAC floor를 사용합니다. Channel은 incident ID, scope, severity, evidence link, requested
decision, expiry처럼 행동에 필요한 최소 context만 받습니다. Secret과 raw customer data는
message에 포함하지 않습니다.

## 다음 단계

| 학습 대상 | 문서 |
|-----------|------|
| 승인이 작동하는 방법 | [승인과 채널](../concepts/approvals-and-channels-ko.md) |
| 에스컬레이션 계약 | [에스컬레이션과 Standing Authority](../../roadmap/decisioning/escalation-and-standing-authority-ko.md) |
| 채널 라우팅 | [채널과 알림](../../roadmap/interfaces/channels-and-notifications-ko.md) |
| Incident ownership | [인시던트 관리](incident-management-ko.md) |
