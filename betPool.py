import os
from flask import Flask, request, jsonify
import requests
import json
from flask_cors import CORS
import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import random
from flask_apscheduler import APScheduler

app = Flask(__name__)
CORS(app)

# 数据库配置
DB_CONFIG = {
    "host": "localhost",
    "database": "postgres",
    "user": "postgres",
    "password": "cjj2468830035",
    "port": 5432
}

# 目标服务器配置
TARGET_SERVER = "http://103.67.53.34:5031"
TARGET_PATH = "/receive_signal"
TARGET_URL = f"{TARGET_SERVER}{TARGET_PATH}"

# 新增最小时间间隔配置（秒）
MIN_SHIPPING_INTERVAL = 30
# 最小调度延迟（防止立即执行的任务被忽略）
MIN_SCHEDULE_DELAY = 1  # 至少延迟1秒


# 调度器配置
class Config:
    SCHEDULER_API_ENABLED = True
    SCHEDULER_TIMEZONE = 'Asia/Shanghai'
    # 关键配置：确保调度器只在主进程中运行
    SCHEDULER_EXECUTORS = {
        'default': {'type': 'threadpool', 'max_workers': 20}
    }
    SCHEDULER_JOB_DEFAULTS = {
        'coalesce': False,
        'max_instances': 3
    }


app.config.from_object(Config)
scheduler = APScheduler()
scheduler.init_app(app)

# 确保调度器只在主进程中启动（避免调试模式下重复启动）
if __name__ == '__main__' and not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
    scheduler.start()
    print("APScheduler已启动")


def create_tables():
    """创建数据库表，使用自增序列作为主键"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        with conn.cursor() as cursor:
            # 创建请求表（ID改为SERIAL，新增status字段）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS betting_requests (
                    id SERIAL PRIMARY KEY,
                    request_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status VARCHAR(20) DEFAULT '未出货',  -- 新增状态字段
                    -- alert对象拆分
                    alert_league_name VARCHAR(255) NOT NULL,
                    alert_home_team VARCHAR(100) NOT NULL,
                    alert_away_team VARCHAR(100) NOT NULL,
                    alert_bet_type_name VARCHAR(50) NOT NULL,
                    alert_odds_name VARCHAR(50) NOT NULL,
                    alert_match_type VARCHAR(50),
                    alert_odds_value NUMERIC(5,2),
                    -- 根级字段
                    bet_amount NUMERIC(10,2) NOT NULL,
                    alert_type VARCHAR(20) NOT NULL,
                    -- 原始数据
                    raw_data JSONB NOT NULL
                )
            """)

            # 创建响应表（ID改为SERIAL，request_id类型调整为INTEGER）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS betting_responses (
                    id SERIAL PRIMARY KEY,
                    request_id INTEGER NOT NULL REFERENCES betting_requests(id),
                    response_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status_code INTEGER NOT NULL,
                    -- 根级字段
                    response_market_type VARCHAR(50),
                    response_message TEXT,
                    response_status VARCHAR(20) NOT NULL,
                    -- receipt对象拆分
                    receipt_chose_con VARCHAR(20),
                    receipt_chose_team VARCHAR(100),
                    receipt_ior NUMERIC(5,2),
                    receipt_league VARCHAR(255),
                    receipt_menutype VARCHAR(50),
                    receipt_order_result TEXT,
                    receipt_score VARCHAR(50),
                    receipt_stake NUMERIC(10,2),
                    receipt_team_c VARCHAR(100),
                    receipt_team_h VARCHAR(100),
                    receipt_tid VARCHAR(50),
                    receipt_win_gold NUMERIC(10,2),
                    -- 原始响应
                    raw_response JSONB NOT NULL
                )
            """)

            # 出货配置表（保持不变）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS shipping_config (
                    id SERIAL PRIMARY KEY,
                    wait_minutes INTEGER DEFAULT 5,
                    ship_minutes INTEGER DEFAULT 10,
                    ship_times INTEGER DEFAULT 5,
                    is_random BOOLEAN DEFAULT FALSE,
                    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 出货任务表（ID改为SERIAL，request_id和config_id类型调整为INTEGER）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS shipping_tasks (
                    id SERIAL PRIMARY KEY,
                    request_id INTEGER NOT NULL REFERENCES betting_requests(id),
                    config_id INTEGER NOT NULL REFERENCES shipping_config(id),
                    total_amount NUMERIC(10,2) NOT NULL,
                    processed_amount NUMERIC(10,2) DEFAULT 0,
                    status VARCHAR(20) DEFAULT 'pending',
                    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    start_time TIMESTAMP,
                    complete_time TIMESTAMP
                )
            """)

            # 出货记录表（ID改为SERIAL，task_id类型调整为INTEGER）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS shipping_records (
                    id SERIAL PRIMARY KEY,
                    task_id INTEGER NOT NULL REFERENCES shipping_tasks(id),
                    amount NUMERIC(10,2) NOT NULL,
                    send_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status VARCHAR(20) NOT NULL,
                    response_data JSONB
                )
            """)

            # 插入默认配置
            cursor.execute("""
                INSERT INTO shipping_config (id, wait_minutes, ship_minutes, ship_times, is_random)
                VALUES (1, 5, 10, 5, FALSE)
                ON CONFLICT (id) DO NOTHING
            """)

        conn.commit()
    except Exception as e:
        print(f"创建数据库表失败: {str(e)}")
    finally:
        if conn:
            conn.close()


def save_request_data(data):
    """保存完全拆分的请求数据（返回自增ID）"""
    alert = data.get('alert', {})
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        with conn.cursor() as cursor:
            cursor.execute(
                """INSERT INTO betting_requests (
                    alert_league_name, alert_home_team, alert_away_team, 
                    alert_bet_type_name, alert_odds_name, alert_match_type, alert_odds_value,
                    bet_amount, alert_type, raw_data
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id""",  # 返回自增ID，状态字段使用默认值
                (alert.get('league_name'),
                 alert.get('home_team'),
                 alert.get('away_team'),
                 alert.get('bet_type_name'),
                 alert.get('odds_name'),
                 alert.get('match_type'),
                 alert.get('odds_value'),
                 data.get('bet_amount'),
                 data.get('alert_type'),
                 json.dumps(data))
            )
            request_id = cursor.fetchone()[0]  # 获取自增ID
        conn.commit()
        return request_id
    except Exception as e:
        print(f"保存请求数据失败: {str(e)}")
        return None
    finally:
        if conn:
            conn.close()


def save_response_data(request_id, status_code, response_data):
    """保存完全拆分的响应数据"""
    receipt = response_data.get('receipt', {})
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        with conn.cursor() as cursor:
            cursor.execute(
                """INSERT INTO betting_responses (
                    request_id, status_code, response_market_type, 
                    response_message, response_status, receipt_chose_con, 
                    receipt_chose_team, receipt_ior, receipt_league, 
                    receipt_menutype, receipt_order_result, receipt_score, 
                    receipt_stake, receipt_team_c, receipt_team_h, 
                    receipt_tid, receipt_win_gold, raw_response
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (request_id,  # 直接使用整数ID
                 status_code,
                 response_data.get('market_type'),
                 response_data.get('message'),
                 response_data.get('status'),
                 receipt.get('chose_con'),
                 receipt.get('chose_team'),
                 float(receipt.get('ior')) if receipt.get('ior') else None,
                 receipt.get('league'),
                 receipt.get('menutype'),
                 receipt.get('order_result'),
                 receipt.get('score'),
                 float(receipt.get('stake')) if receipt.get('stake') else None,
                 receipt.get('team_c'),
                 receipt.get('team_h'),
                 receipt.get('tid'),
                 float(receipt.get('win_gold')) if receipt.get('win_gold') else None,
                 json.dumps(response_data))
            )
        conn.commit()
    except Exception as e:
        print(f"保存响应数据失败: {str(e)}")
    finally:
        if conn:
            conn.close()


def get_shipping_config():
    """获取当前出货配置"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT * FROM shipping_config WHERE id = 1")
            return cursor.fetchone()
    except Exception as e:
        print(f"获取出货配置失败: {str(e)}")
        return None
    finally:
        if conn:
            conn.close()


def update_shipping_config(config):
    """更新出货配置"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE shipping_config 
                SET wait_minutes = %(wait_minutes)s,
                    ship_minutes = %(ship_minutes)s,
                    ship_times = %(ship_times)s,
                    is_random = %(is_random)s,
                    update_time = CURRENT_TIMESTAMP
                WHERE id = 1
            """, config)
        conn.commit()
        return True
    except Exception as e:
        print(f"更新出货配置失败: {str(e)}")
        return False
    finally:
        if conn:
            conn.close()


def create_shipping_task(request_id, total_amount):
    """创建出货任务"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO shipping_tasks (request_id, config_id, total_amount)
                VALUES (%s, 1, %s)
                RETURNING id""",  # 返回自增ID
                (request_id, total_amount)
            )
            task_id = cursor.fetchone()[0]
        conn.commit()
        print(f"[出货任务创建] 任务ID: {task_id}, 关联请求ID: {request_id}, 总金额: {total_amount}")
        return task_id
    except Exception as e:
        print(f"创建出货任务失败: {str(e)}")
        return None
    finally:
        if conn:
            conn.close()


def record_shipping(task_id, amount, status, response_data=None):
    """记录出货结果"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO shipping_records (task_id, amount, status, response_data)
                VALUES (%s, %s, %s, %s)
            """, (task_id, amount, status, json.dumps(response_data)))

            # 更新任务已处理金额
            cursor.execute("""
                UPDATE shipping_tasks
                SET processed_amount = processed_amount + %s,
                    status = CASE 
                        WHEN processed_amount + %s >= total_amount THEN 'completed'
                        ELSE status
                    END,
                    complete_time = CASE 
                        WHEN processed_amount + %s >= total_amount THEN CURRENT_TIMESTAMP
                        ELSE complete_time
                    END
                WHERE id = %s
            """, (amount, amount, amount, task_id))
        conn.commit()
        print(f"[出货记录] 任务ID: {task_id}, 金额: {amount}, 状态: {status}")
    except Exception as e:
        print(f"记录出货结果失败: {str(e)}")
    finally:
        if conn:
            conn.close()


def calculate_shipping_plan(config, total_amount):
    """计算出货计划 - 确定每笔出货的金额和时间"""
    # 保持原有逻辑不变
    ship_times = config['ship_times']
    ship_minutes = config['ship_minutes']
    is_random = config['is_random']

    # 计算每笔金额
    if is_random:
        # 随机金额分配
        amounts = []
        remaining = total_amount
        for i in range(ship_times - 1):
            if remaining <= 0:
                amount = 0
            else:
                # 确保每笔金额至少为0.01，最后一笔补足剩余金额
                max_amount = remaining - 0.01 * (ship_times - i - 1)
                amount = round(random.uniform(0.01, max_amount), 2)
            amounts.append(amount)
            remaining -= amount
        amounts.append(round(remaining, 2))  # 最后一笔补足
    else:
        # 平均分配
        base_amount = round(total_amount / ship_times, 2)
        amounts = [base_amount] * ship_times
        # 调整最后一笔金额，确保总和正确
        total_calculated = sum(amounts)
        if total_calculated != total_amount:
            amounts[-1] += total_amount - total_calculated
            amounts[-1] = round(amounts[-1], 2)

    # 计算每笔出货的延迟时间（秒），确保最小间隔为MIN_SHIPPING_INTERVAL
    total_seconds = ship_minutes * 60

    if ship_times == 1:
        # 只有一笔时，设置为最小调度延迟
        intervals = [MIN_SCHEDULE_DELAY]
    else:
        # 计算理论最大间隔（确保能在ship_minutes内完成）
        max_possible_interval = total_seconds / (ship_times - 1)
        # 如果理论最大间隔小于最小间隔，使用最小间隔，否则使用理论最大间隔
        step = max(MIN_SHIPPING_INTERVAL, max_possible_interval)
        # 生成等间隔时间点，从最小调度延迟开始
        intervals = [int(MIN_SCHEDULE_DELAY + i * step) for i in range(ship_times)]

        # 随机化时间点，但保持最小间隔
        if is_random and total_seconds > MIN_SHIPPING_INTERVAL * (ship_times - 1):
            # 可随机调整的总空间
            total_adjustable = total_seconds - MIN_SHIPPING_INTERVAL * (ship_times - 1)
            # 为每个间隔生成随机调整量
            adjustments = [random.randint(0, total_adjustable // (ship_times - 1)) for _ in range(ship_times - 1)]
            # 应用调整并确保递增且最小间隔
            new_intervals = [MIN_SCHEDULE_DELAY]
            for i in range(ship_times - 1):
                prev = new_intervals[-1]
                new_time = prev + MIN_SHIPPING_INTERVAL + adjustments[i]
                # 确保不超过总时间
                new_time = min(new_time, total_seconds - (ship_times - i - 1) * MIN_SHIPPING_INTERVAL)
                new_intervals.append(new_time)
            intervals = new_intervals

    # 新增打印出货计划
    print(f"[出货计划生成] 总笔数: {ship_times}, 随机分配: {is_random}")
    for idx, (amt, delay) in enumerate(zip(amounts, intervals)):
        print(f"  第{idx + 1}笔: 金额 {amt}, 延迟 {delay}秒")

    return [(amounts[i], intervals[i]) for i in range(ship_times)]


def execute_shipping(task_id, amount, request_data, headers):
    """执行单笔出货"""
    print(f"[开始执行出货] 任务ID: {task_id}, 金额: {amount}")
    try:
        # 更新请求数据中的金额
        request_data['bet_amount'] = amount

        # 转发请求至目标服务器
        # 直接使用传入的 headers，而不是从全局 request 对象获取
        headers = {k: v for k, v in headers.items() if k != 'Host'}
        headers['Host'] = TARGET_SERVER.split('//')[1]

        response = requests.post(
            TARGET_URL,
            headers=headers,
            json=request_data,
            timeout=60
        )

        try:
            response_json = response.json()
            status = 'success' if response.status_code == 200 else 'failed'
            record_shipping(task_id, amount, status, response_json)
            print(f"[出货响应] 任务ID: {task_id}, 状态码: {response.status_code}, 响应数据: {response_json}")
        except json.JSONDecodeError:
            status = 'failed'
            record_shipping(task_id, amount, status, response.text)
            print(
                f"[出货响应] 任务ID: {task_id}, 状态码: {response.status_code}, 原始响应: {response.text[:500]}")

        return status, response.status_code, response.text

    except Exception as e:
        print(f"执行出货失败: {str(e)}")
        status = 'error'
        record_shipping(task_id, amount, status, str(e))
        return status, 500, str(e)
    finally:
        print(f"[出货完成] 任务ID: {task_id}, 金额: {amount}")


def schedule_shipping_task(task_id, request_data):
    """安排出货任务计划"""
    try:
        # 获取当前配置
        config = get_shipping_config()
        if not config:
            config = {
                'wait_minutes': 5,
                'ship_minutes': 10,
                'ship_times': 5,
                'is_random': False
            }
            print("[警告] 使用默认出货配置")

        total_amount = request_data.get('bet_amount', 0)
        print(f"[任务调度开始] 任务ID: {task_id}, 总金额: {total_amount}")
        if total_amount < 250:
            print('无效金额')
            return False, print('无效金额')

        # 计算出货计划
        shipping_plan = calculate_shipping_plan(config, total_amount)
        print(f"[任务调度] 生成{len(shipping_plan)}笔出货计划")

        # 获取当前时间
        now = datetime.now()

        # 计算实际开始出货的时间点（等待时间结束后）
        start_time = now + timedelta(minutes=config['wait_minutes'])

        # 更新任务开始时间
        conn = psycopg2.connect(**DB_CONFIG)
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE shipping_tasks
                    SET status = 'scheduled',
                        start_time = %s
                    WHERE id = %s
                """, (start_time, task_id))  # 使用整数ID
            conn.commit()
            print(
                f"[任务状态更新] 任务ID: {task_id}, 状态设置为scheduled, 计划开始时间: {start_time}")
        finally:
            if conn:
                conn.close()

        # 保存当前请求的 headers
        headers = {k: v for k, v in request.headers.items()}

        # 安排出货任务
        for i, (amount, delay_seconds) in enumerate(shipping_plan):
            # 计算执行时间：开始时间 + 延迟
            run_time = start_time + timedelta(seconds=delay_seconds)
            print(f"[任务调度] 第{i + 1}笔出货, 金额: {amount}, 计划执行时间: {run_time}")

            # 添加任务，确保至少有最小延迟
            scheduler.add_job(
                func=execute_shipping,
                id=f"shipping_{task_id}_{i}",  # 任务ID仍使用字符串标识
                trigger='date',
                run_date=run_time,
                args=[task_id, amount, request_data, headers]
            )
            print(f"[任务添加成功] ID: shipping_{task_id}_{i}, 执行时间: {run_time}")

        return True, f"已安排 {len(shipping_plan)} 笔出货任务"

    except Exception as e:
        print(f"安排出货任务失败: {str(e)}")
        return False, str(e)


@app.route('/shipping/config', methods=['GET', 'POST'])
def shipping_config():
    """获取或更新出货配置"""
    if request.method == 'GET':
        config = get_shipping_config()
        if config:
            return jsonify(config)
        else:
            return jsonify({"error": "获取配置失败"}), 500
    elif request.method == 'POST':
        new_config = request.get_json()
        if update_shipping_config(new_config):
            print(f"[配置更新] 新配置: {new_config}")
            return jsonify({"message": "配置更新成功"})
        else:
            return jsonify({"error": "配置更新失败"}), 500
    return None


@app.route('/shipping/tasks/<int:task_id>', methods=['GET'])
def get_shipping_task(task_id):  # 路径参数明确为整数
    """获取出货任务状态"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # 获取任务信息
            cursor.execute("""
                SELECT * FROM shipping_tasks WHERE id = %s
            """, (task_id,))  # 使用整数ID
            task = cursor.fetchone()

            if not task:
                return jsonify({"error": "任务不存在"}), 404

            # 获取任务记录
            cursor.execute("""
                SELECT * FROM shipping_records WHERE task_id = %s
                ORDER BY send_time ASC
            """, (task_id,))  # 使用整数ID
            records = cursor.fetchall()

            return jsonify({
                "task": task,
                "records": records
            })
    except Exception as e:
        print(f"获取任务状态失败: {str(e)}")
        return jsonify({"error": "获取任务状态失败"}), 500
    finally:
        if conn:
            conn.close()


@app.route('/proxy_bet_request', methods=['POST', 'OPTIONS'])
def proxy_request():
    # 处理跨域预检请求
    if request.method == 'OPTIONS':
        headers = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'POST',
            'Access-Control-Allow-Headers': 'Content-Type',
        }
        return jsonify({}), 200, headers

    try:
        # 1. 解析前端发送的JSON数据
        client_data = request.get_json(force=True)
        alert_type = client_data.get('alert_type')

        # 2. 打印接收到的原始数据
        print("中间件接收到的原始数据：")
        print(json.dumps(client_data, indent=2))

        # 保存请求数据到数据库
        request_id = save_request_data(client_data)

        # 3. 根据alert_type处理请求
        if alert_type == 'first':
            # 执行现有逻辑
            return process_first_type_request(client_data, request_id)
        elif alert_type == 'second':
            # 处理出货信号
            print(f"[接收到出货信号] 请求ID: {request_id}, 总金额: {client_data.get('bet_amount')}")
            return process_second_type_request(client_data, request_id)
        else:
            error_response = {
                "status": "error",
                "message": f"不支持的alert_type: {alert_type}"
            }
            if request_id:
                save_response_data(request_id, 400, error_response)
            return jsonify(error_response), 400

    except requests.exceptions.RequestException as e:
        print(f"网络请求异常: {str(e)}")
        error_response = {
            "status": "error",
            "message": f"网络转发失败：{str(e)}"
        }
        if request_id:
            save_response_data(request_id, 503, error_response)
        return jsonify(error_response), 503
    except json.JSONDecodeError:
        print("JSON解析错误：无法解析请求数据")
        error_response = {
            "status": "error",
            "message": "无效的JSON数据"
        }
        if request_id:
            save_response_data(request_id, 400, error_response)
        return jsonify(error_response), 400
    except Exception as e:
        print(f"未知异常: {str(e)}")
        error_response = {
            "status": "error",
            "message": f"处理请求时发生未知错误：{str(e)}"
        }
        if request_id:
            save_response_data(request_id, 500, error_response)
        return jsonify(error_response), 500


@app.route('/betting/requests/pending', methods=['GET'])
def get_pending_requests():
    """获取所有未出货的投注请求"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
                SELECT 
                    br.id,  -- 确保返回id字段
                    br.request_time,
                    br.status,
                    br.alert_league_name AS league_name,
                    br.alert_home_team AS home_team,
                    br.alert_away_team AS away_team,
                    br.alert_bet_type_name AS bet_type_name,
                    br.alert_odds_name AS odds_name,
                    br.alert_odds_value AS odds_value,
                    br.bet_amount
                FROM betting_requests br
                WHERE br.status = '未出货'
                ORDER BY br.request_time DESC
            """)
            pending_requests = cursor.fetchall()

            return jsonify({
                "status": "success",
                "data": pending_requests
            })
    except Exception as e:
        print(f"获取未出货请求失败: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"获取未出货请求失败: {str(e)}"
        }), 500
    finally:
        if conn:
            conn.close()


@app.route('/betting/requests/<int:request_id>/responses', methods=['GET'])
def get_request_responses(request_id):
    """获取指定请求ID的所有响应信息"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # 查询请求信息（包含所有字段）
            cursor.execute("""
                SELECT 
                    id,
                    request_time,
                    status,
                    alert_league_name AS league_name,
                    alert_home_team AS home_team,
                    alert_away_team AS away_team,
                    alert_bet_type_name AS bet_type_name,
                    alert_odds_name AS odds_name,
                    alert_match_type AS match_type,
                    alert_odds_value AS odds_value,
                    bet_amount,
                    alert_type
                FROM betting_requests
                WHERE id = %s
            """, (request_id,))
            request = cursor.fetchone()

            if not request:
                return jsonify({
                    "status": "error",
                    "message": f"请求ID {request_id} 不存在"
                }), 404

            # 查询关联的响应信息（包含所有字段）
            cursor.execute("""
                SELECT 
                    id,
                    request_id,
                    response_time,
                    status_code,
                    response_market_type AS market_type,
                    response_message AS message,
                    response_status AS status,
                    receipt_chose_con,
                    receipt_chose_team,
                    receipt_ior,
                    receipt_league,
                    receipt_menutype,
                    receipt_order_result,
                    receipt_score,
                    receipt_stake,
                    receipt_team_c,
                    receipt_team_h,
                    receipt_tid,
                    receipt_win_gold
                FROM betting_responses
                WHERE request_id = %s
                ORDER BY response_time DESC
            """, (request_id,))
            responses = cursor.fetchall()

            return jsonify({
                "status": "success",
                "data": {
                    "request": request,
                    "responses": responses
                }
            })
    except Exception as e:
        print(f"获取请求响应失败: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"获取请求响应失败: {str(e)}"
        }), 500
    finally:
        if conn:
            conn.close()


def process_first_type_request(client_data, request_id):
    """处理first类型请求（原有逻辑）"""
    try:
        # 转发请求至目标服务器
        headers = {k: v for k, v in request.headers.items() if k != 'Host'}
        headers['Host'] = TARGET_SERVER.split('//')[1]

        response = requests.post(
            TARGET_URL,
            headers=headers,
            json=client_data,
            timeout=30
        )

        # 打印目标服务器的响应信息
        print("\n==== 目标服务器响应 ====")
        print(f"状态码: {response.status_code}")

        try:
            response_json = response.json()
            print("响应体(JSON):")
            print(json.dumps(response_json, indent=2))

            # 保存详细的响应数据
            if request_id:
                save_response_data(request_id, response.status_code, response_json)
        except json.JSONDecodeError:
            print("响应体(原始文本):")
            print(response.text[:500] + ('...' if len(response.text) > 500 else ''))

        print("======================\n")

        # 透传目标服务器的完整响应
        return (
            response.content,
            response.status_code,
            dict(response.headers)
        )
    except Exception as e:
        # 保持原有异常处理
        raise e


def process_second_type_request(client_data, request_id):
    """处理second类型请求（出货信号）"""
    try:
        # 创建出货任务
        total_amount = client_data.get('bet_amount')
        task_id = create_shipping_task(request_id, total_amount)

        if not task_id:
            error_response = {
                "status": "error",
                "message": "创建出货任务失败"
            }
            save_response_data(request_id, 500, error_response)
            return jsonify(error_response), 500

        print(f"[出货任务创建成功] 任务ID: {task_id}, 关联请求ID: {request_id}")

        # 异步执行出货计划
        schedule_shipping_task(task_id, client_data)

        # 立即返回接收成功的响应
        success_response = {
            "status": "success",
            "message": "出货信号已接收，将按配置执行出货计划",
            "task_id": task_id  # 返回整数ID
        }
        save_response_data(request_id, 202, success_response)
        return jsonify(success_response), 202

    except Exception as e:
        print(f"处理出货信号失败: {str(e)}")
        error_response = {
            "status": "error",
            "message": f"处理出货信号时发生错误：{str(e)}"
        }
        if request_id:
            save_response_data(request_id, 500, error_response)
        return jsonify(error_response), 500


# 应用启动时创建表
create_tables()

if __name__ == "__main__":
    # 禁用调试模式或正确配置
    # 注意：生产环境应使用适当的WSGI服务器，如Gunicorn或uWSGI
    app.run(host="0.0.0.0", port=5033, debug=False)
    print("带出货功能的中间件已启动，监听：http://localhost:5033/proxy_bet_request")
    print(f"目标服务器地址：{TARGET_URL}")