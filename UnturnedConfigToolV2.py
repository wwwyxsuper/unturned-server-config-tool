# -*- coding: utf-8 -*-
"""
Unturned 服务器配置工具 v2
==========================
基于 pywebview(WebView2) 的现代化图形界面，功能：
  - 中/英双语界面（设置中切换）
  - 可视化编辑 Config.json（全部参数）+ Commands.dat + WorkshopDownloadConfig.json
  - 新建实例一键模板（6 种预设）
  - 公网部署向导（GSLT / 端口 / 公网 IP / 端口映射 / 内网穿透 / 启动脚本）
"""

import datetime
import json
import os
import shutil
import socket
import sys
import threading
import urllib.request

import webview

APP_NAME = "Unturned 服务器配置工具"
APP_VERSION = "2.3.4"

# ---------------------------------------------------------------------------
# 基础 JSON / 文本读写（容忍 // 注释）
# ---------------------------------------------------------------------------

def strip_json_comments(text: str) -> str:
    out = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\":
                i += 1
                if i < n:
                    out.append(text[i])
            elif c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def load_json_file(path: str):
    with open(path, "r", encoding="utf-8-sig") as f:
        raw = f.read()
    return json.loads(strip_json_comments(raw))


def save_json_file(path: str, data) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def load_commands(path: str):
    """读取 Commands.dat。优先 UTF-8（带 BOM 兼容），失败时回退 GBK/ANSI，
    再失败返回空列表，绝不向调用方抛编码异常。"""
    if not os.path.isfile(path):
        return []
    raw = None
    for enc in ("utf-8-sig", "utf-8", "gbk", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as f:
                raw = f.read()
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    if raw is None:
        return []
    lines = [ln.rstrip("\r\n") for ln in raw.split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def save_commands(path: str, lines) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
        if lines:
            f.write("\n")


def backup_file(path: str):
    if not os.path.isfile(path):
        return None
    ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")  # 含毫秒，避免同秒覆盖
    bak = f"{path}.bak-{ts}"
    shutil.copy2(path, bak)
    return bak


# ---------------------------------------------------------------------------
# 参数翻译表（键名 -> 中文说明；英文模式显示键名 + 说明）
# ---------------------------------------------------------------------------

GROUP_NAMES = {
    "Browser": "服务器信息", "Server": "服务器网络", "UnityEvents": "Unity 事件",
    "Easy": "简单难度", "Normal": "普通难度", "Hard": "困难难度",
    "Items": "物品", "Vehicles": "载具", "Zombies": "僵尸", "Animals": "动物",
    "Barricades": "路障", "Structures": "建筑", "Players": "玩家",
    "Objects": "物体", "Events": "事件", "Gameplay": "玩法",
}

PARAM_NAMES = {
    # Browser
    "Icon": "服务器图标路径", "Thumbnail": "缩略图路径", "Desc_Hint": "简短描述",
    "Desc_Full": "完整描述", "Desc_Server_List": "服务器列表描述", "Login_Token": "登录令牌 (GSLT)",
    "BookmarkHost": "书签主机", "Is_Using_Anycast_Proxy": "使用任播代理",
    "Monetization": "货币化方式 (Unspecified/None/Items...)", "Links": "链接",
    # Server
    "VAC_Secure": "启用 VAC 反作弊", "BattlEye_Secure": "启用 BattlEye 反作弊",
    "Max_Ping_Milliseconds": "最大允许延迟 (毫秒)",
    "Timeout_Queue_Seconds": "排队超时 (秒)", "Timeout_Game_Seconds": "游戏内超时 (秒)",
    "Join_Rate_Limit_Window_Seconds": "加入速率限制窗口 (秒)",
    "Bad_Packet_Rate_Limit_Window_Seconds": "异常数据包限速窗口 (秒)",
    "Bad_Packet_Rate_Limit_Threshold": "异常数据包限速阈值",
    "Rate_Limit_Kick_Threshold": "限速踢出阈值",
    "Max_Clients_With_Same_IP_Address": "同一 IP 最大客户端数",
    "Max_Clients_With_Same_IP_Address_Log_Warnings": "同 IP 超限记录警告",
    "Fake_Lag_Threshold_Seconds": "假延迟阈值 (秒)", "Fake_Lag_Log_Warnings": "假延迟记录警告",
    "Fake_Lag_Damage_Penalty_Multiplier": "假延迟伤害惩罚倍率",
    "Enable_Kick_Input_Spam": "踢出刷屏输入玩家", "Enable_Kick_Input_Timeout": "踢出输入超时玩家",
    "Enable_Scheduled_Shutdown": "启用定时关机", "Scheduled_Shutdown_Time": "定时关机时间 (如 1:30 am)",
    "Scheduled_Shutdown_Warnings": "关机前警告时间点 (逗号分隔)",
    "Enable_Update_Shutdown": "更新时自动关机", "Update_Steam_Beta_Name": "更新 Steam 测试分支",
    "Update_Shutdown_Warnings": "更新关机前警告 (逗号分隔)",
    "Validate_EconInfo_Hash": "校验经济信息哈希", "Use_FakeIP": "使用假 IP",
    "Reset_Vehicles_Outside_Horizontal_Distance": "重置超出水平距离的载具",
    # UnityEvents
    "Allow_Server_Messages": "允许服务器消息", "Allow_Server_Commands": "允许服务器命令",
    "Allow_Client_Messages": "允许客户端消息", "Allow_Client_Commands": "允许客户端命令",
    # Items
    "Spawn_Chance": "物品生成概率", "Despawn_Dropped_Time": "掉落物品消失时间 (秒)",
    "Despawn_Natural_Time": "自然生成物品消失时间 (秒)", "Respawn_Time": "物品重生时间 (秒)",
    "Quality_Full_Chance": "满品质概率", "Quality_Multiplier": "品质倍率",
    "Gun_Bullets_Full_Chance": "枪械满弹匣概率", "Gun_Bullets_Multiplier": "枪械子弹倍率",
    "Magazine_Bullets_Full_Chance": "弹匣满弹概率", "Magazine_Bullets_Multiplier": "弹匣子弹倍率",
    "Crate_Bullets_Full_Chance": "箱子满弹概率", "Crate_Bullets_Multiplier": "箱子子弹倍率",
    "Has_Durability": "物品有耐久", "Food_Spawns_At_Full_Quality": "食物满品质生成",
    "Water_Spawns_At_Full_Quality": "水满品质生成", "Clothing_Spawns_At_Full_Quality": "衣物满品质生成",
    "Weapons_Spawn_At_Full_Quality": "武器满品质生成", "Default_Spawns_At_Full_Quality": "默认物品满品质生成",
    "Clothing_Has_Durability": "衣物有耐久", "Weapons_Have_Durability": "武器有耐久",
    # Vehicles
    "Decay_Time": "衰减时间 (秒)", "Decay_Damage_Per_Second": "每秒衰减伤害",
    "Has_Battery_Chance": "有电池概率", "Min_Battery_Charge": "电池最小电量",
    "Max_Battery_Charge": "电池最大电量", "Has_Tire_Chance": "有轮胎概率",
    "Unlocked_After_Seconds_In_Safezone": "安全区解锁所需秒数", "Armor_Multiplier": "护甲倍率",
    "Child_Explosion_Armor_Multiplier": "子爆炸护甲倍率",
    "Gun_Lowcal_Damage_Multiplier": "低口径枪伤倍率", "Gun_Highcal_Damage_Multiplier": "高口径枪伤倍率",
    "Melee_Damage_Multiplier": "近战伤害倍率", "Melee_Repair_Multiplier": "近战修复倍率",
    "Max_Instances_Tiny": "微型上限数量", "Max_Instances_Small": "小型上限数量",
    "Max_Instances_Medium": "中型上限数量", "Max_Instances_Large": "大型上限数量",
    "Max_Instances_Insane": "超大型上限数量", "Min_Natural_Vehicles": "自然生成载具最少数量",
    # Zombies
    "Loot_Chance": "掉落概率", "Crawler_Chance": "爬行僵尸概率", "Sprinter_Chance": "奔跑僵尸概率",
    "Flanker_Chance": "侧袭僵尸概率", "Burner_Chance": "燃烧僵尸概率", "Acid_Chance": "酸液僵尸概率",
    "Boss_Electric_Chance": "电系 Boss 概率", "Boss_Wind_Chance": "风系 Boss 概率",
    "Boss_Fire_Chance": "火系 Boss 概率", "Spirit_Chance": "幽灵概率",
    "DL_Red_Volatile_Chance": "红爆裂僵尸概率", "DL_Blue_Volatile_Chance": "蓝爆裂僵尸概率",
    "Boss_Elver_Stomper_Chance": "Elver 践踏 Boss 概率", "Boss_Kuwait_Chance": "Kuwait Boss 概率",
    "Respawn_Day_Time": "白天重生时间 (秒)", "Respawn_Night_Time": "夜晚重生时间 (秒)",
    "Respawn_Beacon_Time": "信标重生时间 (秒)", "Quest_Boss_Respawn_Interval": "任务 Boss 重生间隔 (秒)",
    "Damage_Multiplier": "伤害倍率", "Backstab_Multiplier": "背刺倍率",
    "NonHeadshot_Armor_Multiplier": "非爆头护甲倍率", "Beacon_Experience_Multiplier": "信标经验倍率",
    "Full_Moon_Experience_Multiplier": "满月经验倍率",
    "Min_Drops": "最少掉落数量", "Max_Drops": "最多掉落数量",
    "Min_Mega_Drops": "巨型最少掉落", "Max_Mega_Drops": "巨型最多掉落",
    "Min_Boss_Drops": "Boss 最少掉落", "Max_Boss_Drops": "Boss 最多掉落",
    "Slow_Movement": "僵尸移动缓慢", "Can_Stun": "僵尸可被击晕",
    "Only_Critical_Stuns": "仅暴击可击晕", "Weapons_Use_Player_Damage": "武器使用玩家伤害",
    "Can_Target_Barricades": "可攻击路障", "Can_Target_Structures": "可攻击建筑",
    "Can_Target_Vehicles": "可攻击载具", "Can_Target_Objects": "可攻击物体",
    "Beacon_Max_Rewards": "信标最大奖励数", "Beacon_Max_Participants": "信标最大参与人数",
    "Beacon_Rewards_Multiplier": "信标奖励倍率",
    # Barricades / Structures
    "Armor_Lowtier_Multiplier": "低级护甲倍率", "Armor_Hightier_Multiplier": "高级护甲倍率",
    "Allow_Item_Placement_On_Vehicle": "允许在载具上放置物品",
    "Allow_Trap_Placement_On_Vehicle": "允许在载具上放置陷阱",
    "Max_Item_Distance_From_Hull": "物品距船体最大距离", "Max_Trap_Distance_From_Hull": "陷阱距船体最大距离",
    # Players
    "Health_Default": "默认生命值", "Health_Regen_Min_Food": "回血所需最低食物值",
    "Health_Regen_Min_Water": "回血所需最低水分值", "Health_Regen_Ticks": "回血间隔 (tick)",
    "Food_Default": "默认食物值", "Food_Use_Ticks": "食物消耗间隔 (tick)",
    "Food_Damage_Ticks": "饥饿伤害间隔 (tick)", "Water_Default": "默认水分值",
    "Water_Use_Ticks": "水分消耗间隔 (tick)", "Water_Damage_Ticks": "缺水伤害间隔 (tick)",
    "Virus_Default": "默认病毒值", "Virus_Infect": "病毒感染阈值",
    "Virus_Use_Ticks": "病毒消耗间隔 (tick)", "Virus_Damage_Ticks": "病毒伤害间隔 (tick)",
    "Leg_Regen_Ticks": "腿部恢复间隔 (tick)", "Bleed_Damage_Ticks": "流血伤害间隔 (tick)",
    "Bleed_Regen_Ticks": "止血恢复间隔 (tick)",
    "Experience_Multiplier": "经验倍率", "Detect_Radius_Multiplier": "探测半径倍率",
    "Ray_Aggressor_Distance": "射线攻击者距离",
    "Lose_Skills_PvP": "PvP 技能损失倍率", "Lose_Skills_PvE": "PvE 技能损失倍率",
    "Lose_Skill_Levels_PvP": "PvP 技能等级损失", "Lose_Skill_Levels_PvE": "PvE 技能等级损失",
    "Lose_Experience_PvP": "PvP 经验损失倍率", "Lose_Experience_PvE": "PvE 经验损失倍率",
    "Lose_Items_PvP": "PvP 物品损失倍率", "Lose_Items_PvE": "PvE 物品损失倍率",
    "Lose_Clothes_PvP": "PvP 掉落衣物", "Lose_Clothes_PvE": "PvE 掉落衣物",
    "Lose_Weapons_PvP": "PvP 掉落武器", "Lose_Weapons_PvE": "PvE 掉落武器",
    "Can_Hurt_Legs": "可伤害腿部", "Can_Break_Legs": "可打断腿", "Can_Fix_Legs": "可固定腿伤",
    "Can_Start_Bleeding": "会开始流血", "Can_Stop_Bleeding": "可止血",
    "Spawn_With_Max_Skills": "出生即满技能", "Spawn_With_Stamina_Skills": "出生即满耐力技能",
    "Allow_Instakill_Headshots": "允许爆头秒杀", "Allow_Per_Character_Saves": "按角色独立存档",
    "Enable_Terrain_Color_Kick": "地形颜色校验踢出",
    # Objects
    "Binary_State_Reset_Multiplier": "开关状态重置倍率", "Fuel_Reset_Multiplier": "燃料重置倍率",
    "Water_Reset_Multiplier": "水源重置倍率", "Resource_Reset_Multiplier": "资源重置倍率",
    "Resource_Drops_Multiplier": "资源掉落倍率", "Rubble_Reset_Multiplier": "瓦砾重置倍率",
    "Allow_Holiday_Drops": "允许节日掉落", "Items_Obstruct_Tree_Respawns": "物品阻碍树木重生",
    # Events
    "Rain_Frequency_Min": "下雨频率最小值", "Rain_Frequency_Max": "下雨频率最大值",
    "Rain_Duration_Min": "下雨最短持续", "Rain_Duration_Max": "下雨最长持续",
    "Snow_Frequency_Min": "下雪频率最小值", "Snow_Frequency_Max": "下雪频率最大值",
    "Snow_Duration_Min": "下雪最短持续", "Snow_Duration_Max": "下雪最长持续",
    "Weather_Frequency_Multiplier": "天气频率倍率", "Weather_Duration_Multiplier": "天气时长倍率",
    "Airdrop_Frequency_Min": "空投最小频率", "Airdrop_Frequency_Max": "空投最大频率",
    "Airdrop_Speed": "空投速度", "Airdrop_Force": "空投力度",
    "Arena_Min_Players": "竞技场最少玩家数", "Arena_Compactor_Damage": "竞技场压缩器伤害",
    "Arena_Compactor_Extra_Damage_Per_Second": "压缩器每秒额外伤害",
    "Arena_Clear_Timer": "竞技场清理计时", "Arena_Finale_Timer": "竞技场决赛计时",
    "Arena_Restart_Timer": "竞技场重启计时", "Arena_Compactor_Delay_Timer": "压缩器延迟计时",
    "Arena_Compactor_Pause_Timer": "压缩器暂停计时",
    "Use_Airdrops": "使用空投", "Arena_Use_Compactor_Pause": "竞技场使用压缩器暂停",
    "Arena_Compactor_Speed_Tiny": "微型压缩器速度", "Arena_Compactor_Speed_Small": "小型压缩器速度",
    "Arena_Compactor_Speed_Medium": "中型压缩器速度", "Arena_Compactor_Speed_Large": "大型压缩器速度",
    "Arena_Compactor_Speed_Insane": "超大型压缩器速度", "Arena_Compactor_Shrink_Factor": "压缩器收缩系数",
    # Gameplay
    "Repair_Level_Max": "最大修复等级", "Hitmarkers": "命中标记", "Crosshair": "准星",
    "Ballistics": "弹道", "Chart": "图表", "Satellite": "卫星图", "Compass": "指南针",
    "Group_Map": "队伍地图", "Group_HUD": "队伍 HUD", "Group_Player_List": "队伍玩家列表",
    "Allow_Static_Groups": "允许固定队伍", "Allow_Dynamic_Groups": "允许动态队伍",
    "Allow_Lobby_Groups": "允许大厅队伍", "Allow_Shoulder_Camera": "允许肩后视角",
    "Can_Suicide": "允许自杀", "Friendly_Fire": "友军伤害",
    "Bypass_Buildable_Mobility": "绕过建造移动限制", "Allow_Holidays": "允许节日活动",
    "Allow_Freeform_Buildables": "允许自由建造物", "Allow_Freeform_Buildables_On_Vehicles": "允许在载具上自由建造",
    "Enable_Damage_Flinch": "受击硬直", "Enable_Explosion_Camera_Shake": "爆炸镜头抖动",
    "Enable_Workstation_Requirements": "工作站要求", "Disable_Motion_Sickness_Options": "禁用晕动症选项",
    "Use_2D_Scope_Overlay": "2D 瞄准镜覆盖层",
    "Timer_Exit": "退出计时 (秒)", "Timer_Respawn": "重生计时 (秒)",
    "Timer_Home": "回家计时 (秒)", "Timer_Leave_Group": "离队计时 (秒)",
    "Max_Group_Members": "最大队伍人数 (0=不限)",
    "Explosion_Launch_Speed_Multiplier": "爆炸击飞倍率",
    "AirStrafing_Acceleration_Multiplier": "空中转向加速度倍率",
    "AirStrafing_Deceleration_Multiplier": "空中转向减速度倍率",
    "FirstPerson_RecoilMultiplier": "第一人称后坐力倍率",
    "FirstPerson_AimingRecoilMultiplier": "第一人称瞄准后坐力倍率",
    "FirstPerson_AimingZoomRecoilReduction": "第一人称缩放后坐力减少",
    "ThirdPerson_RecoilMultiplier": "第三人称后坐力倍率",
    "ThirdPerson_SpreadMultiplier": "第三人称散布倍率",
    "Viewmodel_AimingJumpLandMultiplier": "瞄准跳跃落地倍率",
    "Viewmodel_AimingMisalignmentMultiplier": "瞄准偏差倍率",
}

# 参数用途说明（悬停问号显示；中文为主，覆盖 Config.json 全部键）
PARAM_DESCS = {
    # ---- Browser ----
    "Icon": "服务器图标路径（256x256 PNG，显示在服务器列表）。留空用默认图标。",
    "Thumbnail": "服务器缩略图路径（横版图片，进入前展示）。留空用默认图。",
    "Desc_Hint": "简短描述，显示在服务器列表的摘要位置，一两句话即可。",
    "Desc_Full": "完整描述，进入服务器详情页时展示，支持换行。",
    "Desc_Server_List": "服务器列表专用描述，与 Desc_Hint 作用类似。",
    "Login_Token": "GSLT 登录令牌。填了它服务器才会出现在公网列表中，一令牌对应一个服务器。",
    "BookmarkHost": "书签主机名，仅供客户端书签跳转使用，一般留空。",
    "Is_Using_Anycast_Proxy": "是否使用任播代理（用 Anycast 中转时开启），普通家庭网络留 False。",
    "Monetization": "货币化方式：Unspecified（默认）/ None / Items / Plots，按服务器变现方式设置。",
    "Links": "服务器宣传链接，如官网、QQ 群、Steam 组页面，显示在列表详情中。",
    # ---- Server ----
    "VAC_Secure": "启用 VAC（Valve 反作弊）。公网服务器建议开启，防止开挂玩家进入。",
    "BattlEye_Secure": "启用 BattlEye 反作弊。更强的第三方反作弊，开公网服建议开启。",
    "Max_Ping_Milliseconds": "允许进入的最大延迟（毫秒）。超过此延迟的玩家会被拒绝进入，防掉线卡顿。",
    "Timeout_Queue_Seconds": "排队进入的超时秒数。服务器满员时排队玩家等待的上限。",
    "Timeout_Game_Seconds": "游戏内连接超时秒数。长时间无响应会被断开。",
    "Join_Rate_Limit_Window_Seconds": "加入频率限制的统计窗口（秒）。配合下一个值防止频繁进出。",
    "Bad_Packet_Rate_Limit_Window_Seconds": "异常数据包限速统计窗口（秒）。",
    "Bad_Packet_Rate_Limit_Threshold": "异常数据包阈值，超过会被限制，防网络攻击。",
    "Rate_Limit_Kick_Threshold": "限速踢出阈值，超过限制次数的客户端会被踢出。",
    "Max_Clients_With_Same_IP_Address": "同一 IP 地址最多允许多少客户端，防止一人开多号挤占服务器。",
    "Max_Clients_With_Same_IP_Address_Log_Warnings": "同 IP 客户端超限时是否记录警告日志。",
    "Fake_Lag_Threshold_Seconds": "假延迟判定阈值（秒）。网络抖动过大时启动补偿机制。",
    "Fake_Lag_Log_Warnings": "检测到假延迟（网络作弊）时是否记录警告。",
    "Fake_Lag_Damage_Penalty_Multiplier": "假延迟玩家受到额外伤害的倍率，惩罚网络作弊玩家。",
    "Enable_Kick_Input_Spam": "是否踢出疯狂刷屏输入的玩家，保护服务器聊天环境。",
    "Enable_Kick_Input_Timeout": "是否踢出长时间无输入/超时的玩家。",
    "Enable_Scheduled_Shutdown": "是否启用定时关机，例如每天凌晨维护重启。",
    "Scheduled_Shutdown_Time": "定时关机的时间点，格式如 1:30 am。",
    "Scheduled_Shutdown_Warnings": "关机前提前警告的时间点列表，逗号分隔，如 10,5,1。",
    "Enable_Update_Shutdown": "游戏更新时自动关机/重启，避免更新后服务端出错。",
    "Update_Steam_Beta_Name": "更新时切换到的 Steam 测试分支名，一般留空用正式版。",
    "Update_Shutdown_Warnings": "更新关机前的警告时间点，逗号分隔。",
    "Validate_EconInfo_Hash": "校验经济信息哈希（防篡改交易数据），一般保持 True。",
    "Use_FakeIP": "使用假 IP 模式（FakeIP 分发），特殊网络环境才需要，普通开服保持 False。",
    "Reset_Vehicles_Outside_Horizontal_Distance": "载具超出水平距离后自动重置，防止载具被推离地图。",
    # ---- UnityEvents ----
    "Allow_Server_Messages": "允许服务器向客户端发送消息（服务器公告等）。",
    "Allow_Server_Commands": "允许服务器向客户端执行命令。",
    "Allow_Client_Messages": "允许客户端向服务器发送消息（聊天、指令请求）。",
    "Allow_Client_Commands": "允许客户端向服务器请求执行命令。",
    # ---- Items ----
    "Spawn_Chance": "物品生成概率（0-1）。越高物资越多，1=每个生成点都出。",
    "Despawn_Dropped_Time": "玩家扔在地上/掉落的物品多少秒后消失。",
    "Despawn_Natural_Time": "自然刷新出的物品多少秒后消失。",
    "Respawn_Time": "物品被拿走后的重生间隔（秒）。",
    "Quality_Full_Chance": "物品生成时满品质（100%）的概率。越高刷到的好东西越多。",
    "Quality_Multiplier": "物品品质整体倍率，1=默认，2=两倍耐久/性能。",
    "Gun_Bullets_Full_Chance": "枪械生成时自带满弹匣的概率。",
    "Gun_Bullets_Multiplier": "枪械生成时自带子弹数量的倍率。",
    "Magazine_Bullets_Full_Chance": "独立弹匣生成时装满子弹的概率。",
    "Magazine_Bullets_Multiplier": "独立弹匣生成时子弹数量的倍率。",
    "Crate_Bullets_Full_Chance": "弹药箱生成时满载的概率。",
    "Crate_Bullets_Multiplier": "弹药箱生成时子弹数量的倍率。",
    "Has_Durability": "物品是否有耐久度。False=无限耐久，适合快餐服。",
    "Food_Spawns_At_Full_Quality": "食物生成时是否满品质（影响饱腹恢复量）。",
    "Water_Spawns_At_Full_Quality": "饮水（水壶等）生成时是否满品质。",
    "Clothing_Spawns_At_Full_Quality": "衣物生成时是否满品质（影响防御值）。",
    "Weapons_Spawn_At_Full_Quality": "武器生成时是否满品质。",
    "Default_Spawns_At_Full_Quality": "其他默认物品生成时是否满品质。",
    "Clothing_Has_Durability": "衣物是否有耐久度。False=永不磨损。",
    "Weapons_Have_Durability": "武器是否有耐久度。False=武器永不磨损。",
    # ---- Vehicles ----
    "Respawn_Time": "载具被破坏/开走后的重生时间（秒）。",
    "Decay_Time": "载具无人使用多少秒后开始衰减（逐渐损坏）。",
    "Decay_Damage_Per_Second": "载具衰减时每秒受到的伤害值。",
    "Has_Battery_Chance": "载具生成时带电池的概率（没电池的车无法发动）。",
    "Min_Battery_Charge": "载具电池的最小初始电量（0-100）。",
    "Max_Battery_Charge": "载具电池的最大初始电量（0-100）。",
    "Has_Tire_Chance": "载具生成时带轮胎的概率。没轮胎的车开起来很费劲。",
    "Unlocked_After_Seconds_In_Safezone": "载具停在安全区内多少秒后自动解锁（防占车位）。",
    "Armor_Multiplier": "载具护甲倍率，1=默认，越高越耐打。",
    "Child_Explosion_Armor_Multiplier": "载具附属部件（油箱等）爆炸时的护甲倍率。",
    "Gun_Lowcal_Damage_Multiplier": "低口径武器（手枪/冲锋枪）对载具的伤害倍率。",
    "Gun_Highcal_Damage_Multiplier": "高口径武器（步枪/机枪）对载具的伤害倍率。",
    "Melee_Damage_Multiplier": "近战武器对载具的伤害倍率。",
    "Melee_Repair_Multiplier": "近战武器修复载具的效率倍率。",
    "Max_Instances_Tiny": "同屏微型载具（推车等）最大数量。",
    "Max_Instances_Small": "同屏小型载具（摩托等）最大数量。",
    "Max_Instances_Medium": "同屏中型载具（轿车等）最大数量。",
    "Max_Instances_Large": "同屏大型载具（卡车等）最大数量。",
    "Max_Instances_Insane": "同屏超大型载具最大数量。",
    "Min_Natural_Vehicles": "地图上自然刷新的载具最少数量。",
    # ---- Zombies ----
    "Spawn_Chance": "僵尸生成概率（0-1）。越高僵尸越多，0=关闭僵尸。",
    "Armor_Multiplier": "僵尸护甲倍率，越高越难打死。",
    "Loot_Chance": "僵尸掉落物品的概率（0-1）。",
    "Crawler_Chance": "爬行僵尸出现概率（0-1）。",
    "Sprinter_Chance": "奔跑型（速度极快）僵尸出现概率。",
    "Flanker_Chance": "侧袭型僵尸出现概率。",
    "Burner_Chance": "燃烧僵尸出现概率，靠近会引燃玩家。",
    "Acid_Chance": "酸液僵尸出现概率，攻击造成持续伤害。",
    "Boss_Electric_Chance": "电系 Boss 僵尸（雷霆）出现概率。",
    "Boss_Wind_Chance": "风系 Boss 僵尸出现概率。",
    "Boss_Fire_Chance": "火系 Boss 僵尸（熔岩）出现概率。",
    "Spirit_Chance": "幽灵僵尸出现概率（穿墙攻击）。",
    "DL_Red_Volatile_Chance": "死亡之地地图：红色爆裂僵尸概率，爆炸范围大。",
    "DL_Blue_Volatile_Chance": "死亡之地地图：蓝色爆裂僵尸概率。",
    "Boss_Elver_Stomper_Chance": "Elver 地图：践踏型 Boss 出现概率。",
    "Boss_Kuwait_Chance": "Kuwait 地图：特殊 Boss 出现概率。",
    "Respawn_Day_Time": "僵尸白天死亡后的重生间隔（秒）。",
    "Respawn_Night_Time": "僵尸夜晚重生间隔（秒），夜战更刺激可调短。",
    "Respawn_Beacon_Time": "信标（复活点）附近僵尸重生间隔（秒）。",
    "Quest_Boss_Respawn_Interval": "任务 Boss 的重生间隔（秒）。",
    "Damage_Multiplier": "僵尸攻击伤害倍率，1=默认，越高越致命。",
    "Backstab_Multiplier": "僵尸背刺（背后攻击）伤害倍率。",
    "NonHeadshot_Armor_Multiplier": "非爆头部位（身体/四肢）的护甲倍率。",
    "Beacon_Experience_Multiplier": "在信标附近击杀僵尸获得的经验倍率。",
    "Full_Moon_Experience_Multiplier": "满月之夜击杀僵尸的经验倍率。",
    "Min_Drops": "僵尸最少掉落物品数。",
    "Max_Drops": "僵尸最多掉落物品数。",
    "Min_Mega_Drops": "巨型僵尸最少掉落数。",
    "Max_Mega_Drops": "巨型僵尸最多掉落数。",
    "Min_Boss_Drops": "Boss 僵尸最少掉落数。",
    "Max_Boss_Drops": "Boss 僵尸最多掉落数。",
    "Slow_Movement": "僵尸移动是否缓慢（做慢节奏恐怖服用）。",
    "Can_Stun": "僵尸是否可被击晕/击退。",
    "Only_Critical_Stuns": "只有暴击才能击晕僵尸。",
    "Weapons_Use_Player_Damage": "僵尸对武器（弹药消耗等）是否按玩家伤害规则计算。",
    "Can_Target_Barricades": "僵尸是否会攻击玩家放置的路障。",
    "Can_Target_Structures": "僵尸是否会攻击玩家建造的建筑。",
    "Can_Target_Vehicles": "僵尸是否会攻击载具。",
    "Can_Target_Objects": "僵尸是否会攻击地图物体（储物柜等）。",
    "Beacon_Max_Rewards": "信标任务单次最多奖励数量。",
    "Beacon_Max_Participants": "信标任务最多参与玩家数。",
    "Beacon_Rewards_Multiplier": "信标任务奖励倍率。",
    # ---- Animals ----
    "Respawn_Time": "动物被击杀后的重生间隔（秒）。",
    "Armor_Multiplier": "动物护甲倍率，越高越难猎杀。",
    "Damage_Multiplier": "动物攻击伤害倍率。",
    "Weapons_Use_Player_Damage": "动物对武器的伤害是否按玩家规则计算。",
    "Max_Instances_Tiny": "同屏微型动物（鸡兔等）最大数量。",
    "Max_Instances_Small": "同屏小型动物最大数量。",
    "Max_Instances_Medium": "同屏中型动物（鹿等）最大数量。",
    "Max_Instances_Large": "同屏大型动物（熊等）最大数量。",
    "Max_Instances_Insane": "同屏超大型动物最大数量。",
    # ---- Barricades / Structures ----
    "Decay_Time": "路障/建筑无人维护多少秒后开始衰减。",
    "Gun_Lowcal_Damage_Multiplier": "低口径武器对路障/建筑的伤害倍率。",
    "Gun_Highcal_Damage_Multiplier": "高口径武器对路障/建筑的伤害倍率。",
    "Melee_Damage_Multiplier": "近战武器对路障/建筑的伤害倍率。",
    "Melee_Repair_Multiplier": "近战武器修复路障/建筑的效率倍率。",
    "Armor_Lowtier_Multiplier": "低级材料（木头等）建造物的护甲倍率。",
    "Armor_Hightier_Multiplier": "高级材料（金属等）建造物的护甲倍率。",
    "Allow_Item_Placement_On_Vehicle": "是否允许把储物箱等物品放在载具上。",
    "Allow_Trap_Placement_On_Vehicle": "是否允许把陷阱（夹子、地雷）放在载具上。",
    "Max_Item_Distance_From_Hull": "物品最多可放置在距载具船体多远的位置。",
    "Max_Trap_Distance_From_Hull": "陷阱最多可放置在距载具船体多远的位置。",
    # ---- Players ----
    "Armor_Multiplier": "玩家整体护甲倍率，越高越抗揍。",
    "Health_Default": "玩家初始生命值（默认 100）。",
    "Health_Regen_Min_Food": "回血所需的最低饱食度（低于此值不回血）。",
    "Health_Regen_Min_Water": "回血所需的最低水分值。",
    "Health_Regen_Ticks": "每次回血的间隔（tick，1 秒约 64 tick）。",
    "Food_Default": "玩家初始饱食度（默认 100）。",
    "Food_Use_Ticks": "饱食度消耗一次的间隔（tick），越小饿得越快。",
    "Food_Damage_Ticks": "饿到 0 后掉血间隔（tick）。",
    "Water_Default": "玩家初始水分值（默认 100）。",
    "Water_Use_Ticks": "水分消耗间隔（tick）。",
    "Water_Damage_Ticks": "缺水掉血间隔（tick）。",
    "Virus_Default": "玩家初始病毒值（默认 0，越高越接近感染）。",
    "Virus_Infect": "病毒值达到多少时判定感染（持续掉血）。",
    "Virus_Use_Ticks": "病毒值增长间隔（tick），越小感染越快。",
    "Virus_Damage_Ticks": "感染后掉血间隔（tick）。",
    "Leg_Regen_Ticks": "腿部受伤后的恢复间隔（tick）。",
    "Bleed_Damage_Ticks": "流血时掉血间隔（tick），越小流血越快。",
    "Bleed_Regen_Ticks": "流血状态的恢复间隔（tick）。",
    "Experience_Multiplier": "经验获取倍率，2=双倍经验，升级更快。",
    "Detect_Radius_Multiplier": "玩家被发现/探测范围倍率（影响潜行和怪物索敌）。",
    "Ray_Aggressor_Distance": "射线攻击者的索敌距离。",
    "Lose_Skills_PvP": "被玩家击杀时技能等级损失倍率（0=不掉技能）。",
    "Lose_Skills_PvE": "被僵尸击杀时技能等级损失倍率。",
    "Lose_Skill_Levels_PvP": "被玩家击杀时技能等级损失数值（1=掉1级）。",
    "Lose_Skill_Levels_PvE": "被僵尸击杀时技能等级损失数值。",
    "Lose_Experience_PvP": "被玩家击杀时经验损失倍率。",
    "Lose_Experience_PvE": "被僵尸击杀时经验损失倍率。",
    "Lose_Items_PvP": "被玩家击杀时物品掉落比例（0-1，1=全掉，0=不掉）。",
    "Lose_Items_PvE": "被僵尸击杀时物品掉落比例。",
    "Lose_Clothes_PvP": "被玩家击杀时是否掉落衣物。",
    "Lose_Clothes_PvE": "被僵尸击杀时是否掉落衣物。",
    "Lose_Weapons_PvP": "被玩家击杀时是否掉落武器。",
    "Lose_Weapons_PvE": "被僵尸击杀时是否掉落武器。",
    "Can_Hurt_Legs": "玩家腿部是否会被伤害（跑动会瘸）。",
    "Can_Break_Legs": "腿部是否会被打断（重伤状态）。",
    "Can_Fix_Legs": "腿部受伤后是否可以使用药品固定/恢复。",
    "Can_Start_Bleeding": "玩家是否会出现流血状态（持续掉血）。",
    "Can_Stop_Bleeding": "玩家是否可以使用绷带等止血。",
    "Spawn_With_Max_Skills": "出生时是否直接满技能（跳过练级）。",
    "Spawn_With_Stamina_Skills": "出生时是否满耐力相关技能。",
    "Allow_Instakill_Headshots": "是否允许爆头直接秒杀（硬核服常用）。",
    "Allow_Per_Character_Saves": "是否按角色独立存档（True=每个角色分开，False=共用档）。",
    "Enable_Terrain_Color_Kick": "是否踢出地形颜色异常的客户端（反作弊/防作弊皮肤）。",
    # ---- Objects ----
    "Binary_State_Reset_Multiplier": "开关类物体（灯、发电机）状态重置速度倍率。",
    "Fuel_Reset_Multiplier": "燃料（发电机油箱）重置速度倍率。",
    "Water_Reset_Multiplier": "水源（水塔）重置速度倍率。",
    "Resource_Reset_Multiplier": "资源点（矿脉等）重置速度倍率。",
    "Resource_Drops_Multiplier": "资源点掉落物数量倍率。",
    "Rubble_Reset_Multiplier": "瓦砾/废墟重置速度倍率。",
    "Allow_Holiday_Drops": "是否允许节日特殊掉落（万圣节糖果等）。",
    "Items_Obstruct_Tree_Respawns": "物品是否阻碍树木重生（挡着树苗不长大）。",
    # ---- Events ----
    "Rain_Frequency_Min": "下雨事件最小间隔（秒）。",
    "Rain_Frequency_Max": "下雨事件最大间隔（秒）。",
    "Rain_Duration_Min": "下雨最短持续秒数。",
    "Rain_Duration_Max": "下雨最长持续秒数。",
    "Snow_Frequency_Min": "下雪事件最小间隔（秒）。",
    "Snow_Frequency_Max": "下雪事件最大间隔（秒）。",
    "Snow_Duration_Min": "下雪最短持续秒数。",
    "Snow_Duration_Max": "下雪最长持续秒数。",
    "Weather_Frequency_Multiplier": "所有天气事件的整体频率倍率，越大天气越频繁。",
    "Weather_Duration_Multiplier": "所有天气事件的整体时长倍率。",
    "Airdrop_Frequency_Min": "空投事件最小间隔（秒）。",
    "Airdrop_Frequency_Max": "空投事件最大间隔（秒）。",
    "Airdrop_Speed": "空投箱下落速度。",
    "Airdrop_Force": "空投投放力度（影响落点）。",
    "Arena_Min_Players": "竞技场事件最少参与人数。",
    "Arena_Compactor_Damage": "竞技场压缩器（收拢墙壁）伤害。",
    "Arena_Compactor_Extra_Damage_Per_Second": "竞技场压缩器每秒额外伤害。",
    "Arena_Clear_Timer": "竞技场清理计时（清场间隔，秒）。",
    "Arena_Finale_Timer": "竞技场决赛阶段计时（秒）。",
    "Arena_Restart_Timer": "竞技场重启计时（秒）。",
    "Arena_Compactor_Delay_Timer": "竞技场压缩器启动延迟（秒）。",
    "Arena_Compactor_Pause_Timer": "竞技场压缩器暂停计时（秒）。",
    "Use_Airdrops": "是否启用空投事件。",
    "Arena_Use_Compactor_Pause": "竞技场是否使用压缩器暂停机制。",
    "Arena_Compactor_Speed_Tiny": "微型竞技场压缩器移动速度。",
    "Arena_Compactor_Speed_Small": "小型竞技场压缩器移动速度。",
    "Arena_Compactor_Speed_Medium": "中型竞技场压缩器移动速度。",
    "Arena_Compactor_Speed_Large": "大型竞技场压缩器移动速度。",
    "Arena_Compactor_Speed_Insane": "超大型竞技场压缩器移动速度。",
    "Arena_Compactor_Shrink_Factor": "竞技场压缩器收缩系数（每次收拢比例）。",
    # ---- Gameplay ----
    "Repair_Level_Max": "修复技能最高等级（影响修复效率和上限）。",
    "Hitmarkers": "是否显示命中标记（击中反馈小叉）。",
    "Crosshair": "是否显示准星（FPS 手感开关）。",
    "Ballistics": "是否启用真实弹道（下坠、飞行时间）。",
    "Chart": "是否显示小地图图表（右下角地图）。",
    "Satellite": "是否显示卫星视图（大地图全景）。",
    "Compass": "是否显示指南针（方向指示）。",
    "Group_Map": "队友是否在小地图上显示位置。",
    "Group_HUD": "队友血条/状态是否显示在 HUD 上。",
    "Group_Player_List": "是否显示队伍成员列表（TAB 界面）。",
    "Allow_Static_Groups": "是否允许固定的队伍系统（组队界面创建）。",
    "Allow_Dynamic_Groups": "是否允许临时队伍（一起行动自动组队）。",
    "Allow_Lobby_Groups": "是否允许大厅里组队。",
    "Allow_Shoulder_Camera": "是否允许肩后视角（第三人称越肩）。",
    "Can_Suicide": "是否允许玩家自杀（重新出生）。",
    "Friendly_Fire": "是否启用友军伤害（打队友会掉血）。",
    "Bypass_Buildable_Mobility": "是否绕过建造物移动限制（可边移动边建）。",
    "Allow_Holidays": "是否启用节日活动（复活节彩蛋、万圣节等）。",
    "Allow_Freeform_Buildables": "是否允许自由建造（不限格子吸附）。",
    "Allow_Freeform_Buildables_On_Vehicles": "是否允许在载具上自由建造。",
    "Enable_Damage_Flinch": "受击时是否有硬直（画面晃动/后退）。",
    "Enable_Explosion_Camera_Shake": "爆炸时是否镜头震动。",
    "Enable_Workstation_Requirements": "是否启用工作台制作要求（必须靠近工作站）。",
    "Disable_Motion_Sickness_Options": "是否禁用晕动症辅助选项（画面震动调节等）。",
    "Use_2D_Scope_Overlay": "是否使用 2D 瞄准镜覆盖层（开镜画面）。",
    "Timer_Exit": "退出游戏的读秒（秒），防秒退逃战。",
    "Timer_Respawn": "死亡后重生读秒（秒）。",
    "Timer_Home": "回到家园的读秒（秒）。",
    "Timer_Leave_Group": "退出队伍的读秒（秒）。",
    "Max_Group_Members": "队伍最大人数上限（0=不限）。",
    "Explosion_Launch_Speed_Multiplier": "爆炸把人/物击飞的力度倍率。",
    "AirStrafing_Acceleration_Multiplier": "空中转向加速倍率（影响空中机动手感）。",
    "AirStrafing_Deceleration_Multiplier": "空中转向减速倍率。",
    "FirstPerson_RecoilMultiplier": "第一人称后坐力倍率，越低越稳。",
    "FirstPerson_AimingRecoilMultiplier": "第一人称开镜时后坐力倍率。",
    "FirstPerson_AimingZoomRecoilReduction": "第一人称开镜缩放时后坐力减少量。",
    "ThirdPerson_RecoilMultiplier": "第三人称后坐力倍率。",
    "ThirdPerson_SpreadMultiplier": "第三人称弹道散布倍率，越低越准。",
    "Viewmodel_AimingJumpLandMultiplier": "瞄准时跳跃/落地画面晃动倍率。",
    "Viewmodel_AimingMisalignmentMultiplier": "瞄准偏差倍率（镜头与准星偏移）。",
    # ---- WorkshopDownloadConfig.json ----
    "File_IDs": "创意工坊物品 ID 列表（纯数字），服务器启动时自动下载这些模组。",
    "Ignore_Children_File_IDs": "忽略的子物品 ID 列表（这些模组的附属文件不会被下载）。",
    "Query_Cache_Max_Age_Seconds": "创意工坊查询缓存最大保留秒数，到期重新查询。",
    "Max_Query_Retries": "创意工坊查询失败后的最大重试次数。",
    "Use_Cached_Downloads": "是否使用已缓存的文件，避免重复下载相同模组。",
    "Should_Monitor_Updates": "是否监控创意工坊模组更新，检测到更新时按下方倒计时处理。",
    "Shutdown_Update_Detected_Timer": "检测到模组更新后的关服倒计时（秒），到期自动重启/关服。",
    "Shutdown_Update_Detected_Message": "检测到模组更新时的关服提示消息（{0} 会被替换为倒计时秒数）。",
    "Shutdown_Kick_Message": "因模组更新关服时踢出玩家显示的消息。",
}

# 同键名参数在不同组有不同含义时，按组覆盖说明（悬停问号显示）
PARAM_DESCS_OVERRIDES = {
    "Items": {
        "Spawn_Chance": "物品生成概率（0-1）。越高物资越多，1=每个生成点都出。",
        "Respawn_Time": "物品被拿走后的重生间隔（秒）。",
    },
    "Vehicles": {
        "Respawn_Time": "载具被破坏/开走后的重生时间（秒）。",
        "Decay_Time": "载具无人使用多少秒后开始衰减（逐渐损坏）。",
        "Armor_Multiplier": "载具护甲倍率，1=默认，越高越耐打。",
        "Damage_Multiplier": "载具受到的整体伤害倍率。",
        "Gun_Lowcal_Damage_Multiplier": "低口径武器（手枪/冲锋枪）对载具的伤害倍率。",
        "Gun_Highcal_Damage_Multiplier": "高口径武器（步枪/机枪）对载具的伤害倍率。",
        "Melee_Damage_Multiplier": "近战武器对载具的伤害倍率。",
        "Melee_Repair_Multiplier": "近战武器修复载具的效率倍率。",
        "Max_Instances_Tiny": "同屏微型载具（推车等）最大数量。",
        "Max_Instances_Small": "同屏小型载具（摩托等）最大数量。",
        "Max_Instances_Medium": "同屏中型载具（轿车等）最大数量。",
        "Max_Instances_Large": "同屏大型载具（卡车等）最大数量。",
        "Max_Instances_Insane": "同屏超大型载具最大数量。",
    },
    "Zombies": {
        "Spawn_Chance": "僵尸生成概率（0-1）。越高僵尸越多，0=关闭僵尸。",
        "Armor_Multiplier": "僵尸护甲倍率，越高越难打死。",
        "Damage_Multiplier": "僵尸攻击伤害倍率，1=默认，越高越致命。",
        "Weapons_Use_Player_Damage": "僵尸对武器（弹药消耗等）是否按玩家伤害规则计算。",
    },
    "Animals": {
        "Respawn_Time": "动物被击杀后的重生间隔（秒）。",
        "Armor_Multiplier": "动物护甲倍率，越高越难猎杀。",
        "Damage_Multiplier": "动物攻击伤害倍率。",
        "Weapons_Use_Player_Damage": "动物对武器的伤害是否按玩家规则计算。",
        "Max_Instances_Tiny": "同屏微型动物（鸡兔等）最大数量。",
        "Max_Instances_Small": "同屏小型动物最大数量。",
        "Max_Instances_Medium": "同屏中型动物（鹿等）最大数量。",
        "Max_Instances_Large": "同屏大型动物（熊等）最大数量。",
        "Max_Instances_Insane": "同屏超大型动物最大数量。",
    },
    "Barricades": {
        "Decay_Time": "路障无人维护多少秒后开始衰减。",
        "Gun_Lowcal_Damage_Multiplier": "低口径武器对路障的伤害倍率。",
        "Gun_Highcal_Damage_Multiplier": "高口径武器对路障的伤害倍率。",
        "Melee_Damage_Multiplier": "近战武器对路障的伤害倍率。",
        "Melee_Repair_Multiplier": "近战武器修复路障的效率倍率。",
    },
    "Structures": {
        "Decay_Time": "建筑无人维护多少秒后开始衰减。",
        "Gun_Lowcal_Damage_Multiplier": "低口径武器对建筑的伤害倍率。",
        "Gun_Highcal_Damage_Multiplier": "高口径武器对建筑的伤害倍率。",
        "Melee_Damage_Multiplier": "近战武器对建筑的伤害倍率。",
        "Melee_Repair_Multiplier": "近战武器修复建筑的效率倍率。",
    },
    "Players": {
        "Armor_Multiplier": "玩家整体护甲倍率，越高越抗揍。",
    },
}

# Commands.dat 常用命令说明
COMMAND_HINTS = {
    "Name": "服务器名称（显示在列表中）",
    "Map": "地图：PEI / Russia / Washington / Germany / Yukon / Alpha Valley 等",
    "Maxplayers": "最大玩家数",
    "Mode": "难度：Easy / Normal / Hard",
    "Password": "进入密码（仅 SHA1 加密，勿与其他密码相同）",
    "Welcome": "进入欢迎语",
    "Cheats": "管理员作弊指令 (on/off)",
    "Perspective": "视角：First / Third / Both / Vehicle",
    "Owner": "服主 SteamID64（聊天中可执行管理员指令）",
    "Port": "查询端口（每服占用连续两个端口）",
    "GSLT": "Game Server Login Token（公网列表可见必需）",
    "VAC": "启用 VAC (on/off)",
    "BattlEye": "启用 BattlEye (on/off)",
    "MaxPing": "最大延迟（毫秒）",
    "Lang": "服务器语言 (English/Chinese 等)",
}

DIFFICULTIES = ("Easy", "Normal", "Hard")
DIFFICULTY_GROUPS = (
    "Items", "Vehicles", "Zombies", "Animals",
    "Barricades", "Structures", "Players", "Objects",
    "Events", "Gameplay",
)

# ---------------------------------------------------------------------------
# 一键模板（6 种）
# ---------------------------------------------------------------------------

# config overrides: "路径" 用点分路径，例如 "Normal.Gameplay.Friendly_Fire"
TEMPLATES = [
    {
        "id": "lan_vanilla",
        "name_zh": "局域网纯净生存",
        "name_en": "LAN Vanilla Survival",
        "desc_zh": "经典纯净体验，局域网内好友直连，无需公网配置。默认 PEI 地图、简单难度。",
        "desc_en": "Classic vanilla experience for LAN friends. PEI map, Easy mode, no public internet needed.",
        "color": "#10b981",
        "commands": {"Name": "", "Map": "PEI", "Maxplayers": "12", "Mode": "Easy",
                     "Password": "", "Cheats": "off", "Perspective": "Both", "Port": "27015"},
        "overrides": {},
    },
    {
        "id": "internet_vanilla",
        "name_zh": "公网纯净生存",
        "name_en": "Internet Vanilla Survival",
        "desc_zh": "发布到公网服务器列表（需 GSLT 令牌 + 端口映射）。俄罗斯地图、普通难度，官方平衡。",
        "desc_en": "Public internet server (needs GSLT + port forwarding). Russia map, Normal mode, official balance.",
        "color": "#3b82f6",
        "commands": {"Name": "", "Map": "Russia", "Maxplayers": "16", "Mode": "Normal",
                     "Password": "", "Cheats": "off", "Perspective": "Both", "Port": "27015", "GSLT": ""},
        "overrides": {},
    },
    {
        "id": "pve_cozy",
        "name_zh": "PVE 休闲生存",
        "name_en": "PVE Cozy Survival",
        "desc_zh": "弱化僵尸、保留建筑与收集，禁止 PvP 掉落。适合朋友一起慢慢玩。",
        "desc_en": "Weaker zombies, focus on building & looting, no PvP item drops. Chill co-op experience.",
        "color": "#8b5cf6",
        "commands": {"Name": "", "Map": "PEI", "Maxplayers": "10", "Mode": "Easy",
                     "Password": "", "Cheats": "off", "Perspective": "Both", "Port": "27015"},
        "overrides": {
            "Easy.Zombies.Damage_Multiplier": 0.4,
            "Easy.Zombies.Spawn_Chance": 0.1,
            "Easy.Zombies.Loot_Chance": 1,
            "Easy.Players.Lose_Items_PvP": 0.0,
            "Easy.Players.Lose_Clothes_PvP": False,
            "Easy.Players.Lose_Weapons_PvP": False,
            "Easy.Players.Experience_Multiplier": 2.0,
            "Easy.Items.Spawn_Chance": 0.6,
            "Easy.Gameplay.Friendly_Fire": False,
        },
    },
    {
        "id": "pvp_arena",
        "name_zh": "PVP 对抗服",
        "name_en": "PVP Arena",
        "desc_zh": "标准 PvP 规则，死亡掉落、技能损失，公平对抗。普通难度平衡物资。",
        "desc_en": "Standard PvP rules with death drops and skill loss. Balanced loot on Normal mode.",
        "color": "#ef4444",
        "commands": {"Name": "", "Map": "Russia", "Maxplayers": "24", "Mode": "Normal",
                     "Password": "", "Cheats": "off", "Perspective": "Both", "Port": "27015"},
        "overrides": {
            "Normal.Players.Lose_Items_PvP": 1.0,
            "Normal.Players.Lose_Skills_PvP": 1.0,
            "Normal.Players.Lose_Skill_Levels_PvP": 1,
            "Normal.Gameplay.Friendly_Fire": False,
            "Normal.Zombies.Damage_Multiplier": 0.75,
            "Normal.Zombies.Spawn_Chance": 0.2,
        },
    },
    {
        "id": "high_rate",
        "name_zh": "高倍率快餐服",
        "name_en": "High-Rate Fast Server",
        "desc_zh": "物资丰富、经验 5 倍、耐久不愁。快速成型，适合图个爽快。",
        "desc_en": "Rich loot, 5x XP, barely any durability. Quick progression for casual fun.",
        "color": "#f59e0b",
        "commands": {"Name": "", "Map": "PEI", "Maxplayers": "16", "Mode": "Easy",
                     "Password": "", "Cheats": "off", "Perspective": "Both", "Port": "27015"},
        "overrides": {
            "Easy.Items.Spawn_Chance": 0.9,
            "Easy.Items.Quality_Full_Chance": 0.8,
            "Easy.Items.Gun_Bullets_Full_Chance": 0.9,
            "Easy.Players.Experience_Multiplier": 5.0,
            "Easy.Items.Has_Durability": False,
            "Easy.Zombies.Damage_Multiplier": 0.5,
            "Easy.Zombies.Spawn_Chance": 0.15,
            "Easy.Vehicles.Has_Battery_Chance": 1.0,
        },
    },
    {
        "id": "hardcore",
        "name_zh": "硬核生存",
        "name_en": "Hardcore Survival",
        "desc_zh": "困难难度，物资稀缺、僵尸凶猛、爆头秒杀。挑战向。",
        "desc_en": "Hard mode, scarce loot, deadly zombies, instakill headshots. For the brave.",
        "color": "#334155",
        "commands": {"Name": "", "Map": "Washington", "Maxplayers": "12", "Mode": "Hard",
                     "Password": "", "Cheats": "off", "Perspective": "Both", "Port": "27015"},
        "overrides": {
            "Hard.Items.Spawn_Chance": 0.12,
            "Hard.Zombies.Damage_Multiplier": 1.5,
            "Hard.Zombies.Spawn_Chance": 0.3,
            "Hard.Players.Allow_Instakill_Headshots": True,
            "Hard.Players.Can_Start_Bleeding": True,
            "Hard.Players.Can_Stop_Bleeding": False,
            "Hard.Gameplay.Crosshair": False,
        },
    },
]

MAPS = ["PEI", "Russia", "Washington", "Germany", "Yukon", "Alpha Valley",
        "Monolith", "Destruction", "Paintball_Arena_0", "Tutorial"]

# ---------------------------------------------------------------------------
# 后端 Api
# ---------------------------------------------------------------------------

DEFAULT_GAME_DIR = r"D:\SteamLibrary\steamapps\common\U3DS"


class Api:
    def __init__(self, base_dir: str):
        self.base_dir = base_dir          # 工具目录（存 settings.json）
        self.game_dir = DEFAULT_GAME_DIR
        self.settings_path = os.path.join(base_dir, "settings.json")
        self.load_settings()
        self._ws_names_cache = {}
        self._ws_names_loading = set()

    # ---------- settings ----------
    def load_settings(self):
        try:
            if os.path.isfile(self.settings_path):
                with open(self.settings_path, "r", encoding="utf-8") as f:
                    s = json.load(f)
                self.lang = s.get("lang", "zh")
                self.game_dir = s.get("game_dir", DEFAULT_GAME_DIR)
            else:
                self.lang = "zh"
        except Exception:
            self.lang = "zh"

    def save_settings(self):
        try:
            with open(self.settings_path, "w", encoding="utf-8") as f:
                json.dump({"lang": self.lang, "game_dir": self.game_dir}, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def get_settings(self):
        return {"lang": self.lang, "game_dir": self.game_dir,
                "version": APP_VERSION, "app_name": APP_NAME}

    def set_lang(self, lang):
        if lang in ("zh", "en"):
            self.lang = lang
            self.save_settings()
            return {"ok": True, "lang": lang}
        return {"ok": False}

    def set_game_dir(self, path):
        if path and os.path.isdir(os.path.join(path, "Servers")):
            self.game_dir = os.path.normpath(path)
            self.save_settings()
            return {"ok": True, "game_dir": self.game_dir,
                    "instances": self.list_instances()["instances"]}
        return {"ok": False, "error": "目录下未找到 Servers 文件夹"}

    # ---------- instances ----------
    def servers_dir(self):
        return os.path.join(self.game_dir, "Servers")

    def list_instances(self):
        sd = self.servers_dir()
        if not os.path.isdir(sd):
            return {"instances": [], "game_dir": self.game_dir}
        names = sorted(
            n for n in os.listdir(sd)
            if os.path.isdir(os.path.join(sd, n))
        )
        return {"instances": names, "game_dir": self.game_dir}

    def instance_path(self, name):
        return os.path.join(self.servers_dir(), name)

    @staticmethod
    def _instance_name_error(name):
        """校验实例名，返回错误信息；合法返回 None。用于所有以实例名为参数的后端接口。"""
        name = (name or "").strip()
        if not name:
            return "实例名不能为空"
        if name in (".", ".."):
            return "实例名不能为 . 或 .."
        if any(c in name for c in r'\/:*?"<>|'):
            return "实例名包含非法字符（\\ / : * ? \" < > |）"
        if any(c in name for c in "&^%|"):
            return "实例名不能包含 & ^ % | 等符号（会破坏启动脚本）"
        base = name.split(".")[0].upper()
        reserved = {"CON", "PRN", "AUX", "NUL"}
        reserved |= {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}
        if base in reserved:
            return f"实例名不能使用 Windows 保留名（{base}）"
        return None

    def _check_instance_name(self, name):
        err = self._instance_name_error(name)
        if err:
            return {"ok": False, "error": err}
        return None

    def load_instance(self, name):
        name = (name or "").strip()
        bad = self._check_instance_name(name)
        if bad:
            return bad
        inst = self.instance_path(name)
        if not os.path.isdir(inst):
            return {"ok": False, "error": f"实例 {name} 不存在"}
        cfg_path = os.path.join(inst, "Config.json")
        cmd_path = os.path.join(inst, "Server", "Commands.dat")
        ws_path = os.path.join(inst, "WorkshopDownloadConfig.json")

        try:
            config = load_json_file(cfg_path) if os.path.isfile(cfg_path) else None
        except Exception as e:
            return {"ok": False, "error": f"Config.json 解析失败（文件可能损坏）: {e}"}
        try:
            commands = load_commands(cmd_path)
        except Exception as e:
            return {"ok": False, "error": f"Commands.dat 读取失败: {e}"}
        try:
            workshop = load_json_file(ws_path) if os.path.isfile(ws_path) else None
        except Exception as e:
            workshop = None

        # 统计参数
        total = 0
        if config:
            for diff in DIFFICULTIES:
                d = config.get(diff) or {}
                for g in DIFFICULTY_GROUPS:
                    total += len(d.get(g) or {})
            total += len(config.get("Browser") or {})
            total += len(config.get("Server") or {})
            total += len(config.get("UnityEvents") or {})

        players_dir = os.path.join(inst, "Players")
        player_count = len([n for n in os.listdir(players_dir) if os.path.isdir(os.path.join(players_dir, n))]) if os.path.isdir(players_dir) else 0

        return {
            "ok": True,
            "name": name,
            "path": inst,
            "config": config,
            "commands": commands,
            "workshop": workshop,
            "stats": {"config_params": total, "command_lines": len(commands),
                      "players": player_count, "has_gsl": bool(self._cmd_value(commands, "GSLT"))},
            "translations": {"groups": GROUP_NAMES, "params": PARAM_NAMES,
                             "descs": {"flat": PARAM_DESCS, "group": PARAM_DESCS_OVERRIDES},
                             "commands": COMMAND_HINTS},
        }

    @staticmethod
    def _cmd_value(lines, key):
        for ln in lines:
            parts = ln.strip().split(None, 1)
            if parts and parts[0] == key:
                return parts[1] if len(parts) > 1 else ""
        return ""

    def save_instance(self, name, config, commands, workshop):
        name = (name or "").strip()
        bad = self._check_instance_name(name)
        if bad:
            return bad
        inst = self.instance_path(name)
        if not os.path.isdir(inst):
            return {"ok": False, "error": f"实例 {name} 不存在"}
        backs = []
        if config is not None:
            p = os.path.join(inst, "Config.json")
            b = backup_file(p)
            if b:
                backs.append(os.path.basename(b))
            save_json_file(p, config)
        if commands is not None:
            cmd_dir = os.path.join(inst, "Server")
            os.makedirs(cmd_dir, exist_ok=True)
            p = os.path.join(cmd_dir, "Commands.dat")
            b = backup_file(p)
            if b:
                backs.append(os.path.basename(b))
            save_commands(p, commands)
        if workshop is not None:
            p = os.path.join(inst, "WorkshopDownloadConfig.json")
            b = backup_file(p)
            if b:
                backs.append(os.path.basename(b))
            save_json_file(p, workshop)
        return {"ok": True, "backups": backs}

    # ---------- workshop ----------
    UNTURNED_APPID = "304930"

    def _workshop_dirs(self, name):
        """返回所有可能存放已下载模组的目录（数字文件夹 = 模组 ID）。"""
        inst = self.instance_path(name)
        roots = [
            os.path.join(inst, "Workshop", "content", self.UNTURNED_APPID),
            os.path.join(inst, "Workshop", "content"),
        ]
        # Steam 客户端共享创意工坊缓存：<steamapps>/workshop/content/304930
        steamapps = os.path.abspath(os.path.join(self.game_dir, "..", ".."))
        roots.append(os.path.join(steamapps, "workshop", "content", self.UNTURNED_APPID))
        dirs = []
        for r in roots:
            if os.path.isdir(r):
                try:
                    for n in sorted(os.listdir(r)):
                        p = os.path.join(r, n)
                        if os.path.isdir(p) and n.isdigit() and n != self.UNTURNED_APPID:
                            dirs.append(p)
                except OSError:
                    pass
        return dirs

    def list_workshop_mods(self, name):
        """列出本地已下载的创意工坊模组 + 已启用列表。
        名字查询放后台线程做（Steam 接口可能慢），本次先返回缓存结果，刷新后自动补全。"""
        name = (name or "").strip()
        bad = self._check_instance_name(name)
        if bad:
            return bad
        inst = self.instance_path(name)
        if not os.path.isdir(inst):
            return {"ok": False, "error": f"实例 {name} 不存在"}
        enabled = []
        try:
            ws = load_json_file(os.path.join(inst, "WorkshopDownloadConfig.json")) if os.path.isfile(
                os.path.join(inst, "WorkshopDownloadConfig.json")) else None
        except Exception:
            ws = None
        if ws:
            fid = ws.get("File_IDs") or []
            enabled = [str(x) for x in fid]

        mod_dirs = self._workshop_dirs(name)
        downloaded = [os.path.basename(d) for d in mod_dirs]
        # 去重保序
        seen = set()
        downloaded = [i for i in downloaded if not (i in seen or seen.add(i))]

        names = {k: v for k, v in self._ws_names_cache.items() if k in downloaded}
        missing = [i for i in downloaded
                   if i not in self._ws_names_cache and i not in self._ws_names_loading]
        if missing:
            self._ws_names_loading.update(missing)
            threading.Thread(target=self._load_ws_names, args=(missing,),
                             daemon=True).start()
        return {"ok": True, "downloaded": downloaded, "enabled": enabled,
                "names": names, "names_loading": bool(missing),
                "game_dir": self.game_dir}

    def _load_ws_names(self, ids):
        try:
            names = self._steam_workshop_names(ids)
            self._ws_names_cache.update(names)
        finally:
            self._ws_names_loading.difference_update(ids)

    @staticmethod
    def _steam_workshop_names(ids):
        """通过 Steam 公开接口查询模组标题；离线或失败时返回空 dict（前端只显示 ID）。"""
        names = {}
        if not ids:
            return names
        import json as _json
        import urllib.request
        import urllib.parse
        chunks = [ids[i:i + 50] for i in range(0, len(ids), 50)]
        for chunk in chunks:
            try:
                body = urllib.parse.urlencode({
                    "itemcount": len(chunk),
                    **{f"publishedfileids[{i}]": v for i, v in enumerate(chunk)},
                }).encode("utf-8")
                req = urllib.request.Request(
                    "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/",
                    data=body,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                with urllib.request.urlopen(req, timeout=4) as resp:
                    data = _json.loads(resp.read().decode("utf-8", "replace"))
                for item in (data.get("response") or {}).get("publishedfiledetails") or []:
                    pid = str(item.get("publishedfileid", ""))
                    title = (item.get("title") or "").strip()
                    if pid and title:
                        names[pid] = title
            except Exception:
                break
        return names

    # ---------- templates / create ----------
    def get_templates(self):
        return {"templates": TEMPLATES, "maps": MAPS,
                "difficulties": list(DIFFICULTIES)}

    def create_instance(self, name, template_id, params):
        """params: {name, map, maxplayers, mode, password, port, perspective, cheats, gslt, welcome, owner}"""
        name = (name or "").strip()
        bad = self._check_instance_name(name)
        if bad:
            return bad

        tpl = next((t for t in TEMPLATES if t["id"] == template_id), TEMPLATES[0])
        inst = self.instance_path(name)
        if os.path.isdir(inst) and os.listdir(inst):
            return {"ok": False, "error": f"实例 {name} 已存在且非空"}

        # 创建主体：任一环节失败都回滚清理半成品目录
        try:
            # 1) 基础 Config.json：从现有实例复制（优先 Default），没有则建骨架
            os.makedirs(inst, exist_ok=True)
            src_cfg = None
            for cand in ("Default",):
                p = os.path.join(self.servers_dir(), cand, "Config.json")
                if os.path.isfile(p):
                    src_cfg = p
                    break
            if not src_cfg:
                for cand in self.list_instances()["instances"]:
                    p = os.path.join(self.servers_dir(), cand, "Config.json")
                    if os.path.isfile(p):
                        src_cfg = p
                        break
            config = None
            if src_cfg:
                try:
                    config = load_json_file(src_cfg)
                except Exception:
                    config = None
            if not isinstance(config, dict):
                # 骨架：难度组预置全部子组，保证 overrides 有落点
                config = {k: {} for k in ("Browser", "Server", "UnityEvents")}
                config["Easy"] = {g: {} for g in DIFFICULTY_GROUPS}
                config["Normal"] = {g: {} for g in DIFFICULTY_GROUPS}
                config["Hard"] = {g: {} for g in DIFFICULTY_GROUPS}

            # 2) 应用模板 overrides：overrides 键的第一段若是难度，跟随用户所选 mode 写入对应难度节
            mode = (params.get("mode") or tpl["commands"].get("Mode") or "Easy")
            if mode not in DIFFICULTIES:
                mode = "Easy"
            for path, value in tpl.get("overrides", {}).items():
                parts = path.split(".")
                if parts and parts[0] in DIFFICULTIES:
                    parts[0] = mode
                node = config
                ok = True
                for part in parts[:-1]:
                    if isinstance(node, dict) and part in node and isinstance(node[part], dict):
                        node = node[part]
                    elif isinstance(node, dict) and part not in node:
                        node[part] = {}          # 缺的中间层直接创建
                        node = node[part]
                    else:
                        ok = False
                        break
                if ok and isinstance(node, dict):
                    node[parts[-1]] = value
            save_json_file(os.path.join(inst, "Config.json"), config)

            # 3) Commands.dat（字段名大小写规范化）
            FIELD_MAP = {
                "name": "Name", "map": "Map", "maxplayers": "Maxplayers", "mode": "Mode",
                "password": "Password", "port": "Port", "perspective": "Perspective",
                "cheats": "Cheats", "welcome": "Welcome", "owner": "Owner", "gslt": "GSLT",
            }
            cmd = dict(tpl["commands"])
            for k, v in params.items():
                key = FIELD_MAP.get(k, k)
                if v not in (None, ""):
                    cmd[key] = str(v)
            cmd["Name"] = params.get("name") or "Unturned"
            lines = [f"{k} {v}".rstrip() for k, v in cmd.items() if v not in (None, "")]
            os.makedirs(os.path.join(inst, "Server"), exist_ok=True)
            save_commands(os.path.join(inst, "Server", "Commands.dat"), lines)

            # 4) WorkshopDownloadConfig.json
            ws_src = os.path.join(self.servers_dir(), "Default", "WorkshopDownloadConfig.json")
            if os.path.isfile(ws_src):
                shutil.copy2(ws_src, os.path.join(inst, "WorkshopDownloadConfig.json"))
            else:
                save_json_file(os.path.join(inst, "WorkshopDownloadConfig.json"),
                               {"File_IDs": [], "Ignore_Children_File_IDs": [],
                                "Query_Cache_Max_Age_Seconds": 600, "Max_Query_Retries": 2,
                                "Use_Cached_Downloads": True, "Should_Monitor_Updates": True,
                                "Shutdown_Update_Detected_Timer": 600,
                                "Shutdown_Update_Detected_Message": "Workshop file update detected, shutdown in: {0}",
                                "Shutdown_Kick_Message": "Shutdown for Workshop file update."})
        except Exception as e:
            shutil.rmtree(inst, ignore_errors=True)
            return {"ok": False, "error": f"创建实例失败，已清理未完成的目录: {e}"}

        return {"ok": True, "path": inst, "name": name,
                "created_from": os.path.basename(src_cfg) if src_cfg else "内置骨架"}

    def rename_instance(self, old, new):
        """重命名实例文件夹（Servers/<old> -> Servers/<new>）。改名时请先停止服务器。"""
        old = (old or "").strip()
        new = (new or "").strip()
        bad_old = self._check_instance_name(old)
        if bad_old:
            return bad_old
        bad_new = self._check_instance_name(new)
        if bad_new:
            return bad_new
        if old == new:
            return {"ok": True, "renamed": False, "old": old, "new": new}
        src = self.instance_path(old)
        dst = self.instance_path(new)
        if not os.path.isdir(src):
            return {"ok": False, "error": f"实例 {old} 不存在"}
        if os.path.isdir(dst):
            return {"ok": False, "error": f"实例 {new} 已存在"}
        try:
            os.rename(src, dst)
            return {"ok": True, "renamed": True, "old": old, "new": new}
        except Exception as e:
            return {"ok": False, "error": f"重命名失败（服务器可能在运行中）: {e}"}

    # ---------- 公网部署 ----------
    def detect_public_ip(self):
        # ifconfig.me 国内实测最快；ipify 国内常超时放最后；ip.sb 官方端点是 api.ip.sb/geoip
        for url in ("https://ifconfig.me/ip",
                    "https://api.ipify.org?format=json",
                    "https://api.ip.sb/geoip"):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=4) as r:
                    raw = r.read().decode("utf-8", "ignore").strip()
                if "{" in raw:
                    data = json.loads(raw)
                    ip = data.get("ip") or data.get("address") or data.get("query")
                else:
                    ip = raw.strip()
                if ip:
                    return {"ok": True, "ip": ip, "source": url}
            except Exception:
                continue
        return {"ok": False, "error": "无法获取公网 IP（可能无外网连接）"}

    def local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def check_local_port(self, port):
        """检查本机端口是否被占用。Unturned 用 UDP，用 UDP socket 检测更贴近实际。"""
        try:
            port = int(port)
        except (TypeError, ValueError):
            return {"ok": False, "error": f"端口无效: {port}"}
        s = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.6)
            s.bind(("0.0.0.0", port))
            return {"ok": True, "free": True, "port": port}
        except OSError:
            return {"ok": True, "free": False, "port": port}
        except Exception as e:
            return {"ok": False, "error": str(e)}
        finally:
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass

    def generate_start_script(self, name, server_type, port):
        """生成启动脚本 bat。server_type: lan / internet
        官方参数写法为空格分隔：ServerHelper.bat -Port 27015 +InternetServer/名字。"""
        name = (name or "").strip()
        bad = self._check_instance_name(name)
        if bad:
            return bad
        try:
            port = int(port)
        except (TypeError, ValueError):
            return {"ok": False, "error": f"端口无效: {port}"}
        helper = os.path.join(self.game_dir, "ServerHelper.bat")
        if not os.path.isfile(helper):
            helper = os.path.join(self.game_dir, "Unturned.exe")
        prefix = "+InternetServer" if server_type == "internet" else "+LanServer"
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        lines = [
            "@echo off",
            "chcp 65001 >nul",          # 先切 UTF-8 再写中文 rem，避免乱码
            f"rem 由 {APP_NAME} 生成于 {ts}",
            f'start "" "{helper}" -Port {port} "{prefix}/{name}"',
            "exit",
        ]
        out = os.path.join(self.base_dir, f"启动服务器_{name}.bat")
        try:
            with open(out, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            return {"ok": True, "path": out, "lines": lines}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def generate_connect_info(self, name, public_ip, port, mode="public"):
        """生成连接信息。mode: public(公网列表) / lan(局域网)
        官方口径：Port 命令设的是游戏端口（玩家 connect 用），查询端口 = Port+1。"""
        name = (name or "").strip()
        bad = self._check_instance_name(name)
        if bad:
            return bad
        try:
            port = int(port)
        except (TypeError, ValueError):
            return {"ok": False, "error": f"端口无效: {port}"}
        query_port = port + 1
        if mode == "lan":
            lines = [
                f"服务器: {name}",
                f"游戏端口: {port}   查询端口: {query_port}",
                "",
                "【局域网联机方式】",
                "1. 确保和朋友在同一网络（同一 WiFi / 局域网）;",
                "2. 朋友打开游戏 → 服务器列表 → 局域网(LAN) 标签 → 搜索服务器名;",
                f"3. 或游戏控制台输入: connect {public_ip}:{port}",
                "",
                "提示：局域网联机无需公网 IP、无需 GSLT 令牌、无需端口映射。",
            ]
        else:
            lines = [
                f"服务器: {name}",
                f"游戏端口: {port}   查询端口: {query_port}",
                "",
                "【好友连接方式】",
                "1. 游戏内 服务器列表(互联网) 搜索服务器名;",
                f"2. 或游戏控制台输入: connect {public_ip}:{port}",
                "",
                "【需要开放】",
                f"路由器端口映射: UDP {port}-{query_port} → 本机局域网IP",
            ]
        out = os.path.join(self.base_dir, f"连接信息_{name}.txt")
        try:
            with open(out, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            return {"ok": True, "path": out, "content": "\n".join(lines),
                    "game_port": port, "query_port": query_port}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def generate_frp_connect(self, name, tunnel_addr):
        """生成内网穿透连接信息（朋友直接 connect 隧道地址）。"""
        name = (name or "").strip()
        bad = self._check_instance_name(name)
        if bad:
            return bad
        tunnel = (tunnel_addr or "").strip()
        if ":" not in tunnel:
            return {"ok": False, "error": "隧道地址格式应为 域名:端口，如 xxx.sakurafrp.com:12345"}
        lines = [
            f"服务器: {name}",
            "",
            "【朋友连接方式（内网穿透）】",
            f"游戏控制台输入: connect {tunnel}",
            "",
            "提示：隧道转发的是游戏端口（Commands.dat 的 Port），请确认 SakuraFrp 隧道本地端口填的是游戏端口。",
        ]
        out = os.path.join(self.base_dir, f"连接信息_{name}_frp.txt")
        try:
            with open(out, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            return {"ok": True, "path": out, "content": "\n".join(lines)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def open_path(self, path):
        try:
            os.startfile(path)  # noqa
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def get_meta(self):
        return {"maps": MAPS, "difficulties": list(DIFFICULTIES),
                "difficulty_groups": list(DIFFICULTY_GROUPS)}


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def resource_path(rel):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def main():
    # 打包后 __file__ 指向 _MEIPASS 临时目录；settings/bat/txt 必须写到 exe 所在目录
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    api = Api(base)

    index = resource_path(os.path.join("web", "index.html"))
    if not os.path.isfile(index):
        print("未找到 web/index.html")
        return 1

    window = webview.create_window(
        f"{APP_NAME} v{APP_VERSION}",
        url=index,
        js_api=api,
        width=1240, height=820,
        min_size=(980, 640),
        background_color="#f4f6fb",
    )
    webview.start(debug=False, http_server=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
