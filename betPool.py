from flask import Flask, request, jsonify
import requests
import json

app = Flask(__name__)
TARGET_URL = "http://103.67.53.34:5031/receive_signal"  # 目标URL（需实际可达）

@app.route('/proxy_bet_request', methods=['POST'])
def proxy_request():
    try:
        # 1. 强制解析客户端请求为JSON（处理可能的格式错误）
        client_data = request.get_json(force=True)  # 添加force=True处理非标准JSON
        if not client_data:
            return jsonify({"status": "error", "message": "客户端请求数据为空"}), 400

        # 2. **关键验证**：检查客户端是否传递sourceId（原JS代码要求sourceId=2）
        if client_data.get("alert", {}).get("source_id") != 2:
            return jsonify({
                "status": "error",
                "message": "目前仅支持sourceId=2的数据源"
            }), 400  # 直接在中间件拦截，模拟原JS验证逻辑

        # 3. 验证投注金额（模拟原JS的最小金额校验）
        bet_amount = client_data.get("bet_amount", 0.0)
        if bet_amount < 50:
            return jsonify({
                "status": "error",
                "message": "最小投注金额为50"
            }), 400

        # 4. 打印中间件日志（确认数据接收）
        print("中间件接收到客户端数据：")
        print(json.dumps(client_data, indent=2))

        # 5. 转发请求至目标URL（添加超时控制，避免假死）
        response = requests.post(
            TARGET_URL,
            headers={"Content-Type": "application/json"},
            json=client_data,  # 直接传递JSON数据（更简洁）
            timeout=10  # 设置超时时间
        )

        # 6. 透传目标服务器响应（包括非200状态码）
        try:
            result = response.json()  # 尝试解析JSON响应
        except json.JSONDecodeError:
            return jsonify({
                "status": "error",
                "message": "目标服务器返回非JSON数据"
            }), 500

        return jsonify(result), response.status_code  # 返回目标服务器的原始业务结果

    except requests.exceptions.RequestException as e:
        return jsonify({
            "status": "error",
            "message": f"网络请求失败：{str(e)}"
        }), 503


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
    print("中间件已启动，监听地址：http://localhost:5000/proxy_bet_request")