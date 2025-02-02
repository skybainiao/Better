#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
独立测试脚本，用于测试 modify_alert_for_category1 函数的输出。
不会影响你现有主程序逻辑，可单独运行。
"""

import copy
import threading

category_lock = threading.Lock()
category_status = {
    # 示例随意，如需真实测试，你应写和主程序中一致的状态
    "全场让分盘客队涨水": "半场小分盘",
    "全场让分盘主队涨水": "半场小分盘",
    "半场让分盘客队涨水": "半场小分盘",
    "半场让分盘主队涨水": "半场小分盘",
    "全场大分盘涨水": "半场小分盘",
    "全场小分盘涨水": "半场小分盘",
    "半场大分盘涨水": "半场小分盘",
    "半场小分盘涨水": "半场小分盘",
}


def modify_alert_for_category(alert):
    print("[DEBUG] modify_alert_for_category1 => new version loaded!")  # DEBUG

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


def run_test():
    # 准备一些测试用例，每条是一个dict
    test_data = [
        {
            "desc": "测试1: SPREAD_FT_-0.5 + HomeOdds => 全场让分盘客队涨水",
            "alert": {
                "bet_type_name": "SPREAD_FT_-0.5",
                "odds_name": "HomeOdds",
                "match_type": "normal"
            }
        },
        {
            "desc": "测试2: SPREAD_FT_-1.0 + AwayOdds => 全场让分盘主队涨水",
            "alert": {
                "bet_type_name": "SPREAD_FT_-1.0",
                "odds_name": "AwayOdds",
                "match_type": "normal"
            }
        },
        {
            "desc": "测试3: TOTAL_POINTS_FT_2.5 + UnderOdds => 全场大分盘涨水",
            "alert": {
                "bet_type_name": "TOTAL_POINTS_FT_2.5",
                "odds_name": "UnderOdds",
                "match_type": "normal"
            }
        },
        {
            "desc": "测试3: TOTAL_POINTS_FT_2.5 + OverOdds => 全场小分盘涨水",
            "alert": {
                "bet_type_name": "TOTAL_POINTS_FT_2.5",
                "odds_name": "OverOdds",
                "match_type": "normal"
            }
        },
        {
            "desc": "测试4: SPREAD_1H_0.0 + AwayOdds => 半场让分盘主队涨水",
            "alert": {
                "bet_type_name": "SPREAD_1H_0.0",
                "odds_name": "AwayOdds",
                "match_type": "normal"
            }
        },
        {
            "desc": "测试4: SPREAD_1H_0.0 + HomeOdds => 半场让分盘客队涨水",
            "alert": {
                "bet_type_name": "SPREAD_1H_0.0",
                "odds_name": "HomeOdds",
                "match_type": "normal"
            }
        },
        {
            "desc": "测试5: TOTAL_POINTS_1H_2.0 + UnderOdds => 半场大分盘涨水",
            "alert": {
                "bet_type_name": "TOTAL_POINTS_1H_2.0",
                "odds_name": "UnderOdds",
                "match_type": "normal"
            }
        },
        {
            "desc": "测试5: TOTAL_POINTS_1H_2.0 + OverOdds => 半场小分盘涨水",
            "alert": {
                "bet_type_name": "TOTAL_POINTS_1H_2.0",
                "odds_name": "OverOdds",
                "match_type": "normal"
            }
        },
        {
            "desc": "测试6: Corner 情况，不会进入 normal 分支",
            "alert": {
                "bet_type_name": "SPREAD_FT_-0.5",
                "odds_name": "HomeOdds",
                "match_type": "corner"
            }
        },
    ]

    print("=== 开始测试 modify_alert_for_category1 ===\n")
    for idx, item in enumerate(test_data, start=1):
        case_desc = item["desc"]
        raw_alert = item["alert"]
        # 为了安全，先复制一份
        test_alert = copy.deepcopy(raw_alert)

        print(f"--- 测试用例 {idx}: {case_desc} ---")
        print(f"原始 alert = {test_alert}")
        result_alert = modify_alert_for_category(test_alert)
        print(f"处理后 alert = {result_alert}\n")


if __name__ == "__main__":
    run_test()
