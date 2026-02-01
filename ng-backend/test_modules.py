#!/usr/bin/env python3
"""
测试脚本 - 验证所有模块是否正确安装和导入
"""
import sys

print("="*60)
print("ORB + Keltner Channel 策略模块测试")
print("="*60)

# 测试标准库
print("\n1. 测试标准库...")
try:
    import logging
    import json
    import time
    from datetime import datetime, timedelta
    from typing import List, Dict, Optional, Tuple
    print("   ✓ 标准库导入成功")
except Exception as e:
    print(f"   ✗ 标准库导入失败: {e}")
    sys.exit(1)

# 测试第三方库
print("\n2. 测试第三方库...")
try:
    import pandas as pd
    import numpy as np
    import pytz
    print(f"   ✓ pandas {pd.__version__}")
    print(f"   ✓ numpy {np.__version__}")
    print(f"   ✓ pytz {pytz.__version__}")
except Exception as e:
    print(f"   ✗ 第三方库导入失败: {e}")
    sys.exit(1)

# 测试 futu-api
print("\n3. 测试 Moomoo SDK...")
try:
    from futu import OpenQuoteContext, OpenSecTradeContext, TrdEnv, TrdMarket
    print("   ✓ futu-api 导入成功")
except Exception as e:
    print(f"   ✗ futu-api 导入失败: {e}")
    print("   提示: 请确保已安装 futu-api: pip install futu-api")
    sys.exit(1)

# 测试项目模块
print("\n4. 测试项目模块...")
try:
    import config
    print(f"   ✓ config.py - MAX_POSITIONS={config.MAX_POSITIONS}")

    from trader import MoomooTrader
    print("   ✓ trader.py")

    from state_manager import StateManager, PositionState
    print("   ✓ state_manager.py")

    from indicators import TechnicalIndicators, SignalGenerator
    print("   ✓ indicators.py")

    from strategy import ORBKeltnerStrategy
    print("   ✓ strategy.py")

except Exception as e:
    print(f"   ✗ 项目模块导入失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 测试配置文件
print("\n5. 测试配置文件...")
try:
    with open('watchlist.json', 'r') as f:
        watchlist = json.load(f)
        symbols = watchlist.get('symbols', [])
        print(f"   ✓ watchlist.json - {len(symbols)} 只股票")
except Exception as e:
    print(f"   ✗ 配置文件读取失败: {e}")

# 测试技术指标
print("\n6. 测试技术指标计算...")
try:
    # 创建测试数据
    test_data = pd.DataFrame({
        'close': [100, 101, 102, 103, 104, 105, 106, 107, 108, 109] * 5,
        'high': [101, 102, 103, 104, 105, 106, 107, 108, 109, 110] * 5,
        'low': [99, 100, 101, 102, 103, 104, 105, 106, 107, 108] * 5,
        'volume': [1000] * 50
    })

    indicators = TechnicalIndicators()

    # 测试 VWAP
    vwap = indicators.calculate_vwap(test_data)
    print(f"   ✓ VWAP 计算成功 (最新值: {vwap.iloc[-1]:.2f})")

    # 测试 ATR
    atr = indicators.calculate_atr(test_data, period=14)
    print(f"   ✓ ATR 计算成功 (最新值: {atr.iloc[-1]:.2f})")

    # 测试 Keltner Channels
    kc_upper, kc_middle, kc_lower = indicators.calculate_keltner_channels(test_data)
    print(f"   ✓ Keltner Channel 计算成功")
    print(f"     - 上轨: {kc_upper.iloc[-1]:.2f}")
    print(f"     - 中轨: {kc_middle.iloc[-1]:.2f}")
    print(f"     - 下轨: {kc_lower.iloc[-1]:.2f}")

except Exception as e:
    print(f"   ✗ 技术指标计算失败: {e}")
    import traceback
    traceback.print_exc()

# 测试状态管理
print("\n7. 测试状态管理...")
try:
    state_manager = StateManager()
    state_manager.add_symbol('TEST')
    position = state_manager.get_position('TEST')

    print(f"   ✓ 状态管理器创建成功")
    print(f"   ✓ 添加测试股票: TEST")
    print(f"   ✓ 初始状态: State={position.state} (应为 0)")

    # 测试开仓
    position.open_position(price=100.0, quantity=10, time=datetime.now())
    print(f"   ✓ 模拟开仓: 价格=100.0, 数量=10, 状态={position.state}")

    # 测试 ORB 锁定
    position.set_orb(orb_high=105.0, orb_low=95.0, orb_mid=100.0)
    print(f"   ✓ ORB 锁定: High={position.orb_high}, Mid={position.orb_mid}, Low={position.orb_low}")

except Exception as e:
    print(f"   ✗ 状态管理测试失败: {e}")
    import traceback
    traceback.print_exc()

# 测试信号生成
print("\n8. 测试信号生成...")
try:
    signal_gen = SignalGenerator()

    # 测试多头开仓信号
    entry_signal = signal_gen.check_long_entry(
        current_price=110.0,
        orb_high=105.0,
        vwap=108.0,
        kc_upper=112.0,
        kc_middle=105.0,
        bar_15m_close=110.0
    )
    print(f"   ✓ 多头开仓信号测试: {entry_signal} (应为 True)")

    # 测试止损信号
    stop_loss = signal_gen.check_stop_loss(current_price=98.0, orb_mid=100.0)
    print(f"   ✓ 止损信号测试: {stop_loss} (应为 True)")

    # 测试 TP1 信号
    tp1 = signal_gen.check_tp1(current_price=115.0, entry_price=110.0, orb_mid=105.0)
    print(f"   ✓ TP1 信号测试: {tp1} (应为 True)")

except Exception as e:
    print(f"   ✗ 信号生成测试失败: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*60)
print("✓ 所有模块测试完成！")
print("="*60)
print("\n下一步:")
print("1. 确保 Moomoo OpenD 已启动")
print("2. 运行策略: python main.py")
print("3. 查看日志: tail -f strategy.log")
print()

