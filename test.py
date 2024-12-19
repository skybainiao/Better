import requests
from urllib.parse import urlparse
import warnings
from urllib3.exceptions import InsecureRequestWarning

# 忽略 InsecureRequestWarning（可选）
warnings.simplefilter('ignore', InsecureRequestWarning)

# 定义IP池，每个代理格式为 "protocol://username:password@host:port"
IP_POOL = [
    "http://user-spz4nq4hh5-ip-122.8.88.216:jX5ed7Etx32VtrzCm_@isp.visitxiangtan.com:10001",
    "http://user-spz4nq4hh5-ip-122.8.86.139:jX5ed7Etx32VtrzCm_@isp.visitxiangtan.com:10002",
    # 其他代理...
]

def test_proxy(proxy):
    url = 'https://ip.smartdaili-china.com/json'  # 目标URL
    parsed = urlparse(proxy)
    proxy_host = parsed.hostname
    proxy_port = parsed.port
    proxy_username = parsed.username
    proxy_password = parsed.password

    proxies = {
        'http': proxy,
        'https': proxy
    }

    try:
        response = requests.get(url, proxies=proxies, timeout=10, verify=False)  # verify=False跳过SSL验证
        print(f"代理 {proxy} 测试成功，状态码: {response.status_code}")
        print(response.text)
    except Exception as e:
        print(f"代理 {proxy} 测试失败: {e}")

for proxy in IP_POOL:
    test_proxy(proxy)
