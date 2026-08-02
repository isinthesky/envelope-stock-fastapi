# -*- coding: utf-8 -*-
"""Paper Trade (P6) — 무비용 실시간 추적 브리지.

백테스트 통과 config를 실주문 대신 기록 전용으로 운영하기 위한 도메인.
- ledger: 순수 회계(포지션/거래/요약)
- reconcile: paper 성과 vs 백테스트 OOS 괴리 판정(소액 실전 go/no-go 근거)
- bridge: 라이브 dry-run 시그널(StrategySignalDTO) → PaperEvent 변환
"""
