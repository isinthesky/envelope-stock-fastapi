# -*- coding: utf-8 -*-
"""
저장된 리스크/가격 데이터로 매도 피크 규칙 리서치
"""

import argparse
import asyncio
import json
from pathlib import Path

import yaml
from pydantic import ValidationError

from src.adapters.database.connection import close_db, get_async_session
from src.application.domain.strategy.sell_rule_research_service import (
    SellRulePreRegistrationConfig,
    SellPeakRuleResearchService,
    render_preregistered_sell_rule_report,
)


async def main() -> None:
    parser = argparse.ArgumentParser(description="매도 피크 규칙 리서치")
    parser.add_argument("--symbols", type=str, default="", help="쉼표 구분 종목코드 목록")
    parser.add_argument("--start-date", type=str, default=None, help="시작일 YYYYMMDD")
    parser.add_argument("--end-date", type=str, default=None, help="종료일 YYYYMMDD")
    parser.add_argument("--config", type=Path, default=None, help="사전 등록 YAML 설정")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Markdown 리포트 출력 경로",
    )
    args = parser.parse_args()

    symbols = [symbol.strip() for symbol in args.symbols.split(",") if symbol.strip()] or None

    try:
        async with get_async_session() as session:
            service = SellPeakRuleResearchService(session)
            if args.config is None:
                result = await service.research_top_signal_rules(
                    symbols=symbols,
                    start_date=args.start_date,
                    end_date=args.end_date,
                )
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return

            with args.config.open(encoding="utf-8") as config_file:
                raw_config = yaml.safe_load(config_file)
            config = SellRulePreRegistrationConfig.model_validate(raw_config)
            result = await service.research_preregistered_sell_rules(config)
            report = render_preregistered_sell_rule_report(result)
            if args.output is None:
                print(report)
                return
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(report, encoding="utf-8")
            print(f"Wrote sell-rule preregistration report: {args.output}")
    except ValidationError as exc:
        parser.error(f"invalid pre-registration config: {exc}")
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
