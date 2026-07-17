---
title: RCA 증거 수집 Runbook
description: 근본 원인 가설을 수락하기 전에 범위와 citation이 있는 evidence set을 구성하는 템플릿입니다.
translation_of: rca-evidence-collection.md
translation_source_sha: 954471759bb3bbc2c0c104e999b773e5c42b85ce
translation_revised: 2026-07-17
---

# RCA 증거 수집 Runbook

RCA hypothesis를 수락하거나 게시하기 전에 이 템플릿을 사용합니다.

## 절차

1. Incident ID, target resource, time range, evidence budget을 고정합니다.
2. Correlated event, deployment change, metric, log, trace, rule, approved knowledge reference를 수집합니다.
3. Source identity, timestamp, freshness, access scope를 검증합니다.
4. Cause를 정렬하기 전에 chronology를 만듭니다.
5. 모든 hypothesis claim이 supplied evidence set을 인용하도록 요구합니다.
6. Alternative, ambiguity, confidence, abstention reason을 기록합니다.

## 중지 조건

Evidence가 scope를 벗어나거나 citation을 검증할 수 없거나 timestamp가 일치하지 않거나
provider response에 검증되지 않은 data가 포함될 수 있으면 중지합니다. Ungrounded result를
사람 검토로 라우팅합니다.

## 증거

Secret 또는 raw restricted payload 대신 opaque reference와 hash를 저장합니다.
