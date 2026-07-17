---
title: Chaos Game Day Runbook
description: 범위가 제한된 chaos experiment를 계획, 승인, 실행, 복구하는 템플릿입니다.
translation_of: chaos-game-day.md
translation_source_sha: 4c9021d68187fa735ea0d80764e6ae59144141b1
translation_revised: 2026-07-17
---

# Chaos Game Day Runbook

승인된 exercise window 안에서 승격된 scenario를 실행할 때 이 템플릿을 사용합니다.

## 절차

1. Scenario version, hypothesis, owner, approver, target allowlist, exercise window를 확인합니다.
2. Shadow evidence, preflight, steady state, stop condition, rollback을 검증합니다.
3. Target set을 고정하고 필요한 lock을 획득합니다.
4. Probe를 계속 평가하며 approved provider를 통해 주입합니다.
5. Scope expansion, protected dependency degradation, stale probe, duration limit에서 abort합니다.
6. Rollback하고 recovery를 검증하며 temporary resource를 제거하고 audit record를 봉인합니다.

## 증거

Scenario 및 catalog version, target, approval, probe sample, injection time, stop reason,
rollback result, recovery time, unexpected impact를 기록합니다.
