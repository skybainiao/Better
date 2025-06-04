import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor
from flask import Flask, request, jsonify
from flask_cors import CORS
import os

# 数据库配置
DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "database": os.environ.get("DB_NAME", "postgres"),
    "user": os.environ.get("DB_USER", "postgres"),
    "password": os.environ.get("DB_PASSWORD", "cjj2468830035"),
    "port": os.environ.get("DB_PORT", 5432)
}

# 账号作用类型
ACCOUNT_TYPES = [
    "投注", "刷水", "单边", "配合单边虚拟假投注", "2网主投", "2网配合出货"
]


class AccountManager:
    def __init__(self):
        self.conn = None
        self.connect()
        self.create_tables()

    def connect(self):
        """连接到PostgreSQL数据库"""
        try:
            self.conn = psycopg2.connect(**DB_CONFIG)
            print("成功连接到数据库")
        except Exception as e:
            print(f"数据库连接失败: {e}")
            raise

    def create_tables(self):
        """创建必要的数据库表"""
        with self.conn.cursor() as cursor:
            # 创建分组表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS groups (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(100) NOT NULL UNIQUE
                )
            """)

            # 创建网址表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS websites (
                    id SERIAL PRIMARY KEY,
                    url VARCHAR(255) NOT NULL UNIQUE
                )
            """)

            # 创建账号表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS accounts (
                    id SERIAL PRIMARY KEY,
                    group_id INTEGER REFERENCES groups(id),
                    username VARCHAR(100) NOT NULL,
                    password VARCHAR(100) NOT NULL,
                    percentage NUMERIC(5, 2) NOT NULL CHECK (percentage BETWEEN 0 AND 100),
                    commission NUMERIC(5, 2) NOT NULL CHECK (commission BETWEEN 0 AND 100),
                    shareholder_dividend NUMERIC(5, 2) NOT NULL CHECK (shareholder_dividend BETWEEN 0 AND 100),
                    account_type VARCHAR(50) NOT NULL CHECK (account_type IN %s)
                )
            """, (tuple(ACCOUNT_TYPES),))

            # 创建账号-网址关联表（多对多关系）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS account_websites (
                    account_id INTEGER REFERENCES accounts(id),
                    website_id INTEGER REFERENCES websites(id),
                    PRIMARY KEY (account_id, website_id)
                )
            """)

            self.conn.commit()

    def add_group(self, name):
        """添加分组"""
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO groups (name) VALUES (%s) RETURNING id",
                    (name,)
                )
                group_id = cursor.fetchone()[0]
                self.conn.commit()
                return {"success": True, "data": {"id": group_id, "name": name}}
        except psycopg2.IntegrityError:
            self.conn.rollback()
            return {"success": False, "error": f"分组 '{name}' 已存在"}
        except Exception as e:
            self.conn.rollback()
            return {"success": False, "error": str(e)}

    def add_website(self, url):
        """添加网址"""
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO websites (url) VALUES (%s) RETURNING id",
                    (url,)
                )
                website_id = cursor.fetchone()[0]
                self.conn.commit()
                return {"success": True, "data": {"id": website_id, "url": url}}
        except psycopg2.IntegrityError:
            self.conn.rollback()
            print(f"网址 '{url}' 已存在")
            return self.get_website(url)
        except Exception as e:
            self.conn.rollback()
            return {"success": False, "error": str(e)}

    def get_website(self, url):
        """获取网址信息"""
        with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT * FROM websites WHERE url = %s", (url,))
            result = cursor.fetchone()
            return {"success": True, "data": result} if result else {"success": False, "error": "网址不存在"}

    def add_account(self, group_id, username, password, percentage, commission,
                    shareholder_dividend, account_type, website_urls):
        """添加账号（优化游标操作）"""
        try:
            with self.conn.cursor() as cursor:  # 单个游标处理所有操作
                # 检查分组是否存在
                cursor.execute("SELECT id FROM groups WHERE id = %s", (group_id,))
                if not cursor.fetchone():
                    return {"success": False, "error": f"分组 ID {group_id} 不存在"}

                # 检查账号类型是否有效
                if account_type not in ACCOUNT_TYPES:
                    return {"success": False, "error": f"无效的账号类型: {account_type}"}

                # 插入账号信息
                cursor.execute("""
                    INSERT INTO accounts (group_id, username, password, percentage, 
                                        commission, shareholder_dividend, account_type)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (group_id, username, password, percentage, commission,
                      shareholder_dividend, account_type))
                account_id = cursor.fetchone()[0]  # 获取账号ID

                # 添加关联的网址（同一游标操作）
                for url in website_urls:
                    # 先查询网址是否存在
                    cursor.execute("SELECT id FROM websites WHERE url = %s", (url,))
                    website_id = cursor.fetchone()

                    if website_id:
                        website_id = website_id[0]  # 存在则直接使用ID
                    else:
                        # 不存在则插入新网址并获取ID
                        cursor.execute(
                            "INSERT INTO websites (url) VALUES (%s) RETURNING id",
                            (url,)
                        )
                        website_id = cursor.fetchone()[0]

                    # 插入账号-网址关联
                    cursor.execute(
                        "INSERT INTO account_websites (account_id, website_id) VALUES (%s, %s)",
                        (account_id, website_id)
                    )

                self.conn.commit()  # 统一提交事务

                # 返回完整的账号信息
                return self.get_account(account_id)

        except Exception as e:
            self.conn.rollback()
            return {"success": False, "error": str(e)}

    def update_account(self, account_id, **kwargs):
        """更新账号信息"""
        if not kwargs:
            return {"success": False, "error": "没有提供要更新的数据"}

        with self.conn.cursor() as cursor:
            # 检查账号是否存在
            cursor.execute("SELECT id FROM accounts WHERE id = %s", (account_id,))
            if not cursor.fetchone():
                return {"success": False, "error": f"账号 ID {account_id} 不存在"}

            # 检查账号类型是否有效（如果提供了）
            if "account_type" in kwargs and kwargs["account_type"] not in ACCOUNT_TYPES:
                return {"success": False, "error": f"无效的账号类型: {kwargs['account_type']}"}

            # 构建SQL更新语句
            update_stmt = sql.SQL("UPDATE accounts SET {} WHERE id = %s").format(
                sql.SQL(', ').join(
                    sql.Identifier(key) + sql.SQL(' = %s')
                    for key in kwargs.keys()
                )
            )

            # 准备参数
            params = list(kwargs.values()) + [account_id]

            try:
                cursor.execute(update_stmt, params)
                self.conn.commit()
                return self.get_account(account_id)
            except Exception as e:
                self.conn.rollback()
                return {"success": False, "error": str(e)}

    def delete_account(self, account_id):
        """删除账号"""
        with self.conn.cursor() as cursor:
            # 检查账号是否存在
            cursor.execute("SELECT id FROM accounts WHERE id = %s", (account_id,))
            if not cursor.fetchone():
                return {"success": False, "error": f"账号 ID {account_id} 不存在"}

            try:
                # 先删除关联的网址
                cursor.execute("DELETE FROM account_websites WHERE account_id = %s", (account_id,))

                # 再删除账号
                cursor.execute("DELETE FROM accounts WHERE id = %s", (account_id,))

                self.conn.commit()
                return {"success": True, "message": f"账号 ID {account_id} 已删除"}
            except Exception as e:
                self.conn.rollback()
                return {"success": False, "error": str(e)}

    def get_account(self, account_id):
        """获取单个账号信息"""
        with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
                SELECT a.*, g.name as group_name
                FROM accounts a
                LEFT JOIN groups g ON a.group_id = g.id
                WHERE a.id = %s
            """, (account_id,))
            account = cursor.fetchone()

            if not account:
                return {"success": False, "error": f"账号 ID {account_id} 不存在"}

            # 获取关联的网址
            cursor.execute("""
                SELECT w.url
                FROM account_websites aw
                JOIN websites w ON aw.website_id = w.id
                WHERE aw.account_id = %s
            """, (account_id,))
            account['websites'] = [row['url'] for row in cursor.fetchall()]

            return {"success": True, "data": account}

    def list_accounts(self, group_id=None):
        """列出所有账号或指定分组的账号"""
        with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
            if group_id:
                # 检查分组是否存在
                cursor.execute("SELECT id FROM groups WHERE id = %s", (group_id,))
                if not cursor.fetchone():
                    return {"success": False, "error": f"分组 ID {group_id} 不存在"}

                cursor.execute("""
                    SELECT a.*, g.name as group_name
                    FROM accounts a
                    LEFT JOIN groups g ON a.group_id = g.id
                    WHERE a.group_id = %s
                """, (group_id,))
            else:
                cursor.execute("""
                    SELECT a.*, g.name as group_name
                    FROM accounts a
                    LEFT JOIN groups g ON a.group_id = g.id
                """)

            accounts = cursor.fetchall()

            # 获取每个账号关联的网址
            for account in accounts:
                cursor.execute("""
                    SELECT w.url
                    FROM account_websites aw
                    JOIN websites w ON aw.website_id = w.id
                    WHERE aw.account_id = %s
                """, (account['id'],))
                account['websites'] = [row['url'] for row in cursor.fetchall()]

            return {"success": True, "data": accounts}

    def list_groups(self):
        """列出所有分组"""
        with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT * FROM groups")
            return {"success": True, "data": cursor.fetchall()}

    def close(self):
        """关闭数据库连接"""
        if self.conn:
            self.conn.close()
            print("数据库连接已关闭")


def insert_test_data():
    """插入测试账号数据"""
    manager = AccountManager()

    # 添加测试分组
    groups = {
        "VIP组": manager.add_group("VIP组"),
        "普通组": manager.add_group("普通组"),
        "高级组": manager.add_group("高级组")
    }

    # 检查分组是否成功添加
    valid_groups = {name: data["data"]["id"] for name, data in groups.items() if data["success"]}
    if not valid_groups:
        print("无法添加测试分组")
        return

    # 添加测试网址
    websites = [
        "https://site1.com",
        "https://site2.com",
        "https://site3.com",
        "https://site4.com",
        "https://site5.com"
    ]

    # 添加测试账号
    test_accounts = [
        {
            "group_id": valid_groups["VIP组"],
            "username": "vip_user1",
            "password": "vip_pass1",
            "percentage": 90.0,
            "commission": 15.0,
            "shareholder_dividend": 8.0,
            "account_type": "投注",
            "website_urls": [websites[0], websites[1]]
        },
        {
            "group_id": valid_groups["VIP组"],
            "username": "vip_user2",
            "password": "vip_pass2",
            "percentage": 85.0,
            "commission": 12.0,
            "shareholder_dividend": 7.0,
            "account_type": "2网主投",
            "website_urls": [websites[2], websites[3]]
        },
        {
            "group_id": valid_groups["普通组"],
            "username": "normal_user1",
            "password": "normal_pass1",
            "percentage": 70.0,
            "commission": 8.0,
            "shareholder_dividend": 5.0,
            "account_type": "刷水",
            "website_urls": [websites[1], websites[4]]
        },
        {
            "group_id": valid_groups["普通组"],
            "username": "normal_user2",
            "password": "normal_pass2",
            "percentage": 75.0,
            "commission": 9.0,
            "shareholder_dividend": 5.5,
            "account_type": "单边",
            "website_urls": [websites[0], websites[3]]
        },
        {
            "group_id": valid_groups["高级组"],
            "username": "premium_user1",
            "password": "premium_pass1",
            "percentage": 95.0,
            "commission": 18.0,
            "shareholder_dividend": 10.0,
            "account_type": "2网配合出货",
            "website_urls": [websites[2], websites[4]]
        }
    ]

    # 插入测试账号
    for account in test_accounts:
        result = manager.add_account(
            account["group_id"],
            account["username"],
            account["password"],
            account["percentage"],
            account["commission"],
            account["shareholder_dividend"],
            account["account_type"],
            account["website_urls"]
        )

        if result["success"]:
            print(f"成功添加测试账号: {account['username']} (ID: {result['data']['id']})")
        else:
            print(f"添加测试账号失败: {account['username']} - {result['error']}")

    print("测试数据插入完成")
    manager.close()

# 创建Flask应用
app = Flask(__name__)
CORS(app)  # 启用CORS，允许跨域请求
account_manager = AccountManager()


# 分组API
@app.route('/api/groups', methods=['POST'])
def api_add_group():
    data = request.json
    name = data.get('name')
    if not name:
        return jsonify({"success": False, "error": "缺少分组名称"}), 400

    result = account_manager.add_group(name)
    if result["success"]:
        return jsonify(result), 201
    else:
        return jsonify(result), 400


@app.route('/api/groups', methods=['GET'])
def api_list_groups():
    result = account_manager.list_groups()
    return jsonify(result)


# 账号API
@app.route('/api/accounts', methods=['POST'])
def api_add_account():
    data = request.json

    group_id = data.get('group_id')
    username = data.get('username')
    password = data.get('password')
    percentage = data.get('percentage')
    commission = data.get('commission')
    shareholder_dividend = data.get('shareholder_dividend')
    account_type = data.get('account_type')
    website_urls = data.get('websites', [])

    # 验证必填字段
    if not all([group_id, username, password, percentage, commission,
                shareholder_dividend, account_type, website_urls]):
        return jsonify({"success": False, "error": "缺少必要字段"}), 400

    # 转换数据类型
    try:
        group_id = int(group_id)
        percentage = float(percentage)
        commission = float(commission)
        shareholder_dividend = float(shareholder_dividend)
    except ValueError:
        return jsonify({"success": False, "error": "无效的数值类型"}), 400

    result = account_manager.add_account(
        group_id, username, password, percentage, commission,
        shareholder_dividend, account_type, website_urls
    )

    if result["success"]:
        return jsonify(result), 201
    else:
        return jsonify(result), 400


@app.route('/api/accounts', methods=['GET'])
def api_list_accounts():
    group_id = request.args.get('group_id')
    if group_id:
        try:
            group_id = int(group_id)
        except ValueError:
            return jsonify({"success": False, "error": "无效的分组ID"}), 400
        result = account_manager.list_accounts(group_id)
    else:
        result = account_manager.list_accounts()

    return jsonify(result)


@app.route('/api/accounts/<int:account_id>', methods=['GET'])
def api_get_account(account_id):
    result = account_manager.get_account(account_id)
    if result["success"]:
        return jsonify(result)
    else:
        return jsonify(result), 404


@app.route('/api/accounts/<int:account_id>', methods=['PUT'])
def api_update_account(account_id):
    data = request.json

    # 提取并验证数据
    update_data = {}

    if 'group_id' in data:
        try:
            update_data['group_id'] = int(data['group_id'])
        except ValueError:
            return jsonify({"success": False, "error": "无效的分组ID"}), 400

    if 'username' in data:
        update_data['username'] = data['username']

    if 'password' in data:
        update_data['password'] = data['password']

    if 'percentage' in data:
        try:
            update_data['percentage'] = float(data['percentage'])
        except ValueError:
            return jsonify({"success": False, "error": "无效的成数值"}), 400

    if 'commission' in data:
        try:
            update_data['commission'] = float(data['commission'])
        except ValueError:
            return jsonify({"success": False, "error": "无效的佣金值"}), 400

    if 'shareholder_dividend' in data:
        try:
            update_data['shareholder_dividend'] = float(data['shareholder_dividend'])
        except ValueError:
            return jsonify({"success": False, "error": "无效的股东分红值"}), 400

    if 'account_type' in data:
        if data['account_type'] not in ACCOUNT_TYPES:
            return jsonify({"success": False, "error": "无效的账号类型"}), 400
        update_data['account_type'] = data['account_type']

    # 处理网址更新
    if 'websites' in data:
        website_urls = data['websites']
        if not isinstance(website_urls, list):
            return jsonify({"success": False, "error": "网址必须是列表类型"}), 400

        # 先删除原有关联
        with account_manager.conn.cursor() as cursor:
            cursor.execute("DELETE FROM account_websites WHERE account_id = %s", (account_id,))

            # 添加新关联
            for url in website_urls:
                website_result = account_manager.add_website(url)
                if website_result["success"]:
                    website_id = website_result["data"]["id"]
                    cursor.execute(
                        "INSERT INTO account_websites (account_id, website_id) VALUES (%s, %s)",
                        (account_id, website_id)
                    )
                else:
                    account_manager.conn.rollback()
                    return jsonify(website_result), 400

            account_manager.conn.commit()

    if not update_data and 'websites' not in data:
        return jsonify({"success": False, "error": "没有提供要更新的数据"}), 400

    result = account_manager.update_account(account_id, **update_data)
    return jsonify(result)


@app.route('/api/accounts/<int:account_id>', methods=['DELETE'])
def api_delete_account(account_id):
    result = account_manager.delete_account(account_id)
    if result["success"]:
        return jsonify(result)
    else:
        return jsonify(result), 404


if __name__ == "__main__":
    insert_test_data()
    app.run(debug=True, host='0.0.0.0', port=5000)