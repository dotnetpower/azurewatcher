---
title: SLO Burn 대응 Runbook
description: Error-budget burn finding을 검증하고 governed response로 라우팅하는 템플릿입니다.
translation_of: slo-burn-response.md
translation_source_sha: 51104b8ee4ff38fd9de3b65eb5892243dbd4722b
translation_revised: 2026-07-17
---

# SLO Burn 대응 Runbook

Workload SLO가 `slo.error_budget_burn`을 생성할 때 이 템플릿을 사용합니다.

## 절차

1. SLO definition, metric source, freshness, evaluated window를 검증합니다.
2. Short 및 long window threshold와 remaining error budget을 확인합니다.
3. Burn을 deployment, maintenance, capacity, open incident와 연계합니다.
4. Incident를 생성하거나 갱신하고 measured impact로 severity를 지정합니다.
5. Bounded investigation과 proposed mitigation의 what-if를 실행합니다.
6. Typed proposal을 risk 및 approval policy로 라우팅합니다.

## 중지 조건

Sample이 오래됐거나 SLI scope가 잘못됐거나 missing data를 0으로 취급했거나 rollback 및
impact bound가 없으면 중지합니다.

## 증거

SLO version, window value, source timestamp, incident ID, proposal ID, verdict,
terminal outcome을 기록합니다.
