#!/usr/bin/env python3
"""
无 pytest 依赖的测试执行器：跑各 test 模块里的 TESTS 列表。
用法（在仓库根目录）：python -m prediction_markets.tests.run_all
"""
import sys
import traceback

from prediction_markets.tests import (
    test_signer, test_fees, test_arb, test_matcher, test_readonly_guard,
)

MODULES = [test_signer, test_fees, test_arb, test_matcher, test_readonly_guard]


def main():
    passed = failed = 0
    for mod in MODULES:
        for fn in getattr(mod, "TESTS", []):
            name = f"{mod.__name__}.{fn.__name__}"
            try:
                fn()
                passed += 1
                print(f"  PASS  {name}")
            except Exception as e:
                failed += 1
                print(f"  FAIL  {name}: {e}")
                traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
