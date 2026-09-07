# 模块设计

| 模块 | 当前职责 | 数据来源 | 写入行为 |
| --- | --- | --- | --- |
| 数据目录 | 列出允许根目录并触发重新扫描 | 服务端配置 | 无 |
| Capture 目录 | 检索、筛选、语义命名 | manifest 与 `metadata/catalog.json` | 仅目录元数据 |
| Capture 详情 | 展示阶段、设备、数据集、失败和处理能力 | Capture 元数据 | 无 |
| 处理作业 | 串行执行、日志、取消、失败和产物记录 | 固定本地适配器 | 状态 JSON 与派生产物 |
| 质量中心 | 指标、门槛、实测值、证据与测量依据 | acquisition/profile/验收报告 | 无 |
| 数据导出 | EGO/Robot/report 版本化副本 | Capture 派生数据 | 配置的导出根目录 |

## 后端边界

- `config.py`：解析允许根目录，不接受客户端绝对路径。
- `catalog.py`：浅扫描、manifest 解析、状态归一化和质量摘要。
- `jobs.py`：串行运行状态机、真实工具链适配器、取消、持久化和原子导出。
- `main.py`：HTTP 契约、错误映射和静态前端托管。

## API v1

- `GET /api/v1/health`
- `GET /api/v1/roots`
- `GET /api/v1/captures?root_id=&query=&status=`
- `GET /api/v1/captures/{capture_id}?root_id=`
- `PATCH /api/v1/captures/{capture_id}/metadata?root_id=`
- `POST /api/v1/catalog/scan`
- `GET /api/v1/runs`
- `GET /api/v1/runs/{run_id}`
- `POST /api/v1/runs`
- `POST /api/v1/runs/{run_id}/cancel`

## 处理器边界

每个真实适配器必须声明输入、输出、版本、可重试性和资源需求。运行过程中先写临时目录，
完成校验后再原子发布产物，并更新 lineage。失败只记录原因，不把半成品标成 ready。

- `integrity`：平台复核 Source 清单；ready Capture 追加原项目完整校验。
- `ego`：当前仅接已有 `rgb_video` 构建器；已有 EGO 自动跳过。
- `retarget`：调用 `derive_embodiment.py`，默认生成新的 retarget revision，避免覆盖。
- `quality`：调用 `measure_acceptance.py`，报告保留原有指标 schema。
- `export`：复制 EGO、指定机器人版本和报告，并生成 `export_manifest.json`。
