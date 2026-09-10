# stormsuregent —— 风暴潮与海浪智能预报「结果落地」Agent 编排层

编排层骨架：把用户自然语言需求，调度 5 个业务模块（Meta / 地理·插值·统计 / 选优 / 评估 / 简报 / 可视化），
最终以「文字结论 + 图片」返回。产品形态对标豆包式对话 APP。

> 负责人：金智宇（总体编排）

## 目录结构

```
stormsurgeagent/
├── orchestrator/          # 编排层核心
│   ├── contract.py        # 模块接口契约（345 模板「接口」落地）
│   ├── context.py         # 数据上下文辅助
│   ├── intent.py          # 意图解析（规则兜底 + LLM 占位）
│   ├── router.py          # 场景路由
│   ├── engine.py          # 编排引擎（两阶段 + 中间选优）
│   └── memory.py          # 会话记忆（防降智，硬性要求）
├── modules/               # 业务模块
│   ├── meta.py            # ① Meta 分析
│   ├── geo_stats.py       # ② 地理·插值·统计
│   ├── selector.py        # ★ 选优
│   ├── assess.py          # ③ 危险性评估
│   ├── brief.py           # ④ 简报生成（Markdown + Word）
│   ├── brief_tpl.py       # 简报模板引擎（依据厦门海洋预报台格式）
│   └── visualize.py       # ⑤ 可视化
├── scenarios/routes.yaml  # 场景路由表
├── main.py                # Gradio 网页对话入口
└── requirements.txt
```

## 简报模板引擎（modules/brief_tpl.py）

按「厦门中心简报材料」的 5 类发布格式提炼，结构化 dict → 两种渲染：

| template_type | 对应预测内容 | 核心表格 |
| --- | --- | --- |
| storm_surge_alert | 风暴潮警报 | 潮位×警戒潮位对照表 |
| wave_alert | 海浪警报 | 分海域浪高分段表 |
| wave_message | 海浪消息 | 分海域浪高分段表 |
| marine_env_forecast | 海洋环境预报 | 风/浪时段表 |
| situation_analysis | 形势分析预测 | 潮位表 |

`brief.py` 已接入：上游 `assess.brief_data` 塞入标准字段即自动渲染
（`results["brief"] = {markdown, docx_path, template}`）。

## 快速开始

### 方式一：一键部署（推荐，给交付对象）

交付包解压后双击 `1-一键部署-Windows.bat`：自动装 Python → 建虚拟环境 → 装依赖 →
引导填 DeepSeek API Key → 启动并自动打开浏览器。以后启动双击 `2-启动.bat`。

装不上时双击 `3-环境自检.bat`，会生成一份《环境自检报告.md》，
里面包含系统位数、Python、pip 源连通性、磁盘、端口、数据目录等事实，
**可以直接复制给 AI 助手，让它判断缺什么**。详见 `deploy/部署说明.md`。

### 方式二：手工

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      # 然后填入 DEEPSEEK_API_KEY
python main.py              # 浏览器打开 http://localhost:7860
```

打交付包：`python scripts/build_deploy_package.py` → `dist/…-部署包-YYYYMMDD.zip`
（自动排除 `.venv`/`data`/`outputs`/密钥/对话记录）。

### 样例数据（可选）

```bash
python scripts/make_sample_data.py   # 一键生成样例 NC 数据（约30MB）
```

浏览器打开 http://localhost:7860 ，输入：
`帮我看未来5天厦门海域有没有风暴潮海水倒灌风险`

运行说明详见 `部署运行说明.md`；无密钥/无数据时自动降级为骨架演示（stub 假结果，链路跑通）。

## 模块如何接入

每个模块遵守统一契约（见 `orchestrator/contract.py`）：

```python
from orchestrator.contract import ModuleContext

def run(ctx: ModuleContext) -> ModuleContext:
    # 读上游：ctx.request（槽位）、ctx.files（文件）、ctx.results（上游产出）
    # 写自己：ctx.results["你的模块名"] = {...}
    return ctx
```

模块负责人只需在他负责的 `modules/xxx.py` 里实现这个 `run` 函数，
替换掉 stub 即可，**编排引擎零改动**。

## 会话记忆（防降智）

`orchestrator/memory.py` 每轮对话落盘到 `AgentRecord.session.jsonl`，
新对话可 `memory.recent()` 读回最近记录恢复上下文。
（该记录文件属本地运行产物，已在 `.gitignore` 中忽略，不上传仓库。）

## 覆盖范围与任意点查询（orchestrator/geo_domain.py）

用户提问的地点按四级处理，避免给出无依据的结果：

| 情况 | 处理 |
| --- | --- |
| 超出覆盖区（上海、青岛、深圳、宁波…） | 只回文字说明，**不出任何数据/图** |
| 大范围区域（台湾、福建、浙江、中国沿海…） | **追问具体位置**，不出数据 |
| 本站站点（厦门、崇武、晋江、东山东港） | 走本站单点数据 + 四色警戒潮位判级 |
| 覆盖区内任意地名 / 直接给经纬度 | 在模式场/网格上**按点采样**，按风暴增水分级判级 |

- 覆盖范围：`114.5°E ~ 127.5°E，17.0°N ~ 29.5°N`（台湾海峡及福建、浙南沿海）
- 地名字典约 150 个沿海地名（福建/浙南/粤东/台湾各城市与港湾），新增地名只需往
  `KNOWN_PLACES` 加一行"名称: (经度, 纬度)"。
- 经纬度解析支持：`120.5°E, 24.5°N`、`东经120.5 北纬24.5`、`120.5E 24.5N`、`120.5,24.5`。
- 按点采样优先级：非结构三角网格（Ensemble / FTP `*_surge.nc`）→ 结构化网格
  （2526 `output_0/4.nc`）→ 最近本站站点兜底；每个结果都会注明
  "取自最近有效格点（经纬度，距目标点约 N km）"，可在简报注释里看到。
- 采样取"最近 3 个有效格点的中位数"，并排除陆地/未计算格点（`depth<=0`）
  与河口内数值≈0 的假格点（潮位幅度 < 30cm）。

