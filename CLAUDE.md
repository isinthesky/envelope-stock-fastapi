# CLAUDE.md - 프로젝트 가이드

> KIS Trading API Service: 한국투자증권 Open API 기반 자동매매/분석 FastAPI 서버

## ✅ 프로젝트 역할
- FastAPI 기반 REST/WS 서버 + 전략 실행/백테스트 엔진 제공
- 헥사고날 아키텍처(Interface → Domain → Adapters) 유지
- 애플리케이션 초기화/정리는 `src/main.py` lifespan에서 관리

---

## 📁 루트 구조
```
envelope-stock-fastapi/
├── src/                  # 애플리케이션 코드
├── templates/            # Jinja2 대시보드 템플릿
├── docs/                 # 문서
├── examples/             # 예제 스크립트
├── scripts/              # 유틸/실험 스크립트
├── tests/                # pytest 테스트
├── alembic/              # DB 마이그레이션
├── reports/              # 전략/백테스트 리포트 출력
├── docker-compose.yml    # 로컬 인프라
├── Dockerfile            # 컨테이너 빌드
├── pyproject.toml        # 패키지/툴 설정
└── .env.example          # 환경 변수 템플릿
```

---

## 🧠 실행 흐름 요약
`src/main.py`의 lifespan에서 아래 작업을 수행합니다.
- DB 연결 확인 및 상태 로그 출력
- Redis 연결 확인
- `auto_reauth` 활성화 시 KIS 토큰 발급 + 갱신 태스크 시작
- 레거시 전략 엔진 시작 (`strategy.engine`)
- 골든크로스 전략 스케줄러 시작 (`strategy.scheduler`)
- Telegram 알림 스케줄러 시작 (`strategy.notification_scheduler`)
- 종료 시 위 작업과 외부 클라이언트 정리

---

## 🧭 레이어 규칙
```
Interface → Domain → Adapters
         ↘ Common/Settings
```
- Interface는 HTTP/WS 진입점만 담당합니다.
- Domain은 비즈니스 규칙과 트랜잭션 경계를 관리합니다.
- Adapters는 외부 연동(DB/Redis/KIS/Telegram/WS)을 담당합니다.
- Common/Settings는 모든 레이어에서 공통으로 사용합니다.

---

## 🔗 세부 가이드
- `src/CLAUDE.md`
- `src/application/CLAUDE.md`
- `src/application/domain/CLAUDE.md`
- `src/application/common/CLAUDE.md`
- `src/application/interface/CLAUDE.md`
- `src/adapters/CLAUDE.md`
- `src/settings/CLAUDE.md`
