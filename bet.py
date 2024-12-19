import json
import os
import threading
import zipfile

import pandas as pd
import requests
from seleniumwire import webdriver  # 使用 seleniumwire 的 webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import time
import csv
import traceback
from flask import Flask, request, jsonify
from urllib.parse import urlparse
import random
import warnings
from urllib3.exceptions import InsecureRequestWarning

# 用于跟踪抓取线程状态
thread_status = {}
status_lock = threading.Lock()

# 固定密码
FIXED_PASSWORD = 'dddd1111DD'

# 定义要抓取的市场类型及其对应的按钮ID
MARKET_TYPES = {
    'HDP_OU': 'tab_rnou',  # 让球盘/大小球的按钮ID
    'CORNERS': 'tab_cn'  # 角球的按钮ID
}

# 创建Flask应用
app = Flask(__name__)

# 用于跟踪活跃的抓取线程
active_threads = []
thread_control_events = {}

# 忽略 InsecureRequestWarning（可选）
warnings.simplefilter('ignore', InsecureRequestWarning)

# 定义IP池，每个代理格式为 "protocol://username:password@host:port"
IP_POOL = [
    "http://user-spz4nq4hh5-ip-122.8.88.216:jX5ed7Etx32VtrzCm_@isp.visitxiangtan.com:10001",
    "http://user-spz4nq4hh5-ip-122.8.86.139:jX5ed7Etx32VtrzCm_@isp.visitxiangtan.com:10002",
    "http://user-spz4nq4hh5-ip-122.8.15.166:jX5ed7Etx32VtrzCm_@isp.visitxiangtan.com:10003",
    "http://user-spz4nq4hh5-ip-122.8.87.234:jX5ed7Etx32VtrzCm_@isp.visitxiangtan.com:10004",
    "http://user-spz4nq4hh5-ip-122.8.16.212:jX5ed7Etx32VtrzCm_@isp.visitxiangtan.com:10005",
    "http://user-spz4nq4hh5-ip-122.8.83.60:jX5ed7Etx32VtrzCm_@isp.visitxiangtan.com:10006",
    "http://user-spz4nq4hh5-ip-122.8.83.139:jX5ed7Etx32VtrzCm_@isp.visitxiangtan.com:10007",
    "http://user-spz4nq4hh5-ip-122.8.87.216:jX5ed7Etx32VtrzCm_@isp.visitxiangtan.com:10008",
    "http://user-spz4nq4hh5-ip-122.8.87.251:jX5ed7Etx32VtrzCm_@isp.visitxiangtan.com:10009",
    "http://user-spz4nq4hh5-ip-122.8.16.227:jX5ed7Etx32VtrzCm_@isp.visitxiangtan.com:10010"
]


def get_random_proxy():
    return random.choice(IP_POOL)


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

        # 处理可能的弹窗
        try:
            popup_wait = WebDriverWait(driver, 5)
            no_button = popup_wait.until(EC.element_to_be_clickable((By.ID, 'C_no_btn')))
            no_button.click()
        except:
            pass  # 如果没有弹窗，继续执行
        # 等待导航到足球页面
        wait.until(EC.visibility_of_element_located((By.XPATH, '//div[span[text()="Soccer"]]')))
        print(f"{username} 登录成功")
        return True
    except Exception as e:
        print(f"{username} 登录失败或未找到滚球比赛")
        traceback.print_exc()
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
            'match_time': match_time,
            'home_team': home_team,
            'away_team': away_team,
            'home_score': home_score,
            'away_score': away_score,
            'home_corners': '',  # 预留字段
            'away_corners': ''  # 预留字段
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


def save_to_csv(data, filename):
    if not data:
        print(f"没有数据保存到 {filename}")
        return
    # 定义固定的字段名
    fixed_fields = ['league', 'match_time', 'home_team', 'away_team', 'home_score', 'away_score', 'home_corners',
                    'away_corners']
    # 收集所有赔率类型
    odds_fields = set()
    for item in data:
        odds_fields.update(item.keys() - set(fixed_fields))
    # 定义最终的字段名，固定字段在前，赔率字段排序后追加
    fieldnames = fixed_fields + sorted(odds_fields)
    # 保存数据，覆盖模式
    with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for row in data:
            # 仅包含定义的字段
            clean_row = {k: v for k, v in row.items() if k in fieldnames}
            writer.writerow(clean_row)
    #print(f"数据保存到 {filename}")


def run_scraper(account, market_type, scraper_id, proxy):
    # 设置默认值
    username = account['username']
    filename = f"{username}_{market_type}_data.csv"
    interval = 0.3  # 默认抓取间隔（秒）

    stop_event = threading.Event()
    thread_control_events[scraper_id] = stop_event

    driver = None  # 初始化 driver

    try:
        driver = init_driver(proxy)
        # 等待代理配置生效
        time.sleep(2)  # 根据需要调整时间

        with status_lock:
            thread_status[scraper_id] = "启动中"  # 设置为“启动中”（黄色）
            print(f"Scraper ID {scraper_id} 状态更新为: 启动中 使用代理: {proxy}")

        if login(driver, username):
            if navigate_to_football(driver):
                with status_lock:
                    thread_status[scraper_id] = "运行中"  # 设置为“运行中”（绿色）
                    print(f"Scraper ID {scraper_id} 状态更新为: 运行中 使用代理: {proxy}")

                try:
                    # 点击指定的市场类型按钮
                    button = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.ID, MARKET_TYPES[market_type]))
                    )
                    button.click()
                    print(f"{username} 已点击 {market_type} 按钮 使用代理: {proxy}")

                    # 等待页面加载
                    time.sleep(5)

                    # 进入数据抓取循环
                    while not stop_event.is_set():
                        try:
                            soup = get_market_data(driver)
                            if soup:
                                data = parse_market_data(soup, market_type)
                                save_to_csv(data, filename)
                            else:
                                print(f"{username} 未获取到数据 使用代理: {proxy}")
                        except Exception as e:
                            print(f"{username} 抓取数据时发生错误: {e} 使用代理: {proxy}")
                            traceback.print_exc()
                        time.sleep(interval)
                except Exception as e:
                    print(f"{username} 未找到市场类型按钮: {market_type} 使用代理: {proxy}")
                    traceback.print_exc()
                    with status_lock:
                        thread_status[scraper_id] = "已停止"  # 设置为“已停止”（灰色）
                        print(f"Scraper ID {scraper_id} 状态更新为: 已停止。 使用代理: {proxy}")
            else:
                with status_lock:
                    thread_status[scraper_id] = "已停止"  # 设置为“已停止”（灰色）
                    print(f"Scraper ID {scraper_id} 状态更新为: 已停止。 使用代理: {proxy}")
        else:
            with status_lock:
                thread_status[scraper_id] = "已停止"  # 设置为“已停止”（灰色）
                print(f"Scraper ID {scraper_id} 状态更新为: 已停止。 使用代理: {proxy}")
    except Exception as e:
        print(f"{username} 运行过程中发生错误: {e} 使用代理: {proxy}")
        traceback.print_exc()
        with status_lock:
            thread_status[scraper_id] = "已停止"  # 设置为“已停止”（灰色）
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



@app.route('/start_scraper', methods=['POST'])
def start_scraper():
    """
    接收来自客户端的请求，启动相应的抓取线程。
    请求体应包含 'username', 'market_type'。
    """
    data = request.json
    required_fields = ['username', 'market_type']

    # 检查请求数据是否包含所有必需字段
    if not all(field in data for field in required_fields):
        return jsonify({'status': 'error', 'message': '缺少必要的字段'}), 400

    username = data['username']
    market_type = data['market_type']

    if market_type not in MARKET_TYPES:
        return jsonify({'status': 'error', 'message': f"无效的 market_type: {market_type}"}), 400

    # 创建账户字典
    account = {'username': username}

    # 生成唯一的 scraper_id
    scraper_id = f"{username}_{market_type}_{int(time.time())}"

    # 获取一个随机代理
    proxy = get_random_proxy()

    # 初始化线程状态
    with status_lock:
        thread_status[scraper_id] = "正在启动..."
        print(f"Scraper ID {scraper_id} 状态更新为: 正在启动... 使用代理: {proxy}")

    # 启动新的抓取线程，传递代理参数
    scraper_thread = threading.Thread(target=run_scraper, args=(account, market_type, scraper_id, proxy), daemon=True)
    scraper_thread.start()

    # 将线程添加到活跃线程列表
    active_threads.append(scraper_thread)

    return jsonify(
        {'status': 'success', 'message': f"已启动抓取线程: {username} - {market_type}", 'scraper_id': scraper_id}), 200


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
