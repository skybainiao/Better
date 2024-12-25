# proxy_validator.py

import time
import random
from seleniumwire import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from urllib.parse import urlparse
import warnings
from urllib3.exceptions import InsecureRequestWarning
import traceback

# 忽略 InsecureRequestWarning（可选）
warnings.simplefilter('ignore', InsecureRequestWarning)

# 定义IP池，每个代理格式为 "protocol://username:password@host:port"
IP_POOL = {
    "http://user-spz4nq4hh5-ip-122.8.88.216:jX5ed7Etx32VtrzCm_@isp.visitxiangtan.com:10001": {"status": "active",
                                                                                              "failures": 0},
    "http://user-spz4nq4hh5-ip-122.8.86.139:jX5ed7Etx32VtrzCm_@isp.visitxiangtan.com:10002": {"status": "active",
                                                                                              "failures": 0},
    "http://user-spz4nq4hh5-ip-122.8.15.166:jX5ed7Etx32VtrzCm_@isp.visitxiangtan.com:10003": {"status": "active",
                                                                                              "failures": 0},
    "http://user-spz4nq4hh5-ip-122.8.87.234:jX5ed7Etx32VtrzCm_@isp.visitxiangtan.com:10004": {"status": "active",
                                                                                              "failures": 0},
    "http://user-spz4nq4hh5-ip-122.8.16.212:jX5ed7Etx32VtrzCm_@isp.visitxiangtan.com:10005": {"status": "active",
                                                                                              "failures": 0},
    "http://user-spz4nq4hh5-ip-122.8.83.60:jX5ed7Etx32VtrzCm_@isp.visitxiangtan.com:10006": {"status": "active",
                                                                                             "failures": 0},
    "http://user-spz4nq4hh5-ip-122.8.83.139:jX5ed7Etx32VtrzCm_@isp.visitxiangtan.com:10007": {"status": "active",
                                                                                              "failures": 0},
    "http://user-spz4nq4hh5-ip-122.8.87.216:jX5ed7Etx32VtrzCm_@isp.visitxiangtan.com:10008": {"status": "active",
                                                                                              "failures": 0},
    "http://user-spz4nq4hh5-ip-122.8.87.251:jX5ed7Etx32VtrzCm_@isp.visitxiangtan.com:10009": {"status": "active",
                                                                                              "failures": 0},
    "http://user-spz4nq4hh5-ip-122.8.16.227:jX5ed7Etx32VtrzCm_@isp.visitxiangtan.com:10010": {"status": "active",
                                                                                              "failures": 0}
}

# 用户代理列表
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Mozilla/5.0 (X11; Linux x86_64)",
    # 添加更多的User-Agent字符串
]

BASE_URL = 'https://123.108.119.156/'  # 登录页面的URL


def get_random_user_agent():
    return random.choice(USER_AGENTS)


def init_driver(proxy):
    seleniumwire_options = {}

    if proxy:
        # 解析代理URL
        parsed = urlparse(proxy)
        proxy_host = parsed.hostname
        proxy_port = parsed.port
        proxy_username = parsed.username
        proxy_password = parsed.password

        scheme = parsed.scheme.lower()
        if scheme not in ['http', 'https', 'socks5']:
            raise ValueError(f"Unsupported proxy scheme: {scheme}")

        seleniumwire_options['proxy'] = {
            scheme: f"{scheme}://{proxy_username}:{proxy_password}@{proxy_host}:{proxy_port}",
            'no_proxy': 'localhost,127.0.0.1'
        }

    chrome_options = Options()
    chrome_options.add_argument('--headless')  # 无头模式
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('--ignore-certificate-errors')
    chrome_options.add_argument('--allow-insecure-localhost')
    chrome_options.add_argument('--disable-extensions')
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)

    # 随机选择一个User-Agent
    user_agent = get_random_user_agent()
    chrome_options.add_argument(f'user-agent={user_agent}')

    try:
        driver = webdriver.Chrome(options=chrome_options, seleniumwire_options=seleniumwire_options)
    except Exception as e:
        print(f"Error initializing Chrome WebDriver with proxy {proxy}: {e}")
        return None

    # 隐藏 webdriver 属性，防止被网站检测到自动化工具
    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
        'source': '''
            Object.defineProperty(navigator, 'webdriver', {
              get: () => undefined
            })
        '''
    })
    return driver


def validate_proxy(proxy):
    driver = None
    try:
        driver = init_driver(proxy)
        if not driver:
            print(f"[失败] 代理 {proxy} 无法初始化 WebDriver。")
            return False

        driver.set_page_load_timeout(30)  # 设置页面加载超时时间
        driver.get(BASE_URL)

        wait = WebDriverWait(driver, 20)  # 等待最多20秒
        try:
            # 假设登录按钮的ID为 'btn_login'，根据实际情况调整
            login_button = wait.until(EC.presence_of_element_located((By.ID, 'btn_login')))
            if login_button:
                print(f"[成功] 代理 {proxy} 可用，找到登录按钮。")
                return True
            else:
                print(f"[失败] 代理 {proxy} 无法找到登录按钮。")
                return False
        except Exception:
            print(f"[失败] 代理 {proxy} 无法找到登录按钮。")
            return False

    except Exception as e:
        print(f"[错误] 代理 {proxy} 测试时发生异常: {e}")
        traceback.print_exc()
        return False
    finally:
        if driver:
            driver.quit()


def main():
    print("开始验证代理可用性...\n")
    valid_proxies = []
    for proxy, info in IP_POOL.items():
        print(f"验证代理: {proxy}")
        is_valid = validate_proxy(proxy)
        if is_valid:
            valid_proxies.append(proxy)
        else:
            print(f"代理 {proxy} 被封禁或不可用。\n")
        # 随机等待1到3秒，避免过于频繁的请求
        time.sleep(random.uniform(1, 3))

    print("\n验证完成。")
    if valid_proxies:
        print("以下代理可用:")
        for vp in valid_proxies:
            print(f"- {vp}")
    else:
        print("没有可用的代理。")


if __name__ == "__main__":
    main()
