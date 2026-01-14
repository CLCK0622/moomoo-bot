# backend/server.py
from flask import Flask, jsonify
from flask_cors import CORS
from dashboard import get_dashboard_data

app = Flask(__name__)
# 允许跨域，这样你的 Vue/React 前端才能访问
CORS(app)

@app.route('/api/dashboard', methods=['GET'])
def dashboard_api():
    """
    前端每 3 秒调用一次这个接口
    """
    try:
        # 调用 dashboard.py 里的逻辑获取最新数据
        data = get_dashboard_data()
        return jsonify({
            "status": "success",
            "data": data
        })
    except Exception as e:
        print(f"❌ Dashboard Error: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

if __name__ == '__main__':
    print("🚀 Dashboard API Server running on http://localhost:5001")
    # 建议使用 5001 端口，避免和 React/Vue 的 3000 端口冲突
    app.run(host='0.0.0.0', port=5001, debug=True)