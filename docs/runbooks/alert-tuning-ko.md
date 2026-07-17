---
title: Alert Tuning Runbook
description: 측정된 rule 및 routing change로 alert noise와 missed detection을 줄이는 템플릿입니다.
translation_of: alert-tuning.md
translation_source_sha: 2ff9955dc262a97dc4e040d6535655efe3661e35
translation_revised: 2026-07-17
---

# Alert Tuning Runbook

False positive, false negative, duplicate incident, stale routing이 회귀할 때 이 템플릿을 사용합니다.

## 절차

1. Labeled scenario set과 현재 detector, correlation, routing version을 고정합니다.
2. Fire rate, precision, recall, duplicate ratio, cold-start abstention, delivery outcome을 측정합니다.
3. Defect가 baseline, threshold, seasonality, debounce, correlation, channel routing 중 어디에 속하는지 식별합니다.
4. Configuration axis 하나를 변경하고 동일한 scenario를 shadow에서 다시 실행합니다.
5. 정책 위반 escape와 guard-metric regression이 없는지 확인합니다.
6. 변경을 독립적으로 review 및 promote하고 이전 version rollback을 유지합니다.

## 중지 조건

Volume을 줄이기 위해서만 alert를 억제하지 않습니다. Label이 부족하거나 treatment set이
baseline과 다르거나 missed incident가 증가하면 중지합니다.
