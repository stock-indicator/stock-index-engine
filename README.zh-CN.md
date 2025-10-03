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

### 2. 本地运行引擎

您可以使用 Python 直接运行引擎。

```bash
# 安装依赖
pip install -r requirements.txt

# 运行一次完整的刷新，重新生成365天的历史数据
python market_indicators.py --mode full --lookback-days 365

# 运行一次增量刷新
python market_indicators.py --mode manual --lookback-days 365
```

### 3. 运行 API 服务

内置的 FastAPI 服务可用于查看数据和触发刷新。

```bash
# 启动服务
python services/api.py
```

*   交互式文档将在 `http://localhost:8000/docs` 提供。
*   Postman 集合位于 `docs/postman_collection.json`。

## Docker 部署

若需自包含的部署，您可以使用 Docker。

```bash
# 1. 构建镜像
docker build -t stock-index-engine .

# 2. 运行容器
docker run \
  -p 8000:8000 \
  -e FRED_API_KEY="your_fred_api_key_here" \
  -v /local/path/to/output:/app/output \
  stock-index-engine
```

*   使用 `-e` 标志以环境变量形式传递 API 密钥。
*   将本地目录挂载到 `/app/output` 以持久化生成的报告。

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
- `docs/` – API 文档和 Postman 集合。
