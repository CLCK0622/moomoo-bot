"""
verify_store_fingerprint.py —— 让 Qlib store 的复现锚点**可执行**（工部尚书 2026-08-06）

背景：`data/qlib_store/` 体积大、**不入库**，所以「重建能否复现」全靠 provenance 里的
sha256 锚点（`data/qlib_store_provenance.json`）。但那份 provenance 只用**散文**描述算法
（"sha256 over sorted (basename + sha256(bytes))"），没有可跑的实现——歧义点至少两处：

  * `sha256(bytes)` 取 **hexdigest** 还是 **raw digest**？
  * 各条目之间有无分隔符 / 换行？

我按散文描述复算时**第一次没对上**，试了 5 种拼接变体才命中（正解＝`name.encode()` +
`sha256(bytes).digest()` **原始 20/32 字节**，非 hex 串，按文件名排序，无分隔符）。也就是说：
锚点本身是真的、可复现的，但**没有人能不猜就验证它**——控制写在纸面、不可执行，实际就不设防。

本脚本把该算法固化成代码，任何人重建 store 后一条命令即可比对，不必猜。

用法（repo 根，或 qlab/ 下）：
    python -m tools.qlib_gen.verify_store_fingerprint
    python -m tools.qlib_gen.verify_store_fingerprint --src data/daily_full --store data/qlib_store

退出码：0 = 全部匹配；1 = 有不匹配（重建结果与锚点不一致，别拿来跑挖掘）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def fingerprint_inputs(src: Path) -> tuple[str, int]:
    """输入指纹：按 basename 排序，逐个 update(name) + update(sha256(bytes).digest())。

    注意是 **raw digest**（非 hexdigest）——这正是散文描述里没说清、我复算时踩到的那处歧义。
    """
    files = sorted(src.glob("*.parquet"), key=lambda p: p.name)
    h = hashlib.sha256()
    for p in files:
        h.update(p.name.encode())
        h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest(), len(files)


def fingerprint_store(store: Path) -> tuple[str, int]:
    """store 指纹：`<store>/bin` 下**全部文件**，按相对路径排序，同样 relpath + raw digest。

    与并行写入顺序无关（先排序），故重建应当逐位复现。
    """
    root = store / "bin"
    if not root.exists():
        root = store
    files = sorted((p for p in root.rglob("*") if p.is_file()),
                   key=lambda p: str(p.relative_to(root)))
    h = hashlib.sha256()
    for p in files:
        h.update(str(p.relative_to(root)).encode())
        h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest(), len(files)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, default=Path("data/daily_full"))
    ap.add_argument("--store", type=Path, default=Path("data/qlib_store"))
    ap.add_argument("--provenance", type=Path,
                    default=Path("data/qlib_store_provenance.json"))
    a = ap.parse_args(argv)

    if not a.provenance.exists():
        print(f"找不到 provenance: {a.provenance}", file=sys.stderr)
        return 1
    rec = json.loads(a.provenance.read_text(encoding="utf-8"))["fingerprints_sha256"]

    ok = True
    if a.src.exists():
        got, n = fingerprint_inputs(a.src)
        good = (got == rec.get("input_parquets"))
        ok &= good
        print(f"[{'OK ' if good else 'MISMATCH'}] input_parquets ({n} files)")
        print(f"    got      {got}")
        print(f"    expected {rec.get('input_parquets')}")
    else:
        print(f"[SKIP] 输入目录不存在: {a.src}")

    if a.store.exists():
        got, n = fingerprint_store(a.store)
        good = (got == rec.get("store"))
        ok &= good
        print(f"[{'OK ' if good else 'MISMATCH'}] store ({n} files)")
        print(f"    got      {got}")
        print(f"    expected {rec.get('store')}")
    else:
        print(f"[SKIP] store 未构建（{a.store}）——先跑 build_qlib_data 再验")

    print("\n全部匹配：重建与锚点一致，可用于挖掘。" if ok else
          "\n有不匹配：重建结果与锚点不一致，**先排查再跑挖掘**。")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
