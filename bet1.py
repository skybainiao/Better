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
from flask_cors import CORS  # 导入CORS模块
logging.getLogger('werkzeug').setLevel(logging.ERROR)


# 用于跟踪抓取线程状态
thread_status = {}
status_lock = threading.Lock()
# 登录页面的 URL
BASE_URL = 'https://mos011.com/'
# 固定密码
username = 'caafbb22'
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
CORS(app)  # 启用CORS支持
# 忽略 InsecureRequestWarning（可选）
warnings.simplefilter('ignore', InsecureRequestWarning)
# 2) 盘口映射表
ratio_mapping = {
            '0.0': '0', '-0.25': '-0/0.5', '-0.5': '-0.5', '-0.75': '-0.5/1',
            '-1': '-1', '-1.25': '-1/1.5', '-1.5': '-1.5', '-1.75': '-1.5/2',
            '-2': '-2', '-2.25': '-2/2.5', '-2.5': '-2.5', '-2.75': '-2.5/3',
            '-3': '-3', '-3.25': '-3/3.5', '-3.5': '-3.5', '-3.75': '-3.5/4',
            '-4': '-4',
            '0.25': '0/0.5', '0.5': '0.5', '0.75': '0.5/1',
            '1': '1', '1.25': '1/1.5', '1.5': '1.5', '1.75': '1.5/2',
            '2': '2', '2.25': '2/2.5', '2.5': '2.5', '2.75': '2.5/3',
            '3': '3', '3.25': '3/3.5', '3.5': '3.5', '3.75': '3.5/4',
            '4': '4', '4.25': '4/4.5', '4.5': '4.5', '4.75': '4.5/5',
            '5': '5', '5.25': '5/5.5', '5.5': '5.5', '5.75': '5.5/6',
            '6': '6', '6.25': '6/6.5', '6.5': '6.5', '6.75': '6.5/7',
            '7': '7', '7.25': '7/7.5', '7.5': '7.5', '7.75': '7.5/8',
            '8': '8', '8.25': '8/8.5', '8.5': '8.5', '8.75': '8.5/9',
            '9': '9', '9.25': '9/9.5', '9.5': '9.5', '9.75': '9.5/10',
            '10': '10',
            '10.25': '10/10.5', '10.5': '10.5', '10.75': '10.5/11',
            '11': '11', '11.25': '11/11.5', '11.5': '11.5', '11.75': '11.5/12',
            '12': '12', '12.25': '12/12.5', '12.5': '12.5', '12.75': '12.5/13',
            '13': '13', '13.25': '13/13.5', '13.5': '13.5', '13.75': '13.5/14',
            '14': '14', '14.25': '14/14.5', '14.5': '14.5', '14.75': '14.5/15',
            '15': '15'
        }


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Mozilla/5.0 (X11; Linux x86_64)",
    # 添加更多的User-Agent字符串
]



def init_driver():
    """初始化Chrome浏览器驱动"""
    print("初始化浏览器驱动...")
    chrome_options = Options()
    #chrome_options.add_argument('--headless')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('--ignore-certificate-errors')
    chrome_options.add_argument('--allow-insecure-localhost')
    chrome_options.add_argument('--disable-extensions')
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    d = webdriver.Chrome(options=chrome_options)
    # 隐藏webdriver属性以防被检测
    d.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
        'source': '''
                Object.defineProperty(navigator, 'webdriver', {
                  get: () => undefined
                })
            '''
    })
    return d


def login(driver):
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
        time.sleep(3)  # 等页面渲染一会儿，以便弹窗出现

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



        # 6) 等待导航到足球页面成功
        wait.until(EC.element_to_be_clickable((By.ID, 'today_page')))
        print(f"{username} 登录成功")
        return True

    except Exception as e:
        print(f"{username} 登录失败或未找到滚球比赛: {e}")
        traceback.print_exc()
        return False


def navigate_to_football(driver):
    wait = WebDriverWait(driver, 150)
    # --- 新增：先尝试点击弹窗 OK 按钮 ---
    try:
        # 如果在 3 秒内可以找到并点击到 OK 按钮，就点击
        ok_button = WebDriverWait(driver, 3).until(
            EC.element_to_be_clickable((By.ID, 'close_btn1'))
        )
        ok_button.click()
        time.sleep(1)  # 稍作等待，确保弹窗完全消失
        print("系统消息弹窗已关闭")
    except TimeoutException:
        # 若找不到该按钮就跳过
        pass

    try:
        football_btn = wait.until(EC.element_to_be_clickable((By.ID, 'today_page')))
        football_btn.click()
        # 等待页面加载完成
        wait.until(EC.visibility_of_element_located((By.ID, 'div_show')))
        wait.until(EC.visibility_of_element_located((By.CLASS_NAME, 'btn_title_le')))
        button = wait.until(EC.element_to_be_clickable((By.ID, 'tab_rnou')))
        button.click()

        print("导航到足球页面成功")
        return True
    except Exception as e:
        print(f"导航到足球页面失败: {e}")
        traceback.print_exc()
        return False

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


def click_odds(driver, alert, bet_amount):
    # 初始化完整的回执信息结构
    receipt = {
        'menutype': '',
        'score': '',
        'league': '',
        'team_h': '',
        'team_c': '',
        'chose_team': '',
        'chose_con': '',
        'ior': '',
        'stake': '',
        'win_gold': '',
        'tid': '',
        'order_result': '未知'
    }

    try:
        # 1) 从 alert 中提取必要数据
        league_name = alert.get('league_name', '').strip()
        home_team = alert.get('home_team', '').strip()
        away_team = alert.get('away_team', '').strip()
        bet_type_name = alert.get('bet_type_name', '').strip()
        odds_name = alert.get('odds_name', '').strip()

        # 参数校验
        required_fields = ['league_name', 'home_team', 'away_team', 'bet_type_name', 'odds_name']
        for field in required_fields:
            if not alert.get(field):
                print(f"错误: 缺少必要参数 '{field}'")
                receipt['order_result'] = f"错误: 缺少必要参数 '{field}'"
                return receipt

        # 3) 解析 bet_type_name
        bet_type_parts = bet_type_name.split('_')
        if len(bet_type_parts) < 3:
            print(f"无法解析 bet_type_name: {bet_type_name}")
            receipt['order_result'] = f"无法解析盘口类型: {bet_type_name}"
            return receipt

        if bet_type_parts[0] == 'TOTAL' and bet_type_parts[1] == 'POINTS':
            if len(bet_type_parts) < 4:
                print(f"无法解析 bet_type_name: {bet_type_name}")
                receipt['order_result'] = f"无法解析盘口类型: {bet_type_name}"
                return receipt
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
                receipt['order_result'] = f"未知投注方向: {odds_name}"
                return receipt
        elif bet_type == 'TOTAL_POINTS':
            market_section = 'Goals O/U'
            odds_type = None
        else:
            print(f"忽略非处理盘口类型: {bet_type}")
            receipt['order_result'] = f"不支持的盘口类型: {bet_type}"
            return receipt

        # 5) 映射 ratio
        if ratio not in ratio_mapping:
            print(f"未定义的 ratio 映射: {bet_type}{ratio}")
            receipt['order_result'] = f"未知盘口值: {ratio}"
            return receipt
        mapped_ratio = ratio_mapping[ratio]
        ballhead_text = mapped_ratio  # 初始赋值

        # 让分盘补+号（关键修复点）
        if market_section == 'Handicap':
            if ratio.startswith('-'):
                pass  # 负数，已带 -
            elif ratio == '0.0':
                ballhead_text = '0'  # 平手特殊处理
            else:
                # 正数 => 保留+号，与HTML中的文本一致
                ballhead_text = f"+{mapped_ratio}" if not ballhead_text.startswith('-') else ballhead_text
            print(f"[Handicap] 最终球头文本: {ballhead_text}")
        else:
            # 大小球盘 OverOdds / UnderOdds
            if odds_name == 'OverOdds':
                pass  # 你可定义 ballou_text='O'，再做其他操作
            elif odds_name == 'UnderOdds':
                pass
            else:
                print(f"未知的 odds_name: {odds_name}")
                receipt['order_result'] = f"未知投注方向: {odds_name}"
                return receipt
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
        print(f"构造联赛XPath: {league_xpath}")
        league_elements = driver.find_elements(By.XPATH, league_xpath)
        print(f"联赛 '{league_name}' 找到 {len(league_elements)} 个元素(可能折叠/展开)")

        if not league_elements:
            print(f"未找到联赛: {league_name}")
            receipt['order_result'] = f"未找到联赛: {league_name}"
            return receipt

        # 用于判断是否最终找到并点击成功
        found_match = False

        # 7) 遍历联赛
        for league_element in league_elements:
            try:
                # 找到其所有比赛
                game_xpath = ".//following-sibling::div[starts-with(@id, 'game_') and contains(@class, 'box_lebet')]"
                print(f"构造比赛XPath: {game_xpath}")
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
                                print(f"成功点击联赛展开按钮: {league_name}")
                                # 等待页面更新
                                time.sleep(1)
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

                            # 填充基本回执信息
                            receipt['league'] = league_name
                            receipt['team_h'] = home_team
                            receipt['team_c'] = away_team

                            # 再次用 game_id 定位
                            match_xpath = f"//div[@id='{game_id}']"
                            bet_section_xpath = (
                                f"{match_xpath}//div[contains(@class, 'form_lebet_hdpou') "
                                f"and .//span[text()='{market_section}']]"
                            )
                            print(f"构造盘口XPath: {bet_section_xpath}")
                            try:
                                bet_section_element = driver.find_element(By.XPATH, bet_section_xpath)
                                print(f"找到盘口类型: {market_section}")
                                receipt['menutype'] = market_section
                            except NoSuchElementException:
                                print(f"未找到盘口: {market_section} in 比赛 {home_team} vs {away_team}")
                                receipt['order_result'] = f"未找到盘口类型: {market_section}"
                                continue

                            # 7.3 拼出赔率按钮 XPath
                            if market_section == 'Handicap':
                                if odds_type == 'Home':
                                    print(f"[DEBUG] 主队赔率按钮ID后缀: _RH")
                                    odds_button_xpath = (
                                        f"{match_xpath}//div[contains(@class, 'btn_hdpou_odd') "
                                        f"and contains(@id, '_RH') "
                                        f"and .//tt[@class='text_ballhead' and text()='{ballhead_text}']]"
                                    )
                                    receipt['chose_team'] = home_team
                                else:  # 'Away'
                                    print(f"[DEBUG] 客队赔率按钮ID后缀: _RC")
                                    odds_button_xpath = (
                                        f"{match_xpath}//div[contains(@class, 'btn_hdpou_odd') "
                                        f"and contains(@id, '_RC') "
                                        f"and .//tt[@class='text_ballhead' and text()='{ballhead_text}']]"
                                    )
                                    receipt['chose_team'] = away_team
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
                                    receipt['chose_team'] = '大球'
                                else:
                                    odds_button_xpath = (
                                        f"{match_xpath}//div[contains(@class, 'btn_hdpou_odd') "
                                        f"and .//tt[@class='text_ballou' and text()='U'] "
                                        f"and .//tt[@class='text_ballhead' and text()='{ballhead_text}']]"
                                    )
                                    receipt['chose_team'] = '小球'
                            receipt['chose_con'] = ballhead_text
                            print(f"构造赔率按钮XPath: {odds_button_xpath}")

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
                                    print(f"尝试查找赔率按钮 (尝试{attempt + 1}/3): {odds_button_xpath}")
                                    odds_buttons = driver.find_elements(By.XPATH, odds_button_xpath)
                                    if not odds_buttons:
                                        print(f"[{attempt + 1}/3] 未找到赔率按钮 => {ballhead_text}, {odds_name}")
                                        # 输出页面截图辅助调试
                                        try:
                                            driver.save_screenshot(f"odds_not_found_attempt_{attempt + 1}.png")
                                            print(f"已保存页面截图: odds_not_found_attempt_{attempt + 1}.png")
                                        except Exception as e:
                                            print(f"保存截图失败: {e}")
                                        time.sleep(0.5)
                                        continue

                                    odds_button = odds_buttons[0]
                                    driver.execute_script("arguments[0].scrollIntoView(true);", odds_button)
                                    print(f"已滚动到赔率按钮 (尝试{attempt + 1}/3)")

                                    # 检查元素是否可见
                                    is_displayed = odds_button.is_displayed()
                                    is_enabled = odds_button.is_enabled()
                                    print(f"赔率按钮状态: 可见={is_displayed}, 可点击={is_enabled}")

                                    WebDriverWait(driver, 5).until(
                                        EC.element_to_be_clickable(odds_button)
                                    ).click()

                                    print(
                                        f"点击成功: 联赛='{league_name}', 比赛='{home_team} vs {away_team}', "
                                        f"盘口='{market_section}', 比例='{ballhead_text}', 赔率='{odds_name}'"
                                    )

                                    # 传递回执对象到弹窗处理函数
                                    handle_bet_popup(driver, bet_amount, alert, receipt)

                                    clicked_ok = True
                                    break
                                except Exception as e:
                                    print(f"点击失败({attempt + 1}/3): {e}")
                                    # 输出页面截图辅助调试
                                    try:
                                        driver.save_screenshot(f"click_failed_attempt_{attempt + 1}.png")
                                        print(f"已保存页面截图: click_failed_attempt_{attempt + 1}.png")
                                    except Exception as e:
                                        print(f"保存截图失败: {e}")
                                    time.sleep(1)

                            if clicked_ok:
                                return receipt  # 成功点击后立即返回回执信息
                            else:
                                print(f"连续3次点击仍失败 => {ballhead_text}, {odds_name}")
                                receipt['order_result'] = f"无法点击{market_section}盘口 {ballhead_text}"
                                return receipt

                    except (StaleElementReferenceException, NoSuchElementException) as e:
                        print(f"比赛 {idx} 解析时出错: {e}")
                        continue
            except StaleElementReferenceException as e:
                print(f"联赛元素失效: {e}")
                continue

        # 若走到这里还没 return，说明没点成功
        if not found_match:
            print(f"在联赛 '{league_name}' 中未找到比赛: {home_team} vs {away_team}")
            receipt['order_result'] = f"未找到比赛: {home_team} vs {away_team}"
            return receipt

    except Exception as e:
        print(f"点击赔率按钮失败: {e}")
        receipt['order_result'] = f"投注异常: {str(e)}"
        # 输出完整堆栈跟踪
        import traceback
        traceback.print_exc()
        return receipt


def handle_bet_popup(driver, bet_amount, alert, receipt):
    # print("弹窗")

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
            popup_ratio_clean = popup_ratio_clean.lstrip('+')
        except NoSuchElementException:
            print("未找到 bet_chose_con 元素，无法对比盘口，继续投注逻辑。")
            popup_ratio_clean = ""  # 找不到就给个空字符串

        # 2) 从 alert 中解析出原始 ratio，并用 ratio_mapping 转成弹窗格式
        alert_bet_type = alert.get('bet_type_name', '')  # "SPREAD_FT_5.25" 等
        # 拆分得到最后一个是 ratio_str
        ratio_str = alert_bet_type.split('_')[-1] if '_' in alert_bet_type else ''
        mapped_ratio = ratio_mapping.get(ratio_str, '')  # 转换成类似 "5/5.5" 形式

        # 去掉其中空格
        mapped_ratio_clean = mapped_ratio.replace(' ', '')

        # 3) 对比弹窗中的 ratio 是否与 alert 中一致
        if mapped_ratio_clean and popup_ratio_clean and (mapped_ratio_clean != popup_ratio_clean):
            print(f"弹窗盘口 {popup_ratio_clean} 与 Alert 盘口 {mapped_ratio_clean} 不一致，取消投注。")
            receipt['order_result'] = f"盘口不匹配: 预期 {mapped_ratio_clean}，实际 {popup_ratio_clean}"
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
                receipt['order_result'] = "未找到投注金额输入框"
                return

        # 点击并输入金额
        input_field.click()
        input_field.clear()
        bet_amount_int = int(float(bet_amount))
        input_field.send_keys(str(bet_amount_int))
        receipt['stake'] = f"{bet_amount_int}"
        print(f"已在初始弹窗中输入金额: {bet_amount_int}")

        # 2. 找到“PLACE BET”按钮并点击
        try:
            place_bet_button = wait.until(EC.element_to_be_clickable((By.ID, 'order_bet')))
            print("找到 PLACE BET 按钮。")
        except TimeoutException:
            print("找不到 PLACE BET 按钮，放弃。")
            receipt['order_result'] = "未找到确认投注按钮"
            return

        place_bet_button.click()
        print("已点击 PLACE BET 按钮，等待跳转到投注回执弹窗...")

        # 3. 等待出现“receipt”弹窗
        try:
            receipt_popup = wait.until(
                EC.visibility_of_element_located(
                    (By.XPATH, "//div[@id='bet_show' and contains(@class,'receipt')]")
                )
            )
            print("已出现投注回执弹窗 (receipt)。")
        except TimeoutException:
            print("投注回执弹窗未出现，放弃。")
            receipt['order_result'] = "投注回执未显示"
            return

        # 4. 在回执弹窗中提取信息
        try:
            # 直接在回执弹窗内查找下单结果信息
            order_msg_div = receipt_popup.find_element(By.ID, 'orderMsg_div')
            order_result = order_msg_div.find_element(By.XPATH, ".//li").text.strip()
            receipt['order_result'] = order_result
            print(f"下单结果: {order_result}")
        except NoSuchElementException:
            print("未找到下单结果信息元素")
            receipt['order_result'] = "未知结果"

        try:
            receipt['menutype'] = receipt_popup.find_element(By.ID, 'bet_finish_menutype').text.strip()
            receipt['score'] = receipt_popup.find_element(By.ID, 'bet_finish_score').text.strip()
            receipt['league'] = receipt_popup.find_element(By.ID, 'bet_finish_league').text.strip()
            receipt['team_h'] = receipt_popup.find_element(By.ID, 'bet_finish_team_h').text.strip()
            receipt['team_c'] = receipt_popup.find_element(By.ID, 'bet_finish_team_c').text.strip()
            receipt['chose_team'] = receipt_popup.find_element(By.ID, 'bet_finish_chose_team').text.strip()
            receipt['chose_con'] = receipt_popup.find_element(By.ID, 'bet_finish_chose_con').text.strip()
            receipt['ior'] = receipt_popup.find_element(By.ID, 'bet_finish_ior').text.strip()
            receipt['win_gold'] = receipt_popup.find_element(By.ID, 'bet_finish_win_gold').text.strip()
            receipt['tid'] = receipt_popup.find_element(By.ID, 'bet_finish_tid').text.strip()

            # 计算潜在回报（如果没有提供）
            if not receipt['win_gold'] and receipt['ior'] and receipt['stake']:
                try:
                    receipt['win_gold'] = f"{float(receipt['stake']) * float(receipt['ior']):.2f}"
                except:
                    pass

            print("=== 投注回执信息 ===")
            for key, value in receipt.items():
                print(f"{key}: {value}")
            print("==================")
        except NoSuchElementException as e:
            print(f"提取回执信息时出现问题: {e}")

        # 5. 点击“OK”按钮关闭弹窗
        try:
            ok_button = WebDriverWait(receipt_popup, 10).until(
                EC.element_to_be_clickable((By.ID, 'finishBtn_show'))
            )
            ok_button.click()
            print("已点击 OK 按钮，关闭回执弹窗。")
        except TimeoutException:
            print("未找到 OK 按钮，或点击失败。")

    except Exception as e:
        print(f"处理投注流程时发生错误: {e}")
        receipt['order_result'] = f"处理投注弹窗时出错: {str(e)}"
    finally:
        close_bet_popup(driver)


def auto_close_popups(driver):
    """
    自动检测页面中常见的单按钮(OK)弹窗和强制登出弹窗，并点击对应的OK按钮。
    根据你的页面结构，这里列出了可能的OK按钮ID列表。
    """
    try:
        wait = WebDriverWait(driver, 30)  # 短等待时间检测
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


def close_bet_popup(driver):
    """
    检测投注弹窗是否存在，如果存在则点击关闭按钮（id="order_close"），
    确保投注弹窗结束。该方法应在投注操作结束后调用。
    """
    try:
        # 设置等待时间，比如 5 秒
        wait = WebDriverWait(driver, 5)
        # 等待"order_close"按钮可点击
        close_button = wait.until(EC.element_to_be_clickable((By.ID, "finishBtn_show")))
        driver.execute_script("arguments[0].scrollIntoView(true);", close_button)
        close_button.click()
        print("[ClosePopup] 投注弹窗已自动关闭。")
        # 关闭后稍等以确保弹窗完全消失
        time.sleep(0.5)
    except TimeoutException:
        print("[ClosePopup] 未检测到投注弹窗关闭按钮。")
    except Exception as e:
        print(f"[ClosePopup] 关闭投注弹窗时出错: {e}")


def monitor_page_status(driver, stop_event, market_type):
    while not stop_event.is_set():
        time.sleep(60)  # 每2分钟检测一次
        try:
            found_soccer = element_exists(driver, "//span[text()='Soccer']")
            button_id = MARKET_TYPES[market_type]  # 正常盘口 => tab_rnou, 角球盘口 => tab_cn
            found_tab = element_exists(driver, f"//*[@id='{button_id}']")
        except Exception as e:
            print(f"monitor_page_status 检测时出错: 退出监控线程。")
            break  # 出现异常则退出循环

        # 如果 Soccer 和对应按钮都消失，则尝试重新登录
        if not found_soccer and not found_tab:
            re_login(driver, market_type)



def element_exists(driver, xpath):
    try:
        driver.find_element(By.XPATH, xpath)
        return True
    except NoSuchElementException:
        return False
    except Exception as e:
        print(f"[element_exists] 出现异常, xpath: {xpath}")
        return False


def re_login(driver, market_type):
    # 刷新页面或直接get
    driver.get(BASE_URL)

    if login(driver):
        if navigate_to_football(driver):
            # 再点击对应market_type按钮
            try:
                button = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.ID, MARKET_TYPES[market_type]))
                )
                button.click()
            except:
                pass
        else:
            print("重新登录后无法 navigate_to_football。")
    else:
        print("re_login 失败。")


def start():
    global driver, stop_event  # 添加 stop_event 为全局变量
    try:
        # 初始化驱动
        driver = init_driver()

        # 登录流程
        if not login(driver):
            print("登录失败，退出程序")
            return

        # 导航到足球页面
        if not navigate_to_football(driver):
            print("导航失败，退出程序")
            return

        # -------------------- 新增线程启动代码 --------------------
        # 创建线程终止信号
        stop_event = threading.Event()

        # 启动弹窗监控线程（含 auto_close_popups 功能）
        popup_thread = threading.Thread(
            target=popup_monitor,
            args=(driver, stop_event),
            daemon=True  # 守护线程，随主线程退出
        )
        popup_thread.start()
        print("弹窗监控线程已启动")

        # 启动页面状态监控线程（需指定默认 market_type）
        default_market_type = next(iter(MARKET_TYPES.keys()))  # 取第一个市场类型
        monitor_thread = threading.Thread(
            target=monitor_page_status,
            args=(driver, stop_event, default_market_type),
            daemon=True
        )
        monitor_thread.start()
        print(f"页面状态监控线程已启动（监控市场类型：{default_market_type}）")

    except Exception as e:
        print(f"启动过程中发生错误: {e}")
        stop_event.set()  # 出错时触发线程终止




@app.route('/receive_signal', methods=['POST'])
def receive_signal():
    global driver  # 使用全局浏览器驱动

    try:
        # 解析请求数据
        data = request.get_json()
        if not data:
            return jsonify({'status': 'error', 'message': 'No JSON data provided'}), 400

        # 提取alert和bet_amount参数
        alert = data.get('alert')
        bet_amount = data.get('bet_amount')

        # 参数校验
        if not alert:
            return jsonify({'status': 'error', 'message': 'Missing "alert" parameter'}), 400
        if not bet_amount or not isinstance(bet_amount, (int, float)):
            return jsonify({'status': 'error', 'message': 'Missing or invalid "bet_amount" parameter'}), 400

        # 校验alert中的必要字段
        required_fields = ['league_name', 'home_team', 'away_team', 'bet_type_name', 'odds_name']
        for field in required_fields:
            if field not in alert:
                return jsonify({'status': 'error', 'message': f'Missing required field "{field}" in alert'}), 400

        # 映射market_type用于后续处理
        market_type = map_alert_to_market_type(alert)
        if not market_type:
            return jsonify({'status': 'error', 'message': 'Failed to map market type from alert'}), 400

        # 检查market_type是否在支持范围内
        if market_type not in MARKET_TYPES:
            return jsonify({'status': 'error', 'message': f'Unsupported market type: {market_type}'}), 400

        # 检查浏览器驱动是否初始化
        if not driver:
            return jsonify({'status': 'error', 'message': 'Browser driver not initialized'}), 500

        # 记录日志
        logging.info(f"Received betting signal: {alert}, bet_amount: {bet_amount}")

        # 调用投注函数并获取完整回执信息
        receipt = click_odds(driver, alert, bet_amount)

        return jsonify({
            'status': 'success',
            'message': 'Betting signal processed',
            'market_type': market_type,
            'receipt': receipt  # 返回完整回执信息
        }), 200

    except Exception as e:
        logging.error(f"Error processing betting signal: {str(e)}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': f'Internal server error: {str(e)}'
        }), 500



if __name__ == "__main__":
    start()
    app.run(host='0.0.0.0', port=5031)