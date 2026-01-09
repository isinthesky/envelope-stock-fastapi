---
name: stock-ohlcv-cache
description: OHLCV 캐시 통계 조회, 워밍업, 정리 작업을 수행합니다. 일봉 캐시, cache, warmup, 데이터 관리 관련 작업에 사용하세요.
allowed-tools: Bash, Read, Glob, Grep
---

# OHLCV Cache Management Skill

OHLCV 일봉 캐시 데이터를 관리합니다.

## API 엔드포인트

### 통계 조회
```bash
curl http://localhost:8000/api/v1/ohlcv/statistics
```

### 건강 상태 확인
```bash
curl "http://localhost:8000/api/v1/ohlcv/health?freshness_days=7"
```

### 데이터 신선도 요약
```bash
curl http://localhost:8000/api/v1/ohlcv/freshness
```

### 종목 워밍업
```bash
# 특정 종목들 워밍업
curl -X POST http://localhost:8000/api/v1/ohlcv/warmup \
  -H "Content-Type: application/json" \
  -d '{"symbols": ["005930", "000660"], "days": 240}'

# 유니버스 전체 워밍업
curl -X POST "http://localhost:8000/api/v1/ohlcv/warmup/universe?days=240"

# 오래된 데이터만 증분 업데이트
curl -X POST "http://localhost:8000/api/v1/ohlcv/warmup/stale?freshness_days=3"
```

### API 호출 예상치
```bash
curl -X POST http://localhost:8000/api/v1/ohlcv/warmup/estimate \
  -H "Content-Type: application/json" \
  -d '{"symbols": ["005930", "000660", "035420"], "days": 240}'
```

### 오래된 데이터 정리
```bash
# Dry Run (삭제 안함, 예상 결과만)
curl -X POST "http://localhost:8000/api/v1/ohlcv/cleanup?dry_run=true"

# 실제 삭제
curl -X POST "http://localhost:8000/api/v1/ohlcv/cleanup?dry_run=false"

# 커스텀 보존 정책
curl -X POST "http://localhost:8000/api/v1/ohlcv/cleanup?dry_run=false" \
  -H "Content-Type: application/json" \
  -d '{"retention_days": 180, "cleanup_batch_size": 500}'
```

### 종목별 조회
```bash
# 결측 구간 조회
curl "http://localhost:8000/api/v1/ohlcv/005930/gaps?days=240"

# 캐시 통계
curl "http://localhost:8000/api/v1/ohlcv/005930/stats"

# 무결성 검증
curl "http://localhost:8000/api/v1/ohlcv/005930/validate"
```

## 스케줄러 작업

| 작업 | 시간 | 설명 |
|------|------|------|
| cleanup | 02:00 | 365일 이전 데이터 삭제 |
| update | 16:30 (평일) | 장 마감 후 증분 업데이트 |

## 권장 사용 패턴

### 1. 전략 실행 전 워밍업
```bash
# 유니버스 종목 사전 캐싱
curl -X POST "http://localhost:8000/api/v1/ohlcv/warmup/universe?days=240&concurrency=3"
```

### 2. 주간 점검
```bash
# 건강 상태 확인
curl http://localhost:8000/api/v1/ohlcv/health

# 오래된 데이터 갱신
curl -X POST "http://localhost:8000/api/v1/ohlcv/warmup/stale"
```

### 3. 월간 정리
```bash
# 정리 예상 확인
curl -X POST "http://localhost:8000/api/v1/ohlcv/cleanup?dry_run=true"

# 실제 정리 수행
curl -X POST "http://localhost:8000/api/v1/ohlcv/cleanup?dry_run=false"
```

## 응답 예시

### 통계 응답
```json
{
  "success": true,
  "data": {
    "total_symbols": 150,
    "total_candles": 36000,
    "oldest_data_date": "2024-01-01T00:00:00",
    "newest_data_date": "2026-01-09T00:00:00",
    "cache_size_mb": 3.43,
    "intervals": ["1d"]
  }
}
```

### 건강 상태 응답
```json
{
  "success": true,
  "data": {
    "is_healthy": false,
    "stale_count": 5,
    "stale_symbols": ["005930", "000660"],
    "recommendations": ["5개 종목의 데이터가 7일 이상 오래되었습니다."]
  }
}
```
