---
title: 인시던트 완화와 Rollback Runbook
description: Governed mitigation을 적용하고 rollback 또는 recovery를 검증하는 템플릿입니다.
translation_of: incident-mitigation-and-rollback.md
translation_source_sha: c03dbb3e14f8517be6ef50b320a2070e4ce3c3c0
translation_revised: 2026-07-17
---

# 인시던트 완화와 Rollback Runbook

Investigation이 grounded mitigation proposal을 생성한 뒤 이 템플릿을 사용합니다.

## 절차

1. Incident, proposal, `ActionType`, mode, scope, owner, approver를 확인합니다.
2. Policy, what-if, dependency, lock, blast-radius 검사를 실행합니다.
3. Stop condition, rollback contract, recovery verification을 확인합니다.
4. 필요한 verdict와 distinct approval을 받습니다.
5. Authorized executor와 delivery path로만 실행합니다.
6. Effect를 검증하고 선언된 condition이 발생하면 중지하거나 rollback합니다.
7. Terminal state, remaining impact, incident transition을 기록합니다.

## 중지 조건

Stale evidence, lock failure, scope expansion, policy denial, missing audit writer,
unavailable rollback, unexpected dependency impact가 있으면 중지합니다.

## 증거

Dry-run output, verdict, approval, executor, delivery reference, health check,
rollback reference, final incident state를 기록합니다.
