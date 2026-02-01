#!/usr/bin/env python3
"""
项目完整性验证脚本
检查所有必需文件和配置
"""
import os
import sys
import json

# ANSI 颜色代码
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

def check_mark(passed):
    return f"{GREEN}✓{RESET}" if passed else f"{RED}✗{RESET}"

print(f"\n{BLUE}{'='*60}{RESET}")
print(f"{BLUE}ORB + Keltner Channel 策略 - 项目完整性验证{RESET}")
print(f"{BLUE}{'='*60}{RESET}\n")

all_checks_passed = True

# 1. 检查核心 Python 文件
print(f"{YELLOW}1. 检查核心 Python 文件...{RESET}")
python_files = [
    'main.py',
    'config.py',
    'trader.py',
    'strategy.py',
    'indicators.py',
    'state_manager.py',
    'test_modules.py'
]

for file in python_files:
    exists = os.path.exists(file)
    print(f"   {check_mark(exists)} {file}")
    if not exists:
        all_checks_passed = False

# 2. 检查配置文件
print(f"\n{YELLOW}2. 检查配置文件...{RESET}")
config_files = [
    'watchlist.json',
    'requirements.txt',
    '.gitignore'
]

for file in config_files:
    exists = os.path.exists(file)
    print(f"   {check_mark(exists)} {file}")
    if not exists:
        all_checks_passed = False

# 3. 检查文档
print(f"\n{YELLOW}3. 检查文档...{RESET}")
docs = [
    'README.md',
    'CONFIG_GUIDE.md',
    'IMPLEMENTATION_SUMMARY.md',
    'QUICK_REFERENCE.md'
]

for file in docs:
    exists = os.path.exists(file)
    print(f"   {check_mark(exists)} {file}")
    if not exists:
        all_checks_passed = False

# 4. 检查脚本
print(f"\n{YELLOW}4. 检查脚本...{RESET}")
scripts = [
    'setup.sh',
    'run.sh'
]

for file in scripts:
    exists = os.path.exists(file)
    executable = os.access(file, os.X_OK) if exists else False
    print(f"   {check_mark(exists and executable)} {file} {'(可执行)' if executable else '(不可执行)' if exists else ''}")
    if not exists or not executable:
        all_checks_passed = False

# 5. 检查虚拟环境
print(f"\n{YELLOW}5. 检查虚拟环境...{RESET}")
venv_exists = os.path.exists('venv')
print(f"   {check_mark(venv_exists)} venv/ 目录")
if not venv_exists:
    all_checks_passed = False

if venv_exists:
    venv_python = os.path.exists('venv/bin/python')
    print(f"   {check_mark(venv_python)} venv/bin/python")
    if not venv_python:
        all_checks_passed = False

# 6. 检查 watchlist.json 内容
print(f"\n{YELLOW}6. 检查 watchlist.json 内容...{RESET}")
try:
    with open('watchlist.json', 'r') as f:
        watchlist = json.load(f)
        symbols = watchlist.get('symbols', [])
        valid = len(symbols) > 0
        print(f"   {check_mark(valid)} 包含 {len(symbols)} 只股票")
        if len(symbols) > 0:
            print(f"   {BLUE}→{RESET} {', '.join(symbols[:5])}{'...' if len(symbols) > 5 else ''}")
        if not valid:
            all_checks_passed = False
except Exception as e:
    print(f"   {RED}✗{RESET} 读取失败: {e}")
    all_checks_passed = False

# 7. 检查依赖包
print(f"\n{YELLOW}7. 检查依赖包...{RESET}")
if venv_exists:
    try:
        import subprocess
        result = subprocess.run(
            ['./venv/bin/pip', 'list'],
            capture_output=True,
            text=True,
            timeout=5
        )
        packages = result.stdout

        required_packages = [
            ('futu-api', 'futu'),  # 包名和导入名可能不同
            ('pandas', 'pandas'),
            ('numpy', 'numpy'),
            ('pytz', 'pytz')
        ]
        for pkg_name, import_name in required_packages:
            # 检查包列表或尝试导入
            installed = pkg_name in packages or import_name in packages
            if not installed:
                try:
                    __import__(import_name)
                    installed = True
                except ImportError:
                    pass
            print(f"   {check_mark(installed)} {pkg_name}")
            if not installed:
                all_checks_passed = False
    except Exception as e:
        print(f"   {YELLOW}⚠{RESET} 无法检查依赖包: {e}")
else:
    print(f"   {YELLOW}⚠{RESET} 虚拟环境不存在，跳过")

# 8. 检查 config.py 关键配置
print(f"\n{YELLOW}8. 检查配置参数...{RESET}")
try:
    import config

    checks = [
        ('MOOMOO_HOST', hasattr(config, 'MOOMOO_HOST')),
        ('MOOMOO_PORT', hasattr(config, 'MOOMOO_PORT')),
        ('TRADE_ENV', hasattr(config, 'TRADE_ENV')),
        ('MAX_POSITIONS', hasattr(config, 'MAX_POSITIONS')),
        ('STOP_LOSS_RATIO', hasattr(config, 'STOP_LOSS_RATIO')),
        ('STATE_IDLE', hasattr(config, 'STATE_IDLE')),
    ]

    for name, exists in checks:
        print(f"   {check_mark(exists)} {name}")
        if not exists:
            all_checks_passed = False

    # 显示关键值
    if hasattr(config, 'TRADE_ENV'):
        env = '模拟盘' if config.TRADE_ENV == 1 else '真实交易'
        print(f"   {BLUE}→{RESET} 交易环境: {env}")
    if hasattr(config, 'MAX_POSITIONS'):
        print(f"   {BLUE}→{RESET} 最大持仓: {config.MAX_POSITIONS} 只")
    if hasattr(config, 'STOP_LOSS_RATIO'):
        print(f"   {BLUE}→{RESET} 账户止损: {config.STOP_LOSS_RATIO*100}%")

except Exception as e:
    print(f"   {RED}✗{RESET} 导入 config.py 失败: {e}")
    all_checks_passed = False

# 9. 统计代码量
print(f"\n{YELLOW}9. 代码统计...{RESET}")
try:
    total_lines = 0
    for file in python_files:
        if os.path.exists(file):
            with open(file, 'r', encoding='utf-8') as f:
                lines = len(f.readlines())
                total_lines += lines
    print(f"   {GREEN}✓{RESET} 总计 {total_lines} 行 Python 代码")
except Exception as e:
    print(f"   {YELLOW}⚠{RESET} 无法统计代码量: {e}")

# 最终结果
print(f"\n{BLUE}{'='*60}{RESET}")
if all_checks_passed:
    print(f"{GREEN}✓ 所有检查通过！项目配置完整。{RESET}")
    print(f"\n{GREEN}下一步：{RESET}")
    print(f"  1. 启动 Moomoo OpenD (127.0.0.1:11111)")
    print(f"  2. 运行测试: {BLUE}python test_modules.py{RESET}")
    print(f"  3. 启动策略: {BLUE}./run.sh{RESET}")
    sys.exit(0)
else:
    print(f"{RED}✗ 检查失败！请修复上述问题。{RESET}")
    print(f"\n{YELLOW}建议：{RESET}")
    print(f"  - 如果缺少文件，重新运行项目创建步骤")
    print(f"  - 如果虚拟环境有问题，运行: {BLUE}./setup.sh{RESET}")
    print(f"  - 如果脚本不可执行，运行: {BLUE}chmod +x *.sh{RESET}")
    sys.exit(1)

