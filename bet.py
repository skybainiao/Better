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
market_type_to_alert_queue = {}
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


def get_random_proxy():
    active_proxies = [proxy for proxy, info in IP_POOL.items() if info["status"] == "active"]
    if not active_proxies:
        raise Exception("所有代理已被封禁")
    return random.choice(active_proxies)


def get_new_proxy(current_proxy):
    with status_lock:
        available_proxies = [proxy for proxy, info in IP_POOL.items() if
                             info["status"] == "active" and proxy != current_proxy]
    if not available_proxies:
        print("没有可用的代理来重启线程")
        return None
    new_proxy = random.choice(available_proxies)
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


def get_market_data(driver):
    try:
        page_source = driver.page_source
        soup = BeautifulSoup(page_source, 'html.parser')
        return soup
    except Exception as e:
        print(f"获取页面数据失败: {e}")
        traceback.print_exc()
        return None


def parse_market_data(soup, market_type):
    data = []
    league_sections = soup.find_all('div', class_='btn_title_le')
    for league_section in league_sections:
        league_name_tag = league_section.find('tt', id='lea_name')
        league_name = league_name_tag.get_text(strip=True) if league_name_tag else 'Unknown League'
        # 获取该联赛下的所有比赛
        match_container = league_section.find_next_sibling()
        while match_container and 'box_lebet' in match_container.get('class', []):
            match_info = extract_match_info(match_container, league_name, market_type)
            if match_info:
                data.append(match_info)
            match_container = match_container.find_next_sibling()
    return data


def extract_match_info(match_container, league_name, market_type):
    try:
        # 提取主客队名称
        home_team_div = match_container.find('div', class_='box_team teamH')
        away_team_div = match_container.find('div', class_='box_team teamC')

        if home_team_div:
            home_team_tag = home_team_div.find('span', class_='text_team')
            home_team = home_team_tag.get_text(strip=True) if home_team_tag else 'Unknown'
        else:
            home_team = 'Unknown'

        if away_team_div:
            away_team_tag = away_team_div.find('span', class_='text_team')
            away_team = away_team_tag.get_text(strip=True) if away_team_tag else 'Unknown'
        else:
            away_team = 'Unknown'

        # 提取比分
        score_container = match_container.find('div', class_='box_score')
        if score_container:
            score_tags = score_container.find_all('span', class_='text_point')
            if score_tags and len(score_tags) >= 2:
                home_score = score_tags[0].get_text(strip=True)
                away_score = score_tags[1].get_text(strip=True)
            else:
                home_score = away_score = '0'
        else:
            home_score = away_score = '0'

        # 提取比赛时间
        match_time_tag = match_container.find('tt', class_='text_time')
        if match_time_tag:
            icon_info = match_time_tag.find('i', id='icon_info')
            match_time = icon_info.get_text(strip=True) if icon_info else 'Unknown Time'
        else:
            match_time = 'Unknown Time'

        # 初始化数据字典
        match_info = {
            'league': league_name,
            'home_team': home_team,
            'away_team': away_team,
            'home_score': home_score,
            'away_score': away_score,
            'match_time': match_time,
        }

        # 提取赔率信息
        odds = {}
        if market_type == 'HDP_OU':
            desired_bet_types = ['Handicap', 'Goals O/U']

            # 提取全场（FT）赔率信息
            odds_sections_ft = match_container.find_all('div', class_='form_lebet_hdpou hdpou_ft')
            for odds_section in odds_sections_ft:
                bet_type_tag = odds_section.find('div', class_='head_lebet').find('span')
                bet_type = bet_type_tag.get_text(strip=True) if bet_type_tag else 'Unknown Bet Type'
                if bet_type in desired_bet_types:
                    odds.update(extract_odds_hdp_ou(odds_section, bet_type, 'FT'))

            # 提取上半场（1H）赔率信息
            odds_sections_1h = match_container.find_all('div', class_='form_lebet_hdpou hdpou_1h')
            for odds_section in odds_sections_1h:
                bet_type_tag = odds_section.find('div', class_='head_lebet').find('span')
                bet_type = bet_type_tag.get_text(strip=True) if bet_type_tag else 'Unknown Bet Type'
                if bet_type in desired_bet_types:
                    odds.update(extract_odds_hdp_ou(odds_section, bet_type, '1H'))

        elif market_type == 'CORNERS':
            odds_sections = match_container.find_all('div', class_='box_lebet_odd')
            for odds_section in odds_sections:
                odds.update(extract_odds_corners(odds_section))

        match_info.update(odds)
        return match_info

    except Exception as e:
        print(f"提取比赛信息失败: {e}")
        traceback.print_exc()
        return None


def extract_odds_hdp_ou(odds_section, bet_type, time_indicator):
    odds = {}
    # 找到所有的赔率列
    labels = odds_section.find_all('div', class_='col_hdpou')
    for label in labels:
        # 提取主队赔率
        home_odds_div = label.find('div', id=lambda x: x and (x.endswith('_REH') or x.endswith('_ROUH')))
        if home_odds_div and 'lock' not in home_odds_div.get('class', []):
            handicap_tag = home_odds_div.find('tt', class_='text_ballhead')
            odds_tag = home_odds_div.find('span', class_='text_odds')
            handicap = handicap_tag.get_text(strip=True) if handicap_tag else ''
            odds_value = odds_tag.get_text(strip=True) if odds_tag else ''
            # 过滤掉包含占位符的数据
            if '*' in handicap or '*' in odds_value or not handicap or not odds_value:
                continue
            # 正确映射 'O' 为 'Over'，'U' 为 'Under'
            team_info_tag = home_odds_div.find('tt', class_='text_ballou')
            team_info = team_info_tag.get_text(strip=True) if team_info_tag else ''
            over_under = 'Over' if team_info == 'O' else 'Under'
            if bet_type == 'Handicap':
                key_home = f"SPREAD_{time_indicator}_{handicap}_HomeOdds"
            elif bet_type == 'Goals O/U':
                key_home = f"TOTAL_POINTS_{time_indicator}_{handicap}_{over_under}Odds"
            else:
                continue
            odds[key_home] = odds_value

        # 提取客队赔率
        away_odds_div = label.find('div', id=lambda x: x and (x.endswith('_REC') or x.endswith('_ROUC')))
        if away_odds_div and 'lock' not in away_odds_div.get('class', []):
            handicap_tag = away_odds_div.find('tt', class_='text_ballhead')
            odds_tag = away_odds_div.find('span', class_='text_odds')
            handicap = handicap_tag.get_text(strip=True) if handicap_tag else ''
            odds_value = odds_tag.get_text(strip=True) if odds_tag else ''
            # 过滤掉包含占位符的数据
            if '*' in handicap or '*' in odds_value or not handicap or not odds_value:
                continue
            # 正确映射 'O' 为 'Over'，'U' 为 'Under'
            team_info_tag = away_odds_div.find('tt', class_='text_ballou')
            team_info = team_info_tag.get_text(strip=True) if team_info_tag else ''
            over_under = 'Over' if team_info == 'O' else 'Under'
            if bet_type == 'Handicap':
                key_away = f"SPREAD_{time_indicator}_{handicap}_AwayOdds"
            elif bet_type == 'Goals O/U':
                key_away = f"TOTAL_POINTS_{time_indicator}_{handicap}_{over_under}Odds"
            else:
                continue
            odds[key_away] = odds_value
    return odds


def extract_odds_corners(odds_section):
    odds = {}
    # 提取时间指示符（FT 或 1H）
    head_lebet = odds_section.find('div', class_='head_lebet')
    time_indicator_tag = head_lebet.find('tt')
    if time_indicator_tag:
        time_indicator = time_indicator_tag.get_text(strip=True)
    else:
        time_indicator = 'FT'

    # 提取投注类型，例如 'O/U'，'HDP' 等
    bet_type_span = head_lebet.find('span')
    bet_type = bet_type_span.get_text(strip=True) if bet_type_span else 'Unknown Bet Type'

    # 处理每个赔率按钮
    buttons = odds_section.find_all('div', class_='btn_lebet_odd')
    key_counts = {}  # 用于跟踪键名的出现次数

    for btn in buttons:
        odds_tag = btn.find('span', class_='text_odds')
        odds_value = odds_tag.get_text(strip=True) if odds_tag else ''
        # 过滤掉无效数据
        if not odds_value or '*' in odds_value:
            continue

        # 根据按钮的 ID 判断类型
        btn_id = btn.get('id', '')
        if '_H' in btn_id:
            team = 'Home'
        elif '_C' in btn_id:
            team = 'Away'
        elif '_O' in btn_id:
            team = 'Odd'
        elif '_E' in btn_id:
            team = 'Even'
        else:
            team = ''

        # 提取盘口或其他信息
        handicap_tag = btn.find('tt', class_='text_ballhead')
        handicap = handicap_tag.get_text(strip=True) if handicap_tag else ''

        team_info_tag = btn.find('tt', class_='text_ballou')
        team_info = team_info_tag.get_text(strip=True) if team_info_tag else ''

        # 构建键名
        if bet_type == 'HDP':
            key = f"SPREAD_{time_indicator}_{handicap}_{team}Odds"
        elif bet_type == 'O/U':
            over_under = 'Over' if team_info == 'O' else 'Under'
            key = f"TOTAL_POINTS_{time_indicator}_{handicap}_{over_under}Odds"
        elif bet_type == 'Next Corner':
            key = f"NEXT_CORNER_{time_indicator}_{team_info}_{team}Odds"
        elif bet_type == 'O/E':
            key = f"ODD_EVEN_{time_indicator}_{team}Odds"
        else:
            key = f"{bet_type}_{time_indicator}_{team_info}_{handicap}_{team}Odds"

        # 检查键名是否已存在，如果存在，则添加后缀以确保唯一性
        if key in odds:
            if key not in key_counts:
                key_counts[key] = 1
            key_counts[key] += 1
            unique_key = f"{key}_{key_counts[key]}"
        else:
            unique_key = key

        odds[unique_key] = odds_value

    return odds


def run_scraper(account, market_type, scraper_id, proxy, alert_queue):
    username = account['username']

    stop_event = threading.Event()
    thread_control_events[scraper_id] = stop_event

    driver = None  # 初始化 driver

    try:
        driver = init_driver(proxy)
        # 等待代理配置生效
        time.sleep(2)

        with status_lock:
            thread_status[scraper_id] = "启动中"
            print(f"Scraper ID {scraper_id} 状态更新为: 启动中 使用代理: {proxy}")

        if login(driver, username):
            if navigate_to_football(driver):
                with status_lock:
                    thread_status[scraper_id] = "运行中"
                    print(f"Scraper ID {scraper_id} 状态更新为: 运行中 使用代理: {proxy}")

                try:
                    # 点击指定的市场类型按钮
                    button = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.ID, MARKET_TYPES[market_type]))
                    )
                    button.click()
                    print(f"{username} 已点击 {market_type} 按钮 使用代理: {proxy}")

                    # 设置 scraping_market_type 基于 market_type
                    if market_type in ['Full_Handicap', 'Half_Handicap', 'Full_OverUnder', 'Half_OverUnder']:
                        scraping_market_type = 'HDP_OU'
                    elif market_type in ['Full_Corners_Handicap', 'Half_Corners_Handicap',
                                         'Full_Corners_OverUnder', 'Half_Corners_OverUnder']:
                        scraping_market_type = 'CORNERS'
                    else:
                        raise Exception(f"未处理的 market_type: {market_type}")

                    print(f"Scraping Market Type set to: {scraping_market_type}")

                    # 等待页面加载
                    time.sleep(5)

                    # 等待并处理alert
                    while not stop_event.is_set():
                        try:
                            alert = alert_queue.get(timeout=1)  # 等待alert，超时后继续检查停止事件
                        except Empty:
                            continue  # 没有alert，继续等待

                        print(f"接收到Alert: {alert}")

                        # 根据alert信息抓取对应比赛的数据
                        try:
                            # 假设当前页面已经加载了相关市场类型的比赛，直接抓取页面数据
                            soup = get_market_data(driver)
                            if soup:
                                data = parse_market_data(soup, scraping_market_type)
                                # 查找匹配的比赛
                                for match in data:
                                    if (alert['league_name'] == match['league'] and
                                            alert['home_team'] == match['home_team'] and
                                            alert['away_team'] == match['away_team']):
                                        print("匹配到Alert，相关比赛数据如下：")
                                        print(json.dumps(match, ensure_ascii=False, indent=4))

                                        # 调用点击赔率函数，根据 match_type 选择适当的函数
                                        match_type = alert.get('match_type', '').strip().lower()
                                        if match_type == 'corner':
                                            click_corner_odds(driver, alert)
                                        elif match_type == 'normal':
                                            click_odds(driver, alert)
                                        else:
                                            print(f"未知的 match_type: {match_type}")

                                        break
                                else:
                                    print(
                                        f"未找到匹配的比赛: {alert['home_team']} vs {alert['away_team']} in {alert['league_name']}")
                            else:
                                print(f"{username} 未获取到数据 使用代理: {proxy}")
                        except Exception as e:
                            print(f"处理Alert时发生错误: {e} 使用代理: {proxy}")
                            traceback.print_exc()

                        alert_queue.task_done()

                except Exception as e:
                    print(f"{username} 处理市场类型按钮时发生错误: {market_type} 使用代理: {proxy}")
                    traceback.print_exc()
                    with status_lock:
                        thread_status[scraper_id] = "已停止"
            else:
                with status_lock:
                    thread_status[scraper_id] = "已停止"
                    print(f"Scraper ID {scraper_id} 状态更新为: 已停止。 使用代理: {proxy}")
        else:
            with status_lock:
                thread_status[scraper_id] = "已停止"
                print(f"Scraper ID {scraper_id} 状态更新为: 已停止。 使用代理: {proxy}")
    except Exception as e:
        print(f"{username} 运行过程中发生错误: {e} 使用代理: {proxy}")
        traceback.print_exc()
        with status_lock:
            thread_status[scraper_id] = "已停止"
            print(f"Scraper ID {scraper_id} 状态更新为: 已停止。 使用代理: {proxy}")
    finally:
        if driver:
            driver.quit()
            print(f"{username} 已关闭浏览器 使用代理: {proxy}")

        # 从控制事件中移除 scraper_id 并保持 thread_status 直到删除
        with status_lock:
            if scraper_id in thread_control_events:
                del thread_control_events[scraper_id]
            # 保持 thread_status 直到删除


def start_scraper_thread(account, market_type, scraper_id=None, proxy=None):
    if not scraper_id:
        # 生成唯一的 scraper_id
        scraper_id = f"{account['username']}_{market_type}_{int(time.time())}"

    if not proxy:
        try:
            # 获取一个随机代理
            proxy = get_random_proxy()
        except Exception as e:
            print(f"无法获取代理: {e}")
            return

    # 初始化线程状态
    with status_lock:
        thread_status[scraper_id] = "正在启动..."
        print(f"Scraper ID {scraper_id} 状态更新为: 正在启动... 使用代理: {proxy}")

    # 创建一个专用的 alert 队列并注册到字典中
    alert_queue = Queue()
    market_type_to_alert_queue[market_type] = alert_queue

    # 启动新的抓取线程，传递 alert_queue
    scraper_thread = threading.Thread(target=run_scraper, args=(account, market_type, scraper_id, proxy, alert_queue),
                                      daemon=True)
    scraper_thread.start()

    # 将线程添加到活跃线程列表
    active_threads.append(scraper_thread)

    # 更新Account中的ScraperId
    account['scraper_id'] = scraper_id


# 2. 定义一个函数来根据 alert 的信息映射到对应的 market_type
def map_alert_to_market_type(alert):
    bet_type_name = alert.get('bet_type_name', '')
    match_type = alert.get('match_type', '')

    # Determine period
    if 'FT' in bet_type_name:
        period = 'Full'
    elif '1H' in bet_type_name:
        period = 'Half'
    else:
        period = None

    # Determine bet type
    if bet_type_name.startswith('SPREAD'):
        bet_type = 'Handicap'
    elif bet_type_name.startswith('TOTAL_POINTS'):
        bet_type = 'OverUnder'
    else:
        bet_type = None

    # Determine if corner
    if match_type == 'corner':
        corner = 'Corners_'
    else:
        corner = ''

    if period and bet_type:
        market_type = f"{period}_{corner}{bet_type}"
        return market_type
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

        # 定义比例映射表（直接使用 Alert 数据中的比例，不修改正负号）
        ratio_mapping = {
            '0.0': '0', '-0.25': '-0/0.5', '-0.5': '-0.5', '-0.75': '-0.5/1',
            '-1.0': '-1', '-1.25': '-1/1.5', '-1.5': '-1.5', '-1.75': '-1.5/2',
            '-2.0': '-2', '-2.25': '-2/2.5', '-2.5': '-2.5', '-2.75': '-2.5/3',
            '-3.0': '-3', '-3.25': '-3/3.5', '-3.5': '-3.5', '-3.75': '-3.5/4',
            '-4.0': '-4', '0.25': '0/0.5', '0.5': '0.5', '0.75': '0.5/1',
            '1.0': '1', '1.25': '1/1.5', '1.5': '1.5', '1.75': '1.5/2',
            '2.0': '2', '2.25': '2/2.5', '2.5': '2.5', '2.75': '2.5/3',
            '3.0': '3', '3.25': '3/3.5', '3.5': '3.5', '3.75': '3.5/4',
            '4.0': '4',
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
        print(f"找到联赛元素数量: {len(league_elements)}")

        if not league_elements:
            print(f"未找到联赛: {league_name}")
            return

        # 遍历所有联赛元素，不论是否可见
        for league_index, league_element in enumerate(league_elements, start=1):
            try:
                # 无需检查是否可见，处理所有联赛元素
                print(f"处理联赛元素 {league_index}: {league_name}")

                # 查找所有比赛元素（id 以 'game_' 开头的 div）
                game_xpath = ".//following-sibling::div[starts-with(@id, 'game_') and contains(@class, 'box_lebet')]"
                game_elements = league_element.find_elements(By.XPATH, game_xpath)
                print(f"联赛 '{league_name}' 下找到比赛数量: {len(game_elements)}")

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
                                        f"contains(@id, '_REH') and "  # 确保是主队按钮
                                        f".//tt[@class='text_ballhead' and text()='{ballhead_text}']]"
                                    )
                                elif odds_type == 'Away':
                                    odds_button_xpath = (
                                        f".//div[contains(@class, 'btn_hdpou_odd') and "
                                        f"contains(@id, '_REC') and "  # 确保是客队按钮
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

                                # 打印所有匹配的赔率按钮以进行调试
                                print(f"匹配到的赔率按钮数量: {len(odds_buttons)}")
                                for idx, btn in enumerate(odds_buttons, start=1):
                                    try:
                                        btn_text_ballhead = btn.find_element(By.CLASS_NAME,
                                                                             'text_ballhead').text.strip()
                                        btn_text_odds = btn.find_element(By.CLASS_NAME, 'text_odds').text.strip()
                                        btn_classes = btn.get_attribute('class')
                                        print(
                                            f"按钮 {idx}: 类名='{btn_classes}', 比例='{btn_text_ballhead}', 赔率值='{btn_text_odds}'")
                                    except NoSuchElementException:
                                        print(f"按钮 {idx}: 未找到赔率值元素")

                                if not odds_buttons:
                                    print(f"未找到符合条件的赔率按钮: 比例='{ballhead_text}', 赔率名称='{odds_name}'")
                                    continue

                                # 选择第一个匹配的按钮
                                odds_button = odds_buttons[0]

                                # 提取赔率值
                                try:
                                    odds_value_element = odds_button.find_element(By.CLASS_NAME, 'text_odds')
                                    odds_value = odds_value_element.text.strip()
                                except NoSuchElementException:
                                    odds_value = '未知'
                                    print(f"未找到赔率值元素 for {ballhead_text} ({odds_name})")

                                # 点击赔率按钮，添加重试机制
                                for attempt in range(3):
                                    try:
                                        # 确保元素可见并滚动到视图
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
        bet_type_name = alert.get('bet_type_name', '').strip()
        odds_name = alert.get('odds_name', '').strip()

        # 定义比例映射表（直接使用 Alert 数据中的比例，不修改正负号）
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
        bet_type_parts = bet_type_name.split('_')
        if len(bet_type_parts) >= 3:
            key = '_'.join(bet_type_parts[:3])  # e.g., 'CORNER_HANDICAP_FT'
            market_section = bet_type_mapping.get(key)
        else:
            key = bet_type_parts[0]
            market_section = bet_type_mapping.get(key)

        if not market_section:
            print(f"无法映射 bet_type_name: {bet_type_name}")
            return

        # 确定比例
        if 'Handicap' in market_section or 'Goals O/U' in market_section:
            # 这些市场有比例
            if len(bet_type_parts) < 4:
                print(f"无法解析 bet_type_name: {bet_type_name}")
                return
            ratio = bet_type_parts[3]  # e.g., '1.25'
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
            if '1st' in odds_name or 'FirstCorner' in odds_name:
                corner_type = '1st'
            elif '2nd' in odds_name or 'SecondCorner' in odds_name:
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
        print(f"找到联赛元素数量: {len(league_elements)}")

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
                print(f"联赛 '{league_name}' 下找到比赛数量: {len(game_elements)}")

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
                                print(f"匹配到的赔率按钮数量: {len(odds_buttons)}")

                                for idx, btn in enumerate(odds_buttons, start=1):
                                    try:
                                        btn_text_ballhead = btn.find_element(By.CLASS_NAME,
                                                                             'text_ballhead').text.strip()
                                        btn_text_odds = btn.find_element(By.CLASS_NAME, 'text_odds').text.strip()
                                        btn_classes = btn.get_attribute('class')
                                        print(
                                            f"按钮 {idx}: 类名='{btn_classes}', 比例='{btn_text_ballhead}', 赔率值='{btn_text_odds}'")
                                    except NoSuchElementException:
                                        print(f"按钮 {idx}: 未找到赔率值元素")

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
                                    print(f"未找到赔率值元素 for {mapped_ratio} ({odds_name})")

                                # 点击赔率按钮，添加重试机制
                                for attempt in range(3):
                                    try:
                                        # 确保元素可见并滚动到视图
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

    # 根据 alert 的信息映射到对应的 market_type
    market_type = map_alert_to_market_type(data)
    if market_type and market_type in MARKET_TYPES:
        if market_type in market_type_to_alert_queue:
            market_type_to_alert_queue[market_type].put(data)
            print(f"Alert 分配给 market_type: {market_type}")
        else:
            print(f"没有找到对应的 Scraper 处理 market_type: {market_type}")
    else:
        print(f"无法映射 market_type for alert: {data}")

    return jsonify({'status': 'success', 'message': 'Data received'}), 200


@app.route('/start_scraper', methods=['POST'])
def start_scraper_api():
    """
    接收来自客户端的请求，启动相应的抓取线程。
    请求体应包含 'username', 'market_type', 'min_odds', 'max_odds', 'max_bets', 'bet_interval'。
    """
    data = request.json
    required_fields = ['username', 'market_type', 'min_odds', 'max_odds', 'max_bets', 'bet_interval']

    # 检查请求数据是否包含所有必需字段
    if not all(field in data for field in required_fields):
        return jsonify({'status': 'error', 'message': '缺少必要的字段'}), 400

    username = data['username']
    market_type = data['market_type']
    min_odds = data['min_odds']
    max_odds = data['max_odds']
    max_bets = data['max_bets']
    bet_interval = data['bet_interval']

    if market_type not in MARKET_TYPES:
        return jsonify({'status': 'error', 'message': f"无效的 market_type: {market_type}"}), 400

    # 创建账户字典，包括新增的参数
    account = {
        'username': username,
        'min_odds': min_odds,
        'max_odds': max_odds,
        'max_bets': max_bets,  # 仅用于记录
        'bet_interval': bet_interval  # 仅用于记录
    }

    # 生成新的 scraper_id
    scraper_id = f"{username}_{market_type}_{int(time.time())}"

    # 将启动任务加入队列，包括新增的参数
    scraper_queue.put((account, market_type, scraper_id))
    print(
        f"已将 {username} - {market_type} 加入启动队列，Scraper ID: {scraper_id}，参数: min_odds={min_odds}, max_odds={max_odds}, max_bets={max_bets}, bet_interval={bet_interval}")

    return jsonify(
        {'status': 'success', 'message': f"已将 {username} - {market_type} 加入启动队列",
         'scraper_id': scraper_id}), 200


@app.route('/stop_scraper', methods=['POST'])
def stop_scraper():
    """
    停止指定的抓取线程。
    请求体应包含 'scraper_id'。
    """
    data = request.json
    if 'scraper_id' not in data:
        return jsonify({'status': 'error', 'message': '缺少 scraper_id'}), 400

    scraper_id = data['scraper_id']
    with status_lock:
        # 检查 scraper_id 是否存在
        if scraper_id not in thread_status:
            return jsonify({'status': 'error', 'message': f"未找到 scraper_id: {scraper_id}"}), 404

    # 如果 scraper_id 在 thread_control_events 中，先停止线程
    if scraper_id in thread_control_events:
        thread_control_events[scraper_id].set()
        with status_lock:
            del thread_control_events[scraper_id]
        print(f"Scraper ID {scraper_id} 已被停止。")

        with status_lock:
            thread_status[scraper_id] = "已停止"  # 更新状态为“已停止”
            print(f"Scraper ID {scraper_id} 状态更新为: 已停止。")
    else:
        print(f"Scraper ID {scraper_id} 未启动线程。")

    return jsonify({'status': 'success', 'message': f"已停止抓取线程: {scraper_id}"}), 200


@app.route('/delete_scraper', methods=['POST'])
def delete_scraper():
    """
    删除指定的抓取线程。
    请求体应包含 'scraper_id'。
    """
    data = request.json
    if 'scraper_id' not in data:
        return jsonify({'status': 'error', 'message': '缺少 scraper_id'}), 400

    scraper_id = data['scraper_id']
    with status_lock:
        # 检查 scraper_id 是否存在
        if scraper_id not in thread_status:
            return jsonify({'status': 'error', 'message': f"未找到 scraper_id: {scraper_id}"}), 404

    # 如果 scraper_id 在 thread_control_events 中，先停止线程
    if scraper_id in thread_control_events:
        thread_control_events[scraper_id].set()
        with status_lock:
            del thread_control_events[scraper_id]
        print(f"Scraper ID {scraper_id} 已被停止。")

    # 从 thread_status 中移除 scraper_id
    with status_lock:
        if scraper_id in thread_status:
            del thread_status[scraper_id]
            print(f"Scraper ID {scraper_id} 已从状态列表中删除。")

    return jsonify({'status': 'success', 'message': f"已删除抓取线程: {scraper_id}"}), 200


@app.route('/get_status', methods=['GET'])
def get_status():
    """
    获取当前活跃的抓取线程状态。
    """
    statuses = []
    with status_lock:
        for scraper_id, status in thread_status.items():
            statuses.append({
                'scraper_id': scraper_id,
                'status': status
            })
    return jsonify({'status': 'success', 'active_threads': statuses}), 200


if __name__ == "__main__":
    # 定义登录页面的URL
    BASE_URL = 'https://123.108.119.156/'  # 登录页面的URL

    # 启动Flask服务器
    # 你可以根据需要更改host和port
    app.run(host='0.0.0.0', port=5021)