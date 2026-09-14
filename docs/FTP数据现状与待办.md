# FTP 数据现状 · 已确认结论与待办

> 本文记录对课题数据库（FTP）数据性质的核实结论，供后续对接与开发参考。
> 最后更新：2026-09-11

---

## 一、已确认结论（有官方文档 + 数据实测双重印证）

### 1. `output_0.nc` / `output_4.nc` 的语义 —— **已确认**

依据 `/group1/storm_surge/正交/说明.txt` 原文：

```
*_4.nc：风+潮驱动
*_0.nc：潮驱动
文件内：elev(水位) current_u current_v lon lat depth
```

**数据实测印证**（2311 台风，单位 m）：

| 文件 | 厦门 (118.25,24.50) | 崇武 (119.00,25.00) |
| --- | --- | --- |
| `output_0`（潮驱动） | −1.891 ~ 1.807，峰谷差 **3.70 m**，过零 20 次/145h | 峰谷差 **5.54 m** |
| `output_4`（风+潮驱动） | −1.810 ~ 2.153，峰谷差 3.96 m | 峰谷差 5.58 m |
| **相减 = 增水** | **最大 55.8 cm** | **最大 50.9 cm** |

厦门潮差 3.7 m、崇武潮差 5.5 m 均为真实量级；相减得到 50~56 cm 增水，量级正确。

**结论**：
- `output_0.elev` = **天文潮位**
- `output_4.elev` = **总水位**
- **风暴增水 = `output_4.elev` − `output_0.elev`**

> ⚠️ 此前把这两份文件误解为「数值模拟 / AI 融合」两个方案，属**错误**。
> 二者是**同一个数值模式、两种驱动方式**，**都不是 AI 产品**。

### 2. 非结构网格文件的变量语义 —— **有官方说明**

`/group5/irregular/irregular-数据说明.docx`（以 2305 为例）明确列出：

| 变量 | 含义 |
| --- | --- |
| `elev_all` | **天文潮 + 风暴潮**（总水位） |
| `elev_tide` | **天文潮** |
| `elev_surge` | **风暴潮增水** |
| `elev_surge_face` | 风暴潮增水（三角网格面型） |
| `depth` / `lat` / `lon` / `tri` | 深度 / 经纬度 / 三角网格连通表 |
| `surge` | 增减水（源自 `/group3/ocn/typhoon_XXXX/ocn_forecast_*.nc`） |

**与第 1 条完全自洽**：非结构网格文件直接给出三要素，规则网格文件需相减得到增水。

### 3. `regular` / `regular-H` 是什么 —— **是波浪数据，且数值与 AI 并列**

`/group5/regular/regular-数据说明.docx`、`regular-H数据说明.docx`：

| 项 | regular | regular-H |
| --- | --- | --- |
| 网格 | 规则网格，0.05° | 规则网格，**1/120°（约 0.0083°）** |
| 范围 | 16–30°N，110–127°E | **23.2–25.2°N，117–119.5°E（厦门附近细网格）** |
| 时间 | 240 小时，**台风影响期间**，1h | 同 |
| 变量来源①  | `/group1/wave/typhoon_XXXX/R1_wave_*.nc` → `windx` `windy` **`hs`（有效波高）** | 同 |
| 变量来源② | `/group3/wind/typhoon_XXXX/atm_forecast_*.nc` → `u10` `v10` | 同 |
| 变量来源③ | `/group3/forcast_wave/.../atm_hour1h_noLandMask` → **`hs_torch`（显著波高，from EF）** | 同 |
| `*_validate.nc` | 另含 **`hs_torch_validate`** | 同 |

**关键**：
- **`hs` = 数值模式（海浪模式）结果**
- **`hs_torch` = 人工智能方法（深度学习）结果**
- 两者**并列放在同一个文件里**，**没有经过融合**

### 4. 融合产品目前是空的

`/group5/fusion/regular_H_outcome/fusion_2403_regular_forecast.nc` —— **仅 239 字节**，
打开后 `dims={}`、`vars=[]`、无全局属性，**是空占位文件**。

**当前 FTP 上没有任何融合产品。**

### 5. 天文潮的时间覆盖 —— **只有台风期间**

- `/group1/storm_surge/正交/{台风号}/output_0.nc`：**按台风编号分 22 个文件夹**（1006…2526），
  每个只覆盖该台风过程（实测 2311 = 145 h，2526 = 169 h），**各段之间不连续**
- `/group3/dailyforecast/storm_surge_point_system/nc_file/*.nc`：每日滚动 7 天预报（168 h），
  但**只有一个变量 `storm_surge`（纯增水，cm）**，**不含天文潮**
- 结论：**现有数据无法拼出"预报时段对应的总水位"**，缺连续天文潮

---

## 二、FTP 各目录性质速查

| 路径 | 内容 | 类型 | 时间范围 |
| --- | --- | --- | --- |
| `/group1/storm_surge/正交/{台风号}/output_0.nc` | 天文潮 | 数值模式 | 台风期间 |
| `/group1/storm_surge/正交/{台风号}/output_4.nc` | 总水位 | 数值模式 | 台风期间 |
| `/group1/storm_surge/{台风号}.nc` `_new.nc` | 风暴潮场 | 数值模式 | 台风期间 |
| `/group1/wave/typhoon_{号}/M1_wav_*.nc` `R1_wav_*.nc` | 海浪场 | 数值模式 | 台风期间 |
| `/group3/wind/atm_forecast_YYYYMMDD.nc` | 大气风场预报 | 数值模式 | **每天 1 个（788 个）** |
| `/group3/EC_wind/YYYYMMDDHH_ECMWF_wind_msl.nc` | ECMWF 风场+海平面气压 | 数值模式 | 每天 1 个（405 个） |
| `/group3/storm_surge_point/new_wind_v2/typhoon_{号}/*.nc` | 单点纯增水（cm） | 数值模式 | 台风期间，每天凌晨重算 |
| `/group3/storm_surge_field/typhoon_{号}/` | 风暴潮场 | 数值模式 | 台风期间 |
| `/group3/res_ATM_new_wave/**` | 海浪场 | 数值模式 | 台风期间 |
| `/group5/{号}_irregular.nc` | 非结构网格，含 `elev_all/tide/surge` | 数值模式 | 台风期间 |
| `/group5/regular/{号}_regular_forecast.nc` | 波浪：`hs` + **`hs_torch`** | **数值 + AI 并列** | 台风期间 |
| `/group5/202609/regular-H/{号}_regular-H.nc` | 同上，厦门附近细网格 1/120° | **数值 + AI 并列** | 台风期间 |
| `/group5/202609/dataset_GFS_cropped/{号}/output_0,4.nc` | 天文潮 / 总水位（裁剪版） | 数值模式 | 台风期间 |
| `/group5/202609/observation/out2/*.nc` | 浮标实测：`wave_H` `tide_tide` 等 | **实测观测** | 台风期间（另有 2000–2025 长序列 780 MB） |
| `/group5/fusion/regular_H_outcome/` | 融合产品 | **空文件** | — |

---

## 三、按需取数策略（不落地全量数据）

同一份结果在 FTP 上往往有多种"包装"，按"用户问什么"挑**最小的那个文件**即可：

| 需求 | 首选数据源 | 路径模板 | 体积 |
| --- | --- | --- | --- |
| 站点增水过程 | 课题三单点 | `/group3/storm_surge_point/new_wind_v2/typhoon_{号}/storm_surge_forecast_sp_{站}_{日期}.nc` | **8.5 KB/文件** |
| 浮标点波高过程 | 课题三波浪单点 | `/group3/TC_wave_point/wave/typhoon_{号}/point_wave_{站号}_forecast_*.nc` | **10 KB × 16 站** |
| 全场风暴潮分布 | 课题三风暴潮场 | `/group3/storm_surge_field/typhoon_{号}/storm_surge_forecast_*.nc` | **2.04 MB** |
| 实测对比 | 课题五观测 | `/group5/202609/observation/out2/{号}_observation_qc.nc` | 1.4 MB |
| 天文潮 + 总水位 | 裁剪版场 | `/group5/202609/dataset_GFS_cropped/{号}/output_0.nc`(天文潮) `/output_4.nc`(总水位) | 37~117 MB |
| 非结构网格三要素 | 课题五 | `/group5/{号}_irregular.nc` | 0.2~1.2 GB |
| 高精度正交场 | 课题一 | `/group1/storm_surge/正交/{号}/output_0.nc, output_4.nc` | 710 / 921 MB |
| 集合(AI)风暴潮 | 课题五 | `/group5/irregular_surge_Ensemble/{号}_irregular_new.nc` | 0.1~0.6 GB |

**已实现**：`orchestrator/ftp_catalog.py`
- `typhoon_list()` —— FTP 上现有台风清单（实测 33 个）
- `catalog(号)` —— 该台风**实际可用**的数据源与体积
- `best_source(cat, want)` —— 按需求挑最小够用的数据源
- `fetch() / fetch_many()` —— 下载到 `data/ftp_cache/`，大小一致则复用
- CLI：`python -m orchestrator.ftp_catalog 2403`

**台风数据完整度实测**（三个典型）：

| 台风 | 站点增水 | 浮标波浪 | 风暴潮场 | 裁剪场 | 正交场 |
| --- | --- | --- | --- | --- | --- |
| 2403 | 56 文件 0.48 MB | 16 站 0.2 MB | 2 MB | 86+86 MB | 710+921 MB |
| 2526 | — | 16 站 0.2 MB | 2 MB | — | 710+921 MB |
| 2418 | 24 文件 0.21 MB | — | — | 37.8+37.9 MB | — |

---

## 四、待办 / 待确认

| # | 事项 | 状态 |
| --- | --- | --- |
| 1 | **改代码**：网格取数路径改为「`output_4` − `output_0` = 增水」「`output_4` = 总水位」，修正 `visualize` 图标题、`assess` 判级口径 | 待办（已确认语义，可直接改） |
| 2 | **要连续天文潮**：向模式组/厦门中心索取 4 站（厦门/崇武/晋江/东山）**潮汐调和常数**，或要求把「潮驱动」也做成每日滚动 | 待办（阻塞业务化判级） |
| 3 | **融合产品**：`/group5/fusion/` 目前为空，需确认何时产出、由谁产出 | 待确认 |
| 4 | **每日预报停更**：`/group3/dailyforecast/` 最后更新 2026-05-31，需确认是否已切换到别处 | 待确认 |
| 5 | **站点对照表**：潮位站号（`112/113/1102/C4W05`…）↔ 站名 ↔ 经纬度 | 待索取 |
| 6 | 浮标站号 `sta_id`（`46694A/C6W10/…`）与预报单点文件站号一致，**可直接配对做精度评估** | 已确认 |
| 7 | `/group5` 与 `/group1` 的 `output_0/4` 是否同源（group5 为裁剪版） | 待确认 |
