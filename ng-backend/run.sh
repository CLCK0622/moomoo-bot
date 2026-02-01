#!/bin/bash
# 快速启动脚本 - 用于日常运行策略

echo "================================"
echo "ORB + Keltner Channel 策略启动"
echo "================================"
echo ""

# 检查虚拟环境是否存在
if [ ! -d "venv" ]; then
    echo "错误: 虚拟环境不存在，请先运行 ./setup.sh"
    exit 1
fi

# 检查 watchlist.json
if [ ! -f "watchlist.json" ]; then
    echo "错误: watchlist.json 不存在"
    exit 1
fi

echo "检查配置..."
echo "✓ 虚拟环境: venv/"
echo "✓ 配置文件: watchlist.json"
echo ""

# 提醒用户确保 OpenD 已启动
echo "⚠️  重要提醒："
echo "   1. 确保 Moomoo OpenD 已启动（127.0.0.1:11111）"
echo "   2. 当前使用 模拟盘 环境"
echo "   3. 日志文件: strategy.log"
echo ""

read -p "准备好了吗？按 Enter 继续，或 Ctrl+C 取消... "

echo ""
echo "激活虚拟环境并启动策略..."
echo ""

# 激活虚拟环境并运行主程序
source venv/bin/activate
python main.py

echo ""
echo "策略已停止"

