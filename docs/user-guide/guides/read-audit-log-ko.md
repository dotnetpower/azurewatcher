---
title: 감사 로그 읽기(Read the audit log)
description: 모든 자율 결정에 대해 append-only 감사 로그가 기록하는 내용과 증상에서 근본 이벤트까지 역추적하는 방법.
translation_of: read-audit-log.md
translation_source_sha: e37b6870d043d0d63457dd40b9584e28e9bf42ab
translation_revised: 2026-07-13
---

# 감사 로그 읽기(Read the audit log)

감사 로그는 FDAI가 수행한 작업의 유일한 기준 기록입니다. Append-only 방식으로
변경할 수 없으며, 컨트롤 플레인이 내리는 모든 자율 결정을 포함합니다. 거부, 시간 초과,
no-op으로 끝난 결정도 기록합니다. 이 가이드에서는 각 항목의 내용과 증상에서 근본
이벤트까지 역추적하는 방법을 설명합니다.

## 항목이 담는 것

모든 항목은 하나의 결정에 대한 전체 라이프사이클을 기록합니다. 최소:

- **이벤트 ID** - 재처리해도 중복되지 않는 소스 이벤트의 안정적인 식별자. 같은
  이벤트에서 나온 여러 결정은 이 ID를 공유합니다.
- **티어** - T0 / T1 / T2 - 결정이 결정론적으로 돌았는지 추론 티어까지 갔는지
  즉시 알 수 있습니다.
- **규칙, 정책, 모델 참조** - T0/T1은 규칙 ID, T2는 모델 식별자와 인용된
  근거 문서.
- **판정** - AUTO / HIL / DENY와 그것을 만든 분류.
- **판정 증거** - 일치한 리스크 규칙, 카탈로그 버전, feature snapshot, 필요한 정족수,
  자율성을 제한한 `resolved_ceiling` 축.
- **실행 주체** - initiator, judge, approver, executor, auditor를 서로 다른 필드로
  기록합니다.
- **타임스탬프** - RFC 3339, UTC.
- **Shadow vs enforce 모드** - 모든 항목은 그 시점의 기능이 shadow였는지 표시합니다.
  Shadow 항목은 실행되었을 액션을 함께 기록합니다.
- **롤백 참조** - 실행된 액션과 연결된 롤백 계획 또는 복구 증거. No-op, deny, 거부,
  시간 초과, shadow-only 종료 레코드는 복원할 실행 상태가 없습니다. 이는 실행 가능한
  `ActionType`에 필수 `rollback_contract`가 누락된 것과 다릅니다.

## 인시던트 추적

증상(메트릭 급증, 알림, 예상과 다르게 변경된 리소스)에서 시작해 역순으로 추적합니다:

1. 감사 로그에서 리소스를 찾습니다. FDAI 액션은 항상 레코드를 남깁니다. 외부에서
  발생한 변경은 통합된 Activity Log 또는 변경 피드가 관찰하고 정규화한 경우에 나타납니다.
2. 해당 리소스의 최신 관련 항목을 읽습니다. 변경을 만든 이벤트 ID와 결정 체인을
  확인할 수 있습니다.
3. Correlation ID를 사용해 감사, 로그, 메트릭, 트레이스를 연결합니다. 감사 스트림
  안에서는 이벤트 ID로 티어, 리스크, 승인, 실행, 전달, 롤백, 종료 레코드의 순서를
  확인합니다.
4. `resolved_ceiling`과 일치한 리스크 규칙을 확인합니다. 판정 당시 구성을 기준으로 어떤
  입력이 auto, HIL, shadow, deny를 강제했는지 설명합니다.
5. Shadow 항목과 비교합니다. 실행되지 않은 액션도 shadow 모드에서 실행되었을 판정과
  함께 나타나므로 FDAI의 제안과 운영자의 실제 조치를 비교할 수 있습니다.

## 종료 결과 읽기

| 결과 | 변경 실행 여부 | 확인할 내용 |
|------|----------------|-------------|
| `auto` 완료 | 예 | Executor 신원, 전달 참조, stop-condition 상태, 롤백 참조 |
| HIL 승인 후 완료 | 예 | Approval ID, 승인자, 정족수, action hash, executor 및 전달 레코드 |
| 거부 또는 시간 초과 | 아니요 | 사유, TTL, 승인자가 있는 경우 승인자, 최종 no-op |
| `deny` | 아니요 | 일치한 하드 규칙, feature snapshot, 카탈로그 버전 |
| `abstain` 또는 `shadow_only` | 아니요 | 누락된 증거 또는 가장 엄격한 상한, 실행되었을 액션 |
| 롤백 완료 | 실행 후 복원 또는 보상 | 원래 액션, 롤백 실행자, 복구 결과, 남은 영향 |

## Replay와 사후 분석

감사 로그는 **judge-only replay**를 위해 설계되었습니다. 이벤트를 컨트롤 플레인에
replay하면 실제 액션을 다시 실행하지 않고도 다시 계산되는 결정을 볼 수 있습니다.
이 방식으로 지난달 이력과 제안된 규칙 변경의 결과를 비교해 승격 전에 확인할 수 있습니다.

## 감사 로그에 *없는* 것

감사 로그는 결정과 실행 주체 참조를 기록합니다. 시크릿, 토큰, 고객 식별자, 사용자
데이터 페이로드는 절대 기록하지 않습니다. 진단 데이터가 필요하면 관측 스택(로그,
메트릭, 트레이스)이 올바른 위치입니다. 각 감사 항목은 해당 관측 데이터로 연결되는
correlation ID를 담습니다.

예상한 종료 레코드나 correlation 연결이 없다면 감사 완전성 실패로 처리하세요. 오류
레코드가 없다는 이유만으로 성공했다고 판단하지 마세요.

## 다음 단계

| 학습 대상 | 문서 |
|-----------|------|
| 여기서 읽게 될 HIL 항목을 쓰는 운영자 상호작용 | [approve-change-ko.md](approve-change-ko.md) |
| `would-have-been` 결정이 담기는 이유 | [../concepts/shadow-then-enforce-ko.md](../concepts/shadow-then-enforce-ko.md) |
| 부적절한 결과를 계속 기록하는 규칙 좁히기 | [override-a-rule-ko.md](override-a-rule-ko.md) |
| 감사 로그의 스토리지와 보존 설계 | [../../roadmap/rules-and-detection/observability-and-detection-ko.md](../../roadmap/rules-and-detection/observability-and-detection-ko.md) |
