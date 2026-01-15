# -*- coding: utf-8 -*-
"""
Add Stocks to Universe - KOSPI/KOSDAQ 주요 종목 추가

stock_universe 테이블에 KOSPI 200 및 KOSDAQ 150 주요 종목을 추가합니다.
총 200개 이상의 종목으로 매수 전략 스캔 범위를 확장합니다.
"""

import asyncio
from datetime import datetime
from decimal import Decimal

from src.adapters.database.connection import get_db


# 추가할 종목 목록 (KOSPI 200 + KOSDAQ 150 주요 종목)
ADDITIONAL_STOCKS = [
    # ==================== KOSPI 대형주 (시총 상위 50) ====================
    {"symbol": "005930", "name": "삼성전자", "market": "KOSPI", "market_cap": Decimal("400_000_000_000_000")},
    {"symbol": "000660", "name": "SK하이닉스", "market": "KOSPI", "market_cap": Decimal("120_000_000_000_000")},
    {"symbol": "373220", "name": "LG에너지솔루션", "market": "KOSPI", "market_cap": Decimal("85_000_000_000_000")},
    {"symbol": "207940", "name": "삼성바이오로직스", "market": "KOSPI", "market_cap": Decimal("55_000_000_000_000")},
    {"symbol": "005380", "name": "현대차", "market": "KOSPI", "market_cap": Decimal("50_000_000_000_000")},
    {"symbol": "000270", "name": "기아", "market": "KOSPI", "market_cap": Decimal("35_000_000_000_000")},
    {"symbol": "035420", "name": "NAVER", "market": "KOSPI", "market_cap": Decimal("33_000_000_000_000")},
    {"symbol": "035720", "name": "카카오", "market": "KOSPI", "market_cap": Decimal("20_000_000_000_000")},
    {"symbol": "055550", "name": "신한지주", "market": "KOSPI", "market_cap": Decimal("22_000_000_000_000")},
    {"symbol": "105560", "name": "KB금융", "market": "KOSPI", "market_cap": Decimal("25_000_000_000_000")},
    {"symbol": "005490", "name": "POSCO홀딩스", "market": "KOSPI", "market_cap": Decimal("20_000_000_000_000")},
    {"symbol": "003670", "name": "포스코퓨처엠", "market": "KOSPI", "market_cap": Decimal("15_000_000_000_000")},
    {"symbol": "086790", "name": "하나금융지주", "market": "KOSPI", "market_cap": Decimal("14_000_000_000_000")},
    {"symbol": "034020", "name": "두산에너빌리티", "market": "KOSPI", "market_cap": Decimal("13_000_000_000_000")},
    {"symbol": "096770", "name": "SK이노베이션", "market": "KOSPI", "market_cap": Decimal("12_000_000_000_000")},
    {"symbol": "032830", "name": "삼성생명", "market": "KOSPI", "market_cap": Decimal("11_500_000_000_000")},
    {"symbol": "009150", "name": "삼성전기", "market": "KOSPI", "market_cap": Decimal("11_000_000_000_000")},
    {"symbol": "010130", "name": "고려아연", "market": "KOSPI", "market_cap": Decimal("10_500_000_000_000")},
    {"symbol": "028260", "name": "삼성물산", "market": "KOSPI", "market_cap": Decimal("10_000_000_000_000")},
    {"symbol": "018260", "name": "삼성에스디에스", "market": "KOSPI", "market_cap": Decimal("9_500_000_000_000")},
    {"symbol": "003490", "name": "대한항공", "market": "KOSPI", "market_cap": Decimal("9_000_000_000_000")},
    {"symbol": "011200", "name": "HMM", "market": "KOSPI", "market_cap": Decimal("8_500_000_000_000")},
    {"symbol": "010950", "name": "S-Oil", "market": "KOSPI", "market_cap": Decimal("8_000_000_000_000")},
    {"symbol": "000810", "name": "삼성화재", "market": "KOSPI", "market_cap": Decimal("7_500_000_000_000")},
    {"symbol": "015760", "name": "한국전력", "market": "KOSPI", "market_cap": Decimal("7_000_000_000_000")},
    {"symbol": "259960", "name": "크래프톤", "market": "KOSPI", "market_cap": Decimal("15_000_000_000_000")},
    {"symbol": "352820", "name": "하이브", "market": "KOSPI", "market_cap": Decimal("8_000_000_000_000")},
    {"symbol": "036570", "name": "엔씨소프트", "market": "KOSPI", "market_cap": Decimal("7_000_000_000_000")},
    {"symbol": "003550", "name": "LG", "market": "KOSPI", "market_cap": Decimal("13_000_000_000_000")},
    {"symbol": "066570", "name": "LG전자", "market": "KOSPI", "market_cap": Decimal("14_000_000_000_000")},
    {"symbol": "034730", "name": "SK", "market": "KOSPI", "market_cap": Decimal("12_000_000_000_000")},
    {"symbol": "017670", "name": "SK텔레콤", "market": "KOSPI", "market_cap": Decimal("11_000_000_000_000")},
    {"symbol": "024110", "name": "기업은행", "market": "KOSPI", "market_cap": Decimal("8_000_000_000_000")},
    {"symbol": "011170", "name": "롯데케미칼", "market": "KOSPI", "market_cap": Decimal("6_500_000_000_000")},
    {"symbol": "033780", "name": "KT&G", "market": "KOSPI", "market_cap": Decimal("6_000_000_000_000")},
    {"symbol": "030200", "name": "KT", "market": "KOSPI", "market_cap": Decimal("5_500_000_000_000")},
    {"symbol": "032640", "name": "LG유플러스", "market": "KOSPI", "market_cap": Decimal("5_000_000_000_000")},

    # ==================== KOSPI 중형주 (시총 50~100위) ====================
    {"symbol": "051910", "name": "LG화학", "market": "KOSPI", "market_cap": Decimal("25_000_000_000_000")},
    {"symbol": "006400", "name": "삼성SDI", "market": "KOSPI", "market_cap": Decimal("22_000_000_000_000")},
    {"symbol": "012330", "name": "현대모비스", "market": "KOSPI", "market_cap": Decimal("18_000_000_000_000")},
    {"symbol": "000100", "name": "유한양행", "market": "KOSPI", "market_cap": Decimal("5_000_000_000_000")},
    {"symbol": "068270", "name": "셀트리온", "market": "KOSPI", "market_cap": Decimal("18_000_000_000_000")},
    {"symbol": "009540", "name": "HD한국조선해양", "market": "KOSPI", "market_cap": Decimal("7_000_000_000_000")},
    {"symbol": "329180", "name": "HD현대중공업", "market": "KOSPI", "market_cap": Decimal("15_000_000_000_000")},
    {"symbol": "267250", "name": "HD현대", "market": "KOSPI", "market_cap": Decimal("8_000_000_000_000")},
    {"symbol": "042660", "name": "한화오션", "market": "KOSPI", "market_cap": Decimal("9_000_000_000_000")},
    {"symbol": "009830", "name": "한화솔루션", "market": "KOSPI", "market_cap": Decimal("5_000_000_000_000")},
    {"symbol": "012450", "name": "한화에어로스페이스", "market": "KOSPI", "market_cap": Decimal("12_000_000_000_000")},
    {"symbol": "006800", "name": "미래에셋증권", "market": "KOSPI", "market_cap": Decimal("6_000_000_000_000")},
    {"symbol": "138040", "name": "메리츠금융지주", "market": "KOSPI", "market_cap": Decimal("10_000_000_000_000")},
    {"symbol": "316140", "name": "우리금융지주", "market": "KOSPI", "market_cap": Decimal("10_000_000_000_000")},
    {"symbol": "000720", "name": "현대건설", "market": "KOSPI", "market_cap": Decimal("4_000_000_000_000")},
    {"symbol": "047050", "name": "포스코인터내셔널", "market": "KOSPI", "market_cap": Decimal("4_500_000_000_000")},
    {"symbol": "161390", "name": "한국타이어앤테크놀로지", "market": "KOSPI", "market_cap": Decimal("4_500_000_000_000")},
    {"symbol": "004020", "name": "현대제철", "market": "KOSPI", "market_cap": Decimal("4_000_000_000_000")},
    {"symbol": "047810", "name": "한국항공우주", "market": "KOSPI", "market_cap": Decimal("8_000_000_000_000")},
    {"symbol": "036460", "name": "한국가스공사", "market": "KOSPI", "market_cap": Decimal("3_500_000_000_000")},
    {"symbol": "001040", "name": "CJ", "market": "KOSPI", "market_cap": Decimal("4_000_000_000_000")},
    {"symbol": "097950", "name": "CJ제일제당", "market": "KOSPI", "market_cap": Decimal("4_500_000_000_000")},
    {"symbol": "035250", "name": "강원랜드", "market": "KOSPI", "market_cap": Decimal("3_000_000_000_000")},
    {"symbol": "034220", "name": "LG디스플레이", "market": "KOSPI", "market_cap": Decimal("4_000_000_000_000")},
    {"symbol": "090430", "name": "아모레퍼시픽", "market": "KOSPI", "market_cap": Decimal("3_500_000_000_000")},
    {"symbol": "088350", "name": "한화생명", "market": "KOSPI", "market_cap": Decimal("2_500_000_000_000")},
    {"symbol": "078930", "name": "GS", "market": "KOSPI", "market_cap": Decimal("4_000_000_000_000")},
    {"symbol": "006360", "name": "GS건설", "market": "KOSPI", "market_cap": Decimal("2_000_000_000_000")},
    {"symbol": "051900", "name": "LG생활건강", "market": "KOSPI", "market_cap": Decimal("6_500_000_000_000")},
    {"symbol": "271560", "name": "오리온", "market": "KOSPI", "market_cap": Decimal("5_000_000_000_000")},
    {"symbol": "009240", "name": "한샘", "market": "KOSPI", "market_cap": Decimal("1_500_000_000_000")},
    {"symbol": "016360", "name": "삼성증권", "market": "KOSPI", "market_cap": Decimal("3_500_000_000_000")},
    {"symbol": "005940", "name": "NH투자증권", "market": "KOSPI", "market_cap": Decimal("3_000_000_000_000")},
    {"symbol": "003410", "name": "쌍용C&E", "market": "KOSPI", "market_cap": Decimal("2_000_000_000_000")},
    {"symbol": "004990", "name": "롯데지주", "market": "KOSPI", "market_cap": Decimal("3_500_000_000_000")},
    {"symbol": "069960", "name": "현대백화점", "market": "KOSPI", "market_cap": Decimal("2_500_000_000_000")},
    {"symbol": "023530", "name": "롯데쇼핑", "market": "KOSPI", "market_cap": Decimal("2_000_000_000_000")},
    {"symbol": "139480", "name": "이마트", "market": "KOSPI", "market_cap": Decimal("2_500_000_000_000")},
    {"symbol": "326030", "name": "SK바이오팜", "market": "KOSPI", "market_cap": Decimal("7_000_000_000_000")},
    {"symbol": "302440", "name": "SK바이오사이언스", "market": "KOSPI", "market_cap": Decimal("4_000_000_000_000")},

    # ==================== KOSPI 기타 주요 종목 ====================
    {"symbol": "010140", "name": "삼성중공업", "market": "KOSPI", "market_cap": Decimal("6_000_000_000_000")},
    {"symbol": "011790", "name": "SKC", "market": "KOSPI", "market_cap": Decimal("2_500_000_000_000")},
    {"symbol": "000080", "name": "하이트진로", "market": "KOSPI", "market_cap": Decimal("2_000_000_000_000")},
    {"symbol": "004370", "name": "농심", "market": "KOSPI", "market_cap": Decimal("2_500_000_000_000")},
    {"symbol": "005180", "name": "빙그레", "market": "KOSPI", "market_cap": Decimal("1_200_000_000_000")},
    {"symbol": "000150", "name": "두산", "market": "KOSPI", "market_cap": Decimal("2_500_000_000_000")},
    {"symbol": "042670", "name": "두산인프라코어", "market": "KOSPI", "market_cap": Decimal("3_000_000_000_000")},
    {"symbol": "004800", "name": "효성", "market": "KOSPI", "market_cap": Decimal("2_000_000_000_000")},
    {"symbol": "298020", "name": "효성티앤씨", "market": "KOSPI", "market_cap": Decimal("2_500_000_000_000")},
    {"symbol": "298040", "name": "효성중공업", "market": "KOSPI", "market_cap": Decimal("2_000_000_000_000")},
    {"symbol": "241560", "name": "두산밥캣", "market": "KOSPI", "market_cap": Decimal("4_000_000_000_000")},
    {"symbol": "051600", "name": "한전KPS", "market": "KOSPI", "market_cap": Decimal("1_500_000_000_000")},
    {"symbol": "034830", "name": "한국토지신탁", "market": "KOSPI", "market_cap": Decimal("1_000_000_000_000")},
    {"symbol": "011780", "name": "금호석유", "market": "KOSPI", "market_cap": Decimal("3_000_000_000_000")},
    {"symbol": "002790", "name": "아모레G", "market": "KOSPI", "market_cap": Decimal("1_500_000_000_000")},
    {"symbol": "026960", "name": "동서", "market": "KOSPI", "market_cap": Decimal("1_200_000_000_000")},
    {"symbol": "001450", "name": "현대해상", "market": "KOSPI", "market_cap": Decimal("2_500_000_000_000")},
    {"symbol": "000120", "name": "CJ대한통운", "market": "KOSPI", "market_cap": Decimal("3_500_000_000_000")},
    {"symbol": "007070", "name": "GS리테일", "market": "KOSPI", "market_cap": Decimal("1_800_000_000_000")},
    {"symbol": "028050", "name": "삼성엔지니어링", "market": "KOSPI", "market_cap": Decimal("4_500_000_000_000")},
    {"symbol": "000210", "name": "대림산업", "market": "KOSPI", "market_cap": Decimal("2_500_000_000_000")},
    {"symbol": "003240", "name": "태광산업", "market": "KOSPI", "market_cap": Decimal("1_000_000_000_000")},
    {"symbol": "039490", "name": "키움증권", "market": "KOSPI", "market_cap": Decimal("3_000_000_000_000")},
    {"symbol": "044820", "name": "코스맥스", "market": "KOSPI", "market_cap": Decimal("1_500_000_000_000")},
    {"symbol": "003230", "name": "삼양식품", "market": "KOSPI", "market_cap": Decimal("2_000_000_000_000")},
    {"symbol": "005830", "name": "DB손해보험", "market": "KOSPI", "market_cap": Decimal("3_500_000_000_000")},
    {"symbol": "000990", "name": "DB하이텍", "market": "KOSPI", "market_cap": Decimal("2_000_000_000_000")},
    {"symbol": "192820", "name": "코스맥스비티아이", "market": "KOSPI", "market_cap": Decimal("800_000_000_000")},

    # ==================== KOSDAQ 대형주 (시총 상위 30) ====================
    {"symbol": "247540", "name": "에코프로비엠", "market": "KOSDAQ", "market_cap": Decimal("15_000_000_000_000")},
    {"symbol": "086520", "name": "에코프로", "market": "KOSDAQ", "market_cap": Decimal("12_000_000_000_000")},
    {"symbol": "196170", "name": "알테오젠", "market": "KOSDAQ", "market_cap": Decimal("10_000_000_000_000")},
    {"symbol": "403870", "name": "HPSP", "market": "KOSDAQ", "market_cap": Decimal("5_000_000_000_000")},
    # 091990 셀트리온헬스케어: 2024년 셀트리온과 합병으로 상장폐지
    {"symbol": "263750", "name": "펄어비스", "market": "KOSDAQ", "market_cap": Decimal("3_000_000_000_000")},
    {"symbol": "293490", "name": "카카오게임즈", "market": "KOSDAQ", "market_cap": Decimal("2_500_000_000_000")},
    {"symbol": "112040", "name": "위메이드", "market": "KOSDAQ", "market_cap": Decimal("2_000_000_000_000")},
    {"symbol": "041510", "name": "에스엠", "market": "KOSDAQ", "market_cap": Decimal("2_500_000_000_000")},
    {"symbol": "035900", "name": "JYP Ent.", "market": "KOSDAQ", "market_cap": Decimal("3_500_000_000_000")},
    {"symbol": "122870", "name": "와이지엔터테인먼트", "market": "KOSDAQ", "market_cap": Decimal("1_500_000_000_000")},
    {"symbol": "357780", "name": "솔브레인", "market": "KOSDAQ", "market_cap": Decimal("3_000_000_000_000")},
    {"symbol": "140860", "name": "파크시스템스", "market": "KOSDAQ", "market_cap": Decimal("2_500_000_000_000")},
    {"symbol": "067160", "name": "아프리카TV", "market": "KOSDAQ", "market_cap": Decimal("1_500_000_000_000")},
    {"symbol": "095340", "name": "ISC", "market": "KOSDAQ", "market_cap": Decimal("2_000_000_000_000")},
    {"symbol": "214150", "name": "클래시스", "market": "KOSDAQ", "market_cap": Decimal("1_800_000_000_000")},
    {"symbol": "277810", "name": "레인보우로보틱스", "market": "KOSDAQ", "market_cap": Decimal("4_000_000_000_000")},
    {"symbol": "240810", "name": "원익IPS", "market": "KOSDAQ", "market_cap": Decimal("2_500_000_000_000")},
    {"symbol": "039030", "name": "이오테크닉스", "market": "KOSDAQ", "market_cap": Decimal("3_000_000_000_000")},
    {"symbol": "058470", "name": "리노공업", "market": "KOSDAQ", "market_cap": Decimal("4_500_000_000_000")},
    {"symbol": "145020", "name": "휴젤", "market": "KOSDAQ", "market_cap": Decimal("2_000_000_000_000")},
    {"symbol": "314130", "name": "지놈앤컴퍼니", "market": "KOSDAQ", "market_cap": Decimal("1_200_000_000_000")},
    {"symbol": "068760", "name": "셀트리온제약", "market": "KOSDAQ", "market_cap": Decimal("2_500_000_000_000")},
    {"symbol": "036830", "name": "솔브레인홀딩스", "market": "KOSDAQ", "market_cap": Decimal("1_500_000_000_000")},
    {"symbol": "078340", "name": "컴투스", "market": "KOSDAQ", "market_cap": Decimal("1_200_000_000_000")},
    {"symbol": "215200", "name": "메가스터디교육", "market": "KOSDAQ", "market_cap": Decimal("1_000_000_000_000")},
    {"symbol": "060310", "name": "3S", "market": "KOSDAQ", "market_cap": Decimal("800_000_000_000")},
    {"symbol": "348210", "name": "넥스틴", "market": "KOSDAQ", "market_cap": Decimal("2_000_000_000_000")},
    {"symbol": "096530", "name": "씨젠", "market": "KOSDAQ", "market_cap": Decimal("2_500_000_000_000")},
    {"symbol": "950160", "name": "코오롱티슈진", "market": "KOSDAQ", "market_cap": Decimal("1_500_000_000_000")},

    # ==================== KOSDAQ 중형주 (시총 30~80위) ====================
    {"symbol": "383220", "name": "F&F", "market": "KOSDAQ", "market_cap": Decimal("3_000_000_000_000")},
    {"symbol": "131970", "name": "테스나", "market": "KOSDAQ", "market_cap": Decimal("1_200_000_000_000")},
    {"symbol": "042000", "name": "카페24", "market": "KOSDAQ", "market_cap": Decimal("1_000_000_000_000")},
    {"symbol": "032500", "name": "케이엠더블유", "market": "KOSDAQ", "market_cap": Decimal("800_000_000_000")},
    {"symbol": "053800", "name": "안랩", "market": "KOSDAQ", "market_cap": Decimal("1_200_000_000_000")},
    {"symbol": "045660", "name": "에이텍", "market": "KOSDAQ", "market_cap": Decimal("600_000_000_000")},
    {"symbol": "226330", "name": "신테카바이오", "market": "KOSDAQ", "market_cap": Decimal("800_000_000_000")},
    {"symbol": "046890", "name": "서울반도체", "market": "KOSDAQ", "market_cap": Decimal("1_000_000_000_000")},
    {"symbol": "064260", "name": "다날", "market": "KOSDAQ", "market_cap": Decimal("600_000_000_000")},
    {"symbol": "099190", "name": "아이센스", "market": "KOSDAQ", "market_cap": Decimal("1_000_000_000_000")},
    {"symbol": "253450", "name": "스튜디오드래곤", "market": "KOSDAQ", "market_cap": Decimal("1_500_000_000_000")},
    {"symbol": "036810", "name": "에프에스티", "market": "KOSDAQ", "market_cap": Decimal("700_000_000_000")},
    {"symbol": "025900", "name": "동화기업", "market": "KOSDAQ", "market_cap": Decimal("900_000_000_000")},
    {"symbol": "049520", "name": "유아이엘", "market": "KOSDAQ", "market_cap": Decimal("500_000_000_000")},
    {"symbol": "183300", "name": "코미코", "market": "KOSDAQ", "market_cap": Decimal("600_000_000_000")},
    {"symbol": "319660", "name": "피에스케이", "market": "KOSDAQ", "market_cap": Decimal("1_500_000_000_000")},
    {"symbol": "294090", "name": "이오플로우", "market": "KOSDAQ", "market_cap": Decimal("800_000_000_000")},
    {"symbol": "950140", "name": "잉글우드랩", "market": "KOSDAQ", "market_cap": Decimal("700_000_000_000")},
    {"symbol": "060280", "name": "큐렉소", "market": "KOSDAQ", "market_cap": Decimal("600_000_000_000")},
    {"symbol": "086900", "name": "메디톡스", "market": "KOSDAQ", "market_cap": Decimal("1_200_000_000_000")},
    {"symbol": "219130", "name": "타이거일렉", "market": "KOSDAQ", "market_cap": Decimal("500_000_000_000")},
    {"symbol": "039200", "name": "오스코텍", "market": "KOSDAQ", "market_cap": Decimal("600_000_000_000")},
    {"symbol": "084370", "name": "유진테크", "market": "KOSDAQ", "market_cap": Decimal("1_500_000_000_000")},
    {"symbol": "033640", "name": "네패스", "market": "KOSDAQ", "market_cap": Decimal("800_000_000_000")},
    {"symbol": "222080", "name": "씨아이에스", "market": "KOSDAQ", "market_cap": Decimal("700_000_000_000")},
    {"symbol": "054450", "name": "텔레칩스", "market": "KOSDAQ", "market_cap": Decimal("900_000_000_000")},
    {"symbol": "237690", "name": "에스티팜", "market": "KOSDAQ", "market_cap": Decimal("1_200_000_000_000")},
    {"symbol": "234340", "name": "제이엔케이히터", "market": "KOSDAQ", "market_cap": Decimal("500_000_000_000")},
    {"symbol": "036540", "name": "SFA반도체", "market": "KOSDAQ", "market_cap": Decimal("800_000_000_000")},
    {"symbol": "048410", "name": "현대바이오", "market": "KOSDAQ", "market_cap": Decimal("600_000_000_000")},

    # ==================== KOSDAQ 기타 주요 종목 ====================
    {"symbol": "098120", "name": "마이크로컨텍솔", "market": "KOSDAQ", "market_cap": Decimal("700_000_000_000")},
    {"symbol": "092130", "name": "이크레더블", "market": "KOSDAQ", "market_cap": Decimal("500_000_000_000")},
    {"symbol": "192400", "name": "쿠쿠홀딩스", "market": "KOSDAQ", "market_cap": Decimal("800_000_000_000")},
    {"symbol": "194700", "name": "노바텍", "market": "KOSDAQ", "market_cap": Decimal("400_000_000_000")},
    {"symbol": "038540", "name": "상상인", "market": "KOSDAQ", "market_cap": Decimal("300_000_000_000")},
    {"symbol": "066970", "name": "엘앤에프", "market": "KOSDAQ", "market_cap": Decimal("4_000_000_000_000")},
    {"symbol": "298000", "name": "효성화학", "market": "KOSDAQ", "market_cap": Decimal("600_000_000_000")},
    {"symbol": "041920", "name": "메디아나", "market": "KOSDAQ", "market_cap": Decimal("400_000_000_000")},
    {"symbol": "067310", "name": "하나마이크론", "market": "KOSDAQ", "market_cap": Decimal("700_000_000_000")},
    {"symbol": "083930", "name": "아바코", "market": "KOSDAQ", "market_cap": Decimal("500_000_000_000")},
    {"symbol": "019540", "name": "일리아스", "market": "KOSDAQ", "market_cap": Decimal("300_000_000_000")},
    {"symbol": "080220", "name": "제주반도체", "market": "KOSDAQ", "market_cap": Decimal("600_000_000_000")},
    {"symbol": "950170", "name": "JTC", "market": "KOSDAQ", "market_cap": Decimal("400_000_000_000")},
    {"symbol": "056190", "name": "에스에프에이", "market": "KOSDAQ", "market_cap": Decimal("1_000_000_000_000")},
    {"symbol": "141080", "name": "레고켐바이오", "market": "KOSDAQ", "market_cap": Decimal("2_000_000_000_000")},
    {"symbol": "097780", "name": "제너셈", "market": "KOSDAQ", "market_cap": Decimal("400_000_000_000")},
    {"symbol": "322310", "name": "오로스테크놀로지", "market": "KOSDAQ", "market_cap": Decimal("1_500_000_000_000")},
    {"symbol": "251270", "name": "넷마블", "market": "KOSPI", "market_cap": Decimal("4_000_000_000_000")},
    {"symbol": "036490", "name": "SK가스", "market": "KOSPI", "market_cap": Decimal("1_800_000_000_000")},
    {"symbol": "281820", "name": "케이씨텍", "market": "KOSDAQ", "market_cap": Decimal("1_200_000_000_000")},

    # ==================== KOSDAQ 추가 종목 (100개 달성) ====================
    {"symbol": "217190", "name": "제너시스템즈", "market": "KOSDAQ", "market_cap": Decimal("400_000_000_000")},
    {"symbol": "090460", "name": "비에이치", "market": "KOSDAQ", "market_cap": Decimal("800_000_000_000")},
    {"symbol": "052770", "name": "아이톡시", "market": "KOSDAQ", "market_cap": Decimal("300_000_000_000")},
    {"symbol": "079940", "name": "가비아", "market": "KOSDAQ", "market_cap": Decimal("600_000_000_000")},
    {"symbol": "101490", "name": "에스앤에스텍", "market": "KOSDAQ", "market_cap": Decimal("700_000_000_000")},
    {"symbol": "068050", "name": "팬엔터테인먼트", "market": "KOSDAQ", "market_cap": Decimal("400_000_000_000")},
    {"symbol": "052690", "name": "한전기술", "market": "KOSDAQ", "market_cap": Decimal("1_000_000_000_000")},
    {"symbol": "194480", "name": "데브시스터즈", "market": "KOSDAQ", "market_cap": Decimal("800_000_000_000")},
    {"symbol": "089010", "name": "켐트로닉스", "market": "KOSDAQ", "market_cap": Decimal("500_000_000_000")},
    {"symbol": "094360", "name": "칩스앤미디어", "market": "KOSDAQ", "market_cap": Decimal("900_000_000_000")},
    {"symbol": "060540", "name": "에스에이티", "market": "KOSDAQ", "market_cap": Decimal("400_000_000_000")},
    {"symbol": "035760", "name": "CJ ENM", "market": "KOSDAQ", "market_cap": Decimal("2_500_000_000_000")},
    {"symbol": "036620", "name": "감성코퍼레이션", "market": "KOSDAQ", "market_cap": Decimal("300_000_000_000")},
    {"symbol": "115610", "name": "이미지스", "market": "KOSDAQ", "market_cap": Decimal("400_000_000_000")},
    {"symbol": "025320", "name": "시노펙스", "market": "KOSDAQ", "market_cap": Decimal("500_000_000_000")},
    {"symbol": "067630", "name": "HLB생명과학", "market": "KOSDAQ", "market_cap": Decimal("600_000_000_000")},
    {"symbol": "028300", "name": "HLB", "market": "KOSDAQ", "market_cap": Decimal("3_000_000_000_000")},
    {"symbol": "067080", "name": "대화제약", "market": "KOSDAQ", "market_cap": Decimal("400_000_000_000")},
    {"symbol": "065680", "name": "우주일렉트로", "market": "KOSDAQ", "market_cap": Decimal("500_000_000_000")},
    {"symbol": "036930", "name": "주성엔지니어링", "market": "KOSDAQ", "market_cap": Decimal("2_000_000_000_000")},
    {"symbol": "256840", "name": "한국비엔씨", "market": "KOSDAQ", "market_cap": Decimal("700_000_000_000")},
    {"symbol": "078600", "name": "대주전자재료", "market": "KOSDAQ", "market_cap": Decimal("800_000_000_000")},
    {"symbol": "073010", "name": "케이에스피", "market": "KOSDAQ", "market_cap": Decimal("600_000_000_000")},
    {"symbol": "950210", "name": "프레스티지바이오파마", "market": "KOSDAQ", "market_cap": Decimal("1_200_000_000_000")},
    {"symbol": "200670", "name": "휴메딕스", "market": "KOSDAQ", "market_cap": Decimal("500_000_000_000")},
    {"symbol": "137400", "name": "피엔티", "market": "KOSDAQ", "market_cap": Decimal("900_000_000_000")},
    {"symbol": "214450", "name": "파마리서치", "market": "KOSDAQ", "market_cap": Decimal("1_500_000_000_000")},
    {"symbol": "031310", "name": "아이즈비전", "market": "KOSDAQ", "market_cap": Decimal("400_000_000_000")},
    {"symbol": "347890", "name": "엠투아이", "market": "KOSDAQ", "market_cap": Decimal("600_000_000_000")},
    {"symbol": "217270", "name": "넵튠", "market": "KOSDAQ", "market_cap": Decimal("500_000_000_000")},
]


async def add_stocks():
    """종목 추가 실행"""
    print("=" * 80)
    print("📈 Stock Universe 종목 추가")
    print("=" * 80)

    db_gen = get_db()
    session = await db_gen.__anext__()

    try:
        from sqlalchemy import text

        # 현재 상태 확인
        result = await session.execute(text("SELECT COUNT(*) FROM stock_universe"))
        before_count = result.scalar()
        print(f"\n현재 종목 수: {before_count}개")

        # 종목 추가
        added = 0
        skipped = 0

        for stock in ADDITIONAL_STOCKS:
            # 중복 체크
            result = await session.execute(
                text("SELECT symbol FROM stock_universe WHERE symbol = :symbol"),
                {"symbol": stock["symbol"]}
            )
            if result.scalar():
                print(f"  ⏭️ {stock['symbol']} {stock['name']} - 이미 존재")
                skipped += 1
                continue

            # 종목 추가
            await session.execute(
                text("""
                    INSERT INTO stock_universe (
                        symbol, name, market, market_cap,
                        is_active, is_tradable, is_excluded,
                        passed_market_cap, passed_volume,
                        created_at, updated_at
                    ) VALUES (
                        :symbol, :name, :market, :market_cap,
                        true, true, false,
                        true, true,
                        :now, :now
                    )
                """),
                {
                    "symbol": stock["symbol"],
                    "name": stock["name"],
                    "market": stock["market"],
                    "market_cap": stock["market_cap"],
                    "now": datetime.now(),
                }
            )

            cap_trillion = float(stock["market_cap"]) / 1_000_000_000_000
            print(f"  ✅ {stock['symbol']} {stock['name']} ({cap_trillion:.1f}조) 추가")
            added += 1

        await session.commit()

        # 최종 상태 확인
        result = await session.execute(text("SELECT COUNT(*) FROM stock_universe"))
        after_count = result.scalar()

        print("\n" + "=" * 80)
        print(f"📊 결과 요약")
        print(f"  - 추가됨: {added}개")
        print(f"  - 스킵됨: {skipped}개")
        print(f"  - 총 종목 수: {before_count}개 → {after_count}개")
        print("=" * 80)

    except Exception as e:
        print(f"\n❌ 오류: {e}")
        import traceback
        traceback.print_exc()
        await session.rollback()
    finally:
        await session.close()


if __name__ == "__main__":
    asyncio.run(add_stocks())
