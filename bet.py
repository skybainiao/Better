import csv
import json
import random
import threading
import time
import traceback
import warnings
from queue import Queue, Empty
from urllib.parse import urlparse

from bs4 import BeautifulSoup
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
IP_POOL = {
    "http://user-spz4nq4hh5-ip-122.8.88.216:jX5ed7Etx32VtrzCm_@isp.visitxiangtan.com:10001": {"status": "active",
                                                                                              "failures": 0},
    "http://user-spz4nq4hh5-ip-122.8.86.139:jX5ed7Etx32VtrzCm_@isp.visitxiangtan.com:10002": {"status": "active",
                                                                                              "failures": 0},
    #"http://user-spz4nq4hh5-ip-122.8.15.166:jX5ed7Etx32VtrzCm_@isp.visitxiangtan.com:10003": {"status": "active",
    #"failures": 0},
    "http://user-spz4nq4hh5-ip-122.8.87.234:jX5ed7Etx32VtrzCm_@isp.visitxiangtan.com:10004": {"status": "active",
                                                                                              "failures": 0},
    #"http://user-spz4nq4hh5-ip-122.8.16.212:jX5ed7Etx32VtrzCm_@isp.visitxiangtan.com:10005": {"status": "active",
    #"failures": 0},
    "http://user-spz4nq4hh5-ip-122.8.83.60:jX5ed7Etx32VtrzCm_@isp.visitxiangtan.com:10006": {"status": "active",
                                                                                             "failures": 0},
    "http://user-spz4nq4hh5-ip-122.8.83.139:jX5ed7Etx32VtrzCm_@isp.visitxiangtan.com:10007": {"status": "active",
                                                                                              "failures": 0},
    "http://user-spz4nq4hh5-ip-122.8.87.216:jX5ed7Etx32VtrzCm_@isp.visitxiangtan.com:10008": {"status": "active",
                                                                                              "failures": 0},
    "http://user-spz4nq4hh5-ip-122.8.87.251:jX5ed7Etx32VtrzCm_@isp.visitxiangtan.com:10009": {"status": "active",
                                                                                              "failures": 0},
    #"http://user-spz4nq4hh5-ip-122.8.16.227:jX5ed7Etx32VtrzCm_@isp.visitxiangtan.com:10010": {"status": "active",
    #"failures": 0}
}
# 按顺序分配代理的相关变量
proxy_list = list(IP_POOL.keys())
current_proxy_index = 0

# 创建一个队列来管理启动任务
scraper_queue = Queue()


def scheduler():
    while True:
        task = scraper_queue.get()
        if task is None:
            break  # 退出调度器
        account, market_type, scraper_id = task
        # 启动抓取线程
        start_scraper_thread(account, market_type, scraper_id)
        # 随机等待3到5秒
        time.sleep(random.uniform(3, 5))
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


def get_sequential_proxy():
    global current_proxy_index
    with status_lock:
        if current_proxy_index >= len(proxy_list):
            raise Exception("所有代理已被封禁或已使用完毕")
        proxy = proxy_list[current_proxy_index]
        current_proxy_index += 1
        IP_POOL[proxy]['status'] = 'used'  # 标记为已使用
        return proxy


def get_new_proxy():
    global current_proxy_index
    with status_lock:
        if current_proxy_index >= len(proxy_list):
            print("没有可用的代理来重启线程")
            return None
        new_proxy = proxy_list[current_proxy_index]
        current_proxy_index += 1
        IP_POOL[new_proxy]['status'] = 'used'  # 标记为已使用
        return new_proxy


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
    # chrome_options.add_argument('--headless')
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
    driver.get(BASE_URL)
    wait = WebDriverWait(driver, 30)
    try:
        # 选择语言
        lang_field = wait.until(EC.visibility_of_element_located((By.ID, 'lang_en')))
        lang_field.click()
        # 输入用户名和密码
        username_field = wait.until(EC.visibility_of_element_located((By.ID, 'usr')))
        password_field = wait.until(EC.visibility_of_element_located((By.ID, 'pwd')))
        username_field.clear()
        username_field.send_keys(username)
        password_field.clear()
        password_field.send_keys(FIXED_PASSWORD)
        # 点击登录按钮
        login_button = wait.until(EC.element_to_be_clickable((By.ID, 'btn_login')))
        login_button.click()

        # 处理可能的弹窗，增加重试机制
        try:
            for _ in range(3):  # 尝试3次
                popup_wait = WebDriverWait(driver, 10)
                no_button = popup_wait.until(EC.element_to_be_clickable((By.ID, 'C_no_btn')))
                no_button.click()
                print(f"{username} 已点击弹窗中的 'No' 按钮")
                time.sleep(1)  # 等待弹窗消失
        except:
            pass  # 如果没有弹窗，继续执行

        # 检查是否登录成功或遇到被禁止页面
        if check_forbidden_page(driver):
            print(f"{username} 登录后被禁止访问")
            return False

        # 等待导航到足球页面
        wait.until(EC.visibility_of_element_located((By.XPATH, '//div[span[text()="Soccer"]]')))
        print(f"{username} 登录成功")
        return True
    except Exception as e:
        print(f"{username} 登录失败或未找到滚球比赛")
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
    wait = WebDriverWait(driver, 30)
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


def run_scraper(account, market_type, scraper_id, proxy, alert_queue):
    username = account['username']
    stop_event = threading.Event()
    thread_control_events[scraper_id] = stop_event

    driver = None
    try:
        driver = init_driver(proxy)
        time.sleep(2)

        with status_lock:
            thread_status[scraper_id] = "启动中"
            print(f"Scraper ID {scraper_id} 状态: 启动中 (代理: {proxy})")

        # 登录 + 导航
        if login(driver, username):
            if navigate_to_football(driver):
                with status_lock:
                    thread_status[scraper_id] = "运行中"
                    print(f"Scraper ID {scraper_id} 状态: 运行中 (代理: {proxy})")

                try:
                    # 点击对应的市场类型按钮 (让球 / 大小 / 角球 等)
                    button_id = MARKET_TYPES[market_type]
                    button = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.ID, button_id))
                    )
                    button.click()
                    print(f"{username} 已点击市场类型按钮: {market_type} (代理: {proxy})")

                    time.sleep(3)  # 等页面切换稳定

                    # 等待接收 alert，并调用点击函数
                    while not stop_event.is_set():
                        try:
                            alert = alert_queue.get(timeout=1)
                        except Empty:
                            continue

                        print(f"接收到Alert: {alert}")

                        # 根据 alert 中的 match_type 来决定用哪个点击函数
                        try:
                            match_type_in_alert = alert.get('match_type', '').strip().lower()
                            if match_type_in_alert == 'corner':
                                click_corner_odds(driver, alert)
                            elif match_type_in_alert == 'normal':
                                click_odds(driver, alert)
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
                    print(f"Scraper ID {scraper_id} 状态: 已停止 (代理: {proxy})")
        else:
            with status_lock:
                thread_status[scraper_id] = "已停止"
                print(f"Scraper ID {scraper_id} 状态: 已停止 (代理: {proxy})")

    except Exception as e:
        print(f"{username} 运行时发生错误: {e} (代理: {proxy})")
        traceback.print_exc()
        with status_lock:
            thread_status[scraper_id] = "已停止"
    finally:
        if driver:
            driver.quit()
            print(f"{username} 已关闭浏览器 (代理: {proxy})")

        with status_lock:
            if scraper_id in thread_control_events:
                del thread_control_events[scraper_id]


def start_scraper_thread(account, market_type, scraper_id=None, proxy=None):
    if not scraper_id:
        scraper_id = f"{account['username']}_{market_type}_{int(time.time())}"

    if not proxy:
        try:
            proxy = get_sequential_proxy()
        except Exception as e:
            print(f"无法获取代理: {e}")
            return

    with status_lock:
        thread_status[scraper_id] = "正在启动..."
        print(f"Scraper ID {scraper_id} 状态: 正在启动... (代理: {proxy})")

    alert_queue = Queue()

    with status_lock:
        # 初始化市场类型的队列列表和索引
        if market_type not in market_type_to_alert_queues:
            market_type_to_alert_queues[market_type] = []
            market_type_to_next_queue_index[market_type] = 0
        # 将新的 alert_queue 添加到对应市场类型的队列列表中
        market_type_to_alert_queues[market_type].append(alert_queue)

    scraper_thread = threading.Thread(
        target=run_scraper,
        args=(account, market_type, scraper_id, proxy, alert_queue),
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


def click_odds(driver, alert):
    try:
        # 提取并清洗 Alert 数据
        league_name = alert.get('league_name', '').strip()
        home_team = alert.get('home_team', '').strip()
        away_team = alert.get('away_team', '').strip()
        bet_type_name = alert.get('bet_type_name', '').strip()
        odds_name = alert.get('odds_name', '').strip()

        # 定义比例映射表
        ratio_mapping = {
            '0.0': '0', '-0.25': '-0/0.5', '-0.5': '-0.5', '-0.75': '-0.5/1',
            '-1.0': '-1', '-1.25': '-1/1.5', '-1.5': '-1.5', '-1.75': '-1.5/2',
            '-2.0': '-2', '-2.25': '-2/2.5', '-2.5': '-2.5', '-2.75': '-2.5/3',
            '-3.0': '-3', '-3.25': '-3/3.5', '-3.5': '-3.5', '-3.75': '-3.5/4',
            '-4.0': '-4',
            '0.25': '0.25', '0.5': '0.5', '0.75': '0.5/1',
            '1.0': '1', '1.25': '1/1.5', '1.5': '1.5', '1.75': '1.5/2',
            '2.0': '2', '2.25': '2/2.5', '2.5': '2.5', '2.75': '2.5/3',
            '3.0': '3', '3.25': '3/3.5', '3.5': '3.5', '3.75': '3.5/4',
            '4.0': '4',
            '4.25': '4/4.5', '4.5': '4.5', '4.75': '4.5/5',
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

        # 解析 bet_type_name
        bet_type_parts = bet_type_name.split('_')
        if len(bet_type_parts) < 3:
            print(f"无法解析 bet_type_name: {bet_type_name}")
            return

        if bet_type_parts[0] == 'TOTAL' and bet_type_parts[1] == 'POINTS':
            if len(bet_type_parts) < 4:
                print(f"无法解析 bet_type_name: {bet_type_name}")
                return
            bet_type = 'TOTAL_POINTS'
            ratio = bet_type_parts[3]  # 例如 '1.25'
        else:
            bet_type = bet_type_parts[0]  # 例如 'SPREAD'
            ratio = bet_type_parts[2]  # 例如 '0.25'

        # 确定盘口类型
        if bet_type == 'SPREAD':
            market_section = 'Handicap'
        elif bet_type == 'TOTAL_POINTS':
            market_section = 'Goals O/U'
        else:
            print(f"忽略非处理盘口类型: {bet_type}")
            return  # 只处理全场让分和全场大小球

        # 检查 ratio 是否在映射表中
        if ratio not in ratio_mapping:
            print(f"未定义的 ratio 映射: {bet_type}{ratio}")
            return
        mapped_ratio = ratio_mapping[ratio]

        # 处理赔率名称
        if market_section == 'Handicap':
            # 根据 odds_name 确定是 HomeOdds 还是 AwayOdds
            if odds_name == 'HomeOdds':
                odds_type = 'Home'
            elif odds_name == 'AwayOdds':
                odds_type = 'Away'
            else:
                print(f"未知的 odds_name: {odds_name}")
                return
            ballhead_text = mapped_ratio
        elif market_section == 'Goals O/U':
            if odds_name == 'OverOdds':
                ballou_text = 'O'
            elif odds_name == 'UnderOdds':
                ballou_text = 'U'
            else:
                print(f"未知的 odds_name: {odds_name}")
                return
            # 根据实际网页内容决定是否保留 '.0'
            ballhead_text = mapped_ratio.rstrip('.0') if mapped_ratio.endswith('.0') else mapped_ratio
        else:
            print(f"未知的 market_section: {market_section}")
            return

        # 清理盘口数值（根据实际需求调整）
        if '.' in ballhead_text and '/' not in ballhead_text:
            if ballhead_text.endswith('.0'):
                ballhead_text = ballhead_text[:-2]

        # 定位所有匹配的联赛元素
        league_xpath = f"//div[contains(@class, 'btn_title_le') and .//tt[@id='lea_name' and text()='{league_name}']]"
        league_elements = driver.find_elements(By.XPATH, league_xpath)
        print(f"联赛 '{league_name}' 找到 {len(league_elements)} 个元素")

        if not league_elements:
            print(f"未找到联赛: {league_name}")
            return

        # 遍历所有联赛元素，不论是否可见
        for league_index, league_element in enumerate(league_elements, start=1):
            try:
                # 查找所有比赛元素（id 以 'game_' 开头的 div）
                game_xpath = ".//following-sibling::div[starts-with(@id, 'game_') and contains(@class, 'box_lebet')]"
                game_elements = league_element.find_elements(By.XPATH, game_xpath)
                print(f"联赛 '{league_name}' 下找到 {len(game_elements)} 场比赛")

                for game_index, game_element in enumerate(game_elements, start=1):
                    try:
                        # 获取主队和客队名称
                        game_home_team = game_element.find_element(By.XPATH,
                                                                   ".//div[contains(@class, 'teamH')]/span[contains(@class, 'text_team')]").text.strip()
                        game_away_team = game_element.find_element(By.XPATH,
                                                                   ".//div[contains(@class, 'teamC')]/span[contains(@class, 'text_team')]").text.strip()

                        print(f"检查比赛 {game_index}: {game_home_team} vs {game_away_team}")

                        if game_home_team == home_team and game_away_team == away_team:
                            print(f"找到目标比赛: {home_team} vs {away_team} (联赛: {league_name})")

                            # 定位盘口类型 section
                            bet_section_xpath = f".//div[contains(@class, 'form_lebet_hdpou') and .//span[text()='{market_section}']]"
                            try:
                                bet_section_element = game_element.find_element(By.XPATH, bet_section_xpath)
                                print(f"找到盘口类型: {market_section}")
                            except NoSuchElementException:
                                print(f"未找到盘口类型: {market_section} in 比赛 {home_team} vs {away_team}")
                                continue

                            # 定位具体的赔率按钮
                            if market_section == 'Handicap':
                                if odds_type == 'Home':
                                    odds_button_xpath = (
                                        f".//div[contains(@class, 'btn_hdpou_odd') and "
                                        f"contains(@id, '_REH') and "
                                        f".//tt[@class='text_ballhead' and text()='{ballhead_text}']]"
                                    )
                                elif odds_type == 'Away':
                                    odds_button_xpath = (
                                        f".//div[contains(@class, 'btn_hdpou_odd') and "
                                        f"contains(@id, '_REC') and "
                                        f".//tt[@class='text_ballhead' and text()='{ballhead_text}']]"
                                    )
                                else:
                                    print(f"未知的 odds_type: {odds_type}")
                                    continue
                            elif market_section == 'Goals O/U':
                                odds_button_xpath = (
                                    f".//div[contains(@class, 'btn_hdpou_odd') and "
                                    f".//tt[@class='text_ballou' and text()='{ballou_text}'] and "
                                    f".//tt[@class='text_ballhead' and text()='{ballhead_text}']]"
                                )
                            else:
                                print(f"未知的 market_section: {market_section}")
                                continue

                            try:
                                odds_buttons = WebDriverWait(game_element, 10).until(
                                    EC.presence_of_all_elements_located((By.XPATH, odds_button_xpath))
                                )
                                print(f"找到 {len(odds_buttons)} 个符合条件的赔率按钮")

                                if not odds_buttons:
                                    print(f"未找到符合条件的赔率按钮: 比例='{ballhead_text}', 赔率名称='{odds_name}'")
                                    continue

                                # 选择第一个匹配的按钮
                                odds_button = odds_buttons[0]

                                # 提取赔率值
                                try:
                                    odds_value = odds_button.find_element(By.CLASS_NAME, 'text_odds').text.strip()
                                except NoSuchElementException:
                                    odds_value = '未知'

                                # 点击赔率按钮，添加重试机制
                                for attempt in range(3):
                                    try:
                                        driver.execute_script("arguments[0].scrollIntoView(true);", odds_button)
                                        WebDriverWait(driver, 10).until(
                                            EC.element_to_be_clickable((By.XPATH, odds_button_xpath)))
                                        odds_button.click()
                                        print(
                                            f"点击成功: 联赛='{league_name}', 比赛='{home_team} vs {away_team}', "
                                            f"盘口='{market_section}', 比例='{ballhead_text}', 赔率名称='{odds_name}', 赔率值='{odds_value}'"
                                        )
                                        return
                                    except (ElementClickInterceptedException, NoSuchElementException,
                                            StaleElementReferenceException, ElementNotInteractableException) as e:
                                        print(f"尝试 {attempt + 1} 点击赔率按钮失败: {e}")
                                        time.sleep(1)
                                print(
                                    f"所有尝试点击赔率按钮均失败: 比例='{ballhead_text}' ({odds_name}) in 比赛 {home_team} vs {away_team} (联赛: {league_name})"
                                )
                            except TimeoutException:
                                print(
                                    f"未找到赔率按钮: 比例='{ballhead_text}' ({odds_name}) in 比赛 {home_team} vs {away_team} (联赛: {league_name})"
                                )
                                continue

                    except NoSuchElementException:
                        print(f"比赛 {game_index} 中缺少必要的元素，跳过。")
                        continue
                    except StaleElementReferenceException:
                        print(f"比赛 {game_index} 的元素已失效，跳过。")
                        continue

            except StaleElementReferenceException:
                print(f"联赛元素 {league_index} 不可访问，跳过。")
                continue

        print(f"在联赛 '{league_name}' 中未找到比赛: {home_team} vs {away_team}")

    except Exception as e:
        print(f"点击赔率按钮失败: {e}")


def click_corner_odds(driver, alert):
    try:
        # 提取并清洗 Alert 数据
        league_name = alert.get('league_name', '').strip()
        home_team = alert.get('home_team', '').strip()
        away_team = alert.get('away_team', '').strip()
        bet_type_name = alert.get('bet_type_name', '').strip().upper()  # 转为大写
        odds_name = alert.get('odds_name', '').strip()

        # 定义比例映射表
        ratio_mapping = {
            '0.0': '0', '-0.25': '-0/0.5', '-0.5': '-0.5', '-0.75': '-0.5/1',
            '-1.0': '-1', '-1.25': '-1/1.5', '-1.5': '-1.5', '-1.75': '-1.5/2',
            '-2.0': '-2', '-2.25': '-2/2.5', '-2.5': '-2.5', '-2.75': '-2.5/3',
            '-3.0': '-3', '-3.25': '-3/3.5', '-3.5': '-3.5', '-3.75': '-3.5/4',
            '-4.0': '-4',
            '0.25': '0.25', '0.5': '0.5', '0.75': '0.5/1',
            '1.0': '1', '1.25': '1/1.5', '1.5': '1.5', '1.75': '1.5/2',
            '2.0': '2', '2.25': '2/2.5', '2.5': '2.5', '2.75': '2.5/3',
            '3.0': '3', '3.25': '3/3.5', '3.5': '3.5', '3.75': '3.5/4',
            '4.0': '4',
            '4.25': '4/4.5', '4.5': '4.5', '4.75': '4.5/5',
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

        # 定义盘口类型映射
        bet_type_mapping = {
            'CORNER_HANDICAP_FT': 'Corner Kick Handicap',
            'CORNER_HANDICAP_HT': 'Half-time Corner Kick Handicap',
            'CORNER_TOTAL_POINTS_FT': 'Corner Kick Goals O/U',
            'CORNER_TOTAL_POINTS_HT': 'Half-time Corner Kick Goals O/U',
            'NEXT_CORNER_FT': 'Next Corner',
            'NEXT_CORNER_HT': 'Next Corner',
            'ODD_EVEN_FT': 'O/E',
            'ODD_EVEN_HT': 'O/E',
            # 根据需要添加更多映射
        }

        # 解析 bet_type_name 以确定 market_section
        key = bet_type_name  # bet_type_name 已转为大写
        market_section = bet_type_mapping.get(key)

        if not market_section:
            # 尝试更灵活的匹配方式，例如忽略后缀部分
            if key.startswith('CORNER_'):
                key = key.replace('CORNER_', '')
                market_section = bet_type_mapping.get(key)

        if not market_section:
            print(f"无法映射 bet_type_name: {bet_type_name}")
            return

        # 确定比例
        if 'Handicap' in market_section or 'Goals O/U' in market_section:
            # 这些市场有比例
            if len(bet_type_name.split('_')) < 4:
                print(f"无法解析 bet_type_name: {bet_type_name}")
                return
            ratio = bet_type_name.split('_')[3]  # 例如 '1.25'
        else:
            ratio = None  # For markets like 'Next Corner' or 'O/E'

        # 如果有比例，则进行映射
        if ratio:
            mapped_ratio = ratio_mapping.get(ratio)
            if not mapped_ratio:
                print(f"未定义的 ratio 映射: {bet_type_name} {ratio}")
                return
            # 清理比例数值
            if mapped_ratio.endswith('.0'):
                mapped_ratio = mapped_ratio[:-2]
        else:
            mapped_ratio = None  # For markets like 'Next Corner' or 'O/E'

        # 根据 market_section 和 odds_name 处理
        if market_section in ['Corner Kick Handicap', 'Half-time Corner Kick Handicap']:
            # 'HomeOdds' 或 'AwayOdds'
            if odds_name == 'HomeOdds':
                odds_type = 'Home'
            elif odds_name == 'AwayOdds':
                odds_type = 'Away'
            else:
                print(f"未知的 odds_name: {odds_name} for market_section: {market_section}")
                return
        elif market_section in ['Corner Kick Goals O/U', 'Half-time Corner Kick Goals O/U']:
            # 'OverOdds' 或 'UnderOdds'
            if odds_name == 'OverOdds':
                ballou_text = 'O'
            elif odds_name == 'UnderOdds':
                ballou_text = 'U'
            else:
                print(f"未知的 odds_name: {odds_name} for market_section: {market_section}")
                return
        elif market_section == 'Next Corner':
            # 假设 odds_name 对应 '1st', '2nd', 等等
            if '1ST' in odds_name.upper() or 'FIRSTCORNER' in odds_name.upper():
                corner_type = '1st'
            elif '2ND' in odds_name.upper() or 'SECONDCORNER' in odds_name.upper():
                corner_type = '2nd'
            else:
                print(f"未知的 odds_name: {odds_name} for Next Corner market")
                return
        elif market_section == 'O/E':
            # 'OddOdds' 或 'EvenOdds'
            if odds_name == 'OddOdds':
                oe_text = 'Odd'
            elif odds_name == 'EvenOdds':
                oe_text = 'Even'
            else:
                print(f"未知的 odds_name: {odds_name} for O/E market")
                return
        else:
            print(f"未知的 market_section: {market_section}")
            return

        # 定位所有匹配的联赛元素
        league_xpath = f"//div[contains(@class, 'btn_title_le') and .//tt[@id='lea_name' and text()='{league_name}']]"
        league_elements = driver.find_elements(By.XPATH, league_xpath)
        print(f"联赛 '{league_name}' 找到 {len(league_elements)} 个元素")

        if not league_elements:
            print(f"未找到联赛: {league_name}")
            return

        # 遍历所有联赛元素
        for league_index, league_element in enumerate(league_elements, start=1):
            try:
                print(f"处理联赛元素 {league_index}: {league_name}")

                # 查找所有比赛元素（id 以 'game_' 开头的 div）
                game_xpath = ".//following-sibling::div[starts-with(@id, 'game_') and contains(@class, 'box_lebet')]"
                game_elements = league_element.find_elements(By.XPATH, game_xpath)
                print(f"联赛 '{league_name}' 下找到 {len(game_elements)} 场比赛")

                for game_index, game_element in enumerate(game_elements, start=1):
                    try:
                        # 获取主队和客队名称
                        game_home_team = game_element.find_element(By.XPATH,
                                                                   ".//div[contains(@class, 'teamH')]/span[contains(@class, 'text_team')]").text.strip()
                        game_away_team = game_element.find_element(By.XPATH,
                                                                   ".//div[contains(@class, 'teamC')]/span[contains(@class, 'text_team')]").text.strip()

                        print(f"检查比赛 {game_index}: {game_home_team} vs {game_away_team}")

                        if game_home_team == home_team and game_away_team == away_team:
                            print(f"找到目标比赛: {home_team} vs {away_team} (联赛: {league_name})")

                            # 定位盘口类型 section
                            bet_section_xpath = f".//div[contains(@class, 'box_lebet_odd') and .//span[text()='{market_section}' or .//tt[text()='{market_section}']]]"
                            try:
                                bet_section_element = game_element.find_element(By.XPATH, bet_section_xpath)
                                print(f"找到盘口类型: {market_section}")
                            except NoSuchElementException:
                                print(f"未找到盘口类型: {market_section} in 比赛 {home_team} vs {away_team}")
                                continue

                            # 定位具体的赔率按钮
                            if market_section in ['Corner Kick Handicap', 'Half-time Corner Kick Handicap']:
                                if odds_type == 'Home':
                                    # 查找带有 'strong_team' 类的按钮
                                    odds_button_xpath = (
                                        f".//div[contains(@class, 'btn_lebet_odd') and "
                                        f"contains(concat(' ', normalize-space(@class), ' '), ' strong_team ') and "
                                        f".//tt[@class='text_ballhead' and text()='{mapped_ratio}']]"
                                    )
                                elif odds_type == 'Away':
                                    # 查找不带有 'strong_team' 类的按钮
                                    odds_button_xpath = (
                                        f".//div[contains(@class, 'btn_lebet_odd') and "
                                        f"not(contains(concat(' ', normalize-space(@class), ' '), ' strong_team ')) and "
                                        f".//tt[@class='text_ballhead' and text()='{mapped_ratio}']]"
                                    )
                                else:
                                    print(f"未知的 odds_type: {odds_type}")
                                    continue
                            elif market_section in ['Corner Kick Goals O/U', 'Half-time Corner Kick Goals O/U']:
                                if odds_name == 'OverOdds':
                                    odds_button_xpath = (
                                        f".//div[contains(@class, 'btn_lebet_odd') and "
                                        f".//tt[@class='text_ballou' and text()='O'] and "
                                        f".//tt[@class='text_ballhead' and text()='{ballou_text}']]"
                                    )
                                elif odds_name == 'UnderOdds':
                                    odds_button_xpath = (
                                        f".//div[contains(@class, 'btn_lebet_odd') and "
                                        f".//tt[@class='text_ballou' and text()='U'] and "
                                        f".//tt[@class='text_ballhead' and text()='{ballou_text}']]"
                                    )
                                else:
                                    print(f"未知的 odds_name: {odds_name} for Goals O/U market")
                                    continue
                            elif market_section == 'Next Corner':
                                # Next Corner markets: '1st', '2nd', etc.
                                odds_button_xpath = (
                                    f".//div[contains(@class, 'btn_lebet_odd') and "
                                    f".//tt[@class='text_ballou' and text()='{corner_type}']]"
                                )
                            elif market_section == 'O/E':
                                if odds_name == 'OddOdds':
                                    odds_button_xpath = (
                                        f".//div[contains(@class, 'btn_lebet_odd') and "
                                        f".//tt[@class='text_ballou' and text()='Odd']]"
                                    )
                                elif odds_name == 'EvenOdds':
                                    odds_button_xpath = (
                                        f".//div[contains(@class, 'btn_lebet_odd') and "
                                        f".//tt[@class='text_ballou' and text()='Even']]"
                                    )
                                else:
                                    print(f"未知的 odds_name: {odds_name} for O/E market")
                                    continue
                            else:
                                print(f"未知的 market_section: {market_section}")
                                continue

                            # 找到赔率按钮
                            try:
                                odds_buttons = WebDriverWait(bet_section_element, 10).until(
                                    EC.presence_of_all_elements_located((By.XPATH, odds_button_xpath))
                                )
                                print(f"找到 {len(odds_buttons)} 个符合条件的赔率按钮")

                                if not odds_buttons:
                                    print(f"未找到符合条件的赔率按钮: 比例='{mapped_ratio}', 赔率名称='{odds_name}'")
                                    continue

                                # 选择第一个匹配的按钮
                                odds_button = odds_buttons[0]

                                # 提取赔率值
                                try:
                                    odds_value = odds_button.find_element(By.CLASS_NAME, 'text_odds').text.strip()
                                except NoSuchElementException:
                                    odds_value = '未知'

                                # 点击赔率按钮，添加重试机制
                                for attempt in range(3):
                                    try:
                                        driver.execute_script("arguments[0].scrollIntoView(true);", odds_button)
                                        WebDriverWait(driver, 10).until(
                                            EC.element_to_be_clickable((By.XPATH, odds_button_xpath))
                                        )
                                        odds_button.click()
                                        print(
                                            f"点击成功: 联赛='{league_name}', 比赛='{home_team} vs {away_team}', "
                                            f"盘口='{market_section}', 比例='{mapped_ratio}', 赔率名称='{odds_name}', 赔率值='{odds_value}'"
                                        )
                                        return
                                    except (ElementClickInterceptedException, NoSuchElementException,
                                            StaleElementReferenceException, ElementNotInteractableException) as e:
                                        print(f"尝试 {attempt + 1} 点击赔率按钮失败: {e}")
                                        time.sleep(1)
                                print(
                                    f"所有尝试点击赔率按钮均失败: 比例='{mapped_ratio}' ({odds_name}) in 比赛 {home_team} vs {away_team} (联赛: {league_name})"
                                )
                            except TimeoutException:
                                print(
                                    f"未找到赔率按钮: 比例='{mapped_ratio}' ({odds_name}) in 比赛 {home_team} vs {away_team} (联赛: {league_name})"
                                )
                                continue
                    except NoSuchElementException:
                        print(f"比赛 {game_index} 中缺少必要的元素，跳过。")
                        continue
                    except StaleElementReferenceException:
                        print(f"比赛 {game_index} 的元素已失效，跳过。")
                        continue
            except StaleElementReferenceException:
                print(f"联赛元素 {league_index} 不可访问，跳过。")
                continue

        print(f"在联赛 '{league_name}' 中未找到比赛: {home_team} vs {away_team}")

    except Exception as e:
        print(f"点击赔率按钮失败: {e}")


# Flask路由
@app.route('/receive_data', methods=['POST'])
def receive_data():
    data = request.get_json()
    if not data:
        return jsonify({'status': 'error', 'message': 'No JSON data received'}), 400
    print(data)
    market_type = map_alert_to_market_type(data)
    if market_type and market_type in MARKET_TYPES:
        with status_lock:
            queues = market_type_to_alert_queues.get(market_type, [])
            if not queues:
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 无可用的 Scraper 处理 market_type: {market_type}")
                return jsonify({'status': 'error', 'message': f"无可用的 Scraper 处理 market_type: {market_type}"}), 400

            # 获取下一个应该接收 alert 的队列索引
            index = market_type_to_next_queue_index.get(market_type, 0)
            # 获取对应的队列
            alert_queue = queues[index]
            # 将 alert 放入队列
            alert_queue.put(data)
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Alert 分配给 Scraper {index + 1} (market_type: {market_type})")

            # 更新下一个队列的索引，确保轮询
            market_type_to_next_queue_index[market_type] = (index + 1) % len(queues)

    else:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 无法映射 market_type for alert: {data}")

    return jsonify({'status': 'success', 'message': 'Data received'}), 200


@app.route('/start_scraper', methods=['POST'])
def start_scraper_api():
    data = request.json
    required_fields = ['username', 'market_type', 'min_odds', 'max_odds', 'max_bets', 'bet_interval']
    if not all(field in data for field in required_fields):
        return jsonify({'status': 'error', 'message': '缺少必要字段'}), 400

    username = data['username']
    market_type = data['market_type']
    min_odds = data['min_odds']
    max_odds = data['max_odds']
    max_bets = data['max_bets']
    bet_interval = data['bet_interval']

    if market_type not in MARKET_TYPES:
        return jsonify({'status': 'error', 'message': f"无效的 market_type: {market_type}"}), 400

    account = {
        'username': username,
        'min_odds': min_odds,
        'max_odds': max_odds,
        'max_bets': max_bets,
        'bet_interval': bet_interval
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
    data = request.json
    if 'scraper_id' not in data:
        return jsonify({'status': 'error', 'message': '缺少 scraper_id'}), 400

    scraper_id = data['scraper_id']
    with status_lock:
        if scraper_id not in thread_status:
            return jsonify({'status': 'error', 'message': f"未找到 scraper_id: {scraper_id}"}), 404

    # 停止线程
    if scraper_id in thread_control_events:
        thread_control_events[scraper_id].set()
        with status_lock:
            del thread_control_events[scraper_id]
        print(f"Scraper ID {scraper_id} 已停止")
        with status_lock:
            thread_status[scraper_id] = "已停止"
    else:
        print(f"Scraper ID {scraper_id} 未启动线程")

    return jsonify({'status': 'success', 'message': f"已停止线程: {scraper_id}"}), 200


@app.route('/delete_scraper', methods=['POST'])
def delete_scraper():
    data = request.json
    if 'scraper_id' not in data:
        return jsonify({'status': 'error', 'message': '缺少 scraper_id'}), 400

    scraper_id = data['scraper_id']
    with status_lock:
        if scraper_id not in thread_status:
            return jsonify({'status': 'error', 'message': f"未找到 scraper_id: {scraper_id}"}), 404

    # 如果还在运行，先停
    if scraper_id in thread_control_events:
        thread_control_events[scraper_id].set()
        del thread_control_events[scraper_id]
        print(f"Scraper ID {scraper_id} 已停止")

    # 从 thread_status 中移除
    del thread_status[scraper_id]
    print(f"Scraper ID {scraper_id} 已删除")

    return jsonify({'status': 'success', 'message': f"已删除抓取线程: {scraper_id}"}), 200


@app.route('/get_status', methods=['GET'])
def get_status():
    statuses = []
    with status_lock:
        for s_id, st in thread_status.items():
            statuses.append({'scraper_id': s_id, 'status': st})
    return jsonify({'status': 'success', 'active_threads': statuses}), 200


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5021)
