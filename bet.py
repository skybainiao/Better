# bet.py
import json
import threading
import pandas as pd
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import time
import csv
import traceback
from flask import Flask, request, jsonify
import threading

# 用于跟踪抓取线程状态
thread_status = {}
status_lock = threading.Lock()

# 固定密码
FIXED_PASSWORD = 'dddd1111DD'

# 定义要抓取的市场类型及其对应的按钮ID
MARKET_TYPES = {
    'HDP_OU': 'tab_rnou',  # 让球盘/大小球的按钮ID
    'CORNERS': 'tab_cn'    # 角球的按钮ID
}

# 创建Flask应用
app = Flask(__name__)

# 用于跟踪活跃的抓取线程
active_threads = []
thread_control_events = {}

def init_driver():
    chrome_options = Options()
    #chrome_options.add_argument('--headless')  # 无头模式（不显示浏览器界面）
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('--ignore-certificate-errors')
    chrome_options.add_argument('--allow-insecure-localhost')
    chrome_options.add_argument('--disable-extensions')
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    driver = webdriver.Chrome(options=chrome_options)
    # 隐藏webdriver属性，防止被网站检测到自动化工具
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
            'away_corners': ''   # 预留字段
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

def send_csv_as_json(csv_file_path, server_url, t, info):
    print(f"正在发送 {info} 数据...")
    try:
        # 循环发送数据
        while True:
            try:
                # 读取 CSV 文件
                data = pd.read_csv(csv_file_path)

                # 用空字符串替换 NaN 或 inf 值
                data = data.fillna("")  # 替换 NaN
                data = data.replace([float('inf'), float('-inf')], "")  # 替换 inf 和 -inf

                # 将数据转换为 JSON 格式
                json_data = data.to_dict(orient='records')

                # 发送数据
                headers = {'Content-Type': 'application/json'}
                response = requests.post(server_url, json=json_data, headers=headers)

                # 检查服务器响应
                if response.status_code == 200:
                    #print(f"{info} 数据成功发送到服务器: {server_url}")
                    pass
                else:
                    print(f"{info} 发送失败，状态码: {response.status_code}, 响应: {response.text}")

            except FileNotFoundError:
                print(f"文件未找到: {csv_file_path}")
            except Exception as e:
                #print(f"处理 CSV 文件时发生错误: {e}")
                pass

            # 等待指定时间间隔
            time.sleep(t)

    except Exception as e:
        print(f"发送数据时发生错误: {e}")

def run_scraper(account, market_type, scraper_id):
    # 设置默认值
    filename = f"{account['username']}_{market_type}_data.csv"
    interval = 0.3  # 默认抓取间隔（秒）

    stop_event = threading.Event()
    thread_control_events[scraper_id] = stop_event

    while not stop_event.is_set():
        driver = None
        try:
            driver = init_driver()
            with status_lock:
                thread_status[scraper_id] = "尝试登录..."

            if login(driver, account['username']):
                with status_lock:
                    thread_status[scraper_id] = "登录成功，导航到足球页面..."

                if navigate_to_football(driver):
                    with status_lock:
                        thread_status[scraper_id] = "导航到足球页面成功，尝试点击市场类型按钮..."

                    try:
                        # 点击指定的市场类型按钮
                        button = WebDriverWait(driver, 10).until(
                            EC.element_to_be_clickable((By.ID, MARKET_TYPES[market_type]))
                        )
                        button.click()
                        print(f"{account['username']} 已点击 {market_type} 按钮")

                        with status_lock:
                            thread_status[scraper_id] = f"已点击 {market_type} 按钮，开始抓取数据..."

                        # 等待页面加载
                        time.sleep(5)

                        # 启动发送CSV数据到服务器的线程
                        server_url = "http://yourserver.com/api/data"  # 替换为实际的服务器URL
                        info = f"{account['username']} - {market_type}"
                        sender_thread = threading.Thread(target=send_csv_as_json, args=(filename, server_url, interval, info), daemon=True)
                        sender_thread.start()

                        # 进入数据抓取循环
                        while not stop_event.is_set():
                            try:
                                soup = get_market_data(driver)
                                if soup:
                                    data = parse_market_data(soup, market_type)
                                    save_to_csv(data, filename)
                                    #print(f"{account['username']} 成功获取并保存数据")
                                else:
                                    print(f"{account['username']} 未获取到数据")
                            except Exception as e:
                                print(f"{account['username']} 抓取数据时发生错误: {e}")
                                traceback.print_exc()
                            time.sleep(interval)
                    except Exception as e:
                        print(f"{account['username']} 未找到市场类型按钮: {market_type}")
                        traceback.print_exc()
                        with status_lock:
                            thread_status[scraper_id] = f"未找到市场类型按钮: {market_type}。线程已关闭。"
                        break  # 退出循环，结束线程
                else:
                    with status_lock:
                        thread_status[scraper_id] = "未找到足球页面。线程已关闭。"
                    break  # 退出循环，结束线程
            else:
                with status_lock:
                    thread_status[scraper_id] = "登录失败。线程已关闭。"
                break  # 退出循环，结束线程
        except Exception as e:
            print(f"{account['username']} 运行过程中发生错误: {e}")
            traceback.print_exc()
            with status_lock:
                thread_status[scraper_id] = f"运行过程中发生错误: {e}。线程已关闭。"
            break  # 退出循环，结束线程
        finally:
            if driver:
                driver.quit()
                print(f"{account['username']} 已关闭浏览器")

        # 等待一段时间后重启抓取过程，避免过于频繁的重启
        print(f"{account['username']} 准备重新启动抓取线程...")
        with status_lock:
            thread_status[scraper_id] = "准备重新启动抓取线程..."
        time.sleep(5)  # 可根据需要调整等待时间

    # 清理线程控制事件和状态
    with status_lock:
        del thread_control_events[scraper_id]
        del thread_status[scraper_id]


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

    # 初始化线程状态
    with status_lock:
        thread_status[scraper_id] = "正在启动..."

    # 启动新的抓取线程
    scraper_thread = threading.Thread(target=run_scraper, args=(account, market_type, scraper_id), daemon=True)
    scraper_thread.start()

    # 将线程添加到活跃线程列表
    active_threads.append(scraper_thread)

    return jsonify({'status': 'success', 'message': f"已启动抓取线程: {username} - {market_type}", 'scraper_id': scraper_id}), 200


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
    if scraper_id in thread_control_events:
        thread_control_events[scraper_id].set()
        del thread_control_events[scraper_id]
        return jsonify({'status': 'success', 'message': f"已停止抓取线程: {scraper_id}"}), 200
    else:
        return jsonify({'status': 'error', 'message': f"未找到 scraper_id: {scraper_id}"}), 404

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
