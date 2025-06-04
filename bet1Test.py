import requests
import json

url = 'http://localhost:5031/receive_signal'

data = {
    "alert": {
        "league_name": "Brazil Serie B",
        "home_team": "Chapecoense SC",
        "away_team": "Amazonas AM",
        "bet_type_name": "TOTAL_POINTS_FT_2.25",#如果为让分盘，那么就是SPREAD-FT加上盘口值，如果是大小球，那就是TOTAL_POINTS_FT加上盘口值
        "odds_name": "OverOdds",
        "match_type": ""#默认为空字符
    },
    "bet_amount": 50
}

response = requests.post(url, json=data)
print(response.json())