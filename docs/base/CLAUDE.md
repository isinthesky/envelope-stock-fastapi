# CLAUDE.md - docs/base 문서 레이어 가이드

> 이 폴더는 **프로젝트의 “규칙/설계/서비스 가이드”의 단일 소스(SSoT)** 입니다. 코드 변경 시, 해당 변경이 설계/규칙/운영 방식에 영향을 주면 여기 문서도 함께 갱신합니다.

## 이 레이어의 역할
- **아키텍처/레이어 규칙**을 명문화하고, 코드가 그 규칙을 따르도록 가드
- 신규 개발자가 “어디에 무엇을 넣어야 하는지”를 빠르게 파악하도록 안내
- 문서 간 중복을 줄이고, 변경 시 갱신 포인트를 명확히 유지

## 포함 문서(현재 프로젝트 기준)
- **`ARCHITECTURE.md`**
  - 레이어(Ports & Adapters) 구조, 의존성 방향, 트랜잭션/세션/캐시 경계
  - `src/main.py`의 라이프사이클에서 수행되는 백그라운드 작업의 위치/역할
- **`SERVICE.md`**
  - 서비스/유즈케이스 구현 가이드(예: Domain Service에서 정책 결정, Adapter에서 I/O)
  - Repository/Client 조합 방식, 예외 변환, 응답/DTO 계약
- **`convention.md`**
  - 모듈/파일 네이밍, 경로 규칙(특히 KIS REST path ↔ adapter 파일명 매핑)
  - 코드 스타일/테스트 규칙(Black/isort/mypy/pytest)

## 문서 작성/갱신 규칙
- **문서의 “사실”은 코드가 기준**: 폴더/클래스/함수명은 실제 경로와 일치해야 함
- **레이어 경계는 명확히**: `interface/domain/adapters/settings/common`의 책임/금지사항을 분리해서 서술
- **중복 최소화**
  - 상세 내용은 해당 폴더의 `CLAUDE.md`로 내려보내고, 여기서는 링크/요약 중심
- **변경 시 함께 갱신해야 하는 경우**
  - 라우터 prefix/경로, background scheduler 추가/삭제, 설정 키 추가/삭제, DB 스키마/Repository 추가 등

## 빠른 네비게이션
- 프로젝트 개요: `/<repo>/CLAUDE.md`
- 소스 엔트리포인트/라우터: `src/CLAUDE.md`
- 레이어별 상세: `src/**/CLAUDE.md`

