---
title: 포스트모템 Workflow Runbook
description: 해결된 incident를 검토하고 evidence-backed follow-up을 제출하는 템플릿입니다.
translation_of: postmortem-workflow.md
translation_source_sha: de8151d2f14509405713ea1c4f5b74e22641a409
translation_revised: 2026-07-17
---

# 포스트모템 Workflow Runbook

Service recovery를 검증한 뒤 incident를 종료하기 전에 이 템플릿을 사용합니다.

## 절차

1. Incident 및 append-only audit record에서 draft를 생성합니다.
2. Impact, chronology, RCA citation, action, approval, rollback, recovery를 검증합니다.
3. Root cause, contributing factor, detection 또는 response gap을 구분합니다.
4. Machine record를 편집하지 않고 잘 작동한 점과 실패한 점을 기록합니다.
5. Owner와 measurable evidence가 있는 corrective 및 preventive action을 지정합니다.
6. 재사용 가능한 rule, runbook, knowledge candidate를 일반 review로 제출합니다.
7. 승인된 postmortem을 연결하고 incident를 종료합니다.

## 중지 조건

Impact, recovery, unresolved risk, owner, required follow-up이 없으면 종료하지 않습니다.
Unsupported cause는 hypothesis로 유지합니다.
