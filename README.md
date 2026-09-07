# ZDataset Web

面向大体量 Capture、EGO 和机器人派生数据的数据管理工作台。浏览器只提供界面，目录扫描、
SHA-256、EGO 构建、机器人重定向、质量评估和导出均在部署后端的服务器本地执行。原始媒体
不经过浏览器上传，也不写入数据库。

## 当前能力与边界

- 扫描一个或多个服务端 Capture 根目录。
- 展示 Capture、Source、EGO、机器人数据集、数据血缘和质量证据。
- 使用可编辑的 `semantic_id`、显示名称、任务描述和操作者描述 Capture，同时保留不可变的
  `capture_id` 技术主键。
- 串行执行 Source SHA-256 完整性检查、已有 RGB 视频到 EGO、机器人重定向、质量报告和
  版本化导出，并持久化进度、日志、取消状态和失败原因。
- 语义元数据写入 `<capture>/metadata/catalog.json`，不修改 Source 数值和媒体文件。
- 不包含模型训练、仿真或真机部署。

当前 `native_rgbd -> EGO` 消费器在 VLA-HandArm 仓库中尚未闭环，平台会禁用该步骤并展示
原因。已有 `ego/meta/info.json` 的 Capture 可以直接进行质量、重定向和导出；`rgb_video`
Capture 可以调用现有 `build_canonical.py` 构建 EGO。

## 运行架构

```text
工作电脑浏览器
      |
      | HTTP（只传 API 和页面数据）
      v
EGO 处理服务器上的 ZDataset Web
      |
      +-- Capture 根目录（本地磁盘或已挂载 NAS）
      +-- VLA-HandArm 仓库与 LeRobot Python 3.12 环境
      +-- 平台状态目录
      +-- 版本化导出目录
```

`127.0.0.1` 只允许服务器本机访问。局域网其他电脑访问时，后端需要监听 `0.0.0.0`，浏览器
使用 `http://<服务器 IP>:<端口>`。无论浏览器在哪台电脑，平台看到的都是后端服务器配置的
目录，不是浏览器电脑的本地目录。

## 服务端首次部署

以下示例将项目部署到 EGO 处理账号的主目录。大文件不应放入本仓库。

### 1. 准备系统依赖

服务器需要 Linux、Git、Python 3.10 或更高版本以及已有的 VLA-HandArm/LeRobot 处理环境。
Node.js 只在运行前端回归测试时需要，生产服务本身不需要。

```bash
sudo apt-get update
sudo apt-get install -y git python3 python3-venv
git clone git@github.com:ZhangDaMengxx/Zdataset-web.git ~/Zdataset-web
cd ~/Zdataset-web
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r backend/requirements.txt
```

Web API Python 与数据处理 Python 是两个独立环境：

- `ZDATASET_PYTHON`：运行 FastAPI，只需安装 `backend/requirements.txt`。
- `ZDATASET_LEROBOT_PYTHON`：运行 EGO、重定向和质检，应指向服务器现有的 LeRobot Python
  3.12 环境，不能用空白 Web 虚拟环境代替。

### 2. 准备数据目录

Capture 可以位于服务器本地磁盘，也可以通过 NFS、CephFS 等方式预先挂载。不要通过网页上传
TB 级数据。运行服务的 Linux 用户至少需要：

- Capture 根目录读权限。
- 需要编辑语义信息或运行处理时，对 Capture 目录有写权限。
- 状态目录与导出目录读写权限。
- VLA-HandArm 仓库读权限，以及 LeRobot Python 的执行权限。

```bash
sudo mkdir -p /var/lib/zdataset-web/state /data/zdataset-exports
sudo chown -R "$USER":"$USER" /var/lib/zdataset-web /data/zdataset-exports
```

目录属主和组应按服务器实际的数据账号配置，不要为了省事使用 `chmod -R 777`。如果 Capture
只读挂载，浏览和质量查看仍可用，但编辑语义信息、完整性报告、EGO、重定向和质量处理会失败。

### 3. 配置路径

```bash
cd ~/Zdataset-web
cp .env.example .env
chmod 600 .env
```

编辑 `.env`，至少确认以下值：

```dotenv
ZDATASET_PYTHON=/home/ego/Zdataset-web/.venv/bin/python
ZDATASET_HOST=127.0.0.1
ZDATASET_PORT=8090
ZDATASET_CAPTURE_ROOTS=/data/captures:/mnt/archive/captures
ZDATASET_LEROBOT_REPO=/home/ego/VLA-HandArm
ZDATASET_LEROBOT_PYTHON=/home/ego/miniconda3/envs/lerobot-v3/bin/python
ZDATASET_STATE_DIR=/var/lib/zdataset-web/state
ZDATASET_EXPORT_ROOT=/data/zdataset-exports
```

Linux 下多个 Capture 根目录以冒号分隔。只能配置根目录，前端不能提交任意服务器路径或 Shell。
旧部署使用的 `NERO_*` 环境变量仍兼容，但新部署应使用 `ZDATASET_*`。

### 4. 部署前检查

```bash
cd ~/Zdataset-web
./deploy/check-server.sh
./test.sh
```

自检会验证 Web 依赖、Capture 权限、VLA-HandArm 处理脚本、LeRobot Python、状态目录和导出
目录。`./test.sh` 还需要 Node.js；如果生产服务器没有 Node.js，可在 CI 或开发机完成前端测试，
服务器至少应运行：

```bash
ZDATASET_PYTHON=.venv/bin/python .venv/bin/python -m pytest backend/tests
```

### 5. 前台试运行

```bash
./run.sh
```

另一个终端检查：

```bash
curl --fail http://127.0.0.1:8090/api/v1/health
```

确认返回 `status: ok`、`capture_roots` 大于零且 `lerobot_runtime: true`。首次验证只浏览目录，
不要直接对正式大包启动完整性或完整处理链；先用隔离的小型测试 Capture 验证成功、失败、取消、
磁盘空间和输出权限。

### 6. systemd 用户服务

仓库提供用户级 unit，默认项目路径为 `~/Zdataset-web`：

```bash
mkdir -p ~/.config/systemd/user
cp deploy/zdataset-web.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now zdataset-web.service
systemctl --user status zdataset-web.service
journalctl --user -u zdataset-web.service -f
```

需要注销后仍保持服务时执行：

```bash
sudo loginctl enable-linger "$USER"
```

停止服务使用 `systemctl --user stop zdataset-web.service`。systemd 停止时会终止同一服务组中的
处理子进程；中断的 `queued/running` 作业在下次启动时会登记为失败，不会标记为成功。

## 局域网访问与安全

平台目前没有内置账号系统，能够访问 API 的用户可以编辑 Capture 元数据并启动处理任务。因此：

- 不要把端口直接暴露到公网。
- 单机使用保持 `ZDATASET_HOST=127.0.0.1`。
- 局域网直连可设为 `ZDATASET_HOST=0.0.0.0`，但防火墙只允许可信网段访问。
- 跨网络访问优先使用 VPN、SSH 隧道，或带身份认证和 TLS 的反向代理。

SSH 隧道示例无需开放服务端端口：

```bash
ssh -L 8090:127.0.0.1:8090 <user>@<ego-server>
```

然后在工作电脑打开 <http://127.0.0.1:8090>。

## 更新与回滚

更新前等待当前处理作业结束，并备份 `.env` 和 `ZDATASET_STATE_DIR`。Capture 与导出目录不在
Git 仓库中，不应被 `git pull` 修改。

```bash
cd ~/Zdataset-web
git pull --ff-only
.venv/bin/python -m pip install -r backend/requirements.txt
./deploy/check-server.sh
systemctl --user restart zdataset-web.service
curl --fail http://127.0.0.1:8090/api/v1/health
```

回滚时切换到已验证的 Git tag/commit，重新安装该版本依赖并重启。不要在正在运行处理作业时切换
代码。状态文件默认位于项目 `data/state`，正式部署建议固定到项目外的持久目录。

## 目录与开发验证

```text
frontend/           原生 HTML/CSS/ES Modules 工作台
backend/app/        FastAPI API、目录扫描与运行编排
backend/tests/      后端回归测试
frontend/tests/     前端纯函数回归测试
deploy/             服务端自检与 systemd unit
docs/               架构、模块和测试方案
```

```bash
./test.sh
```

后端只接受允许根目录内的 Capture ID。Pipeline 使用固定参数数组，不提供上传、任意路径或任意
Shell 接口。架构、模块边界和测试范围分别见 `docs/ARCHITECTURE.md`、`docs/MODULES.md` 和
`docs/TEST_PLAN.md`。
