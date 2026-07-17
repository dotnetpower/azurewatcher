---
title: 인시던트 관리
description: FDAI가 first-class incident를 생성하고 소유자를 지정하며 전환, 측정, 종료하는 방법입니다.
translation_of: incident-management.md
translation_source_sha: 0bf98a1c61aca87b583497a868b21f5abd63f889
translation_revised: 2026-07-17
---

# 인시던트 관리

인시던트는 연계된 신호, 소유권, 조사, 대응, 복구, 포스트모템 증거를 연결하는 지속적인
운영 레코드입니다. FDAI는 인시던트를 알림에 붙는 label이 아니라 명시적인 lifecycle로
관리합니다.

## 인시던트 라이프사이클

```text
open -> triaging -> mitigated -> resolved -> closed
```

State machine이 전환을 검증하고 idempotent하게 기록합니다. 오래된 expected state는 더
새로운 운영자 또는 자동화 결정을 덮어쓰지 않고 conflict를 발생시킵니다.

| 상태 | 운영 의미 |
|------|-----------|
| `open` | 연계된 증거가 incident record를 생성함 |
| `triaging` | 소유권 지정과 증거 수집이 진행 중임 |
| `mitigated` | 즉각적인 영향은 억제됐지만 복구는 완료되지 않음 |
| `resolved` | 서비스 복구가 검증됨 |
| `closed` | 후속 조치와 필수 사후 작업이 완료됨 |

## 레코드에 포함되는 내용

Incident는 안정적인 ID, correlation key, severity, status, source, owner, timestamp,
member reference, mitigation summary, postmortem reference를 저장합니다. Audit entry는
open, membership change, assignment, transition을 보존합니다.

Ownership, impact, recovery evidence가 없으면 unavailable로 표시합니다. Console은 display
text에서 해당 값을 추론하지 않습니다.

## 안전한 생성과 할당

수동 생성에는 contributor 수준 운영자와 제안된 severity 및 correlation key 확인이
필요합니다. 자동 상관관계는 안정적인 incident anchor를 도출하므로 반복 delivery가 같은
incident를 생성하거나 갱신합니다.

Assignment change는 감사되며 notification delivery는 durable합니다. 알림 실패는 lifecycle
record를 rollback하지 않고, retry claim은 중복 전달이 중복 state transition이 되는 것을
방지합니다.

## 분류, 완화, 해결

1. Membership, scope, severity, 현재 owner를 확인합니다.
2. `triaging`으로 이동하고 범위가 제한된 조사를 시작합니다.
3. Mitigation proposal을 typed pipeline과 필요한 approval로 보냅니다.
4. 영향 억제 증거가 있을 때만 `mitigated`로 표시합니다.
5. 서비스 복구를 검증한 뒤에만 `resolved`로 표시합니다.
6. 필수 follow-up, postmortem, ownership action을 기록한 뒤 종료합니다.

## SLA와 storm 처리

Severity별 acknowledge 및 resolution target을 transition stream에서 평가할 수 있습니다.
Event storm은 deterministic incident ID, deduplication, 명시적 remediation step으로 제한되며
무제한 병렬 변경을 만들지 않습니다.

## 다음 단계

| 학습 대상 | 문서 |
|-----------|------|
| 증거를 수집하는 방법 | [분류와 조사](triage-and-investigation-ko.md) |
| 원인을 표현하는 방법 | [근본 원인 분석](root-cause-analysis-ko.md) |
| 완화를 governed 상태로 유지하는 방법 | [대응 계획과 완화](response-plans-and-mitigation-ko.md) |
| 최종 레코드를 검토하는 방법 | [포스트모템과 학습](postmortems-and-learning-ko.md) |
