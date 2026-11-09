# 主播试镜 AI 评分系统

候选人按试镜题单和录制规则，在系统外录好约 17 分钟的试镜视频，员工上传到系统，系统按《主播评分标准 · 机器可执行版》自动打分、出报告，供 HR 做录用参考。

- 需求：[`docs/prd.md`](docs/prd.md)
- 评分规则唯一来源：[`docs/source/主播评分表-20261105.xls`](docs/source/)（现行配置 `config/rubric/rubric-v0.2.yaml` 逐条引用原文）
- 历史资料：[`docs/rubric.md`](docs/rubric.md)（v0.1 改写版，已停用，仅供追溯）、`docs/source/主播评分标准-20241025.xls`（旧表）
- 与评分表 20261105 的对齐记录：[`docs/decisions.md`](docs/decisions.md) 第 7 节
- 金标准到位前的离线盲打分（本地千问、本地语音模型、外部判定回放）：[`docs/blind-test/README.md`](docs/blind-test/README.md)
- 冲突、决定、待确认项：[`docs/decisions.md`](docs/decisions.md)

## 当前进度

| 里程碑 | 内容 | 状态 |
|---|---|---|
| 1 | 计分引擎、23 条计分配置（2026-11-06 按评分表 20261105 改为 rubric-v0.2）、配置校验与发布检查、数据模型与迁移 | 已完成 |
| 2 | 平台底座（登录、权限、审计、字段加密）和配置后台：评分标准版本、卖点卡、异议库、知识题库、朗读稿、抽题规则、红线词表、试镜题单、账号 | 已完成 |
| 3 | 视频上传与录制规则：候选人与书面同意登记、可打印题单（工作人员联 / 候选人联）、分片上传与断点续传、边看边标分段和异议时间、媒体读取审计（取代原候选人录制端，见 decisions.md C18） | 已完成 |
| 4 | AI 处理流水线 M3 和自动判定 M4：四类能力接口与 Mock、媒体准备、声学特征、23 条检测器与红线检测、临界三轮、两级重试、失败通知与告警、到期删除、压测 | 已完成（全部用 Mock） |
| 5 | 报告 M5：内部报告（结论标签与原因、维度与条目、证据、临界各轮、低置信、追溯信息）、逐句评分与 AI 示范说法、按日期范围排名、Excel / PDF 导出、按新版评分标准重算、新主播查看本人记录 | 已完成 |
| 6 | 校准与看板 M6：金标准集（上线前 / 月度抽检）、2–3 位校准员背对背证据级打分、中位数与分歧裁决、与 AI 逐项对比、一致率与上线门槛、低于目标告警、效率看板 | 已完成 |

## 目录

```
scoring/                 计分引擎（纯函数，不依赖数据库、网络或 AI）
config/rubric/           计分配置（YAML）
backend/app/
  api/                   接口：登录、账号、评分标准、产品与题库、朗读稿、红线词表、题单、录制规则、候选人、录像与上传、媒体、审计日志
  content/               录制规则（按版本）
  models/                数据模型（SQLAlchemy）
  security/              密码、会话、字段加密、角色权限矩阵
  services/              审计、评分标准版本公共逻辑、对象存储、视频探测、通知（Mock）、到期删除
  providers/             外部 AI 能力接口（语音识别、普通话评测、大模型、视觉、笑声检测）及 Mock 实现、限流与重试
  pipeline/              处理流水线：媒体准备、声学特征、逐字稿工具、提示词、检测器（detectors/）、每轮执行、编排
  cli.py                 建账号、导入演示数据、到期删除、启动 worker
config/detectors/        检测配置（P2 词表、停顿阈值、抽帧频率等；改了需重跑模型）
backend/migrations/      数据库迁移（Alembic）
frontend/                管理后台（React + TypeScript + Ant Design）
tests/scoring/           计分引擎测试
backend/tests/           后端接口与数据模型测试（需要 PostgreSQL）
frontend/e2e/            管理后台端到端测试（Playwright）
scripts/run_e2e.sh       端到端测试一键运行
scripts/load_test.py     压测：5 条同时处理
scripts/gen_env.sh       生成 docker-compose 用的 .env（随机密钥）
Dockerfile、docker-compose.yml  单机部署（见“用 Docker 部署”，未在开发环境完整验证）
```

## 本地启动

需要：Python 3.12+、Node.js 20+、PostgreSQL 14+、ffmpeg；生产还需要 Redis（处理队列）。

1. 安装后端依赖：

   ```bash
   python3 -m venv .venv
   ```

   ```bash
   .venv/bin/pip install -e ".[dev]"
   ```

2. 准备环境变量。三把密钥各为 32 字节随机数的 base64，可以这样生成：

   ```bash
   .venv/bin/python -c 'import base64,os;print(base64.b64encode(os.urandom(32)).decode())'
   ```

   需要设置的变量：

   | 变量 | 说明 |
   |---|---|
   | `DATABASE_URL` | 如 `postgresql+psycopg://user:pass@localhost/audition` |
   | `APP_SESSION_KEY` | 登录会话签名密钥 |
   | `APP_DATA_KEY` | 个人信息字段加密密钥。**丢失后已加密的数据无法解密，务必妥善备份** |
   | `APP_HASH_KEY` | 手机号查找哈希密钥 |
   | `APP_COOKIE_SECURE` | 本地用 http 调试时设为 `false`；生产必须走 https，保持默认 `true` |
   | `APP_FRONTEND_DIST` | 前端构建目录（如 `frontend/dist`），设置后由后端直接托管管理后台 |
   | `APP_RETENTION_DAYS` | 未录用候选人媒体保存天数；默认 30 仅为测试占位，正式值待法务确认 |
   | `APP_ENV` | `production` 时禁止使用本地目录存储 |
   | `APP_STORAGE` | `s3`（生产）或 `local`（开发） |
   | `APP_STORAGE_DIR` | 本地存储目录（`APP_STORAGE=local` 时） |
   | `APP_S3_ENDPOINT`、`APP_S3_REGION`、`APP_S3_BUCKET` | S3 兼容存储地址、区域、桶名（阿里云 OSS、腾讯云 COS 等境内服务均可）；访问密钥用标准的 `AWS_ACCESS_KEY_ID`、`AWS_SECRET_ACCESS_KEY` |
   | `APP_S3_SSE` | 服务端加密方式，默认 `AES256`，可设 `aws:kms` |
   | `APP_MAX_UPLOAD_BYTES` | 单个视频大小上限，默认 8 GB |
   | `APP_QUEUE` | `rq`（生产：Redis 队列，多个 worker 并行）或 `inline`（开发：提交后在当前进程同步处理） |
   | `APP_REDIS_URL` | 默认 `redis://localhost:6379/0` |
   | `APP_PROVIDERS` | AI 供应商实现，目前只有 `mock`；接入真实供应商见下文 |
   | `APP_LIMIT_LLM`、`APP_LIMIT_ASR` | 同时调用大模型、语音识别的上限（所有 worker 合计），默认 8、3；按供应商的并发配额设 |
   | `APP_RETRY_BACKOFF_S` | 一轮处理失败后重试的等待秒数，默认 `5,20`（即重试 2 次） |
   | `APP_CALL_RETRY_BACKOFF_S` | 单次供应商调用失败后重试的等待秒数，默认 `1,3` |
   | `APP_CHROMIUM` | 导出 PDF 用的 Chromium 路径（不设则自动查找） |

   服务器上需要安装 ffmpeg（检查上传的视频、抽音频和抽帧）。

3. 建表、导入演示数据、建管理员账号：

   ```bash
   cd backend && ../.venv/bin/alembic upgrade head
   ```

   ```bash
   cd backend && ../.venv/bin/python -m app.cli seed-demo
   ```

   ```bash
   cd backend && ../.venv/bin/python -m app.cli create-user --username admin --role admin --display-name 管理员
   ```

   演示数据：少儿医疗险卖点卡（含演示固定话术和一份**未经人工样本校准**的草稿 S2 校准记录）、4 条异议、红线词表草稿，正式使用前须由培训和合规替换。演示的 S2 校准记录是草稿，据此出的报告都标“非正式”。

4. 构建前端并启动：

   ```bash
   cd frontend && npm install && npm run build
   ```

   ```bash
   cd backend && APP_FRONTEND_DIST=../frontend/dist ../.venv/bin/uvicorn app.main:app --port 8000
   ```

   浏览器打开 http://127.0.0.1:8000 。接口文档在 http://127.0.0.1:8000/api/docs 。

   生产用队列模式时，另外启动 worker（按并发需要启动多个，压测用了 5 个），并每天执行一次到期删除：

   ```bash
   cd backend && APP_QUEUE=rq ../.venv/bin/python -m app.cli worker
   ```

   ```bash
   cd backend && ../.venv/bin/python -m app.cli purge-expired
   ```

   改前端时可以用热更新：后端照常跑在 8000 端口，另开一个终端运行 `cd frontend && npm run dev`，打开 http://127.0.0.1:5173 。

后端接口有改动时，重新生成前端类型：

```bash
.venv/bin/python backend/scripts/export_openapi.py frontend/src/api/openapi.json && cd frontend && npm run gen:api
```

## 运行测试

计分引擎测试（不需要数据库）：

```bash
.venv/bin/python -m pytest tests
```

全部 Python 测试，需要一个**可以清空的** PostgreSQL 库：

```bash
TEST_DATABASE_URL=postgresql+psycopg://audition:audition@localhost/audition_test .venv/bin/python -m pytest
```

管理后台端到端测试：脚本会临时建库 `audition_e2e`，启动后端，用 Chromium 跑一遍，结束后删库。需要一个有建库权限的 PostgreSQL 账号，通过 `E2E_ADMIN_URL` 指定：

```bash
E2E_ADMIN_URL=postgresql://audition:audition@localhost/postgres ./scripts/run_e2e.sh
```

压测（5 条同时处理，见下文“处理时效”）：

```bash
E2E_ADMIN_URL=postgresql://audition:audition@localhost/postgres .venv/bin/python scripts/load_test.py
```

前端类型检查：

```bash
cd frontend && npm run typecheck
```

## 角色与权限

| 角色 | 能做什么 |
|---|---|
| 管理员 | 维护评分标准、卖点卡、异议库、知识题库、朗读稿、抽题规则；生成题单；管理账号；查看审计日志；看全部报告；按新版评分标准重算报告；管理金标准与校准、裁决分歧；看一致率和效率看板 |
| 合规 | 维护红线词表和正确说法（只有合规能改；试镜不做红线，词表留给以后的直播评分，C33） |
| HR | 查看全部内容（含原始视频、全部报告和排名）；登记候选人和书面同意、上传录像、标分段、标记录用状态、关联新主播账号；导出 Excel / PDF |
| 校准员 | 只看分给自己的样本和视频，背对背打分；看不到 AI 报告和其他校准员的打分 |
| 新主播 | 只看本人记录的全部内容（报告、逐句评分、本人录像）；由 HR 在候选人页关联账号 |

完整矩阵见 `backend/app/security/rbac.py`。登录、账号变更、配置导入与发布、题单生成、查看审计日志都会写审计记录。

## 上传一条试镜录像

1. 管理员在“试镜题单”生成题单，打印**工作人员联**给录制时提问的人，**候选人联**（录制规则、流程、卖点卡，不含题目和分值）给候选人。
2. 候选人签署书面同意书，按题单在系统外连续录成一个视频文件。
3. HR 在“试镜录像 → 上传录像”：选候选人（没有就新建），登记书面同意（未登记不能上传），选题单、适用达标线、画面里有无贴片或 KT 板，选文件上传。上传中断后，打开这条录像重新选择同一文件即可续传。
4. 上传完成后边看视频边标出主体段、朗读段的起点（旧版题单另有知识题），异议时间默认取题单，可按视频修正。保存后点“提交处理”。产品卖点卡没有固定话术或对应的 S2 校准记录时，提交会被拒绝（见下文“产品讲解 S2 的固定话术与校准”）。
5. 系统自动评分：
   - 媒体准备：抽各段音频和画面帧，只做一次；
   - 每一轮：语音识别（关闭顺滑）→ 声学特征 → 23 个检测器并行出证据（试镜不做红线检测，C33） → 计分引擎算分；
   - 首轮临界时，自动追加 2 轮（共 3 轮取多数）；
   - 偶发失败先就地重试单次调用，再按整轮重试 2 次；仍失败则通知候选人重录、告警管理员，录像页可点“重新处理”。

## 看报告

- **报告与排名**：按提交日期范围列出最新报告并排名，可按结论标签筛选、按单个维度排序，可导出 Excel。
- **报告页**：
  - 顶部：结论标签（推荐 / 待定 / 不推荐）和一句话原因；
  - 提示：非正式报告、临界样本（列出各轮结果）、低置信条目；
  - 总览：四个维度的分数和档位，23 个条目的得分，点开看证据（原句、时间、判定、加扣分、理由、置信度）；
  - 逐句评分：每句标出命中的条目和加扣分，有问题的句子附 AI 示范说法，点时间跳到视频对应位置；
  - 追溯信息：评分标准、检测配置、各供应商和模型版本、提示词版本、修订历史；
  - 操作：导出 PDF；管理员可按新版评分标准重算（不重跑模型，生成新修订）。
- **新主播**：HR 在候选人页把录用的新主播账号关联到本人记录后，新主播登录只能看到“我的试镜记录”。

导出 PDF 需要服务器装有 Chromium（推荐 chrome-headless-shell）和中文字体（如 `fonts-wqy-zenhei` 或 Noto Sans CJK）。路径可用 `APP_CHROMIUM` 指定。

## 校准与看板

上线前和每月都要用人工金标准核对 AI 的准确度（PRD 第 1、6 节）：

1. **管理员建金标准集**（“金标准与校准”）：选用途（上线前 / 月度抽检）和评分标准版本；
   - 加入已出报告的录像，或按月份随机抽样（每月 10–20 条）；
   - 把全部样本分配给 2–3 位校准员。
2. **校准员背对背打分**（“我的校准任务”）：边看视频边打到证据级，提交前看不到 AI 结果和别人的打分。
   - 计次类条目每看到一次点一次，系统记下视频时间；
   - 等级类直接选等级（主观评分条目和 S2 填 0–满分的整数，S2 对照页面上的固定话术打分）；计次类逐次记录；异议逐项勾选；
   - P4 语速自动沿用机器按时间戳统计的结果。
3. **自动汇总金标准**：全部提交后用同一个计分引擎算分。
   - 条目分取中位数（2 人时平均）；
   - 相差超过条目满分 20% 的条目标为“待裁决”，开会后由管理员录入裁决分和理由；
   - 全部有结果后定稿。
4. **对比与一致率**：
   - 样本页列出每位校准员、金标准、AI 的逐项分数和维度档位；
   - 金标准集页给出维度档位一致率（目标 ≥ 85%）、结论一致率（目标 ≥ 95%）、人与人一致率，以及各条目一致率（低于 85% 告警）；
   - 低于目标会告警管理员（目前是 Mock 渠道）。
5. **看板**（管理员）：
   - 一致率：按金标准集或录像提交日期；
   - 效率：处理时长中位数、p95、最长、超过 30 分钟的条数，失败率，整轮重试次数，临界占比，各条目低置信比例，每日处理量。

统计口径（分母、AI 不完整计为不一致等）见 `docs/decisions.md` C34、C35。

## 处理时效（压测结果）

`scripts/load_test.py`：5 条 17 分钟录像同时提交，5 个 worker。供应商延迟按 1/10 缩小模拟，再乘回 10 估算真实耗时：
- 延迟假设：语音识别耗时 = 音频时长 × 0.15；大模型每次 15 秒；语音评测 10 秒；视觉 30 秒；
- 每次调用 3% 随机失败；
- 演示剧本恰好落在临界区间，每条都要跑满 3 轮，属于最坏情况。

| 大模型并发上限 | 估算最长耗时 | 结论 |
|---|---|---|
| 4 | 34.7 分钟 | 超过 30 分钟目标 |
| 8（默认） | 20.4 分钟（中位数 18.1） | 达标 |

所以选大模型供应商时要确认支持至少 8 路并发。接入真实供应商后，用实际延迟重跑压测（参数见脚本开头）。

## 用 Docker 部署

> **注意：应用镜像还没有完整构建、跑通过。** 开发环境的网络策略禁止访问 Debian 软件源，镜像里装不上 ffmpeg 和 Chromium。已在开发环境用真实容器验证过的部分：PostgreSQL、MinIO 启动；对象写入带服务端加密，磁盘上是密文；数据库迁移和演示数据导入；`scripts/backup.sh` 备份；从备份恢复到全新环境；换掉加密密钥后备份无法解密。第一次在正式机器上部署时，请按下面 Mac Studio 一节最后的检查清单逐项确认。

```bash
./scripts/gen_env.sh
```

```bash
docker compose up -d --build
```

```bash
docker compose exec api python -m app.cli seed-demo
```

```bash
docker compose exec api python -m app.cli create-user --username admin --role admin --display-name 管理员
```

- 浏览器打开 http://服务器:8000 。走公网时必须配 https（前面加反向代理），并把 `.env` 里的 `APP_COOKIE_SECURE` 改为 `true`。
- `.env` 里的密钥务必另外保存：`APP_DATA_KEY` 丢了，已加密的个人信息无法解密；`MINIO_KMS_SECRET_KEY` 丢了，视频无法解密。
- 视频等媒体存放在宿主机目录 `MEDIA_DIR`（默认 `./data/minio`，MinIO 加密后的文件）。在 Linux 上这个目录要归 uid 1001 所有：`mkdir -p data/minio && sudo chown 1001 data/minio`。
- 每天一次：`scripts/daily.sh`，先删除到期媒体，再备份（见下一节）。
- 自带的对象存储是 Bitnami 的 MinIO 归档镜像（官方镜像已不在 Docker Hub 提供，这个镜像也不再更新），只适合内网使用。走公网或长期使用时，请改用阿里云 OSS、腾讯云 COS 等境内对象存储：修改 `.env` 中的 `APP_S3_ENDPOINT`、`APP_S3_BUCKET`、`APP_S3_REGION`、`S3_ACCESS_KEY`、`S3_SECRET_KEY`，并去掉 compose 里的 minio 服务。
- 构建环境需要经 HTTPS 代理（自签证书）访问软件源时，用 `docker build --secret id=build_ca,src=<证书文件> .` 传入证书。证书只在构建时使用，不会留在镜像里。

## 在 Mac Studio 上部署（公司内网，NAS 做备份）

适用于：Apple 芯片的 Mac（如 M5 Max、64 GB 内存、512 GB 硬盘），每月约 100 条试镜录像，只在公司内网使用。所用镜像都有 linux/arm64 版本（python、node、postgres、redis、bitnamilegacy/minio 已逐一核对），不需要改代码。

### 存储怎么分

| 放在哪 | 内容 | 容量估算（每月 100 条） |
|---|---|---|
| Mac 本机 SSD：`MEDIA_DIR` | 视频、音频、抽帧（MinIO 加密后的文件） | 每条 0.6–2.1 GB；未录用的保存 30 天，滚动占用 60–210 GB；已录用的一直保留，每年增加 70–250 GB（按一成录用估算） |
| Mac 本机 SSD：Docker 虚拟机 | 数据库、Redis、镜像 | 20–40 GB |
| NAS：`BACKUP_DIR` | 每日数据库备份（保留 14 天）和媒体镜像 | 与上面两项相当 |
| **密码管理器等，与 NAS 分开** | `.env`（全部密钥） | 几 KB，生成后不变 |

视频不要直接放在 NAS 的共享目录上跑 MinIO：MinIO 不支持网络文件系统作为数据盘。NAS 只用来做备份。如果 NAS 自带 S3 兼容服务（例如 QNAP 的 QuObjects、TrueNAS 的 MinIO 应用），也可以把 `APP_S3_ENDPOINT` 指向 NAS，把视频直接存到 NAS 上，这样不占 Mac 的硬盘。这种做法要先确认 NAS 支持服务端加密（SSE-S3）。

本机磁盘用到 80% 时，`backup.sh` 会在日志里提醒。

### 1. 准备 Mac

1. **部署目录不要放在“桌面”“文稿”“下载”下面。** 这几个文件夹受 macOS 隐私保护，后台定时任务访问不了。建议单独克隆一份到 `~/audition`，开发用的那份仍然留在原处。
2. 打开 FileVault（系统设置 → 隐私与安全性）：磁盘上有候选人的人脸、声音和个人信息。
3. 防止休眠：系统设置 → 能耗，关闭“自动进入睡眠”，打开“断电后自动启动”；或者用命令：

   ```bash
   sudo pmset -a sleep 0 disksleep 0 autorestart 1
   ```

4. 开了 FileVault，断电重启后需要有人到现场登录一次，Docker 才会启动。建议给这台机器接 UPS。
5. 在路由器上给 Mac 固定内网 IP。HR 用 `http://<固定IP>:8000` 访问。只在内网使用时可以保持 `APP_COOKIE_SECURE=false`。代价是登录状态在内网里明文传输，所以不要把 8000 端口映射到公网。

### 2. 安装 Docker

二选一：

- **Docker Desktop**：最省事。员工超过 250 人或年收入超过 1000 万美元的公司，商用需要购买订阅。设置里：Resources 给 8 核 CPU、16 GB 内存；在 General 里勾选“登录时启动 Docker Desktop”。
- **Colima**：免费开源，需要先装 Homebrew：

  ```bash
  brew install colima docker docker-compose
  ```

  ```bash
  colima start --cpu 8 --memory 16 --disk 60 --vm-type vz --mount-type virtiofs --mount ~/audition:w
  ```

  安装后按 brew 的提示，把 docker-compose 链接为 docker 的插件，`docker compose` 命令才能用。开机自启：`brew services start colima`。

### 3. 首次部署

```bash
git clone https://github.com/zhangchunm67-alt/audition-ai-scoring.git ~/audition
```

```bash
cd ~/audition && ./scripts/gen_env.sh && mkdir -p data/minio data/logs
```

编辑 `.env`：把 `BACKUP_DIR` 设为 NAS 挂载目录，例如 `/Volumes/audition-backup`；接入真实 AI 供应商时，再把 `APP_PROVIDERS` 改掉。然后**把整个 `.env` 存进公司密码管理器**，不要放在 NAS 的同一个共享里。

```bash
docker compose up -d --build
```

```bash
docker compose exec api python -m app.cli create-user --username admin --role admin --display-name 管理员
```

### 4. 挂载 NAS，开启每日备份

1. 在访达里“前往 → 连接服务器”，输入 `smb://<NAS地址>/<共享名>`，勾选“记住密码”。再把这个共享拖进“系统设置 → 通用 → 登录项”，登录时会自动挂载。NAS 上为这个共享单独建账号，只给这台 Mac 读写权限。
2. 在共享里放一个标记文件。备份脚本只认带这个文件的目录，NAS 没挂载时会直接失败，不会把备份写到本机：

   ```bash
   touch /Volumes/audition-backup/.audition-backup
   ```

3. 手动跑一次，确认能成功：

   ```bash
   ./scripts/daily.sh
   ```

4. 安装每日任务（每天 02:30 执行到期删除和备份，日志在 `data/logs/daily.log`）：

   ```bash
   sed "s|__DEPLOY_DIR__|$HOME/audition|g" scripts/macos/com.audition.daily.plist > ~/Library/LaunchAgents/com.audition.daily.plist
   ```

   ```bash
   launchctl load ~/Library/LaunchAgents/com.audition.daily.plist
   ```

### 5. 从备份恢复

需要三样东西：NAS 上的 `db/` 和 `media/`，以及密码管理器里的 `.env`。缺了 `.env` 里的密钥，数据库里的个人信息和全部视频都无法解密（已实测：换了 `MINIO_KMS_SECRET_KEY` 后视频读不出来）。

```bash
cd ~/audition && cp <密码管理器里保存的 .env> .env && mkdir -p data && cp -a /Volumes/audition-backup/media data/minio
```

```bash
docker compose up -d postgres minio
```

```bash
docker compose exec -T postgres pg_restore -U audition -d audition --no-owner < /Volumes/audition-backup/db/<最新的 .dump 文件>
```

```bash
docker compose up -d
```

### 6. 首次部署检查清单（应用镜像尚未在 Apple 芯片上跑过）

- [ ] `docker compose up -d --build` 成功；`docker compose ps` 里 api、两个 worker、postgres、redis、minio 都在运行
- [ ] 用演示数据跑完一条录像，能出报告（`seed-demo` 之后按上文“上传一条试镜录像”操作）
- [ ] 报告能导出 PDF（Chromium 和中文字体正常）
- [ ] `./scripts/daily.sh` 成功，NAS 上出现 `db/*.dump` 和 `media/`
- [ ] 在另一台电脑或另一个目录按“从备份恢复”演练一次
- [ ] 断电重启后，登录 Mac，系统能自动恢复服务

## 更换真实 AI 供应商

外部 AI 能力（语音识别、普通话评测、大模型、视觉、笑声检测、声音评价）都在 `backend/app/providers/base.py` 定义了接口，流水线只依赖接口。接入步骤：

1. 在 `backend/app/providers/` 下新建实现，例如 `xxx_asr.py`，实现对应接口：
   - **语音识别** `transcribe()`：必须关闭顺滑（`disfluency_removal=False`，例如阿里云 Paraformer 的 `disfluency_removal_enabled=false`），返回字级时间戳和标点；返回的 `params` 里要如实带回 `disfluency_removal: False`，否则这一轮会被拒绝；
   - **普通话评测** `assess()`：带参考文本（朗读稿）；`details["errors"]` 逐处列出问题 `{text, start_ms, end_ms, type: dialect / mispronounce, confidence}`，P3 按方言处计次，没有这个字段视为评测不完整；
   - **大模型** `complete_json()`：温度固定 0，用 JSON 模式输出，结构见 `backend/app/pipeline/prompts.py`；
   - **视觉** `analyze()`：任务分 `attire`（P1，只判穿着 / 发型是否不符合要求，类别 `attire` / `hairstyle`）、`fidget`（小动作）、`prop_pointing`（指向道具）；
   - **声音评价** `rate()`：P5 语调、P6 音色、P7 节奏的主观评分，须是能直接听音频的模型，返回 0–满分的整数；
   - **笑声检测** `detect()`：返回笑声候选片段，是否算“嘻嘻哈哈”由大模型结合上下文判断；
   - 调用失败抛 `ProviderError`，系统会自动重试。
2. 设 `APP_PROVIDERS=config`，每种能力单独选实现（`APP_ASR`、`APP_LLM`、`APP_VISION`、`APP_VOICE`、`APP_LAUGH`、`APP_SPEECH_EVAL`）。没选的能力视为“未配置”，对应条目缺证据、不出分。已有的实现：本地 SenseVoice 语音识别和 CED 笑声检测（sherpa-onnx）；兼容 OpenAI 接口的大模型、视觉、声音评价（本地 llama-server 上的千问等）；外部判定回放。用法见 [`docs/blind-test/README.md`](docs/blind-test/README.md)。新供应商在 `backend/app/providers/registry.py` 的 `from_env()` 里注册。
3. 供应商必须是境内服务；密钥通过环境变量传入，不要写进代码。
4. 换模型或改提示词前，先在金标准集上跑回归，一致率不下降才发布（PRD 第 5 节）。报告会记录供应商、模型版本和提示词版本。
5. 用固定样本手动验证一次“口头禅保留”：录一段含“那么”“一个”“对不对”的话，确认转写里都在，且 P2 证据逐条列出。

## 修改评分配置

评分规则全部在 `config/rubric/rubric-v0.2.yaml`（规则来源：评分表 20261105，每个条目的 `note` 先引原文）。改分值、免扣次数、封顶、档位表、达标线、临界范围、阈值，都只改配置，不改代码，也不用重跑模型。

1. 复制成新版本文件（例如 `rubric-v0.3.yaml`），修改 `version`。
2. 跑测试：`.venv/bin/python -m pytest tests`。配置不合法（档位表不连续、分值相加不等于满分、题数不对等）会在加载时报错，并说明原因。
3. 在管理后台“评分标准”页导入 YAML。页面会列出全部发布阻碍：带 `pending`（待确认）或 `calibration_required: true`（测试占位值）的节点。也可以在命令行查看：

   ```bash
   .venv/bin/python -c "from scoring import load_config, publish_blockers; print(*publish_blockers(load_config('config/rubric/rubric-v0.2.yaml')), sep='\n')"
   ```

   某项拍板后，修改对应规则、删除标记，并更新 `docs/decisions.md`。阻碍清空后才能发布；标为 published 但仍带标记的配置，导入时会被拒绝。草稿版本可以用来生成题单试用，报告会标注“非正式”。

### 产品讲解 S2 的固定话术与校准

评分表：S2 “根据固定话术的完成准确程度打分”，满分 50。每个产品话术不同，所以：

1. 卖点卡里填 **固定话术**（带版本号）。改话术必须换版本号，原来的校准记录随之失效。
2. 用该产品 20–30 份人工标注样本（产品标识、录像或逐字稿、人工 S2 分及其他条目分、评分依据）校准，另留验证样本检查 AI 与人工的一致性；原始标注另行保存，不覆盖。
3. 在产品页的卖点卡下登记 **S2 校准记录**（`PUT /api/cards/{id}/s2-calibration`）：校准版本、对应的话术版本、样本数、留出验证一致率、给模型参考的校准样例。已发布的卡也能补登（话术不变），每次修改写审计。
4. 没有话术、没有校准记录或版本对不上时，录像不能提交处理，S2 检测器也会拒绝出分（条目缺证据，不当 0 分）。校准记录为草稿时可以试跑，报告标“非正式”；标为“已验证”须至少 20 份校准样本并有留出验证结果。

卖点卡的必讲要点只在旧版评分标准（rubric-v0.1，卖点卡要点 30 + 结构 20）下计分，旧版要求要点分值合计等于 30；新版不再按要点计分。

各计分类型的配置写法：

| 类型 | 用于 | 关键参数 |
|---|---|---|
| T1 逐次扣分 | P1、P2、P3、P8、P10、L3 | `per` 单次扣分，`free` 免扣次数，`normalize` 时长换算 |
| T2 逐次加分 | P9、S4、L2、L4、L5、O1、O2、O3 | `award` 或按类别的 `awards`，`cap` 封顶，`labels` 计分类别，`distinct_by_label` 同类只算一次 |
| T3+T4 | 仅旧版 S2 | `checklist_max` 要点满分（分值取自卖点卡），`structure_levels` 结构等级，`error_penalty` 讲错扣分 |
| T4 分级锚定 | P5、P6、P7、S1、S2、L1、O4（评分表“根据主观打分”及 S2，等级为 0–满分的每个整数） | `parts[].levels` 等级；等级来源 `source`：`evidence` 检测器直接给、`metric` 指标分段、`count` 计次分段、`rules` 多指标规则；`modifiers` 封顶或降级；`boundary_flag` 边界标低置信 |
| T5 阈值 | P4 | `metric`、`limit`、`score_by_over` 超限段数 → 分数 |
| T6 逐题 | S3（旧版另有 O5） | `count` 题数；`levels` 按等级给分，或 `elements` 按要素给分加 `zero_labels` |

检测配置在 `config/detectors/detectors-v2.yaml`（P2 词表、停顿和卡壳阈值、抽帧频率、道具引导语等），与计分配置分开管理，改了需要重跑模型。提示词在 `backend/app/pipeline/prompts.py`，改动须升版本号。

## 交付状态

| 方面 | 状态 |
|---|---|
| PRD 功能 M1–M6 | P0 全部实现；M2 录制端按 C18 改为“系统外录制 + 上传”；M5-3 候选人反馈版（P1）未做（新主播已能看本人完整报告） |
| AI 能力 | 四类能力（加笑声检测）都已定义接口，目前全部是 Mock，分数不代表真实准确度；真实供应商须境内服务，接入方法见上文 |
| 评分配置 | rubric-v0.2 按评分表 20261105 写入配置；评分表未写明的口径和主观评分条目都显式标记（待确认、需校准），发布检查拦截，目前出的报告都标“非正式” |
| 上线前提 | 接入真实供应商 → 定稿评分标准和检测配置的待确认项 → 金标准集达到上线门槛（维度 ≥ 85%、结论 ≥ 95%）→ 影子试用（PRD 第 6 节） |
| 测试 | Python 测试（计分引擎、流水线工具、后端接口与数据模型）、管理后台端到端测试（Playwright）、压测脚本；数量见最近一次提交说明 |
| 未决事项 | 见 `docs/decisions.md` 第 4 节（录制现场谁提问、录制规则审定、同意书正文与扫描件保存期限、保存期限正式值、样本量标准等） |

## P0 验收用例

PRD 第 6 节的 8 条用例。其中两条以系统内录制为前提，已按“上传录好的视频”（C18）改写。

| 用例 | 验证方式 | 状态 |
|---|---|---|
| 不同意授权时无法进入录制 → 改为：未登记候选人书面同意，不能上传和处理（C30） | `backend/tests/test_recordings_api.py::test_no_consent_no_upload`；端到端测试“未登记授权时先登记” | 已完成 |
| 4 条异议按配置时间点弹出 → 改为：题单的异议时间点（可按视频修正）与证据时间戳对得上（C29） | `test_segments_and_objection_alignment`（视频时间 = 主体段起点 + 相对时间）；`backend/tests/test_pipeline.py::test_objection_times_align_with_evidence`（S3 证据都在对应异议弹出之后、主体段之内） | 已完成 |
| 口头禅在转写中保留，未被顺滑删掉 | `test_full_length_critical_three_rounds_and_traceability`（转写里有“那么”“一个”，P2 逐条出证据）；`test_asr_must_keep_disfluencies`（供应商开了顺滑即拒绝）；数据库约束 `transcripts.disfluency_removal` 必须为 false；接真实供应商后按上文第 5 步手动验证 | 自动化已完成，真实供应商待手动验证 |
| 人设塑造按适用满分正确折算（评分表 20261105：满分 100；画面里没有道具时 P9 不适用，按 95 折算） | `tests/scoring/test_dimensions_and_round.py::test_persona_with_props_max_100`、`::test_persona_no_props_p9_not_applicable_scaled_from_95` | 已完成 |
| 红线命中时结论为"不达标"，报告附原句 | 试镜不适用（C33：不做红线）；`test_redlines_off_for_audition` 验证红线话术不影响结论。红线逻辑保留给以后的直播评分，在打开红线的配置下仍有测试：`test_redline_*`、`test_redline_path_when_enabled` | 试镜不适用 |
| 临界样本自动重跑 3 次，报告标"临界"（共 3 轮，首轮参与投票） | 汇总规则：`tests/scoring/test_verdict.py`；流水线：`test_full_length_critical_three_rounds_and_traceability`、`test_rounds_can_disagree_majority_decides`；报告页显示临界和各轮结果（端到端测试、`test_report_html_contents`） | 已完成 |
| 报告里的标准版本、模型版本完整 | `test_traceability_fields`、`test_full_length_critical_three_rounds_and_traceability`；报告接口与 PDF：`test_list_and_detail`、`test_report_html_contents` | 已完成 |
| 到期视频自动删除，报告保留 | `test_retention_purge_keeps_reports`、`test_retention_keeps_hired_and_unexpired`、`test_stale_uploads_aborted` | 已完成 |
