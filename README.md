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

```bash
cd stormsuregent
pip install -r requirements.txt
copy .env.example .env      # 填入自己的 DeepSeek / 腾讯云密钥
python scripts/make_sample_data.py   # 一键生成样例 NC 数据（约30MB，可选）
python main.py
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
