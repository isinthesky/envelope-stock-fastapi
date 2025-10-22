# 백테스팅 예제

이 디렉토리에는 백테스팅 시스템의 사용 예제가 포함되어 있습니다.

## 예제 목록

### 1. simple_backtest.py
단일 종목(삼성전자)에 대한 간단한 백테스팅 예제

**실행 방법:**
```bash
python examples/backtest/simple_backtest.py
```

**주요 기능:**
- 볼린저 밴드 + 엔벨로프 전략 적용
- 손절/익절 설정
- 상세한 결과 출력
- 거래 내역 확인

### 2. multi_symbol_backtest.py
여러 종목에 대한 백테스팅 및 성과 비교 예제

**실행 방법:**
```bash
python examples/backtest/multi_symbol_backtest.py
```

**주요 기능:**
- 다중 종목 동시 백테스팅
- 종목별 성과 비교
- 최고/최저 성과 종목 선정
- 통계 요약

## 사전 준비

### 1. 환경 변수 설정
`.env` 파일에 KIS API 키 설정:
```
KIS_APP_KEY=your_app_key
KIS_APP_SECRET=your_app_secret
KIS_BASE_URL=https://openapi.koreainvestment.com:9443
```

### 2. 의존성 설치
```bash
pip install -r requirements.txt
```

### 3. Redis 실행
```bash
docker run -d -p 6379:6379 redis
```

## 전략 파라미터 조정

백테스팅 성과를 개선하기 위해 다음 파라미터를 조정할 수 있습니다:

### 볼린저 밴드
```python
BollingerBandConfig(
    period=20,          # 이동평균 기간 (10, 20, 30 등)
    std_multiplier=2.0  # 표준편차 배수 (1.5, 2.0, 2.5 등)
)
```

### 엔벨로프
```python
EnvelopeConfig(
    period=20,        # 이동평균 기간
    percentage=2.0    # 채널 폭 비율 (1%, 2%, 3% 등)
)
```

### 리스크 관리
```python
RiskManagementConfig(
    use_stop_loss=True,
    stop_loss_ratio=-0.03,     # -3% 손절
    use_take_profit=True,
    take_profit_ratio=0.05,    # +5% 익절
    use_trailing_stop=False,
    trailing_stop_ratio=0.02,  # 2% Trailing Stop
)
```

## 결과 해석

### 수익 지표
- **총 수익률**: 전체 기간 동안의 누적 수익률
- **연환산 수익률**: 1년 단위로 환산한 평균 수익률
- **CAGR**: 복리 연평균 성장률

### 리스크 지표
- **MDD**: 최대 낙폭 (고점 대비 최대 하락률)
- **변동성**: 수익률의 표준편차 (연환산)
- **Sharpe Ratio**: 위험 대비 수익률 (2.0 이상 우수)
- **Sortino Ratio**: 하방 위험만 고려한 수익률
- **Calmar Ratio**: 수익률 / MDD (2.0 이상 우수)

### 거래 통계
- **승률**: 이익 거래 비율
- **Profit Factor**: 총 이익 / 총 손실 (2.0 이상 우수)
- **평균 보유 기간**: 포지션 평균 보유 일수

## 성과 등급

백테스팅 결과는 다음과 같이 등급이 부여됩니다:

| 등급 | 점수 | 기준 |
|------|------|------|
| A+ | 90+ | 매우 우수 |
| A | 80-89 | 우수 |
| B+ | 70-79 | 양호 |
| B | 60-69 | 보통 |
| C+ | 50-59 | 개선 필요 |
| C | 40-49 | 부족 |
| D | 0-39 | 매우 부족 |

## 주의사항

### 1. 과최적화 (Overfitting) 방지
- 너무 많은 파라미터 조정은 과거 데이터에만 최적화될 위험
- Out-of-sample 테스트 권장

### 2. 거래 비용 고려
- 수수료, 세금, 슬리피지가 수익률에 큰 영향
- 실제 거래 환경을 정확히 반영

### 3. 데이터 품질
- 결측치, 이상치가 결과를 왜곡할 수 있음
- 데이터 검증 필수

## 추가 리소스

- [백테스팅 시스템 문서](../../docs/backtesting/README.md)
- [성과 지표 가이드](../../docs/backtesting/PERFORMANCE_METRICS.md)
- [데이터 검증 가이드](../../docs/backtesting/DATA_VALIDATION.md)
