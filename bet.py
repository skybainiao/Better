import json
import logging
import random
import threading
import time
import traceback
import warnings
from queue import Queue, Empty
from urllib.parse import urlparse

import requests
from flask import Flask, request, jsonify
from selenium.common.exceptions import (
    NoSuchElementException,
    ElementClickInterceptedException,
    TimeoutException,
    StaleElementReferenceException, ElementNotInteractableException
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from seleniumwire import webdriver  # 使用 seleniumwire 的 webdriver
from urllib3.exceptions import InsecureRequestWarning

logging.getLogger('werkzeug').setLevel(logging.ERROR)

# 在你的 Flask 应用里，添加一个 before_request 钩子即可：
allowed_ips = {"127.0.0.1", "188.180.86.74", "160.25.20.123", "160.25.20.134"}

# 用于跟踪抓取线程状态
thread_status = {}
status_lock = threading.Lock()
# 登录页面的 URL
BASE_URL = 'https://123.108.119.156/'
# 固定密码
FIXED_PASSWORD = 'dddd1111DD'

# 定义要抓取的市场类型及其对应的按钮ID
# 更新 MARKET_TYPES 字典，包含所有可能的 market_type 及其对应的按钮 ID
MARKET_TYPES = {
    # 角球的按钮ID
    'Full_Handicap': 'tab_rnou',  # 全场让分盘按钮ID
    'Full_OverUnder': 'tab_rnou',  # 全场大小球按钮ID
    'Full_Corners_Handicap': 'tab_cn',  # 全场角球让分盘按钮ID
    'Full_Corners_OverUnder': 'tab_cn',  # 全场角球大小球按钮ID
    'Half_Handicap': 'tab_rnou',  # 上半场让分盘按钮ID
    'Half_OverUnder': 'tab_rnou',  # 上半场大小球按钮ID
    'Half_Corners_Handicap': 'tab_cn',  # 上半场角球让分盘按钮ID
    'Half_Corners_OverUnder': 'tab_cn'  # 上半场角球大小球按钮ID
}
# 1. 创建一个字典来映射 market_type 到对应的 alert 队列
market_type_to_alert_queues = {}
market_type_to_next_queue_index = {}
# 创建Flask应用
app = Flask(__name__)

# 用于跟踪活跃的抓取线程
active_threads = []
thread_control_events = {}

# 忽略 InsecureRequestWarning（可选）
warnings.simplefilter('ignore', InsecureRequestWarning)

# 定义IP池，每个代理格式为 "protocol://username:password@host:port"
#IP_POOL = {
#   "http://user-spz4nq4hh5-ip-122.8.88.216:jX5ed7Etx32VtrzCm_@isp.visitxiangtan.com:10001": {"status": "active",
#                                                                                             "failures": 0},
#   "http://user-spz4nq4hh5-ip-122.8.86.139:jX5ed7Etx32VtrzCm_@isp.visitxiangtan.com:10002": {"status": "active",
#                                                                                             "failures": 0},
#"http://user-spz4nq4hh5-ip-122.8.15.166:jX5ed7Etx32VtrzCm_@isp.visitxiangtan.com:10003": {"status": "active",
#"failures": 0},
#   "http://user-spz4nq4hh5-ip-122.8.87.234:jX5ed7Etx32VtrzCm_@isp.visitxiangtan.com:10004": {"status": "active",
#                                                                                             "failures": 0},
#"http://user-spz4nq4hh5-ip-122.8.16.212:jX5ed7Etx32VtrzCm_@isp.visitxiangtan.com:10005": {"status": "active",
#"failures": 0},
#   "http://user-spz4nq4hh5-ip-122.8.83.60:jX5ed7Etx32VtrzCm_@isp.visitxiangtan.com:10006": {"status": "active",
#                                                                                            "failures": 0},
#   "http://user-spz4nq4hh5-ip-122.8.83.139:jX5ed7Etx32VtrzCm_@isp.visitxiangtan.com:10007": {"status": "active",
#                                                                                             "failures": 0},
#   "http://user-spz4nq4hh5-ip-122.8.87.216:jX5ed7Etx32VtrzCm_@isp.visitxiangtan.com:10008": {"status": "active",
#                                                                                             "failures": 0},
#   "http://user-spz4nq4hh5-ip-122.8.87.251:jX5ed7Etx32VtrzCm_@isp.visitxiangtan.com:10009": {"status": "active",
#                                                                                             "failures": 0},
#"http://user-spz4nq4hh5-ip-122.8.16.227:jX5ed7Etx32VtrzCm_@isp.visitxiangtan.com:10010": {"status": "active",
#"failures": 0}
#}
# 按顺序分配代理的相关变量
#proxy_list = list(IP_POOL.keys())
current_proxy_index = 0

# 创建一个队列来管理启动任务
scraper_queue = Queue()

scraper_info = {}

# 全局条件变量
scheduler_condition = threading.Condition()


def scheduler():
    while True:
        task = scraper_queue.get()
        if task is None:
            break  # 退出调度器
        account, market_type, scraper_id = task

        with scheduler_condition:
            # 等待前一个线程状态为“运行中”或“已停止”
            while any(status not in ["运行中", "已停止"] for status in thread_status.values()):
                scheduler_condition.wait()

            # 启动抓取线程
            start_scraper_thread(account, market_type, scraper_id)

        scraper_queue.task_done()


# 启动调度线程
scheduler_thread = threading.Thread(target=scheduler, daemon=True)
scheduler_thread.start()

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Mozilla/5.0 (X11; Linux x86_64)",
    # 添加更多的User-Agent字符串
]

# 在全局区域添加
category_status = {
    "全场让分盘客队涨水": "全场让分盘主队",
    "全场让分盘主队涨水": "全场让分盘客队",
    "半场让分盘客队涨水": "半场让分盘主队",
    "半场让分盘主队涨水": "半场让分盘客队",
    "全场大分盘涨水": "全场小分盘",
    "全场小分盘涨水": "全场大分盘",
    "半场大分盘涨水": "半场小分盘",
    "半场小分盘涨水": "半场大分盘"
}
category_lock = threading.Lock()


#def get_sequential_proxy():
#   global current_proxy_index
#  with status_lock:
#     if current_proxy_index >= len(proxy_list):
#        raise Exception("所有代理已被封禁或已使用完毕")
#   proxy = proxy_list[current_proxy_index]
#  current_proxy_index += 1
# IP_POOL[proxy]['status'] = 'used'  # 标记为已使用
#return proxy


#def get_new_proxy():
#   global current_proxy_index
#  with status_lock:
#     if current_proxy_index >= len(proxy_list):
#        print("没有可用的代理来重启线程")
#       return None
#  new_proxy = proxy_list[current_proxy_index]
# current_proxy_index += 1
#IP_POOL[new_proxy]['status'] = 'used'  # 标记为已使用
#return new_proxy


def init_driver(proxy=None):
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

        print(f"Configured {scheme.upper()} proxy: {proxy_username}@{proxy_host}:{proxy_port}")

    chrome_options = Options()
    # 如果需要无头模式，可以取消注释以下行
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('--ignore-certificate-errors')
    chrome_options.add_argument('--allow-insecure-localhost')
    chrome_options.add_argument('--disable-extensions')
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)

    # 随机选择一个User-Agent
    user_agent = random.choice(USER_AGENTS)
    chrome_options.add_argument(f'user-agent={user_agent}')

    try:
        driver = webdriver.Chrome(options=chrome_options, seleniumwire_options=seleniumwire_options)
    except Exception as e:
        print(f"Error initializing Chrome WebDriver: {e}")
        raise e

    # 隐藏 webdriver 属性，防止被网站检测到自动化工具
    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
        'source': '''
            Object.defineProperty(navigator, 'webdriver', {
              get: () => undefined
            })
        '''
    })
    return driver


def login(driver, username):
    """
    尝试使用给定账号 username 登录，并多次重试点击弹窗中的“NO”按钮。
    """
    global BASE_URL
    driver.get(BASE_URL)
    wait = WebDriverWait(driver, 150)
    try:
        # 1) 点击页面语言
        lang_field = wait.until(EC.visibility_of_element_located((By.ID, 'lang_en')))
        lang_field.click()

        # 2) 填写用户名和密码
        username_field = wait.until(EC.visibility_of_element_located((By.ID, 'usr')))
        password_field = wait.until(EC.visibility_of_element_located((By.ID, 'pwd')))
        username_field.clear()
        username_field.send_keys(username)
        password_field.clear()
        password_field.send_keys(FIXED_PASSWORD)

        # 3) 点击登录按钮
        login_button = wait.until(EC.element_to_be_clickable((By.ID, 'btn_login')))
        login_button.click()
        time.sleep(10)  # 等页面渲染一会儿，以便弹窗出现

        # 4) 多次重试点击“NO”按钮
        #    若弹窗没有出现或点不到，就循环重试几次
        for i in range(5):  # 最多重试5次
            try:
                no_button = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.ID, 'C_no_btn'))
                )
                no_button.click()
                print(f"{username} 已点击弹窗中的 'No' 按钮 (第 {i + 1} 次尝试)")
                time.sleep(1)  # 等待弹窗真正消失
            except (TimeoutException, ElementClickInterceptedException, ElementNotInteractableException):
                print(f"{username} 尝试点击 'No' 弹窗失败 (第 {i + 1} 次)，等待重试…")
                time.sleep(1)
                continue
            else:
                # 成功点击一次即可，无需再循环
                break

        # 5) 再检查是否页面被禁止
        if check_forbidden_page(driver):
            print(f"{username} 登录后被禁止访问")
            return False

        # 6) 等待导航到足球页面成功
        wait.until(EC.visibility_of_element_located((By.XPATH, '//div[span[text()="Soccer"]]')))
        print(f"{username} 登录成功")
        return True

    except Exception as e:
        print(f"{username} 登录失败或未找到滚球比赛: {e}")
        traceback.print_exc()
        return False


def check_forbidden_page(driver):
    try:
        page_source = driver.page_source
        if ('被禁止' in page_source) or ('FORBIDDEN' in page_source):
            return True
        return False
    except Exception as e:
        print(f"检查被封禁页面时出错: {e}")
        return False


def navigate_to_football(driver):
    wait = WebDriverWait(driver, 150)
    try:
        # 点击足球按钮
        football_button = wait.until(EC.element_to_be_clickable((By.XPATH, '//div[span[text()="Soccer"]]')))
        football_button.click()
        # 等待页面加载完成
        wait.until(EC.visibility_of_element_located((By.ID, 'div_show')))
        wait.until(EC.visibility_of_element_located((By.CLASS_NAME, 'btn_title_le')))
        print("导航到足球页面成功")
        return True
    except Exception as e:
        print(f"导航到足球页面失败: {e}")
        traceback.print_exc()
        return False


def run_scraper(account, market_type, scraper_id, proxy, alert_queue, login_ip):
    username = account['username']
    bet_amount = int(account.get('bet_amount', 50))
    stop_event = threading.Event()
    thread_control_events[scraper_id] = stop_event

    driver = None
    try:
        # 使用 login_ip 作为 BASE_URL
        global BASE_URL
        original_base_url = BASE_URL
        BASE_URL = f'https://{login_ip}/'

        driver = init_driver(proxy)
        time.sleep(2)
        with status_lock:
            thread_status[scraper_id] = "启动中"
            print(f"Scraper ID {scraper_id} 状态: 启动中 (BASE_URL: {BASE_URL})")

        if login(driver, username):
            if navigate_to_football(driver):

                # === 在这里启动状态监控线程 ===
                status_monitor_thread = threading.Thread(
                    target=monitor_page_status,
                    args=(driver, stop_event, scraper_id, market_type),
                    daemon=True
                )
                status_monitor_thread.start()

                monitor_thread = threading.Thread(target=popup_monitor, args=(driver, stop_event), daemon=True)
                monitor_thread.start()

                scroll_thread = threading.Thread(target=random_scroll, args=(driver, stop_event), daemon=True)
                scroll_thread.start()

                # —— 新增：保存子线程引用
                # 在启动子线程后：
                with status_lock:
                    scraper_info[scraper_id]["sub_threads"] = [
                        status_monitor_thread,
                        monitor_thread,
                        scroll_thread
                    ]

                with status_lock:
                    thread_status[scraper_id] = "运行中"
                    print(f"Scraper ID {scraper_id} 状态: 运行中 (BASE_URL: {BASE_URL})")

                # 通知调度器可以启动下一个账号
                with scheduler_condition:
                    scheduler_condition.notify_all()

                try:
                    button_id = MARKET_TYPES[market_type]
                    button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, button_id)))
                    button.click()
                    print(f"{username} 已点击市场类型按钮: {market_type} (BASE_URL: {BASE_URL})")

                    while not stop_event.is_set():
                        try:
                            alert = alert_queue.get(timeout=0.1)
                        except Empty:
                            continue

                        # --- 新增：如果此scraper当前不允许接Alert，则跳过 ---
                        with status_lock:
                            if not scraper_info[scraper_id].get("allow_alert", True):
                                alert_queue.task_done()
                                continue

                        print(username + f"接收到Alert: {alert}")
                        try:
                            match_type_in_alert = alert.get('match_type', '').strip().lower()
                            if match_type_in_alert == 'corner':
                                click_corner_odds(driver, alert, scraper_id, bet_amount)
                            elif match_type_in_alert == 'normal':
                                # 如果 alert 中包含 'market_category' 和 'market_status' 字段，则统一调用 click_odds_new
                                if alert.get('market_category') and alert.get('market_status'):
                                    click_odds_new(driver, alert, scraper_id, bet_amount)
                                else:
                                    # 否则按照原有逻辑判断是否为半场
                                    if '1H' in alert.get('bet_type_name', ''):
                                        click_odds_half(driver, alert, scraper_id, bet_amount)
                                    else:
                                        click_odds(driver, alert, scraper_id, bet_amount)
                            else:
                                print(f"未知的 match_type: {match_type_in_alert}")
                        except Exception as e:
                            print(f"处理Alert点击时出错: {e}")
                            traceback.print_exc()

                        alert_queue.task_done()

                except Exception as e:
                    print(f"{username} 处理市场类型按钮时出错: {e}")
                    traceback.print_exc()
                    with status_lock:
                        thread_status[scraper_id] = "已停止"
            else:
                with status_lock:
                    thread_status[scraper_id] = "已停止"
                    print(f"Scraper ID {scraper_id} 状态: 已停止 (BASE_URL: {BASE_URL})")
        else:
            with status_lock:
                thread_status[scraper_id] = "已停止"
                print(f"Scraper ID {scraper_id} 状态: 已停止 (BASE_URL: {BASE_URL})")

    except Exception as e:
        print(f"{username} 运行时发生错误: {e} (BASE_URL: {BASE_URL})")
        traceback.print_exc()
        with status_lock:
            thread_status[scraper_id] = "已停止"
    finally:
        if driver:
            driver.quit()
            print(f"{username} 已关闭浏览器 (BASE_URL: {BASE_URL})")
        BASE_URL = original_base_url
        with status_lock:
            if scraper_id in thread_control_events:
                del thread_control_events[scraper_id]
            thread_status[scraper_id] = "已停止"

        # 通知调度器可以启动下一个账号
        with scheduler_condition:
            scheduler_condition.notify_all()


# 修改 scraper_id 的生成方式
def start_scraper_thread(account, market_type, scraper_id=None, proxy=None):
    if not scraper_id:
        # 使用固定的 scraper_id
        scraper_id = f"{account['username']}_{market_type}"

    login_ip = account.get('login_ip')  # 获取登录 IP

    if not login_ip:
        print(f"账户 {account['username']} 没有指定登录 IP，无法启动抓取线程。")
        return

    with status_lock:
        thread_status[scraper_id] = "正在启动..."
        print(f"Scraper ID {scraper_id} 状态: 正在启动... (登录 IP: {login_ip})")

    # 确保 scraper_info 已经初始化
    with status_lock:
        if scraper_id not in scraper_info:
            bet_interval = float(account.get("bet_interval", 0))
            bet_amount = float(account.get("bet_amount", 50))  # 默认投注额为50
            # 若为角球盘口，加一个 allow_alert 标记
            is_corner = "Corners" in market_type  # 简单判断
            scraper_info[scraper_id] = {
                "username": account['username'],
                "bet_interval": bet_interval,
                "pause_until": 0,  # 初始可立即接单
                "bet_count": 0,  # 新增
                "last_bet_info": "",  # 新增
                "login_ip": login_ip,  # 新增
                "allow_alert": True if is_corner else True  # 可以根据需要初始化
            }

    # 以 (scraper_id, alert_queue) 方式存储
    alert_queue = Queue()

    with status_lock:
        if market_type not in market_type_to_alert_queues:
            market_type_to_alert_queues[market_type] = []
            market_type_to_next_queue_index[market_type] = 0

        # 将 (scraper_id, queue) 添加进列表
        market_type_to_alert_queues[market_type].append((scraper_id, alert_queue))

    scraper_thread = threading.Thread(
        target=run_scraper,
        args=(account, market_type, scraper_id, proxy, alert_queue, login_ip),  # 传递 login_ip
        daemon=True
    )
    scraper_thread.start()
    active_threads.append(scraper_thread)
    account['scraper_id'] = scraper_id


# 2. 定义一个函数来根据 alert 的信息映射到对应的 market_type
def map_alert_to_market_type(alert):
    bet_type_name = alert.get('bet_type_name', '')
    match_type = alert.get('match_type', '')

    if 'FT' in bet_type_name:
        period = 'Full'
    elif '1H' in bet_type_name:
        period = 'Half'
    else:
        period = None

    if bet_type_name.startswith('SPREAD'):
        bet_type = 'Handicap'
    elif bet_type_name.startswith('TOTAL_POINTS'):
        bet_type = 'OverUnder'
    else:
        bet_type = None

    # 是否为角球
    if match_type == 'corner':
        corner = 'Corners_'
    else:
        corner = ''

    if period and bet_type:
        return f"{period}_{corner}{bet_type}"
    else:
        return None


def click_odds(driver, alert, scraper_id, bet_amount):
    try:
        # 1) 从 alert 中提取必要数据
        league_name = alert.get('league_name', '').strip()
        home_team = alert.get('home_team', '').strip()
        away_team = alert.get('away_team', '').strip()
        bet_type_name = alert.get('bet_type_name', '').strip()
        odds_name = alert.get('odds_name', '').strip()

        # 2) 盘口映射表
        ratio_mapping = {
            '0.0': '0', '-0.25': '-0/0.5', '-0.5': '-0.5', '-0.75': '-0.5/1',
            '-1.0': '-1', '-1.25': '-1/1.5', '-1.5': '-1.5', '-1.75': '-1.5/2',
            '-2.0': '-2', '-2.25': '-2/2.5', '-2.5': '-2.5', '-2.75': '-2.5/3',
            '-3.0': '-3', '-3.25': '-3/3.5', '-3.5': '-3.5', '-3.75': '-3.5/4',
            '-4.0': '-4',
            '0.25': '0/0.5', '0.5': '0.5', '0.75': '0.5/1',
            '1.0': '1', '1.25': '1/1.5', '1.5': '1.5', '1.75': '1.5/2',
            '2.0': '2', '2.25': '2/2.5', '2.5': '2.5', '2.75': '2.5/3',
            '3.0': '3', '3.25': '3/3.5', '3.5': '3.5', '3.75': '3.5/4',
            '4.0': '4', '4.25': '4/4.5', '4.5': '4.5', '4.75': '4.5/5',
            '5.0': '5', '5.25': '5/5.5', '5.5': '5.5', '5.75': '5.5/6',
            '6.0': '6', '6.25': '6/6.5', '6.5': '6.5', '6.75': '6.5/7',
            '7.0': '7', '7.25': '7/7.5', '7.5': '7.5', '7.75': '7.5/8',
            '8.0': '8', '8.25': '8/8.5', '8.5': '8.5', '8.75': '8.5/9',
            '9.0': '9', '9.25': '9/9.5', '9.5': '9.5', '9.75': '9.5/10',
            '10.0': '10',
            '10.25': '10/10.5', '10.5': '10.5', '10.75': '10.5/11',
            '11.0': '11', '11.25': '11/11.5', '11.5': '11.5', '11.75': '11.5/12',
            '12.0': '12', '12.25': '12/12.5', '12.5': '12.5', '12.75': '12.5/13',
            '13.0': '13', '13.25': '13/13.5', '13.5': '13.5', '13.75': '13.5/14',
            '14.0': '14', '14.25': '14/14.5', '14.5': '14.5', '14.75': '14.5/15',
            '15.0': '15'
        }

        # 3) 解析 bet_type_name
        bet_type_parts = bet_type_name.split('_')
        if len(bet_type_parts) < 3:
            print(f"无法解析 bet_type_name: {bet_type_name}")
            return

        if bet_type_parts[0] == 'TOTAL' and bet_type_parts[1] == 'POINTS':
            if len(bet_type_parts) < 4:
                print(f"无法解析 bet_type_name: {bet_type_name}")
                return
            bet_type = 'TOTAL_POINTS'
            ratio = bet_type_parts[3]
        else:
            bet_type = bet_type_parts[0]  # SPREAD / ...
            ratio = bet_type_parts[2]

        # 4) 确定市场类型 + odds_type
        if bet_type == 'SPREAD':
            market_section = 'Handicap'
            if odds_name == 'HomeOdds':
                odds_type = 'Home'
            elif odds_name == 'AwayOdds':
                odds_type = 'Away'
            else:
                print(f"未知 odds_name: {odds_name}")
                return
        elif bet_type == 'TOTAL_POINTS':
            market_section = 'Goals O/U'
            odds_type = None
        else:
            print(f"忽略非处理盘口类型: {bet_type}")
            return

        # 5) 映射 ratio
        if ratio not in ratio_mapping:
            print(f"未定义的 ratio 映射: {bet_type}{ratio}")
            return
        mapped_ratio = ratio_mapping[ratio]
        ballhead_text = mapped_ratio  # 初始赋值

        # 让分盘补+号
        if market_section == 'Handicap':
            if ratio.startswith('-'):
                pass  # 负数，已带 -
            elif ratio == '0.0':
                pass  # 平手 => '0'
            else:
                # 正数 => 给 ballhead_text 补 "+"
                if not ballhead_text.startswith('-') and ballhead_text != '0':
                    ballhead_text = f"+{ballhead_text}"
        else:
            # 大小球盘 OverOdds / UnderOdds
            if odds_name == 'OverOdds':
                pass  # 你可定义 ballou_text='O'，再做其他操作
            elif odds_name == 'UnderOdds':
                pass
            else:
                print(f"未知的 odds_name: {odds_name}")
                return
            # 如果末尾是 '.0' =>去掉
            ballhead_text = ballhead_text.rstrip('.0') if ballhead_text.endswith('.0') else ballhead_text

        # 若末尾还有 '.0'
        if '.' in ballhead_text and '/' not in ballhead_text and ballhead_text.endswith('.0'):
            ballhead_text = ballhead_text[:-2]

        # 6) 查找联赛
        league_xpath = (
            f"//div[contains(@class, 'btn_title_le') "
            f"and .//tt[@id='lea_name' and text()='{league_name}']]"
        )
        league_elements = driver.find_elements(By.XPATH, league_xpath)
        print(f"联赛 '{league_name}' 找到 {len(league_elements)} 个元素(可能折叠/展开)")

        if not league_elements:
            print(f"未找到联赛: {league_name}")
            return

        # 用于判断是否最终找到并点击成功
        found_match = False

        # 7) 遍历联赛
        for league_element in league_elements:
            try:
                # 找到其所有比赛
                game_xpath = ".//following-sibling::div[starts-with(@id, 'game_') and contains(@class, 'box_lebet')]"
                game_elements = league_element.find_elements(By.XPATH, game_xpath)
                print(f"联赛 '{league_name}' 下找到 {len(game_elements)} 场比赛")

                for idx, game_element in enumerate(game_elements, start=1):
                    try:
                        game_id = game_element.get_attribute("id")
                        # 7.1 检查比赛是否折叠 => style="display:none"
                        style_value = (game_element.get_attribute("style") or "").replace(" ", "").lower()
                        if "display:none" in style_value:
                            # => 点击联赛名称进行展开
                            print(f"比赛 {idx} 折叠，点击联赛展开 -> {league_name}")
                            try:
                                driver.execute_script("arguments[0].scrollIntoView(true);", league_element)
                                league_element.click()
                                # 不等待
                            except Exception as e:
                                print(f"点击联赛展开时出错: {e}")
                                # 即使异常也继续后续查找

                        # 7.2 主客队
                        game_home = game_element.find_element(
                            By.XPATH, ".//div[contains(@class, 'teamH')]/span[contains(@class, 'text_team')]"
                        ).text.strip()
                        game_away = game_element.find_element(
                            By.XPATH, ".//div[contains(@class, 'teamC')]/span[contains(@class, 'text_team')]"
                        ).text.strip()
                        print(f"检查比赛 {idx}: {game_home} vs {game_away}")

                        if game_home == home_team and game_away == away_team:
                            print(f"找到目标比赛: {home_team} vs {away_team} (联赛: {league_name})")
                            found_match = True

                            # 再次用 game_id 定位
                            match_xpath = f"//div[@id='{game_id}']"
                            bet_section_xpath = (
                                f"{match_xpath}//div[contains(@class, 'form_lebet_hdpou') "
                                f"and .//span[text()='{market_section}']]"
                            )
                            try:
                                bet_section_element = driver.find_element(By.XPATH, bet_section_xpath)
                                print(f"找到盘口类型: {market_section}")
                            except NoSuchElementException:
                                print(f"未找到盘口: {market_section} in 比赛 {home_team} vs {away_team}")
                                continue

                            # 7.3 拼出赔率按钮 XPath
                            if market_section == 'Handicap':
                                if odds_type == 'Home':
                                    odds_button_xpath = (
                                        f"{match_xpath}//div[contains(@class, 'btn_hdpou_odd') "
                                        f"and contains(@id, '_REH') "
                                        f"and .//tt[@class='text_ballhead' and text()='{ballhead_text}']]"
                                    )
                                else:  # 'Away'
                                    odds_button_xpath = (
                                        f"{match_xpath}//div[contains(@class, 'btn_hdpou_odd') "
                                        f"and contains(@id, '_REC') "
                                        f"and .//tt[@class='text_ballhead' and text()='{ballhead_text}']]"
                                    )
                            else:
                                # Goals O/U
                                # OverOdds => text_ballou='O'
                                # UnderOdds => text_ballou='U'
                                if odds_name == 'OverOdds':
                                    odds_button_xpath = (
                                        f"{match_xpath}//div[contains(@class, 'btn_hdpou_odd') "
                                        f"and .//tt[@class='text_ballou' and text()='O'] "
                                        f"and .//tt[@class='text_ballhead' and text()='{ballhead_text}']]"
                                    )
                                else:
                                    odds_button_xpath = (
                                        f"{match_xpath}//div[contains(@class, 'btn_hdpou_odd') "
                                        f"and .//tt[@class='text_ballou' and text()='U'] "
                                        f"and .//tt[@class='text_ballhead' and text()='{ballhead_text}']]"
                                    )

                            # 在点击赔率按钮之前添加弹窗检测
                            try:
                                driver.find_element(By.ID, 'bet_show')
                                close_bet_popup(driver)
                                print("已关闭存在的投注弹窗。")
                            except NoSuchElementException:
                                pass  # 如果没有弹窗，则继续

                            # 7.4 多次重试点击
                            clicked_ok = False
                            for attempt in range(3):
                                try:
                                    odds_buttons = driver.find_elements(By.XPATH, odds_button_xpath)
                                    if not odds_buttons:
                                        print(f"[{attempt + 1}/3] 未找到赔率按钮 => {ballhead_text}, {odds_name}")
                                        time.sleep(0.5)
                                        continue

                                    odds_button = odds_buttons[0]
                                    driver.execute_script("arguments[0].scrollIntoView(true);", odds_button)
                                    WebDriverWait(driver, 5).until(
                                        EC.element_to_be_clickable(odds_button)
                                    ).click()

                                    print(
                                        f"点击成功: 联赛='{league_name}', 比赛='{home_team} vs {away_team}', "
                                        f"盘口='{market_section}', 比例='{ballhead_text}', 赔率='{odds_name}'"
                                    )
                                    # 新增: 处理弹窗，并传递 scraper_id 和 bet_amount
                                    handle_bet_popup(driver, scraper_id, bet_amount, alert)

                                    clicked_ok = True
                                    break
                                except Exception as e:
                                    print(f"点击失败({attempt + 1}/3): {e}")
                                    time.sleep(1)

                            if clicked_ok:
                                return  # 成功点击后立即 return
                            else:
                                print(f"连续3次点击仍失败 => {ballhead_text}, {odds_name}")
                                return

                    except (StaleElementReferenceException, NoSuchElementException) as e:
                        print(f"比赛 {idx} 解析时出错: {e}")
                        continue
            except StaleElementReferenceException as e:
                print(f"联赛元素失效: {e}")
                continue

        # 若走到这里还没 return，说明没点成功
        if not found_match:
            print(f"在联赛 '{league_name}' 中未找到比赛: {home_team} vs {away_team}")

    except Exception as e:
        print(f"点击赔率按钮失败: {e}")


def click_odds_new(driver, alert, scraper_id, bet_amount):
    """
    一个改进的点击赔率函数，既支持全场，也支持半场。
    直接借鉴了 click_odds / click_odds_half 在“展开联赛”上的做法，
    当检测到比赛行 style="display:none" 时就点击联赛元素展开。
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    import time

    try:
        # 1) 从 alert 中提取关键数据
        league_name = alert.get('league_name', '').strip()
        home_team = alert.get('home_team', '').strip()
        away_team = alert.get('away_team', '').strip()
        bet_type_name = alert.get('bet_type_name', '').strip()
        odds_name = alert.get('odds_name', '').strip()

        # 2) 判断是让分盘还是大小球 + 区分全场/半场
        if "SPREAD" in bet_type_name:  # 让分盘
            if "1H" in bet_type_name:  # 半场让分
                if odds_name == 'HomeOdds':
                    button_id_suffix = "_HREH"  # 半场让分 主队
                elif odds_name == 'AwayOdds':
                    button_id_suffix = "_HREC"  # 半场让分 客队
                else:
                    print(f"[click_odds_new] 无效 odds_name: {odds_name} (SPREAD_1H)")
                    return
                half_mode = True
            else:  # 全场让分
                if odds_name == 'HomeOdds':
                    button_id_suffix = "_REH"  # 全场让分 主队
                elif odds_name == 'AwayOdds':
                    button_id_suffix = "_REC"  # 全场让分 客队
                else:
                    print(f"[click_odds_new] 无效 odds_name: {odds_name} (SPREAD_FT)")
                    return
                half_mode = False

        elif "TOTAL_POINTS" in bet_type_name:  # 大小球
            if "1H" in bet_type_name:  # 半场大小
                if odds_name == 'OverOdds':
                    button_id_suffix = "_HROUC"  # 半场大球
                elif odds_name == 'UnderOdds':
                    button_id_suffix = "_HROUH"  # 半场小球
                else:
                    print(f"[click_odds_new] 无效 odds_name: {odds_name} (TOTAL_POINTS_1H)")
                    return
                half_mode = True
            else:  # 全场大小
                if odds_name == 'OverOdds':
                    button_id_suffix = "_ROUC"  # 全场大球
                elif odds_name == 'UnderOdds':
                    button_id_suffix = "_ROUH"  # 全场小球
                else:
                    print(f"[click_odds_new] 无效 odds_name: {odds_name} (TOTAL_POINTS_FT)")
                    return
                half_mode = False
        else:
            print(f"[click_odds_new] 未知盘口类型: {bet_type_name}")
            return

        # 3) 查找联赛: 以 league_name 匹配
        league_xpath = (
            f"//div[contains(@class, 'btn_title_le') "
            f" and .//tt[@id='lea_name' and text()='{league_name}']]"
        )
        league_elements = driver.find_elements(By.XPATH, league_xpath)
        if not league_elements:
            print(f"[click_odds_new] 未找到联赛: {league_name}")
            return
        print(f"[click_odds_new] 联赛 '{league_name}' 找到 {len(league_elements)} 个元素")

        found_match = False

        # 4) 遍历联赛元素
        for league_element in league_elements:
            try:
                # 找到其后的所有比赛行
                game_xpath = ".//following-sibling::div[starts-with(@id, 'game_') and contains(@class, 'box_lebet')]"
                game_elements = league_element.find_elements(By.XPATH, game_xpath)
                print(f"[click_odds_new] 联赛 '{league_name}' 下找到 {len(game_elements)} 场比赛")

                # 注意: league_element 本身可能也带有 style="display:none"，
                # 但通常是 "game_xxx" 那些才是真正表示单场比赛折叠。
                # 在 click_odds/click_odds_half 里就是对每个 game_element 判断 style。
                for idx, game_element in enumerate(game_elements, start=1):
                    try:
                        game_id = game_element.get_attribute("id")
                        style_value = (game_element.get_attribute("style") or "").replace(" ", "").lower()
                        # 如果这场比赛折叠 => 点击联赛展开
                        if "display:none" in style_value:
                            print(f"[click_odds_new] 比赛 {idx} 折叠，点击联赛展开 -> {league_name}")
                            try:
                                driver.execute_script("arguments[0].scrollIntoView(true);", league_element)
                                league_element.click()  # 照搬 click_odds 里的做法
                                time.sleep(0.5)  # 稍等页面反应
                            except Exception as e:
                                print(f"[click_odds_new] 点击联赛展开时出错: {e}")
                                # 即使失败也继续后面的逻辑

                            # 再次获取最新 style
                            style_value = (game_element.get_attribute("style") or "").replace(" ", "").lower()
                            if "display:none" in style_value:
                                print(f"[click_odds_new] 比赛 {idx} 依旧折叠，可能无法展开，跳过")
                                continue

                        # 取主客队
                        game_home = game_element.find_element(
                            By.XPATH, ".//div[contains(@class, 'teamH')]/span[contains(@class, 'text_team')]"
                        ).text.strip()
                        game_away = game_element.find_element(
                            By.XPATH, ".//div[contains(@class, 'teamC')]/span[contains(@class, 'text_team')]"
                        ).text.strip()

                        print(f"[click_odds_new] 检查比赛 {idx}: {game_home} vs {game_away}")

                        if game_home == home_team and game_away == away_team:
                            print(f"[click_odds_new] 找到目标比赛: {home_team} vs {away_team}")
                            found_match = True

                            # 如果需要半场 => 点击 1H 按钮
                            if half_mode:
                                numeric_id = game_id[5:] if game_id.startswith("game_") else game_id
                                right_info_id = f"right_info_{numeric_id}"
                                # 先判断是否已经是半场模式(是否出现 .hdpou_1h)
                                already_half = len(game_element.find_elements(
                                    By.CSS_SELECTOR, "div.form_lebet_hdpou.hdpou_1h"
                                )) > 0
                                if already_half:
                                    print("[1H] 已是半场模式, 无需点击 1H")
                                else:
                                    print("[1H] 需要切换到半场，尝试点击 1H 按钮...")
                                    try:
                                        right_info_el = driver.find_element(By.ID, right_info_id)
                                        half_btn_div = right_info_el.find_element(
                                            By.CSS_SELECTOR, "div.rnou_btn.rnou_btn_1H"
                                        )
                                        btn_class = half_btn_div.get_attribute("class") or ""
                                        if "off" in btn_class or "none" in btn_class:
                                            print(f"[1H] 半场按钮处于 off/none => 无法点击 => {numeric_id}")
                                            return

                                        driver.execute_script("arguments[0].scrollIntoView(true);", half_btn_div)
                                        WebDriverWait(driver, 5).until(
                                            EC.element_to_be_clickable(half_btn_div)
                                        ).click()
                                        time.sleep(1.0)

                                        # 再判断是否出现 hdpou_1h
                                        new_half = len(game_element.find_elements(
                                            By.CSS_SELECTOR, "div.form_lebet_hdpou.hdpou_1h"
                                        )) > 0
                                        if new_half:
                                            print("[1H] 切换成功 => 已出现 .hdpou_1h")
                                        else:
                                            print("[1H] 等待半场切换仍失败 => 放弃")
                                            return

                                    except Exception as e:
                                        print(f"[1H] 点击/定位 1H 按钮时出错: {e}")
                                        return

                            # 构造按钮 xpath
                            odds_button_xpath = (
                                f"//div[@id='{game_id}']"
                                f"//div[contains(@class, 'btn_hdpou_odd') and contains(@id, '{button_id_suffix}')]"
                            )

                            # 在点击前关闭弹窗
                            try:
                                driver.find_element(By.ID, 'bet_show')
                                close_bet_popup(driver)
                                print("[click_odds_new] 已关闭存在的投注弹窗。")
                            except:
                                pass

                            # 多次重试点击
                            clicked_ok = False
                            for attempt in range(3):
                                try:
                                    odds_buttons = driver.find_elements(By.XPATH, odds_button_xpath)
                                    if not odds_buttons:
                                        print(
                                            f"[click_odds_new] 第{attempt + 1}次，"
                                            f"未找到按钮 => {button_id_suffix}"
                                        )
                                        time.sleep(0.5)
                                        continue

                                    # 点击第一个
                                    btn = odds_buttons[0]
                                    driver.execute_script("arguments[0].scrollIntoView(true);", btn)
                                    WebDriverWait(driver, 5).until(
                                        EC.element_to_be_clickable(btn)
                                    ).click()

                                    print(f"[click_odds_new] 点击成功 => {button_id_suffix}")
                                    # 调用下注弹窗处理
                                    handle_bet_popup(driver, scraper_id, bet_amount, alert)
                                    clicked_ok = True
                                    break
                                except Exception as e:
                                    print(f"[click_odds_new] 第{attempt + 1}次点击失败: {e}")
                                    time.sleep(1)

                            if clicked_ok:
                                return  # 成功点击后直接return
                            else:
                                print(f"[click_odds_new] 多次点击失败 => {button_id_suffix}")
                                return

                    except Exception as e:
                        print(f"[click_odds_new] 比赛 {idx} 解析出错: {e}")
                        continue
            except Exception as e:
                print(f"[click_odds_new] 联赛元素解析异常: {e}")
                continue

        if not found_match:
            print(f"[click_odds_new] 未在联赛 '{league_name}' 中找到比赛: {home_team} vs {away_team}")

    except Exception as e:
        print(f"[click_odds_new] 出现异常: {e}")
        import traceback
        traceback.print_exc()


def click_odds_half(driver, alert, scraper_id, bet_amount):
    """
    点击半场赔率的函数（方法2: 通过检查是否已出现 hdpou_1h 判断是否需要点击 1H 按钮）：
    1) 从Alert获取联赛、主客队、盘口信息
    2) 找到比赛行(若折叠则展开)
    3) 如果页面未出现半场数据(div.form_lebet_hdpou.hdpou_1h)，则点击右侧1H按钮 => 等待半场切换
    4) 构造半场盘口xpath => 点击对应赔率
    5) 处理投注弹窗(如需)
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    import time

    try:
        # 1) 提取 Alert 信息
        league_name = alert.get('league_name', '').strip()
        home_team = alert.get('home_team', '').strip()
        away_team = alert.get('away_team', '').strip()
        bet_type_name = alert.get('bet_type_name', '').strip()
        odds_name = alert.get('odds_name', '').strip()

        # 2) 盘口映射表
        ratio_mapping = {
            '0.0': '0', '-0.25': '-0/0.5', '-0.5': '-0.5', '-0.75': '-0.5/1',
            '-1.0': '-1', '-1.25': '-1/1.5', '-1.5': '-1.5', '-1.75': '-1.5/2',
            '-2.0': '-2', '-2.25': '-2/2.5', '-2.5': '-2.5', '-2.75': '-2.5/3',
            '-3.0': '-3', '-3.25': '-3/3.5', '-3.5': '-3.5', '-3.75': '-3.5/4',
            '-4.0': '-4',
            '0.25': '0/0.5', '0.5': '0.5', '0.75': '0.5/1',
            '1.0': '1', '1.25': '1/1.5', '1.5': '1.5', '1.75': '1.5/2',
            '2.0': '2', '2.25': '2/2.5', '2.5': '2.5', '2.75': '2.5/3',
            '3.0': '3', '3.25': '3/3.5', '3.5': '3.5', '3.75': '3.5/4',
            '4.0': '4', '4.25': '4/4.5', '4.5': '4.5', '4.75': '4.5/5',
            '5.0': '5', '5.25': '5/5.5', '5.5': '5.5', '5.75': '5.5/6',
            '6.0': '6', '6.25': '6/6.5', '6.5': '6.5', '6.75': '6.5/7',
            '7.0': '7', '7.25': '7/7.5', '7.5': '7.5', '7.75': '7.5/8',
            '8.0': '8', '8.25': '8/8.5', '8.5': '8.5', '8.75': '8.5/9',
            '9.0': '9', '9.25': '9/9.5', '9.5': '9.5', '9.75': '9.5/10',
            '10.0': '10',
            '10.25': '10/10.5', '10.5': '10.5', '10.75': '10.5/11',
            '11.0': '11', '11.25': '11/11.5', '11.5': '11.5', '11.75': '11.5/12',
            '12.0': '12', '12.25': '12/12.5', '12.5': '12.5', '12.75': '12.5/13',
            '13.0': '13', '13.25': '13/13.5', '13.5': '13.5', '13.75': '13.5/14',
            '14.0': '14', '14.25': '14/14.5', '14.5': '14.5', '14.75': '14.5/15',
            '15.0': '15'
        }

        # 3) 解析 bet_type_name
        bet_type_parts = bet_type_name.split('_')
        if len(bet_type_parts) < 3:
            print(f"无法解析 bet_type_name: {bet_type_name}")
            return

        if bet_type_parts[0] == 'TOTAL' and bet_type_parts[1] == 'POINTS':
            # e.g. TOTAL_POINTS_1H_2.5
            if len(bet_type_parts) < 4:
                print(f"无法解析 bet_type_name: {bet_type_name}")
                return
            bet_type = 'TOTAL_POINTS'
            ratio = bet_type_parts[3]
        else:
            bet_type = bet_type_parts[0]  # SPREAD
            ratio = bet_type_parts[2]

        # 4) 根据 bet_type + odds_name，确定半场按钮后缀
        if bet_type == 'SPREAD':
            # "Handicap 1H" => '_HREH' 或 '_HREC'
            if odds_name == 'HomeOdds':
                half_odds_id = '_HREH'
            elif odds_name == 'AwayOdds':
                half_odds_id = '_HREC'
            else:
                print(f"未知 odds_name: {odds_name}")
                return
        elif bet_type == 'TOTAL_POINTS':
            # "Goals O/U 1H" => '_HROUC' 或 '_HROUH'
            if odds_name == 'OverOdds':
                half_odds_id = '_HROUC'
            elif odds_name == 'UnderOdds':
                half_odds_id = '_HROUH'
            else:
                print(f"未知 odds_name: {odds_name}")
                return
        else:
            print(f"忽略非处理盘口类型: {bet_type}")
            return

        # 5) 映射 ratio
        if ratio not in ratio_mapping:
            print(f"未定义的 ratio 映射: {bet_type}{ratio}")
            return
        ballhead_text = ratio_mapping[ratio]

        # 若为让球 => 可能补 + 号；大小球 => 去掉末尾.0
        if bet_type == 'SPREAD':
            if ratio.startswith('-'):
                pass
            elif ratio == '0.0':
                pass
            else:
                if not ballhead_text.startswith('-') and ballhead_text != '0':
                    ballhead_text = f"+{ballhead_text}"
        else:
            # 大小球
            ballhead_text = ballhead_text.rstrip('.0') if ballhead_text.endswith('.0') else ballhead_text

        if '.' in ballhead_text and '/' not in ballhead_text and ballhead_text.endswith('.0'):
            ballhead_text = ballhead_text[:-2]

        # 6) 查找联赛
        league_xpath = (
            f"//div[contains(@class, 'btn_title_le') "
            f"and .//tt[@id='lea_name' and text()='{league_name}']]"
        )
        league_elements = driver.find_elements(By.XPATH, league_xpath)
        print(f"联赛 '{league_name}' 找到 {len(league_elements)} 个元素(可能折叠/展开)")

        if not league_elements:
            print(f"未找到联赛: {league_name}")
            return

        found_match = False

        # 7) 遍历联赛
        for league_element in league_elements:
            try:
                # 找到其所有比赛
                game_xpath = ".//following-sibling::div[starts-with(@id, 'game_') and contains(@class, 'box_lebet')]"
                game_elements = league_element.find_elements(By.XPATH, game_xpath)
                print(f"联赛 '{league_name}' 下找到 {len(game_elements)} 场比赛")

                for idx, game_element in enumerate(game_elements, start=1):
                    try:
                        raw_game_id = game_element.get_attribute("id")  # e.g. "game_9052206"
                        style_value = (game_element.get_attribute("style") or "").replace(" ", "").lower()

                        # 若折叠 => 展开
                        if "display:none" in style_value:
                            print(f"比赛 {idx} 折叠，点击联赛展开 -> {league_name}")
                            try:
                                driver.execute_script("arguments[0].scrollIntoView(true);", league_element)
                                league_element.click()
                            except Exception as e:
                                print(f"点击联赛展开时出错: {e}")

                        # 提取主客队
                        game_home = game_element.find_element(
                            By.XPATH,
                            ".//div[contains(@class, 'teamH')]/span[contains(@class, 'text_team')]"
                        ).text.strip()
                        game_away = game_element.find_element(
                            By.XPATH,
                            ".//div[contains(@class, 'teamC')]/span[contains(@class, 'text_team')]"
                        ).text.strip()
                        print(f"检查比赛 {idx}: {game_home} vs {game_away}")

                        if game_home == home_team and game_away == away_team:
                            print(f"找到目标比赛: {home_team} vs {away_team} (联赛: {league_name})")
                            found_match = True

                            # ======= 先检查是否已经是半场模式: .hdpou_1h =======
                            # 若已出现 => 不再点击1H
                            already_half = len(game_element.find_elements(
                                By.CSS_SELECTOR, "div.form_lebet_hdpou.hdpou_1h"
                            )) > 0

                            if already_half:
                                print("[1H] 已是半场模式 (hdpou_1h 已出现)，无需点击1H按钮")
                            else:
                                # =========== 点击 1H 按钮 ============
                                numeric_id = raw_game_id[5:] if raw_game_id.startswith("game_") else raw_game_id
                                right_info_id = f"right_info_{numeric_id}"
                                try:
                                    right_info_el = driver.find_element(By.ID, right_info_id)
                                    half_btn_div = right_info_el.find_element(
                                        By.CSS_SELECTOR, "div.rnou_btn.rnou_btn_1H"
                                    )
                                    # off/none => 无法点击
                                    btn_class = half_btn_div.get_attribute("class") or ""
                                    if "off" in btn_class or "none" in btn_class:
                                        print(f"[1H] 半场按钮处于off/none状态 => 无法点击 => {numeric_id}")
                                        return

                                    driver.execute_script("arguments[0].scrollIntoView(true);", half_btn_div)
                                    WebDriverWait(driver, 5).until(
                                        EC.element_to_be_clickable(half_btn_div)
                                    ).click()
                                    print("[1H] 已点击1H按钮 => 等待切换到半场...")

                                    # 等待 .hdpou_1h 出现
                                    try:
                                        WebDriverWait(driver, 5).until(
                                            lambda d: len(d.find_elements(
                                                By.XPATH,
                                                f"//div[@id='{raw_game_id}']//div[contains(@class,'hdpou_1h')]"
                                            )) > 0
                                        )
                                        print("[1H] 检测到 hdpou_1h => 半场切换完成")
                                    except TimeoutException:
                                        print("[1H] 等待 .hdpou_1h 超时，可能切换失败")
                                        return

                                except Exception as e:
                                    print(f"[1H] 定位/点击 1H按钮时出错: {e}")
                                    return

                            # ============ 点击半场赔率按钮 =============
                            match_xpath = f"//div[@id='{raw_game_id}']"
                            half_odds_xpath = (
                                f"{match_xpath}//div[contains(@class, 'btn_hdpou_odd') "
                                f"and contains(@id, '{half_odds_id}') "
                                f"and .//tt[@class='text_ballhead' and text()='{ballhead_text}']]"
                            )

                            # 在点击赔率按钮之前添加弹窗检测
                            try:
                                driver.find_element(By.ID, 'bet_show')
                                close_bet_popup(driver)
                                print("已关闭存在的投注弹窗。")
                            except NoSuchElementException:
                                pass  # 如果没有弹窗，则继续

                            clicked_ok = False
                            for attempt in range(3):
                                try:
                                    half_odds_buttons = driver.find_elements(By.XPATH, half_odds_xpath)
                                    if not half_odds_buttons:
                                        print(f"[1H] [{attempt + 1}/3] 未找到半场赔率按钮 => {ballhead_text}")
                                        time.sleep(0.5)
                                        continue

                                    odds_button = half_odds_buttons[0]
                                    driver.execute_script("arguments[0].scrollIntoView(true);", odds_button)
                                    WebDriverWait(driver, 5).until(
                                        EC.element_to_be_clickable(odds_button)
                                    ).click()

                                    print(f"[1H] 点击成功 => 比例={ballhead_text}, odds={odds_name}")
                                    # 如需处理弹窗:
                                    handle_bet_popup(driver, scraper_id, bet_amount, alert)
                                    clicked_ok = True
                                    break
                                except Exception as e:
                                    print(f"[1H] 点击失败({attempt + 1}/3): {e}")
                                    time.sleep(1)

                            if clicked_ok:
                                return
                            else:
                                print(f"[1H] 连续3次点击仍失败 => {ballhead_text}, {odds_name}")
                                return

                    except (StaleElementReferenceException, NoSuchElementException) as e:
                        print(f"比赛 {idx} 解析时出错: {e}")
                        continue
            except StaleElementReferenceException as e:
                print(f"联赛元素失效: {e}")
                continue

        if not found_match:
            print(f"在联赛 '{league_name}' 中未找到比赛: {home_team} vs {away_team}")

    except Exception as e:
        print(f"点击半场赔率按钮失败: {e}")


def click_corner_odds(driver, alert, scraper_id, bet_amount):
    """
    修正后的角球点击逻辑，依据真实网页结构进行 XPath 定位：
      - 大类： 角球容器 => 父级 div[class*='bet_type_cn']
      - 子类： box_lebet_odd => <div class="head_lebet"><span>HDP</span> or <span>O/U</span>, [<tt>1H</tt>]>
      - 按钮 ID: 全场 => ROUC/ROUH/REH/REC, 半场 => HROUC/HROUH/HREH/HREC
    """
    try:
        league_name = alert.get('league_name', '').strip()
        home_team = alert.get('home_team', '').strip()
        away_team = alert.get('away_team', '').strip()
        bet_type_name = alert.get('bet_type_name', '').strip()
        odds_name = alert.get('odds_name', '').strip()

        # 角球 ratio 映射（示例）
        ratio_mapping = {
            '0.0': '0', '-0.25': '-0/0.5', '-0.5': '-0.5', '-0.75': '-0.5/1',
            '-1.0': '-1', '-1.25': '-1/1.5', '-1.5': '-1.5', '-1.75': '-1.5/2',
            '-2.0': '-2', '-2.25': '-2/2.5', '-2.5': '-2.5', '-2.75': '-2.5/3',
            '-3.0': '-3', '-3.25': '-3/3.5', '-3.5': '-3.5', '-3.75': '-3.5/4',
            '-4.0': '-4',
            '0.25': '0/0.5', '0.5': '0.5', '0.75': '0.5/1',
            '1.0': '1', '1.25': '1/1.5', '1.5': '1.5', '1.75': '1.5/2',
            '2.0': '2', '2.25': '2/2.5', '2.5': '2.5', '2.75': '2.5/3',
            '3.0': '3', '3.25': '3/3.5', '3.5': '3.5', '3.75': '3.5/4',
            '4.0': '4', '4.25': '4/4.5', '4.5': '4.5', '4.75': '4.5/5',
            '5.0': '5', '5.25': '5/5.5', '5.5': '5.5', '5.75': '5.5/6',
            '6.0': '6', '6.25': '6/6.5', '6.5': '6.5', '6.75': '6.5/7',
            '7.0': '7', '7.25': '7/7.5', '7.5': '7.5', '7.75': '7.5/8',
            '8.0': '8', '8.25': '8/8.5', '8.5': '8.5', '8.75': '8.5/9',
            '9.0': '9', '9.25': '9/9.5', '9.5': '9.5', '9.75': '9.5/10',
            '10.0': '10',
            '10.25': '10/10.5', '10.5': '10.5', '10.75': '10.5/11',
            '11.0': '11', '11.25': '11/11.5', '11.5': '11.5', '11.75': '11.5/12',
            '12.0': '12', '12.25': '12/12.5', '12.5': '12.5', '12.75': '12.5/13',
            '13.0': '13', '13.25': '13/13.5', '13.5': '13.5', '13.75': '13.5/14',
            '14.0': '14', '14.25': '14/14.5', '14.5': '14.5', '14.75': '14.5/15',
            '15.0': '15'
        }

        # period：全场('FT') or 半场('1H')
        if '1H' in bet_type_name:
            period = '1H'
        else:
            period = 'FT'

        # 确定让球或大小球
        # SPREAD => 让球(HDP)，TOTAL_POINTS => 大小球(O/U)
        if bet_type_name.startswith('SPREAD'):
            is_handicap = True
        else:
            is_handicap = False  # TOTAL_POINTS or OVERUNDER => 大小球

        # 从 bet_type_name 获取 ratio (末尾部分)，例如 "SPREAD_FT_-0.5" => ratio = "-0.5"
        # 具体解析因项目而异，下例仅演示
        ratio = bet_type_name.split('_')[-1]
        mapped_ratio = ratio_mapping.get(ratio, ratio)

        # 根据 period + is_handicap, 推断按钮ID的后缀
        # 全场让球 => REH/REC, 全场大小 => ROUC/ROUH
        # 半场让球 => HREH/HREC, 半场大小 => HROUC/HROUH
        if period == 'FT':
            if is_handicap:
                # REH / REC
                if odds_name == 'HomeOdds':
                    target_id_part = 'REH'
                else:
                    target_id_part = 'REC'
                main_tag = 'HDP'
                half_tag = ''  # FT不出现<tt>1H</tt>
            else:
                # ROUC / ROUH
                if odds_name == 'OverOdds':
                    target_id_part = 'ROUC'
                else:
                    target_id_part = 'ROUH'
                main_tag = 'O/U'
                half_tag = ''
        else:
            # period == '1H'
            if is_handicap:
                # HREH / HREC
                if odds_name == 'HomeOdds':
                    target_id_part = 'HREH'
                else:
                    target_id_part = 'HREC'
                main_tag = 'HDP'
                half_tag = '1H'
            else:
                # HROUC / HROUH
                if odds_name == 'OverOdds':
                    target_id_part = 'HROUC'
                else:
                    target_id_part = 'HROUH'
                main_tag = 'O/U'
                half_tag = '1H'

        # 1) 查找联赛
        league_xpath = (
            f"//div[contains(@class, 'btn_title_le') "
            f" and .//tt[@id='lea_name' and text()='{league_name}']]"
        )
        league_elements = driver.find_elements(By.XPATH, league_xpath)
        if not league_elements:
            print(f"[Corner] 未找到联赛: {league_name}")
            return

        found_match = False

        for league_el in league_elements:
            # 找到紧随其后的比赛
            game_xpath = ".//following-sibling::div[starts-with(@id, 'game_') and contains(@class, 'box_lebet')]"
            games = league_el.find_elements(By.XPATH, game_xpath)
            for g_el in games:
                style_val = (g_el.get_attribute("style") or "").lower()
                if "display:none" in style_val:
                    # 若折叠，则尝试点击联赛展开
                    try:
                        league_el.click()
                    except:
                        pass

                # 判断主客队
                try:
                    game_home = g_el.find_element(By.XPATH, ".//div[contains(@class,'teamH')]/span").text.strip()
                    game_away = g_el.find_element(By.XPATH, ".//div[contains(@class,'teamC')]/span").text.strip()
                except:
                    continue

                if game_home == home_team and game_away == away_team:
                    print(f"[Corner] 匹配到比赛: {home_team} vs {away_team}")
                    found_match = True

                    # 2) 在此比赛下查找对应 box_lebet_odd
                    #   注意: 角球盘 often 在 parent div class="box_lebet bet_type_cn"
                    #   但每个具体盘口是 .box_lebet_odd
                    #   其中 <div class="head_lebet"><tt>1H</tt><span>O/U</span></div> (或 HDP)
                    #   所以我们匹配 half_tag + main_tag
                    #   half_tag 为空则不加, 不为空则必须出现 <tt>1H</tt>
                    if half_tag:
                        bet_section_xpath = (
                            f".//div[contains(@class, 'box_lebet_odd')]"
                            f"[.//div[contains(@class,'head_lebet')]"
                            f"[./tt[text()='{half_tag}'] and ./span[text()='{main_tag}']]]"
                        )
                    else:
                        bet_section_xpath = (
                            f".//div[contains(@class, 'box_lebet_odd')]"
                            f"[.//div[contains(@class,'head_lebet')]"
                            f"[./span[text()='{main_tag}']]]"
                        )

                    try:
                        bet_section_el = g_el.find_element(By.XPATH, bet_section_xpath)
                    except NoSuchElementException:
                        print(f"[Corner] 未找到对应盘口区: half_tag={half_tag}, main_tag={main_tag}")
                        return

                    # 3) 点击具体赔率按钮 => 根据 target_id_part, mapped_ratio
                    #   例如: //div[@id='bet_xxx_ROUC'][.//tt[text()='{mapped_ratio}']]
                    odds_btn_xpath = (
                        f".//div[contains(@class,'btn_lebet_odd') and contains(@id,'{target_id_part}')]"
                        f"[.//tt[@class='text_ballhead' and text()='{mapped_ratio}']]"
                    )
                    odds_btns = bet_section_el.find_elements(By.XPATH, odds_btn_xpath)
                    if not odds_btns:
                        print(f"[Corner] 找不到赔率按钮 => ratio={mapped_ratio}, id_part={target_id_part}")
                        return

                    # 在点击赔率按钮之前添加弹窗检测
                    try:
                        driver.find_element(By.ID, 'bet_show')
                        close_bet_popup(driver)
                        print("已关闭存在的投注弹窗。")
                    except NoSuchElementException:
                        pass  # 如果没有弹窗，则继续

                    clicked = False
                    for attempt in range(3):
                        try:
                            btn = odds_btns[0]
                            driver.execute_script("arguments[0].scrollIntoView(true);", btn)
                            WebDriverWait(driver, 5).until(EC.element_to_be_clickable(btn)).click()

                            print(f"[Corner] 点击成功 => ratio={mapped_ratio}, odds_name={odds_name}")
                            # 处理弹窗
                            handle_bet_popup(driver, scraper_id, bet_amount, alert)
                            clicked = True
                            break
                        except Exception as e:
                            print(f"[Corner] 第{attempt + 1}次点击失败: {e}")
                            time.sleep(1)

                    if clicked:
                        return
                    else:
                        print(f"[Corner] 多次点击失败 => ratio={mapped_ratio}, id_part={target_id_part}")
                        return
        if not found_match:
            print(f"[Corner] 联赛 {league_name} 下未匹配到比赛 {home_team} vs {away_team}")

    except Exception as e:
        print(f"[Corner] click_corner_odds 出错: {e}")


def handle_bet_popup(driver, scraper_id, bet_amount, alert):
    #print("弹窗")

    try:
        wait = WebDriverWait(driver, 15)

        # 1. 等待初始弹窗出现（输入金额的弹窗）
        popup = wait.until(EC.visibility_of_element_located((By.ID, 'bet_show')))
        print("初始弹窗已出现。")

        # 等待加载层 'info_loading' 消失
        try:
            wait.until(EC.invisibility_of_element_located((By.ID, 'info_loading')))
        except TimeoutException:
            pass  # 若未消失也继续

        # 1) 获取弹窗中显示的盘口文本对比赔率是否正确
        try:
            ratio_tt = popup.find_element(By.ID, 'bet_chose_con')
            popup_ratio_text = ratio_tt.text.strip()  # 例如 "5 / 5.5"
            # 去掉中间可能的空格，使得 "5 / 5.5" => "5/5.5"
            popup_ratio_clean = popup_ratio_text.replace(' ', '')
        except NoSuchElementException:
            print("未找到 bet_chose_con 元素，无法对比盘口，继续投注逻辑。")
            popup_ratio_clean = ""  # 找不到就给个空字符串

            # 2) 从 alert 中解析出原始 ratio，并用 ratio_mapping 转成弹窗格式
            #    假设 alert['bet_type_name'] 里类似 "SPREAD_FT_-0.75" 或 "TOTAL_POINTS_FT_5.25"
            #    需要先提取最后的数值部分（-0.75 / 5.25 等）
        ratio_mapping = {
            '0.0': '0', '-0.25': '-0/0.5', '-0.5': '-0.5', '-0.75': '-0.5/1',
            '-1.0': '-1', '-1.25': '-1/1.5', '-1.5': '-1.5', '-1.75': '-1.5/2',
            '-2.0': '-2', '-2.25': '-2/2.5', '-2.5': '-2.5', '-2.75': '-2.5/3',
            '-3.0': '-3', '-3.25': '-3/3.5', '-3.5': '-3.5', '-3.75': '-3.5/4',
            '-4.0': '-4',
            '0.25': '0/0.5', '0.5': '0.5', '0.75': '0.5/1',
            '1.0': '1', '1.25': '1/1.5', '1.5': '1.5', '1.75': '1.5/2',
            '2.0': '2', '2.25': '2/2.5', '2.5': '2.5', '2.75': '2.5/3',
            '3.0': '3', '3.25': '3/3.5', '3.5': '3.5', '3.75': '3.5/4',
            '4.0': '4', '4.25': '4/4.5', '4.5': '4.5', '4.75': '4.5/5',
            '5.0': '5', '5.25': '5/5.5', '5.5': '5.5', '5.75': '5.5/6',
            '6.0': '6', '6.25': '6/6.5', '6.5': '6.5', '6.75': '6.5/7',
            '7.0': '7', '7.25': '7/7.5', '7.5': '7.5', '7.75': '7.5/8',
            '8.0': '8', '8.25': '8/8.5', '8.5': '8.5', '8.75': '8.5/9',
            '9.0': '9', '9.25': '9/9.5', '9.5': '9.5', '9.75': '9.5/10',
            '10.0': '10',
            '10.25': '10/10.5', '10.5': '10.5', '10.75': '10.5/11',
            '11.0': '11', '11.25': '11/11.5', '11.5': '11.5', '11.75': '11.5/12',
            '12.0': '12', '12.25': '12/12.5', '12.5': '12.5', '12.75': '12.5/13',
            '13.0': '13', '13.25': '13/13.5', '13.5': '13.5', '13.75': '13.5/14',
            '14.0': '14', '14.25': '14/14.5', '14.5': '14.5', '14.75': '14.5/15',
            '15.0': '15'
        }

        alert_bet_type = alert.get('bet_type_name', '')  # "SPREAD_FT_5.25" 等
        # 拆分得到最后一个是 ratio_str
        ratio_str = alert_bet_type.split('_')[-1] if '_' in alert_bet_type else ''
        mapped_ratio = ratio_mapping.get(ratio_str, '')  # 转换成类似 "5/5.5" 形式

        # 去掉其中空格
        mapped_ratio_clean = mapped_ratio.replace(' ', '')

        # 3) 对比弹窗中的 ratio 是否与 alert 中一致
        if mapped_ratio_clean and popup_ratio_clean and (mapped_ratio_clean != popup_ratio_clean):
            print(f"弹窗盘口 {popup_ratio_clean} 与 Alert 盘口 {mapped_ratio_clean} 不一致，取消投注。")
            close_bet_popup(driver)  # 关闭弹窗
            return

        # 找到输入框 (PC优先)
        try:
            input_field = wait.until(EC.element_to_be_clickable((By.ID, 'bet_gold_pc')))
        except TimeoutException:
            try:
                input_field = wait.until(EC.element_to_be_clickable((By.ID, 'bet_gold')))
            except TimeoutException:
                print("未找到可用输入框，放弃。")
                return

        # 点击并输入金额
        input_field.click()
        input_field.clear()
        bet_amount_int = int(float(bet_amount))
        input_field.send_keys(str(bet_amount_int))
        print(f"已在初始弹窗中输入金额: {bet_amount_int}")

        # 2. 找到“PLACE BET”按钮并点击
        try:
            place_bet_button = wait.until(EC.element_to_be_clickable((By.ID, 'order_bet')))
            print("找到 PLACE BET 按钮。")
        except TimeoutException:
            print("找不到 PLACE BET 按钮，放弃。")
            return

        place_bet_button.click()
        print("已点击 PLACE BET 按钮，等待跳转到投注回执弹窗...")

        # 当成功点击 PLACE BET 后立即更新 bet_count
        with status_lock:
            if scraper_id in scraper_info:
                scraper_info[scraper_id]["bet_count"] += 1
                print(f"已增加 bet_count, 当前值: {scraper_info[scraper_id]['bet_count']}")

        # 3. 等待出现“receipt”弹窗
        #    用 bet_show 且 class 里包含 receipt
        try:
            receipt_popup = wait.until(
                EC.visibility_of_element_located(
                    (By.XPATH, "//div[@id='bet_show' and contains(@class,'receipt')]")
                )
            )
            print("已出现投注回执弹窗 (receipt)。")
        except TimeoutException:
            print("投注回执弹窗未出现，放弃。")
            return

        # 4. 在回执弹窗中提取信息
        try:
            menutype = receipt_popup.find_element(By.ID, 'bet_finish_menutype').text.strip()
            score = receipt_popup.find_element(By.ID, 'bet_finish_score').text.strip()
            league = receipt_popup.find_element(By.ID, 'bet_finish_league').text.strip()
            team_h = receipt_popup.find_element(By.ID, 'bet_finish_team_h').text.strip()
            team_c = receipt_popup.find_element(By.ID, 'bet_finish_team_c').text.strip()
            chose_team = receipt_popup.find_element(By.ID, 'bet_finish_chose_team').text.strip()
            chose_con = receipt_popup.find_element(By.ID, 'bet_finish_chose_con').text.strip()
            ior = receipt_popup.find_element(By.ID, 'bet_finish_ior').text.strip()
            stake = receipt_popup.find_element(By.ID, 'bet_finish_gold').text.strip()
            win_gold = receipt_popup.find_element(By.ID, 'bet_finish_win_gold').text.strip()
            tid = receipt_popup.find_element(By.ID, 'bet_finish_tid').text.strip()
            status_div = receipt_popup.find_element(By.ID, 'bet_finish_dg')
            status_text = status_div.text.strip() if status_div else ""

            print("=== 投注回执信息 ===")
            print(f"菜单类型: {menutype}")
            print(f"比分: {score}")
            print(f"联赛: {league}")
            print(f"主队: {team_h}")
            print(f"客队: {team_c}")
            print(f"投注队伍: {chose_team}")
            print(f"选择盘口: {chose_con}")
            print(f"赔率: {ior}")
            print(f"投注金额: {stake}")
            print(f"可赢金额: {win_gold}")
            print(f"注单号: {tid}")
            print(f"单据状态: {status_text}")
            print("==================")
        except NoSuchElementException:
            print("提取回执信息时出现问题。")

        # 5. 异步发送到 Java 服务器
        def send_to_java_alert_bet():
            username = scraper_info[scraper_id].get("username", "unknown")
            post_url = "http://localhost:8080/api/store-alert-bet"
            # 1) 组装 alert
            if alert is None:
                # 如果没有alert，就简单发bet
                # 但最好别出现这种情况
                alert_dict = {}
            else:
                # 譬如我们只提取一部分，也可直接用 alert.copy()
                alert_dict = {
                    "eventId": alert.get("event_id", 0),
                    "betTypeName": alert.get("bet_type_name", ""),
                    "oddsName": alert.get("odds_name", ""),
                    "leagueName": alert.get("league_name", ""),
                    "homeTeam": alert.get("home_team", ""),
                    "awayTeam": alert.get("away_team", ""),
                    "matchType": alert.get("match_type", ""),
                    "oldValue": float(alert.get("old_value", 0)),
                    "newValue": float(alert.get("new_value", 0)),
                    "diffPoints": float(alert.get("diff_points", 0)),
                    "timeWindow": int(alert.get("time_window", 0)),
                    "historySeries": alert.get("history_series", ""),
                    "homeScore": int(alert.get("home_score", 0)),
                    "awayScore": int(alert.get("away_score", 0)),
                    # 将score也发送
                    "signalScore": float(alert.get("score", 0)),
                    # alert_time 可以让Java端自动填，也可这里给
                }

            # 2) 组装 bet
            bet_dict = {
                "menutype": menutype,
                "score": score,
                "league": league,
                "homeTeam": team_h,
                "awayTeam": team_c,
                "choseTeam": chose_team,
                "choseCon": chose_con,
                "ior": ior,
                "stake": stake,
                "winGold": win_gold,
                "tid": tid,
                "statusText": status_text,
                "username": username
            }

            combined_data = {
                "alert": alert_dict,
                "bet": bet_dict
            }

            try:
                response = requests.post(post_url, json=combined_data, timeout=5)
                if response.status_code == 200:
                    print("成功将alert+bet一起发送到Java服务器( store-alert-bet )。")
                else:
                    print(f"发送到Java服务器失败，状态码: {response.status_code}, 内容:{response.text}")
            except Exception as e:
                print(f"发送到Java服务器时出错: {e}")

        threading.Thread(target=send_to_java_alert_bet, daemon=True).start()

        # 6. 点击“OK”按钮关闭弹窗
        try:
            ok_button = WebDriverWait(receipt_popup, 10).until(
                EC.element_to_be_clickable((By.ID, 'finishBtn_show'))
            )
            ok_button.click()
            print("已点击 OK 按钮，关闭回执弹窗。")
        except TimeoutException:
            print("未找到 OK 按钮，或点击失败。")

        # 7. 记录完整的投注回执信息
        with status_lock:
            if scraper_id in scraper_info:
                full_info = (
                    f"菜单类型: {menutype} | "
                    f"比分: {score} | "
                    f"联赛: {league} | "
                    f"主队: {team_h} | "
                    f"客队: {team_c} | "
                    f"投注队伍: {chose_team} | "
                    f"选择盘口: {chose_con} | "
                    f"赔率: {ior} | "
                    f"投注金额: {stake} | "
                    f"可赢金额: {win_gold} | "
                    f"注单号: {tid}"
                )
                scraper_info[scraper_id]["last_bet_info"] = full_info
                print("记录完整投注回执信息。")

    except Exception as e:
        print(f"处理投注流程时发生错误")
    finally:
        close_bet_popup(driver)


def check_malay_odds(old_val, new_val, min_odds, max_odds):
    """
    判断马来盘赔率是否符合要求：
      - 如果某个值是正数 => 它必须 >= min_odds
      - 如果某个值是负数 => 它必须 <= max_odds
      - 如果一个正一个负 => 正的必须>=min_odds，负的必须<=max_odds
      - 只要有任意值不满足 => return False
    """
    # old_val 检查
    if old_val >= 0:
        if old_val < min_odds:
            return False
    else:  # old_val < 0
        if old_val > max_odds:
            return False

    # new_val 检查
    if new_val >= 0:
        if new_val < min_odds:
            return False
    else:  # new_val < 0
        if new_val > max_odds:
            return False

    return True


def auto_close_popups(driver):
    """
    自动检测页面中常见的单按钮(OK)弹窗和强制登出弹窗，并点击对应的OK按钮。
    根据你的页面结构，这里列出了可能的OK按钮ID列表。
    """
    try:
        wait = WebDriverWait(driver, 2)  # 短等待时间检测
        ok_button_ids = [
            "ok_btn",  # 左侧单按钮弹窗
            "C_ok_btn",  # PC中间单按钮弹窗
            "C_ok_btn_system",  # 系统弹窗中的OK按钮
            "kick_ok_btn",  # 强制登出弹窗的OK按钮
            "message_ok",  # 吐司消息OK按钮
            "message_ok_bef"  # 登录前弹窗的OK按钮
        ]
        for btn_id in ok_button_ids:
            try:
                ok_button = wait.until(EC.element_to_be_clickable((By.ID, btn_id)))
                driver.execute_script("arguments[0].scrollIntoView(true);", ok_button)
                ok_button.click()
                print(f"[AUTO] 自动点击弹窗按钮: {btn_id}")
                # 点击后等待防止重复点击
                time.sleep(0.5)
            except TimeoutException:
                continue
    except Exception as e:
        print(f"[AUTO] 自动关闭弹窗时发生错误: {e}")


def popup_monitor(driver, stop_event):
    """
    后台监控线程，每隔1秒调用 auto_close_popups 检测并关闭弹窗，
    独立于主投注逻辑。
    """
    while not stop_event.is_set():
        auto_close_popups(driver)
        time.sleep(1)


def random_scroll(driver, stop_event):
    """
    每隔1-3秒随机滚动页面，模拟人类操作，防止会话长时间不活动。
    参数：
      - driver: 当前账号的 WebDriver 对象
      - stop_event: 用于控制退出的事件，当线程需要结束时设置该事件。
    """
    try:
        while not stop_event.is_set():
            # 获取页面当前高度
            scroll_height = driver.execute_script("return document.body.scrollHeight")
            # 生成一个随机滚动位置（0 ~ 页面高度）
            random_position = random.randint(0, scroll_height)
            driver.execute_script("window.scrollTo(0, arguments[0]);", random_position)
            #print(f"[Scroll] 随机滚动到位置：{random_position}")
            # 随机等待1~3秒后再滚动
            time.sleep(random.uniform(1, 3))
    except Exception as e:
        print(f"[Scroll] 随机滚动时出现异常: {e}")


def close_bet_popup(driver):
    """
    检测投注弹窗是否存在，如果存在则点击关闭按钮（id="order_close"），
    确保投注弹窗结束。该方法应在投注操作结束后调用。
    """
    try:
        # 设置等待时间，比如 5 秒
        wait = WebDriverWait(driver, 5)
        # 等待"order_close"按钮可点击
        close_button = wait.until(EC.element_to_be_clickable((By.ID, "order_close")))
        driver.execute_script("arguments[0].scrollIntoView(true);", close_button)
        close_button.click()
        print("[ClosePopup] 投注弹窗已自动关闭。")
        # 关闭后稍等以确保弹窗完全消失
        time.sleep(0.5)
    except TimeoutException:
        print("[ClosePopup] 未检测到投注弹窗关闭按钮。")
    except Exception as e:
        print(f"[ClosePopup] 关闭投注弹窗时出错: {e}")


def monitor_page_status(driver, stop_event, scraper_id, market_type):
    while not stop_event.is_set():
        time.sleep(120)  # 每2分钟检测一次
        try:
            found_soccer = element_exists(driver, "//span[text()='Soccer']")
            button_id = MARKET_TYPES[market_type]  # 正常盘口 => tab_rnou, 角球盘口 => tab_cn
            found_tab = element_exists(driver, f"//*[@id='{button_id}']")
        except Exception as e:
            print(f"[{scraper_id}] monitor_page_status 检测时出错: 退出监控线程。")
            break  # 出现异常则退出循环

        # 如果 Soccer 和对应按钮都消失，则尝试重新登录
        if not found_soccer and not found_tab:
            re_login(driver, scraper_id, market_type)
        else:
            # 针对角球盘口的特殊逻辑
            if "Corners" in market_type:
                if found_soccer and not found_tab:
                    with status_lock:
                        scraper_info[scraper_id]["allow_alert"] = False
                    print(f"[{scraper_id}] tab_cn消失, 角球账号暂停接收Alert.")
                elif found_soccer and found_tab:
                    with status_lock:
                        if not scraper_info[scraper_id].get("allow_alert", True):
                            try:
                                WebDriverWait(driver, 5).until(
                                    EC.element_to_be_clickable((By.ID, button_id))
                                ).click()
                            except Exception as e:
                                print(f"[{scraper_id}] monitor_page_status 点击 {button_id} 时出错: {e}")
                            scraper_info[scraper_id]["allow_alert"] = True
                    print(f"[{scraper_id}] 角球账号检测到tab_cn重新出现, 恢复接收Alert.")


def element_exists(driver, xpath):
    try:
        driver.find_element(By.XPATH, xpath)
        return True
    except NoSuchElementException:
        return False
    except Exception as e:
        print(f"[element_exists] 出现异常, xpath: {xpath}")
        return False


def re_login(driver, scraper_id, market_type):
    """
    刷新并重新登录该账号，保留bet_count等信息。
    """
    with status_lock:
        # 先保存旧的bet_count
        old_bet_count = scraper_info[scraper_id].get("bet_count", 0)

    # 刷新页面或直接get
    driver.get(BASE_URL)
    username = scraper_info[scraper_id]["username"]

    if login(driver, username):
        if navigate_to_football(driver):
            # 再点击对应market_type按钮
            try:
                button = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.ID, MARKET_TYPES[market_type]))
                )
                button.click()
            except:
                pass

            # 恢复 bet_count
            with status_lock:
                scraper_info[scraper_id]["bet_count"] = old_bet_count
            print(f"[{scraper_id}] 已重新登录并恢复 bet_count={old_bet_count}。")
        else:
            print(f"[{scraper_id}] 重新登录后无法 navigate_to_football。")
    else:
        print(f"[{scraper_id}] re_login 失败。")


def modify_alert_for_category(alert):
    #print("[DEBUG] modify_alert_for_category1 => new version loaded!")  # DEBUG

    if alert.get('match_type') != 'normal':
        return alert

    bet_type = alert.get('bet_type_name', '')
    odds_name = alert.get('odds_name', '')
    current_category = None

    # 1) 根据 bet_type_name + odds_name 区分大类别
    if bet_type.startswith("SPREAD_FT_"):
        if odds_name == "HomeOdds":
            current_category = "全场让分盘客队涨水"
        elif odds_name == "AwayOdds":
            current_category = "全场让分盘主队涨水"
    elif bet_type.startswith("SPREAD_1H_"):
        if odds_name == "HomeOdds":
            current_category = "半场让分盘客队涨水"
        elif odds_name == "AwayOdds":
            current_category = "半场让分盘主队涨水"
    elif bet_type.startswith("TOTAL_POINTS_FT_"):
        if odds_name == "UnderOdds":
            current_category = "全场大分盘涨水"
        elif odds_name == "OverOdds":
            current_category = "全场小分盘涨水"
    elif bet_type.startswith("TOTAL_POINTS_1H_"):
        if odds_name == "UnderOdds":
            current_category = "半场大分盘涨水"
        elif odds_name == "OverOdds":
            current_category = "半场小分盘涨水"

    if not current_category:
        return alert

    # 2) 取出全局状态
    with category_lock:
        current_status = category_status.get(current_category, "")

    # 3) 构造 "大字典"
    # [内容与之前一致，省略，这里只给出省略号...请保留你的once_replace和所有子状态定义]
    def once_replace(value: str, old: str, new: str):
        return value.replace(old, new, 1)

    target_categories = {
        "全场让分盘客队涨水": {
            # 1) "全场让分盘客队"
            "全场让分盘客队": {
                "odds_name_original": "HomeOdds",
                "odds_name_new": "AwayOdds",
                "modify_value": lambda x: -x if x != 0.0 else x,
                "change_period": None,
                # 合并底部逻辑 => 这条子状态无字符串替换 => None
                "edit_rule": None
            },
            # 2) "半场让分盘客队"
            "半场让分盘客队": {
                "odds_name_original": "HomeOdds",
                "odds_name_new": "AwayOdds",
                "modify_value": lambda x: -x if x != 0.0 else x,
                "change_period": "1H",
                "edit_rule": None
            },
            # 3) "半场让分盘主队"
            "半场让分盘主队": {
                "odds_name_original": None,
                "odds_name_new": None,
                "modify_value": None,
                "change_period": "1H",
                "edit_rule": None
            },
            # 4) "全场大分盘" => 原底部: "SPREAD"->"TOTAL_POINTS", odds->"OverOdds"
            "全场大分盘": {
                "odds_name_original": None,  # 无条件
                "odds_name_new": "OverOdds",
                "modify_value": None,
                "change_period": None,
                "edit_rule": lambda txt: once_replace(txt, "SPREAD", "TOTAL_POINTS")
            },
            # 5) "全场小分盘" => ...
            "全场小分盘": {
                "odds_name_original": None,
                "odds_name_new": "UnderOdds",
                "modify_value": None,
                "change_period": None,
                "edit_rule": lambda txt: once_replace(txt, "SPREAD", "TOTAL_POINTS")
            },
            # 6) "半场大分盘" => SPREAD->TOTAL_POINTS & FT->1H, odds->OverOdds
            "半场大分盘": {
                "odds_name_original": None,
                "odds_name_new": "OverOdds",
                "modify_value": None,
                "change_period": None,
                "edit_rule": lambda txt: once_replace(
                    once_replace(txt, "SPREAD", "TOTAL_POINTS"), "FT", "1H"
                )
            },
            # 7) "半场小分盘"
            "半场小分盘": {
                "odds_name_original": None,
                "odds_name_new": "UnderOdds",
                "modify_value": None,
                "change_period": None,
                "edit_rule": lambda txt: once_replace(
                    once_replace(txt, "SPREAD", "TOTAL_POINTS"), "FT", "1H"
                )
            },
        },
        "全场让分盘主队涨水": {
            # 1) 全场让分盘主队 (顶部逻辑)
            "全场让分盘主队": {
                "odds_name_original": "AwayOdds",
                "odds_name_new": "HomeOdds",
                "modify_value": lambda x: -x if x != 0.0 else x,
                "change_period": None,
                "edit_rule": None  # 不需要字符串替换
            },
            # 2) 半场让分盘主队 (顶部逻辑)
            "半场让分盘主队": {
                "odds_name_original": "AwayOdds",
                "odds_name_new": "HomeOdds",
                "modify_value": lambda x: -x if x != 0.0 else x,
                "change_period": "1H",
                "edit_rule": None
            },
            # 3) 半场让分盘客队 (顶部逻辑)
            "半场让分盘客队": {
                "odds_name_original": None,
                "odds_name_new": None,
                "modify_value": None,
                "change_period": "1H",
                "edit_rule": None
            },
            # 4) 全场大分盘 (底部逻辑: "SPREAD"→"TOTAL_POINTS", odds→"OverOdds")
            "全场大分盘": {
                "odds_name_original": None,
                "odds_name_new": "OverOdds",
                "modify_value": None,
                "change_period": None,
                "edit_rule": lambda txt: txt.replace("SPREAD", "TOTAL_POINTS", 1)
            },
            # 5) 全场小分盘 (底部逻辑: odds→"UnderOdds", "SPREAD"→"TOTAL_POINTS")
            "全场小分盘": {
                "odds_name_original": None,
                "odds_name_new": "UnderOdds",
                "modify_value": None,
                "change_period": None,
                "edit_rule": lambda txt: txt.replace("SPREAD", "TOTAL_POINTS", 1)
            },
            # 6) 半场大分盘 (底部逻辑: "SPREAD"→"TOTAL_POINTS" & "FT"→"1H", odds→"OverOdds")
            "半场大分盘": {
                "odds_name_original": None,
                "odds_name_new": "OverOdds",
                "modify_value": None,
                "change_period": None,
                "edit_rule": lambda txt: txt.replace("SPREAD", "TOTAL_POINTS", 1).replace("FT", "1H", 1)
            },
            # 7) 半场小分盘
            "半场小分盘": {
                "odds_name_original": None,
                "odds_name_new": "UnderOdds",
                "modify_value": None,
                "change_period": None,
                "edit_rule": lambda txt: txt.replace("SPREAD", "TOTAL_POINTS", 1).replace("FT", "1H", 1)
            }
        },
        "半场让分盘客队涨水": {
            # 1) 全场让分盘主队 (顶部逻辑)
            "全场让分盘主队": {
                "odds_name_original": None,
                "odds_name_new": None,
                "modify_value": None,
                "change_period": "FT",
                "edit_rule": None
            },
            # 2) 全场让分盘客队 (顶部逻辑)
            "全场让分盘客队": {
                "odds_name_original": "HomeOdds",
                "odds_name_new": "AwayOdds",
                "modify_value": lambda x: -x if x != 0.0 else x,
                "change_period": "FT",
                "edit_rule": None
            },
            # 3) 半场让分盘客队 (顶部逻辑)
            "半场让分盘客队": {
                "odds_name_original": "HomeOdds",
                "odds_name_new": "AwayOdds",
                "modify_value": lambda x: -x if x != 0.0 else x,
                "change_period": None,
                "edit_rule": None
            },
            # 4) 全场大分盘
            "全场大分盘": {
                "odds_name_original": None,
                "odds_name_new": "OverOdds",
                "modify_value": None,
                "change_period": None,
                "edit_rule": lambda txt: txt.replace("SPREAD", "TOTAL_POINTS", 1).replace("1H", "FT", 1)
            },
            # 5) 全场小分盘
            "全场小分盘": {
                "odds_name_original": None,
                "odds_name_new": "UnderOdds",
                "modify_value": None,
                "change_period": None,
                "edit_rule": lambda txt: txt.replace("SPREAD", "TOTAL_POINTS", 1).replace("1H", "FT", 1)
            },
            # 6) 半场大分盘
            "半场大分盘": {
                "odds_name_original": None,
                "odds_name_new": "OverOdds",
                "modify_value": None,
                "change_period": None,
                "edit_rule": lambda txt: txt.replace("SPREAD", "TOTAL_POINTS", 1)
            },
            # 7) 半场小分盘
            "半场小分盘": {
                "odds_name_original": None,
                "odds_name_new": "UnderOdds",
                "modify_value": None,
                "change_period": None,
                "edit_rule": lambda txt: txt.replace("SPREAD", "TOTAL_POINTS", 1)
            }
        },
        "半场让分盘主队涨水": {
            # 1) 全场让分盘主队 (顶部逻辑)
            "全场让分盘主队": {
                "odds_name_original": "AwayOdds",
                "odds_name_new": "HomeOdds",
                "modify_value": lambda x: -x if x != 0.0 else x,
                "change_period": "FT",
                "edit_rule": None
            },
            # 2) 全场让分盘客队 (顶部逻辑)
            "全场让分盘客队": {
                "odds_name_original": None,
                "odds_name_new": None,
                "modify_value": None,
                "change_period": "FT",
                "edit_rule": None
            },
            # 3) 半场让分盘主队 (顶部逻辑)
            "半场让分盘主队": {
                "odds_name_original": "AwayOdds",
                "odds_name_new": "HomeOdds",
                "modify_value": lambda x: -x if x != 0.0 else x,
                "change_period": None,
                "edit_rule": None
            },
            # 4) 全场大分盘
            "全场大分盘": {
                "odds_name_original": None,
                "odds_name_new": "OverOdds",
                "modify_value": None,
                "change_period": None,
                "edit_rule": lambda txt: txt.replace("SPREAD", "TOTAL_POINTS", 1).replace("1H", "FT", 1)
            },
            # 5) 全场小分盘
            "全场小分盘": {
                "odds_name_original": None,
                "odds_name_new": "UnderOdds",
                "modify_value": None,
                "change_period": None,
                "edit_rule": lambda txt: txt.replace("SPREAD", "TOTAL_POINTS", 1).replace("1H", "FT", 1)
            },
            # 6) 半场大分盘
            "半场大分盘": {
                "odds_name_original": None,
                "odds_name_new": "OverOdds",
                "modify_value": None,
                "change_period": None,
                "edit_rule": lambda txt: txt.replace("SPREAD", "TOTAL_POINTS", 1)
            },
            # 7) 半场小分盘
            "半场小分盘": {
                "odds_name_original": None,
                "odds_name_new": "UnderOdds",
                "modify_value": None,
                "change_period": None,
                "edit_rule": lambda txt: txt.replace("SPREAD", "TOTAL_POINTS", 1)
            }
        },
        "全场大分盘涨水": {
            # 1) 全场大分盘 (顶部逻辑)
            "全场大分盘": {
                "odds_name_original": "UnderOdds",
                "odds_name_new": "OverOdds",
                "modify_value": None,
                "change_period": None,
                "edit_rule": None
            },
            # 2) 半场大分盘 (顶部逻辑)
            "半场大分盘": {
                "odds_name_original": "UnderOdds",
                "odds_name_new": "OverOdds",
                "modify_value": None,
                "change_period": "1H",
                "edit_rule": None
            },
            # 3) 半场小分盘 (顶部逻辑)
            "半场小分盘": {
                "odds_name_original": None,
                "odds_name_new": None,
                "modify_value": None,
                "change_period": "1H",
                "edit_rule": None
            },

            # 4) 全场让分盘主队 (底部逻辑: "TOTAL_POINTS"→"SPREAD", odds→"HomeOdds")
            "全场让分盘主队": {
                "odds_name_original": None,
                "odds_name_new": "HomeOdds",
                "modify_value": None,
                "change_period": None,
                "edit_rule": lambda txt: txt.replace("TOTAL_POINTS", "SPREAD", 1)
            },
            # 5) 全场让分盘客队 (底部逻辑: odds→"AwayOdds")
            "全场让分盘客队": {
                "odds_name_original": None,
                "odds_name_new": "AwayOdds",
                "modify_value": None,
                "change_period": None,
                "edit_rule": lambda txt: txt.replace("TOTAL_POINTS", "SPREAD", 1)
            },
            # 6) 半场让分盘主队 (底部逻辑: "TOTAL_POINTS"→"SPREAD", "FT"→"1H", odds→"HomeOdds")
            "半场让分盘主队": {
                "odds_name_original": None,
                "odds_name_new": "HomeOdds",
                "modify_value": None,
                "change_period": None,
                "edit_rule": lambda txt: txt.replace(
                    "TOTAL_POINTS", "SPREAD", 1
                ).replace("FT", "1H", 1)
            },
            # 7) 半场让分盘客队
            "半场让分盘客队": {
                "odds_name_original": None,
                "odds_name_new": "AwayOdds",
                "modify_value": None,
                "change_period": None,
                "edit_rule": lambda txt: txt.replace(
                    "TOTAL_POINTS", "SPREAD", 1
                ).replace("FT", "1H", 1)
            }
        },
        "全场小分盘涨水": {
            # 1) 全场小分盘 (顶部逻辑)
            "全场小分盘": {
                "odds_name_original": "OverOdds",
                "odds_name_new": "UnderOdds",
                "modify_value": None,
                "change_period": None,
                "edit_rule": None
            },
            # 2) 半场大分盘 (顶部逻辑)
            "半场大分盘": {
                "odds_name_original": None,
                "odds_name_new": None,
                "modify_value": None,
                "change_period": "1H",
                "edit_rule": None
            },
            # 3) 半场小分盘 (顶部逻辑)
            "半场小分盘": {
                "odds_name_original": "OverOdds",
                "odds_name_new": "UnderOdds",
                "modify_value": None,
                "change_period": "1H",
                "edit_rule": None
            },

            # 4) 全场让分盘主队 (底部: "TOTAL_POINTS"→"SPREAD", odds→"HomeOdds")
            "全场让分盘主队": {
                "odds_name_original": None,
                "odds_name_new": "HomeOdds",
                "modify_value": None,
                "change_period": None,
                "edit_rule": lambda txt: txt.replace("TOTAL_POINTS", "SPREAD", 1)
            },
            # 5) 全场让分盘客队
            "全场让分盘客队": {
                "odds_name_original": None,
                "odds_name_new": "AwayOdds",
                "modify_value": None,
                "change_period": None,
                "edit_rule": lambda txt: txt.replace("TOTAL_POINTS", "SPREAD", 1)
            },
            # 6) 半场让分盘主队 ( "TOTAL_POINTS"→"SPREAD", "FT"→"1H", odds→"HomeOdds")
            "半场让分盘主队": {
                "odds_name_original": None,
                "odds_name_new": "HomeOdds",
                "modify_value": None,
                "change_period": None,
                "edit_rule": lambda txt: txt.replace("TOTAL_POINTS", "SPREAD", 1).replace("FT", "1H", 1)
            },
            # 7) 半场让分盘客队
            "半场让分盘客队": {
                "odds_name_original": None,
                "odds_name_new": "AwayOdds",
                "modify_value": None,
                "change_period": None,
                "edit_rule": lambda txt: txt.replace("TOTAL_POINTS", "SPREAD", 1).replace("FT", "1H", 1)
            }
        },
        "半场大分盘涨水": {
            # 1) 全场大分盘 (顶部逻辑)
            "全场大分盘": {
                "odds_name_original": "UnderOdds",
                "odds_name_new": "OverOdds",
                "modify_value": None,
                "change_period": "FT",
                "edit_rule": None
            },
            # 2) 半场大分盘
            "半场大分盘": {
                "odds_name_original": "UnderOdds",
                "odds_name_new": "OverOdds",
                "modify_value": None,
                "change_period": None,
                "edit_rule": None
            },
            # 3) 全场小分盘 (顶部类似)
            "全场小分盘": {
                "odds_name_original": None,
                "odds_name_new": None,
                "modify_value": None,
                "change_period": "FT",
                "edit_rule": None
            },

            # 4) 全场让分盘主队 (底部: "TOTAL_POINTS"->"SPREAD", "1H"->"FT", odds->"HomeOdds")
            "全场让分盘主队": {
                "odds_name_original": None,
                "odds_name_new": "HomeOdds",
                "modify_value": None,
                "change_period": None,
                "edit_rule": lambda txt: txt.replace("TOTAL_POINTS", "SPREAD", 1).replace("1H", "FT", 1)
            },
            # 5) 全场让分盘客队
            "全场让分盘客队": {
                "odds_name_original": None,
                "odds_name_new": "AwayOdds",
                "modify_value": None,
                "change_period": None,
                "edit_rule": lambda txt: txt.replace("TOTAL_POINTS", "SPREAD", 1).replace("1H", "FT", 1)
            },
            # 6) 半场让分盘主队
            "半场让分盘主队": {
                "odds_name_original": None,
                "odds_name_new": "HomeOdds",
                "modify_value": None,
                "change_period": None,
                "edit_rule": lambda txt: txt.replace("TOTAL_POINTS", "SPREAD", 1)
                # 如果还需 "FT"->"1H", 也可加
            },
            # 7) 半场让分盘客队
            "半场让分盘客队": {
                "odds_name_original": None,
                "odds_name_new": "AwayOdds",
                "modify_value": None,
                "change_period": None,
                "edit_rule": lambda txt: txt.replace("TOTAL_POINTS", "SPREAD", 1)
            }
        },
        "半场小分盘涨水": {
            # 1) 全场大分盘 / 全场小分盘 / 半场小分盘 (顶部类似)
            "全场大分盘": {
                "odds_name_original": None,
                "odds_name_new": None,
                "modify_value": None,
                "change_period": "FT",
                "edit_rule": None
            },
            "全场小分盘": {
                "odds_name_original": "OverOdds",
                "odds_name_new": "UnderOdds",
                "modify_value": None,
                "change_period": "FT",
                "edit_rule": None
            },
            "半场小分盘": {
                "odds_name_original": "OverOdds",
                "odds_name_new": "UnderOdds",
                "modify_value": None,
                "change_period": None,
                "edit_rule": None
            },

            # 4) 全场让分盘主队 (底部: "TOTAL_POINTS"->"SPREAD", "1H"->"FT", odds->"HomeOdds")
            "全场让分盘主队": {
                "odds_name_original": None,
                "odds_name_new": "HomeOdds",
                "modify_value": None,
                "change_period": None,
                "edit_rule": lambda txt: txt.replace("TOTAL_POINTS", "SPREAD", 1).replace("1H", "FT", 1)
            },
            # 5) 全场让分盘客队
            "全场让分盘客队": {
                "odds_name_original": None,
                "odds_name_new": "AwayOdds",
                "modify_value": None,
                "change_period": None,
                "edit_rule": lambda txt: txt.replace("TOTAL_POINTS", "SPREAD", 1).replace("1H", "FT", 1)
            },
            # 6) 半场让分盘主队
            "半场让分盘主队": {
                "odds_name_original": None,
                "odds_name_new": "HomeOdds",
                "modify_value": None,
                "change_period": None,
                "edit_rule": lambda txt: txt.replace("TOTAL_POINTS", "SPREAD", 1)
            },
            # 7) 半场让分盘客队
            "半场让分盘客队": {
                "odds_name_original": None,
                "odds_name_new": "AwayOdds",
                "modify_value": None,
                "change_period": None,
                "edit_rule": lambda txt: txt.replace("TOTAL_POINTS", "SPREAD", 1)
            }
        }
    }

    # 4) 找到 rule
    category_sub = target_categories.get(current_category, {})
    rule = category_sub.get(current_status)
    if not rule:
        return alert

    if rule["odds_name_original"] is not None and odds_name != rule["odds_name_original"]:
        return alert

    # 5) 执行一次修改
    try:
        # 1) 根据 "TOTAL_POINTS_" 还是 "SPREAD" 不同，拆分出 prefix / period / val_str
        parts = bet_type.split('_')

        if bet_type.startswith("TOTAL_POINTS_"):
            # => 期待 4 段，比如 ["TOTAL","POINTS","FT","2.5"]
            if len(parts) != 4:
                return alert  # 结构不对就直接返回
            prefix_part1, prefix_part2, period, val_str = parts
            prefix = prefix_part1 + "_" + prefix_part2  # => "TOTAL_POINTS"
        else:
            # => "SPREAD_FT_-0.5" 或 "SPREAD_1H_0.0"，只有 3 段
            if len(parts) != 3:
                return alert
            prefix, period, val_str = parts

        # 2) 解析数值
        val = float(val_str)
        modified = False

        # 3) 如果 value=0.0 且有取反 => 不取反
        if val == 0.0 and rule["modify_value"]:
            rule["modify_value"] = lambda x: x

        # (a) 数值取反
        if rule["modify_value"]:
            new_val = rule["modify_value"](val)
            if new_val != val:
                val = new_val
                modified = True

        # (b) change_period
        if rule["change_period"] and rule["change_period"] != period:
            period = rule["change_period"]
            modified = True

        # (c) 拼装 bet_type_name
        new_bet_type_name = f"{prefix}_{period}_{val}"

        # (d) 若有 edit_rule (字符串替换)
        if rule.get("edit_rule"):
            replaced = rule["edit_rule"](new_bet_type_name)
            if replaced != new_bet_type_name:
                new_bet_type_name = replaced
                modified = True

        # (e) 若 odds_name_new 不同也算修改
        if rule.get("odds_name_new"):
            if rule["odds_name_new"] != alert.get('odds_name'):
                modified = True

        # 最后若 modified=True => 写回 alert
        if modified:
            alert['bet_type_name'] = new_bet_type_name
            if rule["odds_name_new"]:
                alert['odds_name'] = rule["odds_name_new"]
            alert['market_category'] = current_category
            alert['market_status'] = current_status
            print(f"Alert 修改后: {alert}")

    except Exception as e:
        print(f"修改 alert 时出错: {e}")

    return alert


@app.before_request
def limit_remote_addr():
    client_ip = request.remote_addr
    if client_ip not in allowed_ips:
        return jsonify({'status': 'error', 'message': 'Forbidden IP'}), 403


# Flask路由
@app.route('/update_category', methods=['POST'])
def update_category():
    data = request.get_json()
    category = data.get('category')
    selected_option = data.get('selected_option')

    if category not in category_status:
        return jsonify({'status': 'error', 'message': 'Invalid category'}), 400

    with category_lock:
        category_status[category] = selected_option
        print(f"更新 {category} 状态为: {selected_option}")

    return jsonify({'status': 'success', 'message': f"{category} 更新成功"}), 200


@app.route('/get_category_status', methods=['GET'])
def get_category_status():
    with category_lock:
        return jsonify({'status': 'success', 'categories': category_status}), 200


@app.route('/receive_data', methods=['POST'])
def receive_data():
    data = request.get_json()
    print(data)
    if not data:
        return jsonify({'status': 'error', 'message': 'No JSON data received'}), 400

    # 根据需求修改alert
    modify_alert_for_category(data)

    # ============== 原有逻辑 ==============
    market_type = map_alert_to_market_type(data)
    if not market_type or market_type not in MARKET_TYPES:
        return jsonify({'status': 'error', 'message': 'Invalid or unmapped market_type'}), 400

    # 从 alert 中取旧值 / 新值
    try:
        old_val = float(data.get('old_value', 0))
        new_val = float(data.get('new_value', 0))
    except ValueError:
        return jsonify({'status': 'error', 'message': 'Invalid value format'}), 400

    with status_lock:
        queue_list = market_type_to_alert_queues.get(market_type, [])
        if not queue_list:
            return jsonify({'status': 'error', 'message': f"No scrapers for {market_type}"}), 200

        n = len(queue_list)
        valid_assigned = False
        now = time.time()

        for _ in range(n):
            # 轮询获取下一个 Scraper
            index = market_type_to_next_queue_index[market_type]
            scraper_id, alert_q = queue_list[index]
            market_type_to_next_queue_index[market_type] = (index + 1) % n

            info = scraper_info.get(scraper_id, {})
            pause_until = info.get("pause_until", 0)
            max_bets = info.get("max_bets", 0)
            current_count = info.get("bet_count", 0)

            # 1) 判断是否已达 max_bets
            if max_bets > 0 and current_count >= max_bets:
                # 跳过此账号，尝试下一个
                continue

            # 2) 判断是否处于暂停期
            if now < pause_until:
                # 说明此账号还在暂停期
                continue

            # 3) 读取当前账号的 min_odds / max_odds
            min_odds = float(info.get("min_odds", 0.2))
            max_odds = float(info.get("max_odds", -0.1))

            # 4) 检查赔率 (若不符合则继续尝试下一个)
            if not check_malay_odds(old_val, new_val, min_odds, max_odds):
                print(
                    f"[{scraper_id}] 赔率不符合 => old={old_val}, new={new_val}, min_odds={min_odds}, max_odds={max_odds}")
                continue

            # 如果符合 => 分配该 alert
            alert_q.put(data)
            scraper_info[scraper_id]["pause_until"] = now + info.get("bet_interval", 0)

            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Alert 分配给 {scraper_id}")
            valid_assigned = True
            break

        if not valid_assigned:
            # 若所有 Scraper 要么达 max_bets、要么在暂停期、或赔率不符 => 此条 alert 作废
            print(f"所有账号不可用(满bets/暂停/赔率不符), alert作废 => {data}")
            return jsonify({
                'status': 'error',
                'message': 'All scrapers unavailable (bets/full or paused or odds mismatch); alert discarded.'
            }), 200

    return jsonify({'status': 'success', 'message': 'Data received'}), 200


@app.route('/start_scraper', methods=['POST'])
def start_scraper_api():
    data = request.json
    print(f"接收到的数据: {data}")  # 添加这一行
    required_fields = ['username', 'market_type', 'min_odds', 'max_odds', 'max_bets', 'bet_interval',
                       'bet_amount', 'login_ip']  # 新增 'login_ip'
    if not all(field in data for field in required_fields):
        return jsonify({'status': 'error', 'message': '缺少必要字段'}), 400

    username = data['username']
    market_type = data['market_type']
    min_odds = data['min_odds']
    max_odds = data['max_odds']
    max_bets = data['max_bets']
    bet_interval = data['bet_interval']
    bet_amount = data['bet_amount']  # 已有
    login_ip = data['login_ip']  # 新增

    account = {
        'username': username,
        'min_odds': min_odds,
        'max_odds': max_odds,
        'max_bets': max_bets,
        'bet_interval': bet_interval,
        'bet_amount': bet_amount,
        'login_ip': login_ip  # 新增
    }

    scraper_id = f"{username}_{market_type}_{int(time.time())}"
    scraper_queue.put((account, market_type, scraper_id))
    print(f"已将 {username} - {market_type} 加入启动队列, Scraper ID: {scraper_id}")

    return jsonify({
        'status': 'success',
        'message': f"已将 {username} - {market_type} 加入启动队列",
        'scraper_id': scraper_id
    }), 200


@app.route('/stop_scraper', methods=['POST'])
def stop_scraper():
    data = request.get_json()
    if 'scraper_id' not in data:
        return jsonify({'status': 'error', 'message': '缺少 scraper_id'}), 400

    scraper_id = data['scraper_id']
    with status_lock:
        if scraper_id not in thread_status:
            return jsonify({'status': 'error', 'message': f"未找到 scraper_id: {scraper_id}"}), 404

    # 停止线程(但不清理数据)
    if scraper_id in thread_control_events:
        # 1) 设置 stop_event
        thread_control_events[scraper_id].set()
        del thread_control_events[scraper_id]

        print(f"Scraper ID {scraper_id} 收到停止指令。")

        # 2) 显式 join 子线程，确保它们都退出循环
        sub_threads = scraper_info.get(scraper_id, {}).get("sub_threads", [])
        for t in sub_threads:
            t.join(timeout=5)  # 最多等5秒，避免阻塞过久

        print(f"Scraper ID {scraper_id} 的后台子线程已全部退出。")

        # 3) 如果你想删除 sub_threads 引用，防止后续使用
        if "sub_threads" in scraper_info.get(scraper_id, {}):
            del scraper_info[scraper_id]["sub_threads"]

        # **新增：从 market_type_to_alert_queues 队列中删除该 scraper_id**
        for mtype, queue_list in market_type_to_alert_queues.items():
            market_type_to_alert_queues[mtype] = [
                (sid, alert_q) for (sid, alert_q) in queue_list if sid != scraper_id
            ]
            print(f"已从 {mtype} 队列中移除 Scraper ID: {scraper_id}")

        # **防止索引越界**
        for mtype in market_type_to_next_queue_index:
            if market_type_to_next_queue_index[mtype] >= len(market_type_to_alert_queues[mtype]):
                market_type_to_next_queue_index[mtype] = 0

        # 4) 更新状态为已停止
        with status_lock:
            thread_status[scraper_id] = "已停止"
        print(f"Scraper ID {scraper_id} 已停止 (主线程 + 子线程)，并从队列中移除。")

    else:
        print(f"Scraper ID {scraper_id} 未启动线程，跳过。")

    return jsonify({'status': 'success', 'message': f"已停止线程: {scraper_id}"}), 200


@app.route('/delete_scraper', methods=['POST'])
def delete_scraper():
    data = request.get_json()
    if 'scraper_id' not in data:
        return jsonify({'status': 'error', 'message': '缺少 scraper_id'}), 400

    scraper_id = data['scraper_id']
    with status_lock:
        if scraper_id not in thread_status:
            return jsonify({'status': 'error', 'message': f"未找到 scraper_id: {scraper_id}"}), 404

    # 1) 如果还在运行，就先停掉
    if scraper_id in thread_control_events:
        thread_control_events[scraper_id].set()
        del thread_control_events[scraper_id]
        print(f"Scraper ID {scraper_id} 收到停止指令（因为要删除）。")

        # 显式 join 子线程
        sub_threads = scraper_info.get(scraper_id, {}).get("sub_threads", [])
        for t in sub_threads:
            t.join(timeout=5)
        print(f"Scraper ID {scraper_id} 的后台子线程已全部退出。")

        # 清理子线程引用
        if "sub_threads" in scraper_info.get(scraper_id, {}):
            del scraper_info[scraper_id]["sub_threads"]

    # 2) 从 market_type_to_alert_queues 中删除 (scraper_id, alert_queue)，避免接收新的 alert
    for mtype, queue_list in market_type_to_alert_queues.items():
        new_list = []
        for (sid, alert_q) in queue_list:
            if sid != scraper_id:
                new_list.append((sid, alert_q))
            else:
                print(f"从 {mtype} 中移除队列: {scraper_id}")
        market_type_to_alert_queues[mtype] = new_list
        new_len = len(new_list)
        if market_type_to_next_queue_index[mtype] >= new_len:
            market_type_to_next_queue_index[mtype] = 0

    # 3) 删除 scraper_info
    if scraper_id in scraper_info:
        del scraper_info[scraper_id]
        print(f"已清理 scraper_info 中的数据: {scraper_id}")

    # 4) 删除 thread_status
    del thread_status[scraper_id]
    print(f"Scraper ID {scraper_id} 已删除所有数据 (包含子线程).")

    return jsonify({'status': 'success', 'message': f"已删除抓取线程: {scraper_id}"}), 200


@app.route('/get_status', methods=['GET'])
def get_status():
    statuses = []
    with status_lock:
        for s_id, st in thread_status.items():
            info = scraper_info.get(s_id, {})
            login_ip = info.get("login_ip", "")  # 从 scraper_info 获取 login_ip

            statuses.append({
                'scraper_id': s_id,
                'status': st,
                'bet_count': info.get('bet_count', 0),
                'last_bet_info': info.get('last_bet_info', ''),
                'login_ip': login_ip  # 新增
            })
    return jsonify({'status': 'success', 'active_threads': statuses}), 200


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5021)
