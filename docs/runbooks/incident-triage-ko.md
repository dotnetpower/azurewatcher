---
title: 인시던트 분류 Runbook
description: Incident scope, severity, ownership, investigation readiness를 확인하는 customer-neutral 템플릿입니다.
translation_of: incident-triage.md
translation_source_sha: eed44ee12c1f7db5435f2cbd6f4f6dd236ba5f07
translation_revised: 2026-07-17
---

# 인시던트 분류 Runbook

Incident가 생성되거나 severity 또는 scope가 크게 변경될 때 이 템플릿을 사용합니다.

## 전제 조건

- Incident ID, correlation key, current state, member count를 확인합니다.
- Telemetry와 inventory freshness를 확인하고 unavailable source를 명시합니다.
- Accountable owner를 지정하고 사용된 on-call schedule을 검증합니다.

## 절차

1. Affected resource를 검증하고 감사되는 correction으로만 unrelated member를 제거합니다.
2. 측정된 user impact, SLO burn, bounded scope를 기준으로 severity를 설정합니다.
3. Expected current state와 함께 incident를 `triaging`으로 이동합니다.
4. 시간과 resource 범위가 제한된 investigation을 시작합니다.
5. Evidence link, unknown, next decision deadline을 기록합니다.
6. 선택된 responder에게 알리고 durable delivery status를 확인합니다.

## 중지 조건

Identity, ownership, scope, evidence freshness를 확정할 수 없으면 중지하고 에스컬레이션합니다.
데이터가 없다는 이유로 severity를 낮추지 않습니다.

## 증거

Transition audit ID, owner, severity basis, member reference, investigation ID,
notification result, next review time을 기록합니다.
