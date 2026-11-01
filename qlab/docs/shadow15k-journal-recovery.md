# ShadowLedger 非 DELETE 拒绝后的人工保全与恢复

本规程只处理 `evo881.shadow15k.offline` 的 SQLite 文件，不启用账户、策略或运行闸。由原授权线指定的运维责任人执行；生产目录替换/恢复须另有明确授权、静止窗口、回滚保全和非作者核验。本说明不是执行授权。产品不自动切模式、不清理 sidecar，原文件白名单和非 DELETE 守卫保持不变。

**含已提交帧的 WAL 不得直接丢弃。** 事务可能已提交到 WAL、尚未进入主库；只保留主库可能丢行，而且丢行后的 `integrity_check` 仍可返回 `ok`。不要执行 `rm *-wal *-shm`，也不要用 `immutable=1` 忽略 WAL 后宣称数据完整。[SQLite WAL 文件说明](https://sqlite.org/wal.html#the_wal_file)及[checkpoint 语义](https://sqlite.org/pragma.html#pragma_wal_checkpoint)是这里的依据。

已审的 macOS 环境观测如下，不是所有 Python/SQLite 组合的普遍保证：

| 固定环境 | 首次非 DELETE 拒绝、连接关闭后 | 新构造／旧对象再次读取 |
| --- | --- | --- |
| Python 3.9.6 / SQLite 3.51.0 | WAL 0 B，SHM 32768 B | 白名单拒绝，`namespace_contains_foreign_files`，connect=0 |
| Python 3.12.13 / SQLite 3.53.1 | 无 sidecar | `journal_mode_delete_required:wal`，connect=1；只有模式查询 |

其他构建依实际文件、SQL 和连接证据诊断，不能按 Python 版本猜文件是否存在。新回归只在上述两组已审原生环境执行，两组有独立断言；原通用模式测试继续覆盖其他环境。3.9 转回 DELETE 后也可能留下 SHM，不能把切换成功当作清理许可。

## 1. 授权、静止与环境

先通过该命名空间原获准的管理方式停用所有消费者、写入者及外部改模式进程；确认对应 PID 已退出、没有连接/句柄/锁持有者，保持禁止重新打开的维护窗口。不得按可执行名全机 kill。以下 `ps`/`lsof` 是只读证据，空输出本身不能证明没有未来重开者；权限不足、错误、身份不明或无法保证静止就停手升级。

在原获准 checkout 的 shell 中设置实际路径（必须替换下面三个占位路径）：

```sh
set -eu
export LEDGER_PY='/absolute/path/to/the-approved-python'
export LEDGER_CHECKOUT='/absolute/path/to/the-approved-checkout'
export LEDGER_SOURCE='/absolute/path/to/the-approved-namespace/shadow15k'
test -x "$LEDGER_PY"
test -d "$LEDGER_CHECKOUT/.git"
test -d "$LEDGER_SOURCE"
"$LEDGER_PY" -I -S -c 'import sys,sqlite3; print(sys.version); print(sqlite3.sqlite_version)'
git -C "$LEDGER_CHECKOUT" rev-parse HEAD
git -C "$LEDGER_CHECKOUT" status --porcelain
```

核对批准的 commit、解释器/SQLite 和原 genesis、费用 SHA、故障前事件控制总数。不要自行安装或升级 SQLite。保全区必须私有、不是源目录的子目录；下面使用原已存在的离线物理容器内独立案件目录，以便最后能在副本上走原产品路径检查，不改变 `PHYSICAL_ROOT`：

```sh
test -d "$LEDGER_CHECKOUT/.shadow15k-offline"
umask 077
export LEDGER_CASE
LEDGER_CASE="$(mktemp -d "$LEDGER_CHECKOUT/.shadow15k-offline/recovery-XXXXXXXX")"
/bin/ps -axo pid,ppid,user,command > "$LEDGER_CASE/processes-before.txt"
if /usr/sbin/lsof -nP +D "$LEDGER_SOURCE" > "$LEDGER_CASE/lsof-before.txt" 2> "$LEDGER_CASE/lsof-before.stderr"; then
    printf '0\n' > "$LEDGER_CASE/lsof-before.rc"
else
    printf '%s\n' "$?" > "$LEDGER_CASE/lsof-before.rc"
fi
```

人工核对进程、lsof 结果及 stderr：只接受已确认静止的对象。`lsof` 的非零退出也可能是错误，不能直接当“无人持有”。若要终止一个已识别进程，先按其原管理规程核权限；若它可能是 Multica 子进程，另读 `multica daemon status --output json` 排除 daemon PID，不提供按名终止命令。

## 2. SQLite 打开前，整体保全现场

下面只读源文件并复制整个静止目录，不调用 SQLite。任何 symlink、非普通文件、nlink!=1、复制期间变化都停止。保留源目录原样；不只拷 `ledger.sqlite3`，不遗漏 WAL/SHM/journal 或未知外来文件。未知文件也保全，随后诊断，不能为通过白名单先删掉。

```sh
"$LEDGER_PY" -I -S - <<'PY'
import datetime, hashlib, json, os, shutil, sqlite3, stat, sys
from pathlib import Path
source = Path(os.environ['LEDGER_SOURCE'])
case = Path(os.environ['LEDGER_CASE'])
assert source.is_absolute() and source.resolve() == source
assert case.is_absolute() and case.resolve() == case
assert source not in case.parents and case not in source.parents
assert not any(p.is_symlink() for p in [source, *source.parents, case, *case.parents])
def snapshot(root):
    result = {}
    for p in sorted(root.iterdir()):
        s = p.lstat()
        assert stat.S_ISREG(s.st_mode) and s.st_nlink == 1, p
        result[p.name] = dict(size=s.st_size, uid=s.st_uid, gid=s.st_gid,
            mode=stat.S_IMODE(s.st_mode), nlink=s.st_nlink, dev=s.st_dev,
            inode=s.st_ino, mtime_ns=s.st_mtime_ns,
            sha256=hashlib.sha256(p.read_bytes()).hexdigest())
    return result
before = snapshot(source)
assert 'ledger.sqlite3' in before
image = case / 'evidence' / 'shadow15k'
shutil.copytree(source, image, copy_function=shutil.copy2)
after = snapshot(source)
assert before == after, 'source changed: keep isolation; do not diagnose this copy'
copied = snapshot(image)
assert set(copied) == set(before)
assert all(copied[n]['sha256'] == before[n]['sha256'] for n in before)
manifest = dict(source=str(source), evidence=str(image), files=before,
    python=sys.version, sqlite=sqlite3.sqlite_version,
    utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
(case / 'source-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
print(json.dumps(manifest, indent=2))
PY
if /usr/sbin/lsof -nP +D "$LEDGER_SOURCE" > "$LEDGER_CASE/lsof-after-backup.txt" 2> "$LEDGER_CASE/lsof-after-backup.stderr"; then
    printf '0\n' > "$LEDGER_CASE/lsof-after-backup.rc"
else
    printf '%s\n' "$?" > "$LEDGER_CASE/lsof-after-backup.rc"
fi
```

再次人工核对静止窗口和持有者；复制前后文件 SHA 相等不能替代这一步。源目录、`evidence` 和 manifest 都保留，**不对它们运行 SQLite**；以下只在复制出的诊断/工作目录操作。

## 3. 完整副本的逻辑基线与导出

创建两个独立副本：diagnostic 取得保全时的完整 WAL 视图，work 用于受控 checkpoint。SQLite 打开副本仍可能产生/修改 sidecar，正是将诊断隔离出去的原因。

```sh
"$LEDGER_PY" -I -S - <<'PY'
import os, shutil
from pathlib import Path
c = Path(os.environ['LEDGER_CASE'])
for name in ('diagnostic', 'work'):
    shutil.copytree(c/'evidence/shadow15k', c/name/'shadow15k')
PY
cat > "$LEDGER_CASE/view.py" <<'PY'
import hashlib, json, os, sqlite3, sys
from contextlib import closing
from pathlib import Path
from urllib.parse import quote
case = Path(os.environ['LEDGER_CASE']).resolve()
path = Path(sys.argv[1]).resolve(strict=True)
assert case in path.parents and case/'evidence' not in path.parents
def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode('utf-8')
def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()
with closing(sqlite3.connect('file:'+quote(str(path))+'?mode=ro', uri=True)) as db:
    db.execute('PRAGMA query_only=ON')
    mode = db.execute('PRAGMA journal_mode').fetchone()[0]
    integrity = db.execute('PRAGMA integrity_check').fetchall()
    assert integrity == [('ok',)]
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables == {'metadata', 'events'}
    metadata = db.execute('SELECT * FROM metadata ORDER BY id').fetchall()
    events = db.execute('SELECT * FROM events ORDER BY seq').fetchall()
    assert len(metadata) == 1 and metadata[0][0] == 1
    genesis = json.loads(metadata[0][1])
    assert genesis['namespace'] == 'evo881.shadow15k.offline'
    assert canonical(genesis).decode() == metadata[0][1]
    chain = digest(genesis)
    for expected, (seq, eid, kind, body, previous, recorded) in enumerate(events, 1):
        value = json.loads(body)
        assert type(seq) is int and seq == expected and previous == chain
        assert canonical(value).decode() == body
        chain = digest(dict(seq=seq, event_id=eid, kind=kind,
            body=value, previous_hash=previous))
        assert chain == recorded
    content = dict(metadata=metadata, events=events)
    print(json.dumps(dict(mode=mode, integrity=integrity,
        metadata_rows=len(metadata), event_rows=len(events), last_seq=len(events),
        event_tip=chain, genesis_body_sha256=hashlib.sha256(metadata[0][1].encode()).hexdigest(),
        logical_sha256=digest(content), genesis=genesis), sort_keys=True))
PY
"$LEDGER_PY" -I -S "$LEDGER_CASE/view.py" "$LEDGER_CASE/diagnostic/shadow15k/ledger.sqlite3" > "$LEDGER_CASE/before.json"
cat "$LEDGER_CASE/before.json"
```

这是备份时完整三文件视图的逻辑基线，不是只读主库得到的基线。人工与故障前独立执行回执/控制总数核对 `event_rows/last_seq/event_tip`、genesis/fee_binding、内容 SHA；副本自洽不证明故障前没有丢记录。独立控制缺失或冲突时保持隔离，不能只凭 `integrity=ok` 或前后相同就核收。

再从完整诊断视图导出独立数据库，验证 WAL 中提交的数据也进入导出。此处使用 [SQLite backup API](https://sqlite.org/backup.html)，不会只拷主库页面；目标是全新私有副本，拒绝覆盖已有导出。

```sh
"$LEDGER_PY" -I -S - <<'PY'
import os, sqlite3
from contextlib import closing
from pathlib import Path
from urllib.parse import quote
c = Path(os.environ['LEDGER_CASE'])
target = c/'exported/shadow15k/ledger.sqlite3'
target.parent.mkdir(parents=True)
assert not target.exists()
with closing(sqlite3.connect('file:'+quote(str(c/'diagnostic/shadow15k/ledger.sqlite3'))+'?mode=ro', uri=True)) as source:
    with closing(sqlite3.connect(str(target), isolation_level=None)) as dest:
        source.backup(dest)
        assert dest.execute('PRAGMA journal_mode=DELETE').fetchone() == ('delete',)
PY
"$LEDGER_PY" -I -S "$LEDGER_CASE/view.py" "$LEDGER_CASE/exported/shadow15k/ledger.sqlite3" > "$LEDGER_CASE/exported.json"
```

## 4. 仅在工作副本 checkpoint，再明确转 DELETE

确认所有诊断/导出连接已关闭，原命名空间仍静止。指定责任人明确执行下面的**副本写入操作**；不要移进产品读取路径或改为对源路径运行。

```sh
"$LEDGER_PY" -I -S - <<'PY'
import json, os, sqlite3
from contextlib import closing
from pathlib import Path
c = Path(os.environ['LEDGER_CASE'])
with closing(sqlite3.connect(str(c/'work/shadow15k/ledger.sqlite3'), isolation_level=None, timeout=0)) as db:
    mode = db.execute('PRAGMA journal_mode').fetchone()[0]
    assert mode in ('wal', 'delete')
    checkpoint = None
    if mode == 'wal':
        checkpoint = db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
        assert checkpoint == (0, 0, 0), ('busy or unprocessed frames', checkpoint)
    assert db.execute('PRAGMA journal_mode=DELETE').fetchone() == ('delete',)
    assert db.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
(c/'checkpoint.json').write_text(json.dumps(dict(prior_mode=mode,
    checkpoint=checkpoint, mode='delete', connections_closed=True))+'\n')
PY
"$LEDGER_PY" -I -S "$LEDGER_CASE/view.py" "$LEDGER_CASE/work/shadow15k/ledger.sqlite3" > "$LEDGER_CASE/after.json"
"$LEDGER_PY" -I -S - <<'PY'
import json, os
from pathlib import Path
c = Path(os.environ['LEDGER_CASE'])
before = json.loads((c/'before.json').read_text())
keys = ('metadata_rows','event_rows','last_seq','event_tip','genesis_body_sha256','logical_sha256','genesis')
for name in ('exported.json','after.json'):
    other = json.loads((c/name).read_text())
    assert other['mode'] == 'delete' and other['integrity'] == [['ok']]
    assert all(other[k] == before[k] for k in keys), name
print('row counts, complete logical SHA, genesis/fees and event chain preserved; DELETE verified')
PY
if /usr/sbin/lsof -nP +D "$LEDGER_CASE/work/shadow15k" > "$LEDGER_CASE/work-handles.txt" 2> "$LEDGER_CASE/work-handles.stderr"; then
    printf '0\n' > "$LEDGER_CASE/work-handles.rc"
else
    printf '%s\n' "$?" > "$LEDGER_CASE/work-handles.rc"
fi
```

checkpoint 返回三列分别是 busy、日志页数、已处理页数；TRUNCATE 成功要求 `(0,0,0)`，否则停止，不删除任何文件。已经是 DELETE 时不为了清理而重新启用 WAL。所有连接关闭、人工核完 lsof 与误差后，检查 sidecar：WAL 仍存在（包括非零或意外空 WAL）就停手另诊断；不能由文件大小推导“可删除”。

若**仅有 stale SHM**，且以上零busy、DELETE、完整性/行数/内容/链一致、独立控制总数、无持有者、原件完整保留等条件同时满足，才将**工作副本**的 SHM 移出命名空间保全；绝不删源或 evidence 的 sidecar。不能证明条件则保留锁死状态。

```sh
"$LEDGER_PY" -I -S - <<'PY'
import hashlib, json, os, stat
from pathlib import Path
c = Path(os.environ['LEDGER_CASE'])
root = c/'work/shadow15k'
assert not (root/'ledger.sqlite3-wal').exists()
assert not (root/'ledger.sqlite3-journal').exists()
assert json.loads((c/'after.json').read_text())['mode'] == 'delete'
shm = root/'ledger.sqlite3-shm'
if shm.exists():
    info = shm.lstat()
    assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1
    digest = hashlib.sha256(shm.read_bytes()).hexdigest()
    target = c/'quarantine/ledger.sqlite3-shm'
    target.parent.mkdir()
    assert not target.exists()
    shm.rename(target)
    assert hashlib.sha256(target.read_bytes()).hexdigest() == digest
    (c/'shm-quarantine.json').write_text(json.dumps(dict(sha256=digest,
        source=str(shm), preserved=str(target)))+'\n')
assert {p.name for p in root.iterdir()} == {'ledger.sqlite3'}
PY
```

这条保全命令依赖上面人工核收的前提，不是通用清理脚本。出现其他文件、链接或状态不符时停止，不扩大白名单。

## 5. 产品与回滚验收

继续使用原批准 checkout/原 genesis 与费用绑定，不改 `PHYSICAL_ROOT`、不使用 fixture 冒充真实输入。由责任人提供 `LEDGER_BINDING` 指向原绑定 JSON：`genesis`（原构造六字段）、`params_path`、`schedule_path`、`params_sha256`、`schedule_sha256`。这些值来自原配置/回执，不从坏库或本说明猜默认值。

```sh
export LEDGER_BINDING='/absolute/path/to/the-approved-original-binding.json'
PYTHONPATH="$LEDGER_CHECKOUT/qlab" "$LEDGER_PY" -B - <<'PY'
import json, os
from pathlib import Path
from qlab.shadow15k import FeeBook, ShadowLedger
from qlab.shadow15k.ledger import PHYSICAL_ROOT
c = Path(os.environ['LEDGER_CASE']).resolve()
root = c/'work/shadow15k'
assert PHYSICAL_ROOT in root.parents, 'wrong checkout/container: do not override root'
binding = json.loads(Path(os.environ['LEDGER_BINDING']).read_text())
fees = FeeBook(binding['params_path'], binding['schedule_path'],
    params_sha256=binding['params_sha256'], schedule_sha256=binding['schedule_sha256'])
expected = json.loads((c/'before.json').read_text())
for book in (ShadowLedger(root, binding['genesis'], fees),
             ShadowLedger(root, binding['genesis'], fees)):
    with book._connection(write=False) as db:
        assert db.execute('PRAGMA journal_mode').fetchone() == ('delete',)
        _, tip, count = book._load(db)
        assert count == expected['event_rows'] and tip == expected['event_tip']
    result = book.readout({})
    assert result['metrics']['event_count'] == expected['event_rows']
    assert result['metrics']['ledger_sha256'] == expected['event_tip']
print('new constructor and existing-object read verified on recovery COPY; no valuation claim')
PY
"$LEDGER_PY" -I -S "$LEDGER_CASE/view.py" "$LEDGER_CASE/work/shadow15k/ledger.sqlite3" > "$LEDGER_CASE/accepted.json"
"$LEDGER_PY" -I -S - <<'PY'
import hashlib, json, os, stat
from pathlib import Path
c = Path(os.environ['LEDGER_CASE'])
before = json.loads((c/'before.json').read_text())
after = json.loads((c/'accepted.json').read_text())
for key in ('metadata_rows','event_rows','last_seq','event_tip','genesis_body_sha256','logical_sha256','genesis'):
    assert before[key] == after[key], key
assert after['mode'] == 'delete' and after['integrity'] == [['ok']]
manifest = json.loads((c/'source-manifest.json').read_text())
for root in (Path(manifest['source']), c/'evidence/shadow15k'):
    assert {p.name for p in root.iterdir()} == set(manifest['files'])
    for name, record in manifest['files'].items():
        p = root/name; s = p.lstat()
        assert stat.S_ISREG(s.st_mode) and s.st_nlink == 1
        assert hashlib.sha256(p.read_bytes()).hexdigest() == record['sha256']
print('accepted copy: row counts/content SHA/DELETE verified; original and full evidence retained unchanged')
PY
```

`readout({})` 只验证现有对象确能经过账本读取及事件链，不提供价格/估值认证；缺 marks 的报告仍拒绝估值。副本验收还须由非作者核对原费用/元策略/控制总数。主库**物理** SHA 在恢复转换后可以变化，验收用逐行逻辑内容 SHA 与行数/链保持；原现场在各次拒绝以及复制前后则要求完整物理 SHA 不变。

本规程到此只产出经过核对的恢复副本，不会替换/删除原目录，也不启动消费者。实际恢复另行由原授权运维责任方和非作者核验者给出明确提升/回滚步骤；不得把受控副本成功外推为真实账本认证。任何不一致、busy、未知已提交帧、无法证明静止、白名单或绑定失败时，保留源/evidence/quarantine 和所有日志，继续隔离并回报，禁止重试清理求通过。
