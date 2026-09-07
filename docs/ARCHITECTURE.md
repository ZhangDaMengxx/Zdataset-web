# 架构方案

## 目标

把采集产物转成可检索、可重算、可评估和可审计的数据资产，同时保留原始 Capture，
允许同一 EGO 数据并行派生多个机器人和版本。

```text
Local Capture roots
        |
        v
Catalog scanner ----> Read-only API ----> Web workbench
        |                                      |
        |                                      v
        +---- bundle / manifests          Processing API
                                               |
                                               v
                                      Fixed pipeline adapters
                                               |
                         Source -> EGO Canonical -> RobotDataset -> Reports
```

## 存储原则

1. 文件系统和 Capture manifest 是事实来源。Source 原件不移动、不转码、不复制。
2. 扫描只读取浅层目录和已有 manifest/checksum 索引，不递归遍历大型媒体来计算容量。
3. 首版不需要数据库。数据量增大后可增加 SQLite 作为可删除、可重建的搜索缓存；大文件仍留在文件系统。
4. 浏览器不上传 Capture。后端仅暴露预先配置的允许根目录，前端选择的是根目录标识。
5. Pipeline 只能调用登记过的适配器，禁止客户端提交任意命令或任意路径。

## 数据和作业语义

- `task`：Capture 中演示内容的业务语义，例如“拿起红色方块”。
- `run`：对一个 Capture 发起的一次处理运行，包含版本、参数、日志和失败原因。
- `stage`：运行中的固定步骤，如完整性、EGO 构建、机器人重定向、质量和导出。
- `artifact`：某次运行生成的 EGO、RobotDataset、报告或导出包。

Capture 状态来自 `bundle.json`。Run 状态是平台运行态，二者不能互相覆盖。

`capture_id` 是不可变技术主键；`semantic_id` 是人读、可编辑且在目录集合内唯一的业务标识，
显示名称、任务描述和操作者随它保存在 `metadata/catalog.json`。派生数据和血缘仍引用 `capture_id`。

## 首版与后续

本地执行器采用单机串行队列，运行记录持久化到 `data/state/runs.json`。完整性检查实际复核
Source SHA-256，完整 Capture 继续调用现有 strict-v3 校验器；RGB 视频、重定向和质量分别调用
仓库现有构建器。导出写入 `.partial`，完成后原子发布，同盘优先硬链接、跨盘复制。

现阶段 `native_rgbd` 的 Source 到 EGO 消费器在原仓库尚未闭环，平台按能力判定阻止执行并展示原因，
不能把它显示成成功。该消费者完成后，只需新增固定适配器，不改变 API 和作业模型。
