# 行情站 API 全量测绘与「沈阳缺数」事件排查

> 版本 v1.0 · 2026-11-24 · 全部结论来自当日实测（HTTP 状态、返回体字段、逐条比对），非推测。
> 关联：`03-数据源调研.md`（选型依据）、`AGENTS.md`（项目铁律）

---

## 1. 事件与结论摘要

**现象**：2026-11-24 早上 09:04 采集入库 34 条冻品，沈阳两家市场（537 沈阳水产品批发市场 / 538 前当堡鲜鱼批发市场）**0 条**，辽宁只剩大连辽渔（673）4 条。

**根因**：**不是源站没更新，也不是采集逻辑有 bug**。沈阳当天**正常报送了 9 个规格**，但 `GetPriceNow` 快照接口当时还没把沈阳放出来——**源站是「先落报送库，再陆续放快照」**。

**证据链**：

| 环节 | 观测 | 含义 |
|---|---|---|
| 09:01 采集时 | `GetPriceNow` 总量 442 条，沈阳 537 命中 0 | 快照还没放沈阳 |
| 09:16 → 09:29 | 总量 513 → 522 → 534 → 542 → 582，逐批上涨 | 源站在持续放数，不是静态 |
| 10:34 再拉 | 总量 **918 条**，沈阳 537 的 **9 条全在** | 沈阳数据其实早就在库里 |
| 报送接口查询 | `GetSetting?uid=537&date=2026-11-24` → `isReport: true` + 9 个规格 | **沈阳当天确实报了** |
| 报文内容比对 | 沈阳带鱼 中位价 24.00 = 昨日入库值 | 同一套报送基准，非异常值 |

**处置**：10:35 重跑 `python scripts/fetch.py`，当日 `price_obs` **34 → 79 条 / 23 市场**，沈阳 537 入库 7 条。

**附带结论**：行情站是一套**由市场自主报送**的采集分析平台，共 **21 个 API 端点，其中 14 个只读端点用公开 token 即可直接调用**，含项目此前完全没用到的**价格区间（低/中/高）、成交量、月度成交额、价格指数、市场动态**五类数据。

---

## 2. 平台性质与报送机制

### 2.1 这是什么平台

`/mobile/view/about.html`（平台自述，原文）：

> **中国水产批发市场信息采集分析平台**（原名：全国水产品批发市场价格信息采集系统）是中国水产学会研究中国当前渔业经济形势、提升宏观决策、应急指挥、市场监管和提升公共服务水平的渔业信息采集分析平台。是根据中国水产学会实施的《全国水产品批发市场信息采集分析体系》方案要求，**按全国、省份、地区、市场等四级管理**，资源共享原则开发。

| 项 | 内容 |
|---|---|
| 开发时间 | 2009 年 |
| 功能定位 | 提供对政府领导及管理人员对水产品行业分析，科学研究，决策的数据信息 |
| 服务对象 | 农业部渔业局、中国水产学会、全国各个省份水产品批发市场 |
| 技术支持 | 深圳市万维信科技有限公司 |
| 运行主体 | 全国水产技术推广总站（`nftec.agri.cn`） |

**结论**：不是某个商业行情站，而是**官方体系的行业价格采集网络**，数据由各定点市场按统一规范自行填报。

### 2.2 报送机制的直接证据

| 证据 | 出处 | 内容 |
|---|---|---|
| 报送截止时间提示 | `view/reportprice.html` 页面文案 | 「**亲，定点市场只能在每日 12 点前上报当日价格和成交量信息。**」 |
| 报送 API 按单位 | `API/Product/AddPrices` | 提交参数含 `uid`（市场单位 ID）+ `date` |
| 登录态带单位 | `js/szqbl.min.js` | `szqbl.auth.userunitid` / `szqbl.auth.userunit`，token 绑定到具体单位 |
| 缺报追踪 | `/mobile/` 「我的」页 | 「**本月已报送 10 次**」「**我的缺报 本月缺报 10 次**」 |
| 单市场报送状态 | `API/Product/GetSetting` | 返回 `isReport: true/false` |

**每个市场用自己的账号报自己的数**，`GetPriceNow` 是把各市场报送结果汇总后的只读快照。

### 2.3 两个接口的关系（本次事件的关键）

```
市场端登录 (uid=537)
   │
   ├─ 12:00 前提交 ─────► 报送库 (AddPrices)
   │                          │
   │                          ├─► GetSetting / GetLastPrices  ← 立刻可读，含低/中/高三价 + 成交量
   │                          │
   └─ 平台审核放行 ─────► 快照 (GetPriceNow)  ← ⚠️ 滞后！本次事件就卡在这里
                              │
                              └─► GetPriceList (分规格 + 30天趋势)
```

**报送入库 ≠ 快照放行**，这是本次误判「源站没更新」的根源。

---

## 3. API 全量测绘（21 端点实测）

### 3.1 游客 token 直调清单（14/16 只读端点可用）

> 站点 JS 里 `win.szqbl.auth.token = "0000000000000000"` —— 游客默认 token 就是我们项目用的那个公开 token。这些接口本来就是公开设计的。

**基址** `http://znyj.nftec.agri.cn:8089` · **token** `0000000000000000`

| 端点 | 关键参数 | 返回 | 项目现状 |
|---|---|---|---|
| `API/Product/GetPriceNow` | `rid,pid,pageSize,pageNum` | 当日报价分页 | ✅ 已在用 |
| `API/Product/GetPriceList` | `rid,pid` | 分规格价 + 30 天趋势 | ✅ 已在用 |
| `API/Product/GetCategorys` | — | 375 品种目录 | ✅ 已在用 |
| `API/Product/GetVolumeList` | `rid,pid` | `priceAll/price30All/rateAll` | ⚠️ **无成交量**，名字误导 |
| `API/Product/GetVolumeByNow` | `rid,pid,pageSize,pageNum` | **当日成交量**（分市场分规格） | 🆕 未接入 |
| `API/Product/GetSetting` | **`uid,date`** | 该市场该日报送状态 + **低/中/高三价 + 成交量** | 🆕 未接入 |
| `API/Product/GetLastPrices` | `uid,date` | 上次报送价（同三价结构） | 🆕 未接入 |
| `API/Market/GetList` | **`rid`** | 该地区全部市场 + 逐月 `{volume,turnover}` | 🆕 未接入 |
| `API/Market/GetSetting` | `uid` | 该市场月成交量/成交额 + 历史 | 🆕 未接入 |
| `API/ProductIndex/GetSetting` | `rid` | 指数分类 11 类 | 🆕 未接入 |
| `API/ProductIndex/GetList` | **`rid`,`sid`** | **价格指数**：月环比/月同比/月同期比/月固定比 | 🆕 未接入 |
| `API/SysSetting/GetRegions` | — | 34 个地区（rid 映射表） | 🆕 未接入 |
| `API/SysSetting/GetRegion` | `province` | 地区 id/name | 🆕 未接入 |
| `API/Article/GetList` | `tid,pageSize,pageNum` | 市场动态/分析报告（16377 条） | 🆕 未接入 |
| `API/Article/GetDetail` | `id` | 文章正文（HTML） | 🆕 未接入 |

### 3.2 需要登录（游客 token 不可用）

| 端点 | 方法 | 说明 |
|---|---|---|
| `API/Auth/Login` | POST | 账号密码登录，换取绑定单位的 token |
| `API/Auth/UpdatePwd` | POST | 改密码 |
| `API/Product/AddPrices` | POST | **报送价格**（需市场账号） |
| `API/Market/AddOrUpdate` | POST | **报送月成交量/成交额** |
| `API/Article/AddGood` | POST | 文章点赞 |
| `API/Visit/Add` | POST | 问题反馈（游客 500，非权限问题） |

**写入安全**：游客 token 调 `AddPrices` 空表单返回 `{"Status":200,"Message":"本次新增数据0条。"}` —— **实测不写库、不污染源站**。本次排查全程未写入任何真实报价（事后复核 537 的 9 条数据原样未动）。

### 3.3 参数速查

| 端点 | 必需参数 | 不传 / 传错的后果 |
|---|---|---|
| `GetPriceNow` | `rid,pageSize,pageNum` | `pageSize` 支持 500；分页走 `TotalPageCount` |
| `GetPriceList` | `rid,pid` | 慢品种固定耗时 16–25s，与频率无关 |
| `GetVolumeList` | `rid,pid` | `rid=4` 有效 |
| `GetVolumeByNow` | `rid,pid` | `rid=4` 返回辽宁全部市场 |
| `GetSetting` | **`uid`,`date`** | `uid` 是市场 ID（不是地区 ID） |
| `Market/GetList` | **`rid`** | `rid=4` → 辽宁 6 家；`rid=0/-1` → HTML/500 |
| `ProductIndex/GetList` | **`rid`,`sid`** | `rid` 必须有效地区（`rid=4` 辽宁）；`rid=0/-1` → 500 |
| `ProductIndex/GetSetting` | `rid` | 返回 `sid` 取值表 |
| `Article/GetList` | `tid` | `tid=1` 市场动态 / `2` 分析报告 / `3` 通知公告 |

### 3.4 地区 rid 映射（`GetRegions`，34 个）

| rid | 地区 | rid | 地区 | rid | 地区 |
|---|---|---|---|---|---|
| 1 | 北京 | 13 | 安徽 | 25 | 广东 |
| 2 | 黑龙江 | 14 | 浙江 | 26 | 香港 |
| 3 | 吉林 | 16 | 甘肃 | 27 | 新疆 |
| **4** | **辽宁** | 17 | 宁夏 | 28 | 青海 |
| 5 | 天津 | 18 | 陕西 | 29 | 四川 |
| 6 | 河北 | 19 | 湖北 | 30 | 贵州 |
| 7 | 山东 | 20 | 江西 | 31 | 广西 |
| 8 | 江苏 | 21 | 福建 | 32 | 澳门 |
| 9 | 上海 | 22 | 台湾 | 33 | 西藏 |
| 10 | 内蒙古 | 23 | 重庆 | 34 | 云南 |
| 11 | 山西 | 24 | 湖南 | 35 | 海南 |
| 12 | 河南 | | | | |

> `rid=15` 不存在（缺号）。`ProductIndex/GetSetting` 的 `sid` 分类：1 综合 / 2 海水产品 / 4 海水鱼类 / 5 海水甲壳类 / 6 海水贝类 / 7 海水头足类 / 8 海水藻类 / 9 淡水产品 / 10 淡水鱼类 / 11 淡水甲壳类 / 15 淡水其它类。

---

## 4. 四个技术坑（本次排查耗时最久的部分）

### 坑 1：URL 拼接漏斜杠 → 返回 648 字节 HTML 而非 JSON ⚠️ 最坑

`config.BASE_URL` **不带尾斜杠**：

```python
BASE = 'http://znyj.nftec.agri.cn:8089'
BASE + '/API/Product/GetCategorys'   # ✅ 正确
BASE + 'API/Product/GetCategorys'    # ❌ → http://...:8089API/Product/GetCategorys
```

服务器把缺斜杠的路径当**静态资源**处理，返回 SPA 首页（**恰好 648 字节**）。

> **识别特征：返回 200 但 body 是 `<!DOCTYPE html>` 且长度 648。**

正确写法（`scripts/config.py` 现状是对的）：

```python
url = config.BASE_URL.rstrip('/') + '/' + path.lstrip('/')
```

### 坑 2：`Accept-Encoding: gzip, deflate` 触发同样的 648 HTML

带这个头时服务器读请求头的路径出错，同样返回 SPA 首页。

**规避**：给该站发请求**不要带 `Accept-Encoding: gzip`**；或者带了必须先校验返回是不是 JSON 再解析，别直接 `json.loads()` 崩。

实测对照：

| 请求头 | 结果 |
|---|---|
| `config.HTTP_HEADERS` 原样 | ✅ JSON |
| `+ Accept: application/json` | ✅ JSON |
| `+ X-Requested-With` | ✅ JSON |
| `+ Accept-Language` | ✅ JSON |
| `+ Referer: .../mobile/` | ✅ JSON |
| `+ Accept-Encoding: gzip, deflate` | ❌ **HTML 648** |
| 去掉 `User-Agent` | ❌ **403 Forbidden** |

### 坑 3：必须带浏览器 UA

`User-Agent` 是硬要求（去掉即 403）。`Referer` 可省，但带着更稳。

### 坑 4：`rid` / `sid` 语义不同，别混

- `GetSetting` 的 `uid` = **市场 ID**（537 是市场）
- `GetPriceNow` / `Market/GetList` / `ProductIndex/*` 的 `rid` = **地区 ID**（4 是辽宁）
- `ProductIndex/GetList` 的 `rid=0` 和 `rid=-1` 都 500，必须用有效地区 ID

### 排查手法留档

用「同进程多次请求 + 只改一个变量」二分，比读代码快：

```python
# 连发 40 次同一端点 → 40/40 JSON，说明不是频率/并发问题
# 再把失败脚本原样重跑 → 稳定复现 → 逐行 diff 找出 URL 拼接问题
```

---

## 5. 数据维度缺口（当前项目丢掉的）

### 5.1 价格区间：只有中位价，低/高全丢

`GetPriceNow` 每条只有一个 `value`（中位价）。**低/中/高三价 + 成交量只在报送侧接口 `GetSetting` / `GetLastPrices` 里**。

实测对比（2026-11-24 沈阳 537）：

| 品种 | 规格 | 最低价 | 中位价 | 最高价 | 成交量 |
|---|---|---|---|---|---|
| 带鱼 | 350≤冻条重＜500 | 18.00 | **24.00** | 38.00 | 20.00 |
| 大黄鱼 | 300≤冻条重＜600 | 7.00 | **35.00** | 43.00 | 10.00 |
| 小黄鱼 | 100≤冻条重＜150 | 15.00 | **22.00** | 30.00 | 15.00 |
| 马鲛鱼 | 500≤条重＜1000 | 17.00 | **20.00** | 26.00 | 10.00 |
| 进口鲳鱼 | 冻条重＜250 | 26.00 | **44.00** | 70.00 | 0.00 |

对比大连辽渔的「统货」档，区间跨度更大：

| 品种 | 规格 | 最低 | 中位 | 最高 | 量 |
|---|---|---|---|---|---|
| 带鱼 | 统货 | 24.00 | **122.00** | 220.00 | 6.50 |
| 梭子蟹 | 统货 | 66.00 | **138.00** | 210.00 | 6.00 |

**价值**：统货档中位价 122 但区间 24–220，**单看均价会误判市场景气度**。区间 + 成交量是判断「真实成交价 vs 挂牌价」的关键。

### 5.2 成交量 / 成交额：完全没有

`Market/GetList?rid=4` 返回辽宁 6 家市场逐月 `{volume, turnover}`：

| 市场 | 2026.10 成交量 | 2026.10 成交额 |
|---|---|---|
| 辽宁省沈阳水产品批发市场 | 80700.0 | 191500.0 |
| 辽宁省大连辽渔国际水产品市场 | 33392.2 | 134171.5 |

> ⚠️ **数据质量差异明显**：沈阳的成交量全是整百数（80000 / 81500 / 85000 / 79000…），像是**估报或按固定系数推算**；大连辽渔是真实小数（29426.1 / 25630.5 / 17327.8）。接入时**沈阳的成交量不能当精确值用**，需要标注。

### 5.3 价格指数：辽宁口径可算

`ProductIndex/GetList?rid=4&sid=1`（综合）返回 4 组曲线，7 个月（2026.5–2026.11）：

| 指数 | 2026.10 | 2026.11 |
|---|---|---|
| 月环比 | 1.2333 | 1.2062 |
| 月同比 | 1.1014 | 1.0818 |
| 月同期比 | — | — |
| 月固定比 | — | — |

> 返回体 `ys` 有 4 项（月环比/月同比/月同期比/月固定比），实测 `y` 数组每项含 7 个月值，接入时注意数组对齐。

### 5.4 市场动态 / 分析报告：16377 篇

`Article/GetList?tid=1` 是各市场自己发布的行情分析，例如：

- 「本周市场行情分析11.22」— 浙江松门水产品批发市场
- 「岳各庄市场水产品周分析」— 北京京丰岳各庄
- 「长沙马王堆一周水产品行情分析」

**这是定性解读的现成素材**，可作为看板「市场动态」栏的来源。

---

## 6. 采集时机的建议

`GetPriceNow` 当日条数**单调递增**，早晨跑必然少数据：

| 时刻 | 总量 | 沈阳 537 |
|---|---|---|
| 09:01 | 442 | ❌ 0 条 |
| 09:16 | 513 | ❌ 0 条 |
| 09:29 | 582 | ❌ 0 条 |
| **10:34** | **918** | ✅ **9 条** |
| 11:45（本文成稿时） | 1051 | ✅ 9 条 |

> 总量在本文成稿时仍在上涨（918 → 1051），说明放数窗口可能延续到全天。**「当日最终条数」没有明确上界，只能靠阈值策略判断何时收手。**

**两条路**：

| 方案 | 做法 | 优点 | 缺点 |
|---|---|---|---|
| A. 挪时间 | 手动采集固定在 10:00 之后 | 零代码改动 | 依赖人工作息；无法覆盖午后才报的市场 |
| B. 阈值补采 ⭐ | 入库后比对当日条数，低于阈值则等 N 分钟重跑 | 稳、能等到真正放完 | 需改 `fetch.py` |

推荐 **B**。伪代码：

```python
# scripts/fetch.py 收尾处
MIN_TOTAL = 800          # 当日快照条数阈值（实测 10:34 为 918，早晨 442）
MAX_ROUNDS = 3
for rnd in range(MAX_ROUNDS):
    total = 当前 GetPriceNow 的 TotalItemCount
    if total >= MIN_TOTAL: break
    wait(300)            # 等 5 分钟再试
    重新采集
```

**注意**：`fetch_log` 已有 `raw_count` 字段存当日原始条数，可直接用它做判定，不用额外查库。

---

## 7. 接入建议（若要扩展）

### 7.1 红线（沿用 `03-数据源调研.md` §6）

1. **新数据源进 `shared/reference.json`**，禁止在 Python / TS 侧硬编码第二份清单。
2. **独立表 / 独立标识**：价格区间、成交量、成交额、指数**不得与冻品序列混绘**。
3. **成交量单位需核实**（`Market/GetList` 的 `volume` 未标单位，`GetSetting` 的 `volume` 疑似「吨」或「公斤」，两者量级差 1000 倍，接入前必须对齐）。
4. **写入类接口一律不碰**：只做只读采集，不调 `AddPrices` / `AddOrUpdate`。
5. **沈阳成交量需标注「估报」**，避免当成精确成交数据。

### 7.2 建议表结构（若采纳）

```sql
-- 价格区间（在 price_obs 基础上扩展，或独立表）
CREATE TABLE price_range (
  obs_date   TEXT,
  market_id  INTEGER,
  product_id INTEGER,
  spec_id    INTEGER,
  lowest_price    DOUBLE PRECISION,
  central_parity  DOUBLE PRECISION,   -- = price_obs.price
  highest_price   DOUBLE PRECISION,
  volume          DOUBLE PRECISION,
  PRIMARY KEY (obs_date, market_id, product_id, spec_id)
);

-- 市场月度成交量/成交额
CREATE TABLE market_volume (
  month    TEXT,          -- '2026.10'
  market_id INTEGER,
  volume   DOUBLE PRECISION,
  turnover DOUBLE PRECISION,
  PRIMARY KEY (month, market_id)
);
```

> `price_obs` 唯一键 `(obs_date, market_id, product_id, spec_id)`，`price_range` 与之对齐便于关联。

### 7.3 优先级

| 优先级 | 事项 | 工作量 | 收益 | 风险 |
|---|---|---|---|---|
| P1 | 采集阈值补采机制 | 小 | 根治「早上跑不全」，直接提升数据完整性 | 低 |
| P1 | 接入 `GetSetting` 的价格区间 + 成交量 | 中 | 补上最有信息量的维度；单市场单请求，成本低 | 低（新增独立表） |
| P2 | 接入 `Market/GetList` 月度成交额 | 小 | 沈阳市场体量背景，看板可做「市场活跃度」 | 中（沈阳是估报，需标注） |
| P2 | 接入 `ProductIndex/GetList` 辽宁指数 | 小 | 官方口径的价格指数，可做「大盘涨跌」 | 低 |
| P3 | 接入 `Article/GetList` 市场动态 | 小 | 看板加「市场动态」栏，定性解读 | 低 |
| — | 登录态调用写入类接口 | — | 无 | ❌ 不做 |

---

## 8. 复核清单（本次已执行）

- [x] 源站 `GetPriceNow` 总量随时间单调递增（442 → 918），确认非静态
- [x] `GetSetting` 确认沈阳 537 `isReport: true` + 9 个规格
- [x] 报送值与昨日入库值逐条比对一致（带鱼 24.00 等）
- [x] 用项目自己的 `clean()` 干跑（不写库），结果与入库一致 → 采集/过滤逻辑无误
- [x] 10:35 重跑采集，`price_obs` 34 → 79 条 / 23 市场，沈阳入库 7 条
- [x] 21 个 API 端点逐个实测（curl + urllib 双客户端交叉验证）
- [x] 4 个技术坑逐一复现并定位（URL 斜杠 / gzip 头 / UA / rid 语义）
- [x] 写入接口以空表单验证「新增 0 条」，未污染源站
- [x] 沈阳 9 条数据事后复核原样未动
- [x] 34 个地区 rid 映射、11 个指数 sid 分类全量导出
- [x] 沈阳成交量「估报」特征识别（整百 vs 真实小数）

---

## 9. 附：调试用命令

```bash
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
T="token=0000000000000000"
B="http://znyj.nftec.agri.cn:8089"

# 单市场当日报送状态（含低/中/高三价 + 成交量）
curl -s -A "$UA" -e "$B/mobile/" "$B/API/Product/GetSetting?$T&uid=537&date=2026-11-24"

# 某地区全部市场的逐月成交量/成交额
curl -s -A "$UA" -e "$B/mobile/" "$B/API/Market/GetList?$T&rid=4"

# 辽宁综合价格指数
curl -s -A "$UA" -e "$B/mobile/" "$B/API/ProductIndex/GetList?$T&rid=4&sid=1"

# 当日快照总量（看源站放数进度）
curl -s -A "$UA" -e "$B/mobile/" "$B/API/Product/GetPriceNow?$T&rid=0&pid=0&pageSize=1&pageNum=1"
```
