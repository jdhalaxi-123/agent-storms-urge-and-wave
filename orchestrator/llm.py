"""LLM 对话大脑：DeepSeek 驱动，支持常识问答 + 预报工具调用（Function Calling）。

职责：
    - 常识/知识类问题（"风暴潮是什么"、"厦门在哪"）→ LLM 直接回答
    - 预报需求 → LLM 调用 forecast_risk 工具 → 编排引擎 → 结果回 LLM 组织语言
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from openai import OpenAI

MODEL = "deepseek-v4-pro"
BASE_URL = "https://api.deepseek.com"

SYSTEM_PROMPT = (
    "你是「风暴潮与海浪智能预报助手」。"
    "对风暴潮、海浪、海洋预报相关的常识或知识问题，直接清晰回答；"
    "当用户需要查询某个海域的具体预报风险（海水倒灌、增水、浪高、预警等级等）时，"
    "调用 forecast_risk 工具获取结果，再把结果整理成简洁易懂的回复。"

    # ===================== 需求澄清（grill-me 风格）===================== #
    "【先说清“什么时候该问、什么时候直接做”】"
    "**默认直接做**：只要用户说了「地点 + 灾种」（例如“厦门的风暴潮”“闽南的海浪”“崇武的增水”），"
    "就**立刻调 forecast_risk 取数并给结论 + 一张核心图**，不要追问。"
    "缺的槽位一律按默认值处理，并在结论里用一句话说明你按什么默认值算的："
    "时间=最近一次每日预报；要素=增水（风暴潮）/有效波高（海浪）；图=该灾种的核心图。"
    "**没给范围时不要问“看哪里”**：把 region 直接填“全场”，按全场给结论和成品图。"
    "（全场海浪→系统自动给课题三的『全场预报 风+浪双面板动图』；"
    "全场风暴潮→自动给最大增水场图 + 站点时序图）。"
    "**用户不需要说“动图/动画”两个字**：出图是系统按范围自动决定的——"
    "全场海浪=课题三全场风+浪动图；局地（闽南、厦门沿海、台湾海峡等）=区域场分布图；"
    "站点=该站时序图。用户正常问“全场海浪”“闽南的增水”就行。"
    "**只有两种情况才追问**：① 用户明确说“先问我几个问题/帮我把需求问清楚”；"
    "② 要历史台风个例但没说台风编号。"
    "【开工前先过一遍 5 个槽位】这是本助手的习惯：宁可多问一句，不要猜着给结果。"
    "① 位置——哪个站点（厦门/崇武/晋江/东山东港）、哪个区域（福建/台湾海峡/粤东…）、还是经纬度？"
    "② 时间——今天/明天/未来几天/某个历史台风？"
    "③ 数据口径——看**当天的每日预报**，还是**某个历史台风个例**？"
    "④ 关心什么——增水多大 / 总水位会不会超警戒潮位 / 浪高多少 / 会不会海水倒灌？"
    "⑤ 要不要图——站点过程曲线 / 区域分布图 / 海浪曲线（要哪些给哪些）？"
    "**上面①②③④⑤只是自检清单**：缺的槽位一律按默认值直接做"
    "（范围默认“全场”、时间默认最近一次每日预报、灾种默认风暴潮），**不要拿这些去反问用户**。"
    "要追问时：先调用 query_options 拿到真实可选项，然后**一次性**向用户提 2~3 个带选项的问题。"
    "追问要求："
    "· **只问缺的**——用户已说清的不要再问，能从对话上文推断的直接沿用；"
    "· **每个问题都给可选答案**，用户一句话甚至一个词就能答完（如“厦门”“明天”“要图”）；"
    "· **一次问完**，不要一轮问一个地挤牙膏；"
    "· **选项必须真实**——日期范围、台风编号、区域名一律取自 query_options 的返回，"
    "不能凭印象编（例如不要问“要不要看 2020 年的台风”而系统里根本没有）；"
    "· 结尾加一句：“也可以直接说‘你看着给’，我就按常用默认值出结果”。"
    "用户回答后：**把前后几轮的信息合并**成完整槽位再调 forecast_risk，不要重复确认已答过的内容。"
    "若用户明确说“别问了/直接给/你看着给”，就按默认值（范围=全场、时间=最近一次每日预报、"
    "灾种=风暴潮）直接执行，不再追问。"
    "若用户说“先问我几个问题/帮我把需求问清楚”，即使信息看起来够，也先按上面 5 个槽位问一轮。"

    "【画图】当用户要求“画/看/展示”某类图时，调用 forecast_risk 工具，"
    "并通过 plot 参数**只指定用户要的那一类图**（wind=风场、surge_station=站点过程曲线、"
    "surge_field=**风暴潮/增水场空间分布**、wave_field=**海浪场空间分布**、"
    "wave=海浪波高曲线、wind_wave=风+浪并排双联图、gif=动图/动画、"
    "validation=预报与实测对比图）；"
    "【要“场”怎么填】用户说“**厦门沿海的海浪场**”“闽北沿海的增水分布”“XX沿海的波高分布图”这类话时："
    "region 填那个地名、disaster 按灾种、plot 填 wave_field（浪）或 surge_field（潮/增水），"
    "**不要追问“想看哪个范围”**——场不是预先定好的，系统会自动以该地点为中心、"
    "东南西北各约 90 km 取一个框出场分布图。只有用户说的是真的泛指（“沿海”“近海”这种没有具体地名）才需要追问。"
    "【要看全场】用户说“**全场**”“全域”“全部海域”“整个覆盖范围”“最大的范围”时，"
    "region **必须填“全场”**（系统会理解为整个覆盖范围 114.5~127.5°E／17~29.5°N），"
    "**绝对不要沿用上一轮对话里的地名**（比如上文在聊厦门，用户说“我想看全场的”就填“全场”，不要填厦门）。"
    "用户要多种时才用 all。切忌用户只要一种却把各类图都画出来。"
    "用户没提图时不要传 plot（默认按灾种给一张核心图）。"
    "【EC 不是地名】用户说“EC 预报 / 欧洲中心 / ECMWF”时，那是**预报来源**、不是地点："
    "region 填“全场”（不要填 EC），plot 填 gif，系统会给 EC 起报的那张风+浪动图。"
    "【自绘图只有区域场分布图】本系统自己画的图**只有一种：区域/局地的场分布图**"
    "（如“闽南的增水场”“厦门沿海的海浪场”）。站点过程曲线、时序曲线、风浪双联图、"
    "动图**都不再自绘**：这些一律用 FTP 上的静态成品图；FTP 上没有的（例如增水动图、"
    "单站动图），就如实说没有，**不要说自己画了一张**，也不要拿别的图顶。"
    "【自绘动图只是风场图】本系统自己画的那张动图是**风场动图**（风速+风向），"
    "**不是“风+浪双面板”**，说它时必须按“风场动图”说，不要用“风+浪双面板”这种说法。"
    "【没有的图不许编】课题三**没有出“单站动图”**：用户要“某站的增水/风暴潮动图”时，"
    "工具只会返回该站的**静态过程曲线**，你要如实说明“他们没出单站动图，这是该站的过程曲线”，"
    "**不许把场动图说成该站动图，也不许说“已生成该站动图”**。"
    "系统自带的动图只有**风场（风+浪）动图**；要“增水/风暴潮”的动图而没有成品时，"
    "先如实说没有，再**问用户**“要不要用数据现画一版（我们自己画的，不是他们的成品）”，"
    "用户同意后才画。**任何情况下都不许拿不相关的图充数。**"
    "【图片说明以 image_notes 为准】工具返回的 image_notes 逐张写明了每张图是什么，"
    "**必须照它说，不许自己发挥**。特别注意："
    "① 他们**没有“单站动图”**——站点要动图时，给的是“覆盖该海域的 0.01° 场动图”，"
    "必须说成“福建中南部 0.01° 增水场动图（覆盖厦门海域）”，"
    "**绝对不许说成“厦门站的动图/崇武站的动图”**；"
    "② images 里没有的图，一句都不许说“已生成”；"
    "③ 系统没有的产品就说没有（例如“他们没出单站动图”），**不要编**。"
    "【动图/动画】用户说“动图/动画/动起来/gif”时传 plot=gif。"
    "课题三**只有两张成品动图**：**全场预报**（风+浪双面板）与 **EC 预报**（风+浪双面板）。"
    "**他们没有增水动图、也没有单站动图**——用户要“增水/风暴潮的动图”时，"
    "如实体说明“他们只有风+浪两张动图，没有增水动图”，并把工具返回的"
    "**最大增水场图（静态）**给用户；"
    "**绝对不许说增水动图/某站动图已生成，也不许把风+浪动图说成增水动图**。"
    "用户要 EC 那版就说 EC 预报，要全场那版就说全场预报。"
    "闽南、厦门沿海这类**局地**动图，系统会自己画（画的是**风场**动图）。"
    "**站点问题不要传 surge_field**：问“厦门/崇武/晋江/东山东港 的风暴潮/海浪”时，"
    "默认那张站点过程曲线就是对的东西，不要传 plot（传了反而可能出不来图）。"
    "【风场】问“今天的风场/风有多大/画一下风场”时传 plot=wind："
    "系统会**自己按需取当天的每日风场**（/group3/wind，约 260 MB，首次 30~60 秒，之后走缓存）。"
    "**规则（务必遵守）**："
    "① 直接取、直接画，**不要问用户“要不要我取一次”“数据没下载要不要等”**——没下载就下载，这是系统的活；"
    "② **不要用“每日风暴潮预报尚未更新”去否定风场**——风场有独立的更新节奏"
    "（通常前一日 22:00 后上传当天，工具返回的 wind.date 就是风场起报日，照它说）；"
    "③ 工具返回里 **images 里有哪张图就说哪张图**；如果没有风场图，就如实说“风场图未生成”，"
    "**绝不允许拿风暴增水分布图、海浪图等别的图冒充风场图**；"
    "④ 顺手把风场的关键数字讲清楚（最大风速、出现在哪、影响哪个海域），不要只贴图不说话。"
    "当用户询问数据库/数据位置（如“XX数据在哪”“FTP上有什么”“有没有XX台风的YY数据”）时，"
    "调用 ftp_query 工具查询课题数据库，并把查到的路径/目录内容清楚告诉用户；"
    "只报告工具实际返回的路径，不要推测不存在的路径。"
    "当用户明确要求下载/同步某数据时，调用 ftp_sync 工具同步到本地，并告知同步了多少文件/多大。"
    "注意区分：问“数据在哪/有什么”→ ftp_query；问“预报结论/画图/看风场”→ forecast_risk。"
    "【台风】当用户提到台风编号（如“2403号台风”“1513台风厦门的情况”）时，"
    "把编号填进 typhoon 参数。数据完整的台风有 10 个："
    "1513、1521、1601、1614、1617、1709、1808、2305、2311、2403，"
    "另有 2526 及若干只有部分数据源的台风（1909、2004、2106、2418、2420、2421、"
    "2504、2506、2511、2518、2524）。"
    "系统会自动按需从课题数据库(FTP)取数，不需要用户提供路径。"
    "若用户询问“有哪些台风可以用/能查哪些台风”，把上面这份清单直接告诉用户。"
    "【任意地点/经纬度】用户给出经纬度（如“120.5°E, 24.5°N”“东经120.5 北纬24.5”）时，"
    "在 region 里原样写上该坐标，并同时填写 lon / lat 两个参数；"
    "用户给出覆盖区内的任意沿海地名（如福州、平潭、澎湖、金门、高雄、汕头、温州）时，"
    "直接填 region，系统会在该地点的坐标处采样模式场，不需要再问经纬度。"
    "【站点：两套站别搞混】"
    "① 风暴潮单点（潮/增水）＝ **4 个本站**：厦门 XMN、崇武 CWU、晋江 JNJ、东山东港 DSN，有中文名与坐标；"
    "② 海浪单点（浪）＝ **浮标站号**：C6W10、46694A、C5W09 等 16 个，只有站号、没有中文名与经纬度。"
    "用户问「某个地方的浪」（如「厦门的海浪」）时，按地名取**模式场最近格点**并在回复里说明这一点；"
    "用户给的是浮标站号（如「C6W10 的浪高」）时按原样填进 region，系统会取真正的海浪单点产品。"
    "若用户问「有哪些浮标站 / 浪的站号」，用 query_options 的 wave_point_stations 回答。"
    "【简报行由程序追加】**正式简报的下载链接由程序在回复末尾自动追加**。"
    "你在回复里**不要写简报文件名、不要写“点击打开”、不要给下载链接**，"
    "也不要写“已生成简报 Word”之类的话——只讲结论和数据的要点即可。"
    "【覆盖范围】若 forecast_risk 返回“不在覆盖范围”的说明（如上海、青岛等），"
    "直接如实转达该说明，**绝不可自行编造该海域的任何数据或结论**。"
    "【需追问】若 forecast_risk 返回“范围较大，请具体说明位置”的追问说明"
    "（如用户只说“台湾”“福建”这类大范围），请把该追问**原样转达给用户**并等待用户补充具体位置，"
    "不要臆测用户想看的位置、也不要先给任何数据。"
    "【区域（面）预报】注意：问“福建的风暴潮”“台湾海峡的海浪”“浙江的增水”这类**较大区域**时，"
    "系统会用课题三每日人工智能预报的**场数据**直接给出该区域的"
    "「过程最大增水/浪高的空间分布图 + 区域峰值位置 + 分级格点数」，这是正常的**区域预报**，"
    "**不是**追问。回复时请按“空间分布”来描述（讲清峰值在哪、范围多大、有多少格点达某级别），"
    "不要只当成一个点来说。只有当系统明确返回“范围较大，请具体说明位置”时才转达追问。"
    "【重要】生成的图片会自动附加到对话中显示，回复里不要再用 markdown 图片语法"
    "（如 ![](...)）或写出本地文件路径，只需简要说明图的内容即可。"
    "【数字纪律】增水值、浪高、警戒潮位、时间、站点名等所有数值一律**照抄工具返回结果**，"
    "不要改写、不要凭印象补数字（例如警戒潮位 373/393/413/433 就照抄这四位数）；"
    "工具没给的数值就不要写。"
)

FORECAST_TOOL = {
    "type": "function",
    "function": {
        "name": "forecast_risk",
        "description": (
            "查询指定海域的风暴潮或海浪预报风险，并生成预报图"
            "（站点增水/水位过程曲线、全场增水分布、风场图、海浪波高曲线）。"
            "返回预警等级、风险结论与简报。"
            "用户要求“画图/看风场/看预报图”时也调用本工具。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "region": {
                    "type": "string",
                    "description": (
                        "海域或地名，如：厦门、崇武、晋江、东山东港、福州、平潭、泉州、"
                        "澎湖、金门、马祖、高雄、基隆、汕头、温州、台州；缺省为厦门。"
                        "覆盖区内的任意沿海地名都会在该坐标处采样模式场。"
                    ),
                },
                "disaster": {
                    "type": "string",
                    "enum": ["storm_surge", "wave"],
                    "description": "灾种：风暴潮=storm_surge，海浪=wave",
                },
                "time_window": {"type": "string", "description": "时间窗，如：未来5天"},
                "risk_type": {"type": "string", "description": "风险类型，如：海水倒灌、增水、浪高"},
                "typhoon": {
                    "type": "string",
                    "description": (
                        "台风编号（可省略）。**数据完整的 10 个台风**："
                        "1513、1521、1601、1614、1617、1709、1808、2305、2311、2403"
                        "（直接查课题数据库 FTP，含站点增水、全场增水、天文潮、总水位、"
                        "浮标波高与实测对照，可做「总水位对照警戒潮位」判级）；"
                        "2526 走本地数据；1909、2004、2106、2418、2420、2421、2504、2506、"
                        "2511、2518、2524 仅部分数据源。用户未指定台风时省略。"
                    ),
                },
                "date": {"type": "string", "description": "查看日期（可省略），如：7月22日、2024-07-22；用户指定具体日期时填写，否则省略"},
                "lon": {
                    "type": "number",
                    "description": (
                        "任意点经度（东经，十进制度，如 120.5），必须与 lat 成对出现。"
                        "用户给出经纬度坐标时填写；只说了地名时不要填（由 region 自动定位）。"
                    ),
                },
                "lat": {
                    "type": "number",
                    "description": (
                        "任意点纬度（北纬，十进制度，如 24.5），必须与 lon 成对出现。"
                        "用户给出经纬度坐标时填写。"
                    ),
                },
                "plot": {
                    "type": "string",
                    "enum": ["wind", "surge_station", "surge_field", "wave_field", "wave",
                             "wind_wave", "gif", "validation", "product", "all"],
                    "description": (
                        "需要出图时填写图类型（问什么画什么，不要多给）："
                        "wind=风场图（风速填色+风向箭头+7/10级等值线）；"
                        "surge_station=站点增水/水位过程曲线；"
                        "surge_field=**风暴潮/增水场空间分布**（区域或某地沿海的“场”）；"
                        "wave_field=**海浪场空间分布**（如“厦门沿海的海浪场”）；"
                        "wave=海浪波高曲线；"
                        "wind_wave=风+浪并排双联图（业务上最常用的合成图）；"
                        "gif=**动图/动画**（用“动图/动画/动起来”时才用；"
                        "课题三只有两张成品动图：**全场预报**与 **EC 预报**（都是风+浪双面板），"
                        "**没有增水动图、没有单站动图**；局地如闽南由系统自绘**风场**动图）；"
                        "validation=预报与实测对比密度散点（仅台风个例有实测时）；"
                        "product=**直接用课题三自己出的成品图**（官方版本：0.01° 最大增水场图 "
                        "＋该站时序图；用户说“用他们的图/官方图/课题三的图”时填这个）；"
                        "all=全部图。用户没明确要图时省略（默认按灾种给一张核心图）。"
                        "注意：用户点名某地要“场/分布”时用 surge_field / wave_field，"
                        "系统会自动以该地点为中心取一个框，不需要追问范围。"
                    ),
                },
            },
            "required": ["disaster"],
        },
    },
}


OPTIONS_TOOL = {
    "type": "function",
    "function": {
        "name": "query_options",
        "description": (
            "查询系统**当前可选的范围**（可查的站点/区域/台风编号、最新一次每日预报的起报日与覆盖时段、"
            "灾害类型、可出的图类型）。"
            "**在向用户追问之前先调用它**，这样问出来的选项都是真实可用的，不会问到查不到的东西。"
            "返回后按“需求澄清”协议向用户提 3~5 个带选项的问题。"
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}


def _call_options(args: Dict[str, Any]) -> Dict[str, Any]:
    """返回当前数据可用范围（供 LLM 生成**准确的追问选项**）。"""
    from orchestrator import geo_domain

    out: Dict[str, Any] = {
        "stations": list(geo_domain.SESSION_STATION_COORD.keys()),
        "disaster": {"storm_surge": "风暴潮（增水/总水位/倒灌风险）", "wave": "海浪（有效波高/浪高）"},
        "plots": {"surge_station": "站点过程曲线", "surge_field": "全场增水分布",
                  "wave": "海浪波高曲线", "wind": "风场", "wind_wave": "风+浪并排双联图",
                  "gif": "动图/动画（只有两张：全场预报、EC 预报，均风+浪双面板）",
                  "product": "课题三出的官方成品图", "all": "全部"},
        "domain": geo_domain.DOMAIN_DESC,
        "out_of_domain_examples": ["上海", "青岛", "大连", "深圳", "宁波", "舟山", "海口"],
    }
    # 海浪单点的浮标站号（与风暴潮单点的 4 个本站是**两套不同的站**）
    try:
        from modules import ai_daily as _ad
        codes = _ad.list_point_wave_stations("")
        out["wave_point_stations"] = codes
        out["stations_note"] = (
            "风暴潮单点=4 个本站（厦门 XMN / 崇武 CWU / 晋江 JNJ / 东山东港 DSN，有中文名与坐标）；"
            "海浪单点=浮标站号（如 C6W10 / 46694A，只有站号、没有中文名与经纬度）。"
            "用户没说站号但问「某个地方的浪」时，按地名取模式场最近格点，"
            "并在回复里说明「取的是该位置最近格点」，不要说成浮标站数据。")
    except Exception:
        pass
    # 可查的区域（大范围 → 会出区域分布图）
    try:
        out["regions_field"] = sorted(geo_domain.FIELD_CAPABLE_BROAD)
    except Exception:
        out["regions_field"] = ["福建", "浙江", "台湾", "台湾海峡", "粤东", "闽南", "东海"]
    # 可查的台风个例
    try:
        from . import ftp_catalog as fc
        tys = fc.typhoon_list()
        from modules import ftp_typhoon as fty
        out["typhoons_complete"] = list(fty.COMPLETE_TYPHOONS)
        out["typhoons_partial"] = [t for t in tys if t not in fty.COMPLETE_TYPHOONS]
        out["typhoons_hint"] = ("用户提到台风编号时填 typhoon 参数；"
                                "未提台风时按“当日预报”回答")
    except Exception:
        out["typhoons_complete"] = ["1513", "1521", "1601", "1614", "1617",
                                    "1709", "1808", "2305", "2311", "2403"]
    # 当日预报的时效
    try:
        from modules import ai_daily as ad
        i = ad.update_info(kind="surge")
        w = ad.update_info(kind="wave")
        out["daily_forecast"] = {
            "latest_issue_date": i.get("latest_date"),
            "storm_surge_cover": f"{i.get('latest_start')} ~ {i.get('cover_end')}",
            "wave_cover": f"{w.get('latest_start')} ~ {w.get('cover_end')}",
            "update_schedule": i.get("schedule"),
            "today_ready": i.get("today_ready"),
        }
    except Exception:
        pass
    return {"ok": True, **out}


FTP_TOOL = {
    "type": "function",
    "function": {
        "name": "ftp_query",
        "description": (
            "查询课题数据库(FTP)上的数据目录/文件位置。用户问“数据在哪”“FTP上有什么”“有没有XX数据”时调用。"
            "FTP 根目录下有 group1~group5（对应课题一~五）；"
            "group1/storm_surge 是风暴潮场, group1/storm_surge/era5 是ERA5风场, "
            "group3/wind 是风场, group3/storm_surge_point 是风暴潮单点。"
            "【重要】只能报告本工具实际返回的路径/文件名，"
            "绝不能凭推测补充未在返回结果中出现的路径；"
            "若某目录不存在会在返回中体现，请如实告知用户“该路径不存在”。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要查看的FTP目录，如 /group3/wind；缺省 /"},
                "keyword": {"type": "string", "description": "可选：按关键字过滤或搜索，如 2526、wave、storm_surge"},
                "search_root": {"type": "string", "description": "可选：递归搜索的起始目录（与keyword配合），如 /group1"},
            },
            "required": [],
        },
    },
}


FTP_SYNC_TOOL = {
    "type": "function",
    "function": {
        "name": "ftp_sync",
        "description": (
            "从课题数据库(FTP)同步数据到本地，供后续预报/绘图使用。"
            "当用户明确要求“下载/同步/拉取某数据”时调用。"
            "注意：单个文件可达数百MB，应先用 ftp_query 确认目录内容，"
            "并在同步前告知用户预计数据量；默认最多同步20个文件。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "remote_dir": {"type": "string", "description": "要同步的FTP目录，如 /group3/wind/typhoon_2526"},
                "keyword": {"type": "string", "description": "可选：只同步文件名含此关键字的文件，如 2025111"},
                "max_files": {"type": "integer", "description": "可选：最多同步文件数，默认20"},
            },
            "required": ["remote_dir"],
        },
    },
}


def _load_api_key() -> str:
    key = os.environ.get("DEEPSEEK_API_KEY")
    if key:
        return key
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DEEPSEEK_API_KEY="):
                val = line.split("=", 1)[1].strip()
                if val:
                    return val
    raise RuntimeError("未找到 DEEPSEEK_API_KEY，请在项目根目录 .env 文件里配置")


_client = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=_load_api_key(), base_url=BASE_URL)
    return _client


def _call_ftp(args: Dict[str, Any]) -> Dict[str, Any]:
    """执行 FTP 查询工具：列目录 或 关键字搜索。"""
    from . import ftp_client

    keyword = (args.get("keyword") or "").strip()
    search_root = (args.get("search_root") or "").strip()
    if keyword and search_root:
        res = ftp_client.search(search_root, keyword)
    else:
        res = ftp_client.query(args.get("path") or "/", keyword)
    return res


def _call_ftp_sync(args: Dict[str, Any]) -> Dict[str, Any]:
    """执行 FTP 同步工具：把远程目录下的文件拉到本地。"""
    from . import ftp_client

    return ftp_client.sync_dir(
        args.get("remote_dir", ""),
        keyword=(args.get("keyword") or "").strip(),
        max_files=int(args.get("max_files") or 20),
    )


def _call_forecast(args: Dict[str, Any], user_text: str = "") -> Dict[str, Any]:
    """执行预报工具：把 LLM 填的参数转成槽位，跑编排引擎。

    user_text：**用户这一轮的原话**。必须传，否则"动图/动画"这类关键词会丢，
    引擎里"原话要动图 → 一定出动图"的兜底就失效（见 engine.run_with_slots）。
    """
    from . import engine  # 延迟导入，避免循环依赖

    slots = {
        "disaster": args.get("disaster", "storm_surge"),
        "risk_type": args.get("risk_type", "general"),
        # 没填范围时默认"全场"（用户可查的最大范围），不再默认厦门
        "region": args.get("region") or "全场",
        "time_window": args.get("time_window", "未指定"),
        "typhoon": args.get("typhoon", ""),
        "date": args.get("date", ""),
        "plot": args.get("plot", ""),
        "lon": args.get("lon"),
        "lat": args.get("lat"),
        "raw": user_text or "llm",
    }
    result = engine.run_with_slots(
        slots, raw=user_text or json.dumps(args, ensure_ascii=False))
    # ⭐ 简报下载行由 main.py 统一追加（读 briefs/.last_brief，带可点链接）。
    #    这里**必须把 docx 信息从工具返回里摘掉**：模型一旦看到路径，
    #    就会自己再写一行"📄 正式简报：xxx.docx　点击打开"，末尾变成两条简报行。
    result.pop("docx_path", None)
    # ⭐ 出图失败时把原因交给模型，让它如实告诉用户（以前只打在控制台，界面上看不出）
    vis_err = result.get("plot_error")
    if vis_err and not (result.get("images") or []):
        result["plot_error"] = vis_err
        result["reply"] = (
            f"{result.get('reply', '')}\n\n"
            f"⚠️ 本次绘图未成功（数据是好的，问题在绘图环节）：{vis_err}\n"
            "请把启动窗口里的报错发给技术支持；也可运行 "
            "`python scripts/check_pipeline.py` 定位。"
        )
    return result


TOOLS = [FORECAST_TOOL, OPTIONS_TOOL, FTP_TOOL, FTP_SYNC_TOOL]

# 允许的最大工具轮数：够 query_options → forecast_risk → 出结论这条链，
# 又不至于让异常情况下无限循环。超出后强制不带工具出最终文本。
MAX_TOOL_ROUNDS = 3

_WEEKDAY = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _system_prompt() -> str:
    """系统提示 + 当前日期，避免模型把“今天/明天”算错。"""
    now = datetime.now()
    return (SYSTEM_PROMPT
            + f"\n【当前时间】{now:%Y-%m-%d %H:%M}（{_WEEKDAY[now.weekday()]}）。"
            "用户说“今天/明天/后天/昨天/本周”时按此换算成具体日期；"
            "不要凭训练记忆猜现在是几号。")


def _run_tool(tc, user_text: str = "") -> Tuple[Dict[str, Any], List[str]]:
    """执行一个工具调用，返回 (结果, 新增图片)。user_text = 用户本轮原话。"""
    try:
        args = json.loads(tc.function.arguments or "{}")
    except json.JSONDecodeError:
        args = {}
    if not isinstance(args, dict):
        args = {}

    name = tc.function.name
    if name == "ftp_query":
        return _call_ftp(args), []
    if name == "ftp_sync":
        return _call_ftp_sync(args), []
    if name == "query_options":
        return _call_options(args), []

    result = _call_forecast(args, user_text=user_text)
    return result, list(result.get("images") or [])


def chat(message: str, history: List[List[str]]) -> Tuple[str, List[str]]:
    """一轮对话。history 为 Gradio 传入的 [[user, assistant], ...]，返回 (文本, 图片列表)。

    每次 API 调用带 120s 超时，避免网络阻塞导致前端挂起。
    支持多轮工具调用（最多 MAX_TOOL_ROUNDS 轮），这样 LLM 可以：
        先 query_options 拿真实可选项 → 追问用户（纯文本，结束）；
        或 query_options → forecast_risk → 基于真实结果作答。
    """
    client = _get_client()

    if not message or not str(message).strip():
        return "（没有识别到有效内容，请重试）", []

    messages: List[Dict[str, Any]] = [{"role": "system", "content": _system_prompt()}]
    for user_msg, bot_msg in history:
        # Gradio 传进来的助手消息是 (文本, 图片列表) 元组，取文本即可，
        # 否则 str(tuple) 会把图片路径一起塞进上下文。
        if isinstance(bot_msg, (tuple, list)):
            bot_msg = bot_msg[0] if bot_msg else ""
        # 跳过空消息，避免 DeepSeek 报 "content or tool_calls must be set"
        if user_msg:
            messages.append({"role": "user", "content": str(user_msg)})
        if bot_msg:
            messages.append({"role": "assistant", "content": str(bot_msg)})
    messages.append({"role": "user", "content": str(message)})

    images: List[str] = []
    docx_made: List[str] = []
    seen: Dict[Tuple[str, str], Tuple[Dict[str, Any], List[str]]] = {}
    for _round in range(MAX_TOOL_ROUNDS):
        resp = client.chat.completions.create(
            model=MODEL, messages=messages, tools=TOOLS, timeout=120)
        msg = resp.choices[0].message

        # 未调工具：直接返回文本（追问、常识回答、预报结论都走这里）
        if not msg.tool_calls:
            return msg.content or "（未生成回复，请重试）", images

        # 调了工具：手动构造 assistant 的 tool_calls 消息补回
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name,
                                 "arguments": tc.function.arguments or "{}"},
                }
                for tc in msg.tool_calls
            ],
        })

        for tc in msg.tool_calls:
            key = (tc.function.name, tc.function.arguments or "{}")
            if key in seen:
                # 模型偶尔会把同一个调用重复发很多遍；预报/下载很贵，直接复用结果
                result, new_images = seen[key]
            else:
                try:
                    result, new_images = _run_tool(tc, user_text=str(message))
                except Exception as exc:  # 工具异常不能让整轮对话挂掉
                    result, new_images = {"ok": False,
                                          "error": f"{type(exc).__name__}: {exc}"}, []
                seen[key] = (result, new_images)
            if new_images:
                images = new_images
            _dx = (result or {}).get('docx_path')
            if _dx:
                docx_made.append(str(_dx))
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, ensure_ascii=False),
            })

    # 轮数用尽：强制不带工具出最终文本，保证一定给用户一个回复
    resp = client.chat.completions.create(model=MODEL, messages=messages, timeout=120)
    _final = resp.choices[0].message.content or "（未生成回复，请重试）"
    # 简报行只由 main.py 追加（此处不再补，避免出现两条）
    return _final, images
