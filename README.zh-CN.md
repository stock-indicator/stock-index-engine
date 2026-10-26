[English](README.md)

# 股票指数引擎

## 项目概述

股票指数引擎是一个基于 Python 的工具，用于获取、计算和评估广泛的金融市场指标。它从不同来源收集数据，以创建关于市场健康状况的全面视图，涵盖估值、情绪、动量和宏观经济因素。该引擎的主要目标是生成一份统一的“市场状况”报告，可用于分析和决策。

## 功能特性

*   **全面的指标库：** 跟踪超过20个关键市场指标。
*   **分类：** 将指标分为四个主要类别：估值、情绪、宏观经济和技术。
*   **数据获取与缓存：** 从各种来源（如 FRED 的经济数据）下载数据并缓存到 `resources/` 目录中。
*   **数据输出：** 在 `output/` 目录中以 JSON 和 CSV 格式生成详细的历史数据和实时摘要。
*   **API 服务：** 包含一个 FastAPI 服务，用于公开数据和触发刷新。
*   **容器化：** 提供 Dockerfile，便于自包含的部署。

## 如何使用

### 1. 配置 (API 密钥)

在运行引擎之前，您必须提供必要的 API 密钥。

1.  在 `stock-index-engine` 目录下创建一个名为 `api.key` 的文件。
2.  以 `KEY=VALUE` 的格式添加您的密钥。例如：
    ```
    FRED_API_KEY=your_fred_api_key_here
    ANOTHER_API_KEY=your_other_key_here
    ```

引擎也可以从环境变量中读取密钥。如果同一个密钥同时存在于环境变量和 `api.key` 文件中，将优先使用环境变量。

“内部人买入占比”指标读取 SEC EDGAR 的数据，SEC 要求每个请求都带上联系人身份。在 `api.key` 中加一行，或在环境变量中设置它：

```
EDGAR_IDENTITY="Your Name your.email@example.com"
```

缺少这一项时，只有该指标会显示为 `unavailable`，其他指标照常运行。

### 2. 本地运行引擎

您可以使用 Python 直接运行引擎。

```bash
# 安装依赖
pip install -r requirements.txt

# 刷新全部指标，并导出每个指标的完整历史
python market_indicators.py --mode manual

# 从头重建单个指标（保留共享下载缓存：FINRA 屏蔽数据中心 IP，文件不一定能重新下载）
python market_indicators.py --mode full --indicator cape_ratio --keep-resource-cache
```

### 3. 运行 API 服务

内置的 FastAPI 服务可用于查看数据和触发刷新。

```bash
# 启动服务
python services/api.py
```

*   交互式文档将在 `http://localhost:8000/docs` 提供。
*   Postman 集合位于 `docs/postman_collection.json`。

## 内部人买入占比（SEC Form 4）

内部人买入占比是一个基于内部人交易的情绪指标，计算的是内部人交易金额中买入所占的比例：

```
买入占比 (%) = 买入金额 / (买入金额 + 卖出金额) × 100
```

*   **数据来源：** SEC Form 4 申报，通过 [edgartools](https://edgartools.readthedocs.io/en/latest/insider-filings/) 读取。
*   **股票池：** 默认为标普 500 当前成分股，取自 Wikipedia 的成分股表，缓存 30 天。若只想跟踪自选股票，在 `settings.json` 中加入 `"insider_buy_share.universe": ["AAPL", "MSFT"]`。
*   **统计口径：** 只计入公开市场买入（代码 `P`）和公开市场卖出（代码 `S`）。授予、期权行权、代扣税款、赠与和股权互换一律排除。为缴纳归属股票的税款而卖出（申报脚注中注明“覆盖税款”的卖出）同样排除。
*   **滚动窗口：** 按日汇总买卖金额，再做 30 日和 90 日滚动。状态由 90 日读数决定。
*   **状态判定：** 90 日买入占比处于其过去一年的最低 10% 区间时为 `high`，表示内部人相对近期常态在大量卖出。这里不用固定阈值：内部人买入本来就少，典型读数在 2%–3% 左右，若以固定的 10% 作为分界线，几乎每天都会是 `high`。历史上，股价上涨时内部人集中卖出，往往出现在市场阶段性顶部附近。若不足 180 天的 90 日读数，或窗口内交易不足 30 笔，状态为 `unavailable`。
*   **注意事项：** 指标按金额加权，一笔大额买入就可能明显拉高读数。价格会做合理性检查：单价超过 10 万美元，或偏离该公司窗口内中位价 100 倍以上的交易会被剔除。部分申报的价格被放大了 1000 倍（例如把 1031.414 写成 1031414），若不剔除，仅这几笔就会虚增约 830 亿美元的卖出金额。默认保留 10b5-1 交易计划下的卖出；若要排除，把 `indicators/sentiment/insider_buy_share.py` 中的 `EXCLUDE_10B5_1` 改为 `True`。每次增量刷新都会重读最近 30 天的交易日，以捕捉延迟申报。

### 缓存与首次构建耗时

每一笔 Form 4 申报（以 accession 编号区分）只解析一次，结果保存为 `resources/raw/sec_form4/filings/<accession>.json`。申报编号一经提交便不会改变，因此这份缓存不会过期。全量刷新该指标时会清空它自己的清洗数据，但会保留 Form 4 缓存；中断的任务则从磁盘上已有的文件继续。

首次构建需要下载窗口内标普 500 所有的 Form 4 申报，数量在数万份量级。SEC 的请求上限约为每秒 9 次，首次构建大约需要一小时。之后的运行只会列出各公司的申报索引，只下载新增的 accession。若要强制全部重新下载，删除 `resources/raw/sec_form4/` 即可。

```bash
# 构建 Form 4 缓存和该指标的历史数据（中断后重新运行即可续传）
python market_indicators.py --mode full --indicator insider_buy_share --keep-resource-cache --lookback-days 365
```

`--mode full` 必须搭配 `--indicator` 使用。若要一起刷新所有指标，请使用 `--mode manual`。

## 社交与预测市场情绪

三个基于公开免密接口的情绪指标——不需要 API 密钥、不需要注册、不需要 OAuth：

| 指标 | 数据源 | 触发 `high` 的条件 |
|---|---|---|
| Retail Buzz Velocity | Reddit Atom feed | 发帖速率 >= 自身历史的 90 分位 |
| Social Bull-Bear Ratio | StockTwits 个股消息流 | 自标注消息中看多占比 >= 75% |
| Recession Odds | Polymarket Gamma API | 隐含概率 >= 35% |

**这三个指标无法回填历史。** 三个数据源都不提供历史快照，因此它们从首次运行当天
开始，每天累积一行——`--lookback-days 365` 对它们不生效。把今天的实时读数记到过去
的日期上，等于把当时无人能掌握的信息塞进回测，所以我们不提供这种做法。

Retail Buzz Velocity 在累积满 30 个观测值之前，会以 `normal` 状态返回“正在建立基线”
的说明——五个读数算出来的分位数不是分位数。

指标口径、失败处理和可调参数见 [docs/social-sentiment.md](docs/social-sentiment.md)。

## 长历史与双向信号

### 历史深度

每次刷新都会把每个指标存储的**全部**历史导出到 `output/history/<slug>.json`。
API 按请求的范围（`lookback_days`）截取，并可为图表抽稀（`max_points`），详见
[docs/api.md](docs/api.md)。

存储的历史会在下一次刷新时自动回填，不需要 full refresh：

| 数据源 | 可追溯到 |
|---|---|
| 价格类指标（RSI、MACD、200DMA、12 个月涨幅、VIX） | 每次运行下载 Yahoo 全量历史：标普 500 从 1927 年，纳指 100 从 1985 年，VIX 从 1990 年 |
| FRED 宏观指标 | 每次运行读取整条序列：CPI 从 1947 年，10 年期收益率从 1953 年，T10Y2Y 从 1976 年 |
| multpl.com 估值表 | PE、CAPE、股息率从 1871 年；P/B、P/S 从 2000 年 |
| CNN 恐惧贪婪指数 | 从 2021 年 1 月起，这是 CNN 提供的最早日期 |
| ETF 净流入（SPY） | 从 2003 年 12 月起，即道富 NAV 历史的起点 |
| AAII、FINRA 融资余额、BIS 信贷/GDP | 本来就是完整历史（1987、1997、1947 年） |

无法回填的：QQQ 资金流（景顺只公布当天数据）、Insider Buy Share（需要下载起始日以来
的全部 Form 4）、社交与预测市场类指标。

每日运行日志从引擎首次部署才开始记录，所以更早的历史点使用指标自身规则对该数值给出的
状态（`BaseIndicator.status_for_value`）。几十年的图表上能看到过去每一次 `high` 和 `low`，
而不只是引擎恰好记录下来的那些。

### `high` 与 `low`

`high` 表示市场过热：估值拉伸、情绪自满、广度超买。`low` 表示市场被洗盘：估值便宜、
恐慌、广度超卖。原有指标只报告 `high` 或 `normal`，下面新增的指标两个方向都会报告。
汇总里用 `low_available` 和 `by_category.<category>.low` 统计 low。

### 新增指标

| 指标 | 类别 | 数据源 | 起始 | `high` | `low` |
|---|---|---|---|---|---|
| Buffett Indicator | Valuation | 美联储 Z.1 企业股权市值 / GDP（FRED） | 1947 | > 150% | < 60% |
| Tobin's Q | Valuation | 美联储 Z.1 企业股权市值 / 净资产（FRED） | 1945 | > 1.4 | < 0.5 |
| Excess CAPE Yield | Valuation | 1 / CAPE（multpl）减实际 10 年期收益率（FRED） | 1957 | < 1% | > 7% |
| Stocks Above 200DMA (S&P 500) | Technical | TradingView `INDEX:S5TH` | 1990 | > 80% | < 20% |
| Stocks Above 200DMA (Nasdaq 100) | Technical | TradingView `INDEX:NDTH` | 2006 | > 80% | < 20% |
| VIX Term Structure | Technical | VIX / VIX3M（Yahoo） | 2006 | < 0.80 | > 1.00 |
| Equity Put/Call Ratio | Sentiment | TradingView `USI:PCCE`，10 日均值 | 2007 | < 0.60 | > 1.00 |
| High-Yield Credit Spread | Macro | ICE BofA 高收益债 OAS：TradingView `FRED:BAMLH0A0HYM2` 加 FRED | 1996 | < 3.0% | > 7.0% |

阈值都用全量历史校验过：`high` 区间覆盖了 1968、2000、2021 年的极值，`low` 区间覆盖了
2002、2009、2020、2022 年和 2025 年 4 月的低点。Z.1 按季度发布、滞后约十周，所以
Buffett 和 Tobin's Q 会用标普 500 自上一季度以来的涨跌幅来缩放最新季度的数值；这些行带
`estimated: true`，直到 Z.1 公布该季度的实际值。

### TradingView 数据

`common/tradingview.py` 是 [TradingView-API](https://github.com/Mathieu2301/TradingView-API)
所用图表会话协议的一个小型 Python 移植。它匿名连接 TradingView 的图表 websocket，读取
完整的日线历史，覆盖了没有任何免密 API 提供的市场广度、CBOE put/call 和 FRED 镜像数据。
FRED 自己的 API 现在只返回最近三年的 ICE 利差数据。

这个接口是非官方的，所以下载失败时保留已存储的历史。基于 TradingView 的读数在最新数据
点超过 7-10 天后会变成 `unavailable`，避免数据源坏掉时把冻结的旧值当成当前值。

## Docker 部署

若需自包含的部署，您可以使用 Docker。

```bash
# 1. 构建镜像（APP_UID 应与宿主机上挂载目录的属主一致）
docker build --build-arg APP_UID="$(id -u)" -t stock-index-engine .

# 2. 运行容器
docker run \
  -p 127.0.0.1:8000:8000 \
  -e FRED_API_KEY="your_fred_api_key_here" \
  -e EDGAR_IDENTITY="Your Name your.email@example.com" \
  -e REFRESH_TOKEN="一串足够长的随机字符" \
  -v /local/path/to/output:/app/output \
  -v /local/path/to/resources:/app/resources \
  stock-index-engine
```

*   使用 `-e` 标志以环境变量形式传递 API 密钥。
*   `POST /refresh` 只接受容器内部发起、并带有 `REFRESH_TOKEN` 的请求（放在 `Authorization: Bearer <token>` 请求头里），例如用 `docker exec` 进入容器后调用 `http://127.0.0.1:8000/refresh`。不设置 token 则关闭该接口，每日定时刷新照常运行。
*   容器以非 root 用户运行（`APP_UID`，默认 10001），挂载的目录需要对该 uid 可写。
*   将本地目录挂载到 `/app/output` 以持久化生成的报告。
*   同时挂载 `/app/resources`，让 SEC Form 4 缓存在容器重启后保留。否则每个新容器都会重复一次首次构建。

## 输出文件

引擎在 `output/` 目录中生成以下文件：

*   `market_status.latest.json`: 所有指标最新评估值的快照。
*   `history/{indicator_slug}.json`: 每个指标的一系列历史数据点。
*   `market_indicator_log.csv`: 指标值随时间变化的日志。

## 项目结构

- `common/` – 共享工具和配置助手。
- `indicators/` – 所有市场指标的实现。
- `services/` – 编排层（刷新、评估、API、历史记录、导出）。
- `resources/` – 缓存的原始和清洗后的数据集。
- `output/` – 生成的报告和历史序列。
- `docs/` – API 文档、指标说明和 Postman 集合。
