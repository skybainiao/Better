import requests
import json

def test_send_alert_bet():
    """
    模拟发送 (alert + bet) 数据到 Java 的 /store-alert-bet 接口。
    你可以直接运行此脚本来测试。
    """

    # 1) 构造 alert dict
    alert_dict = {
        "eventId": 123456,
        "betTypeName": "SPREAD_FT_-0.75",
        "oddsName": "HomeOdds",
        "leagueName": "England - Premier League",
        "homeTeam": "Manchester City",
        "awayTeam": "Chelsea",
        "matchType": "normal",
        "oldValue": 0.55,
        "newValue": 0.62,
        "diffPoints": 7.0,
        "timeWindow": 10,
        "historySeries": "[0.55,0.57,0.62]",
        "homeScore": 1,
        "awayScore": 0,
        "signalScore": 0.78  # 多因子打分
        # alertTime 让Java端自动生成
    }

    # 2) 构造 bet dict
    bet_dict = {
        "menutype": "FT HDP",          # 示意：全场让球
        "score": "1-0(45')",          # 可能是场上比分
        "league": "England - Premier League",
        "homeTeam": "Manchester City",
        "awayTeam": "Chelsea",
        "choseTeam": "Manchester City",
        "choseCon": "-0.75",
        "ior": "0.62",
        "stake": "100",
        "winGold": "80",
        "tid": "TID123ABC",
        "statusText": "Bet Accepted",
        "username": "GA1A711D00"      # 假定使用此账号
        # timestamp 让Java端自动生成
    }

    # 3) 合并
    combined_data = {
        "alert": alert_dict,
        "bet": bet_dict
    }

    # 4) 发送请求
    post_url = "http://localhost:8080/api/store-alert-bet"

    try:
        response = requests.post(post_url, json=combined_data, timeout=5)
        if response.status_code == 200:
            print("成功将alert+bet一起发送到Java服务器(/store-alert-bet)。")
            print("服务器返回:", response.text)
        else:
            print(f"发送失败: 状态码={response.status_code}, 内容={response.text}")
    except Exception as e:
        print(f"请求时发生异常: {e}")


if __name__ == "__main__":
    test_send_alert_bet()
