#!/bin/bash
# 项目环境初始化脚本

echo "================================"
echo "ORB + Keltner Channel 策略"
echo "环境初始化脚本"
echo "================================"

# 检查 Python 版本
echo "检查 Python 版本..."
python3 --version

# 创建虚拟环境
echo "创建虚拟环境..."
python3 -m venv venv

# 激活虚拟环境
echo "激活虚拟环境..."
source venv/bin/activate

# 升级 pip
echo "升级 pip..."
pip install --upgrade pip

# 安装依赖
echo "安装依赖包..."
pip install -r requirements.txt

echo ""
echo "================================"
echo "环境初始化完成！"
echo "================================"
echo ""
echo "使用说明："
echo "1. 确保 Moomoo OpenD 已启动（默认端口 11111）"
echo "2. 激活虚拟环境：source venv/bin/activate"
echo "3. 运行策略：python main.py"
echo "4. 停止策略：Ctrl+C"
echo ""
echo "配置文件："
echo "- config.py: 策略参数配置"
echo "- watchlist.json: 监控股票列表"
echo ""

