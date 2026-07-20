# -*- coding: utf-8 -*-
"""
Telegram 메시지 분할(_split_message) HTML 안전성 테스트

4096자 초과 단일 라인 강제 분할 시 HTML entity(&amp; 등)나 태그(<b> 등)
중간이 잘리면 Telegram이 해당 청크를 parse error로 거부한다.
(M-a 회귀 방지: raw offset 절단 → 경계 백트래킹)
"""

import html
import re

from src.adapters.external.telegram.notifier import TelegramNotifier

LIMIT = TelegramNotifier._TELEGRAM_MAX_LENGTH

# 청크 끝이 entity/태그 중간에서 잘렸는지 검출
UNTERMINATED_ENTITY_AT_END = re.compile(r"&[A-Za-z0-9#]*$")
UNTERMINATED_TAG_AT_END = re.compile(r"<[^>]*$")


def _make_notifier() -> TelegramNotifier:
    return TelegramNotifier(bot_token="x", chat_id="y", enabled=False)


def _assert_chunks_html_safe(chunks: list[str]) -> None:
    for chunk in chunks:
        assert chunk, "빈 청크가 생성되면 안 된다"
        assert len(chunk) <= LIMIT
        assert not UNTERMINATED_ENTITY_AT_END.search(chunk), (
            f"entity 중간 절단: ...{chunk[-16:]!r}"
        )
        assert not UNTERMINATED_TAG_AT_END.search(chunk), (
            f"태그 중간 절단: ...{chunk[-16:]!r}"
        )


def test_long_escaped_line_split_preserves_entity_integrity() -> None:
    # 동적 필드는 전부 html.escape되어 들어온다 (&amp; &lt; &gt; 밀집 라인)
    line = html.escape("삼성전자&SK하이닉스 <신고가> 급등 & 점검 ") * 400
    assert len(line) > LIMIT * 2
    assert "\n" not in line

    chunks = _make_notifier()._split_message(line)

    assert len(chunks) >= 3
    assert "".join(chunks) == line  # 내용 무손실
    _assert_chunks_html_safe(chunks)


def test_long_line_with_tags_split_preserves_tag_integrity() -> None:
    line = "<b>005930 알림 &amp; 점검</b> <i>급등주</i> " * 300
    assert len(line) > LIMIT * 2

    chunks = _make_notifier()._split_message(line)

    assert "".join(chunks) == line
    _assert_chunks_html_safe(chunks)
    for chunk in chunks:
        # 태그 괄호가 청크 내부에서 짝을 이뤄야 한다
        assert chunk.count("<") == chunk.count(">")


def test_line_without_safe_point_falls_back_to_raw_cut() -> None:
    # entity/태그가 전혀 없는 초장문 라인: 백트래킹 대상이 없어 raw 절단 유지
    line = "A" * (LIMIT * 2 + 500)

    chunks = _make_notifier()._split_message(line)

    assert chunks == [
        "A" * LIMIT,
        "A" * LIMIT,
        "A" * 500,
    ]


def test_pathological_ampersand_line_terminates_and_reassembles() -> None:
    # 무한루프 방지: 어떤 입력에서도 분할이 전진하며 내용이 보존되어야 한다
    line = "&" * (LIMIT + 900)

    chunks = _make_notifier()._split_message(line)

    assert "".join(chunks) == line
    assert all(len(chunk) <= LIMIT for chunk in chunks)
    assert all(chunk for chunk in chunks)


def test_line_based_split_path_unchanged() -> None:
    # 줄 단위 분할 경로(라인이 limit 이하)는 기존 동작 유지
    text = "\n".join(f"line-{i:05d} &amp; <b>ok</b>" for i in range(300))
    assert len(text) > LIMIT

    chunks = _make_notifier()._split_message(text)

    assert len(chunks) >= 2
    assert "\n".join(chunks) == text  # 라인 순서/내용 보존
    for chunk in chunks:
        assert len(chunk) <= LIMIT
        # 줄 단위 경로에서는 라인 중간 절단이 발생하지 않는다
        for line in chunk.split("\n"):
            assert line.startswith("line-")


def test_entity_inside_unclosed_tag_cuts_before_tag_start() -> None:
    """태그 내부 entity에 절단점이 걸리면 태그 시작(<) 앞에서 잘라야 한다 (R3 회귀)."""
    prefix = "a" * (LIMIT - 11)
    line = prefix + '<i data="&amp;q">' + "b" * 200
    assert "\n" not in line

    chunks = _make_notifier()._split_message(line)

    assert chunks[0] == prefix  # entity(&) 위치가 아니라 태그 시작 앞에서 절단
    assert "".join(chunks) == line  # 내용 무손실
    _assert_chunks_html_safe(chunks)
