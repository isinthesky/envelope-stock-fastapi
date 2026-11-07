# -*- coding: utf-8 -*-
"""
관리자 비밀번호 해시 생성기 (ADMIN_PASSWORD_HASH 값 출력)

사용:
    python3 scripts/ops/hash_admin_password.py            # 프롬프트로 입력(화면 미표시)
    python3 scripts/ops/hash_admin_password.py --generate # 강한 랜덤 비밀번호 생성 + 해시 출력

출력된 해시를 .env의 ADMIN_PASSWORD_HASH에 넣고 api 컨테이너를 재기동한다.
해시가 바뀌면 기존 로그인 세션은 모두 무효화된다. 외부 의존성 없음(stdlib만 사용).
"""

import argparse
import getpass
import importlib.util
import secrets
import sys
from pathlib import Path

# src.application.common 패키지 __init__은 sqlalchemy 등을 import하므로, 의존성 없는 호스트에서도
# 돌도록 password_hash.py 모듈 파일만 직접 로드한다.
_MODULE_PATH = Path(__file__).resolve().parents[2] / "src/application/common/password_hash.py"
_spec = importlib.util.spec_from_file_location("_password_hash", _MODULE_PATH)
assert _spec and _spec.loader
_password_hash = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_password_hash)
hash_password = _password_hash.hash_password

MIN_LENGTH = 12


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--generate", action="store_true", help="랜덤 비밀번호를 생성한다")
    args = parser.parse_args()

    if args.generate:
        password = secrets.token_urlsafe(18)
        print(f"PASSWORD (한 번만 표시됨): {password}", file=sys.stderr)
    else:
        password = getpass.getpass("새 관리자 비밀번호: ")
        if getpass.getpass("비밀번호 확인: ") != password:
            print("비밀번호가 일치하지 않습니다.", file=sys.stderr)
            return 1
        if len(password) < MIN_LENGTH:
            print(f"비밀번호는 {MIN_LENGTH}자 이상이어야 합니다.", file=sys.stderr)
            return 1

    print(f"ADMIN_PASSWORD_HASH={hash_password(password)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
