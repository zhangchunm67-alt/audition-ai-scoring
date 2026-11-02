# 主播试镜 AI 评分系统

候选人按试镜题单和录制规则，在系统外录好约 17 分钟的试镜视频，员工上传到系统，系统按《主播评分标准 · 机器可执行版》自动打分、出报告，供 HR 做录用参考。

- 需求：[`docs/prd.md`](docs/prd.md)
- 评分标准：[`docs/rubric.md`](docs/rubric.md)
- 原始评分表：[`docs/source/主播评分标准-20241025.xls`](docs/source/)
- 冲突、决定、待确认项：[`docs/decisions.md`](docs/decisions.md)

## 当前进度

| 里程碑 | 内容 | 状态 |
|---|---|---|
| 1 | 计分引擎、23 条计分配置、配置校验与发布检查、数据模型与迁移 | 已完成 |
| 2 | 平台底座（登录、权限、审计、字段加密）和配置后台：评分标准版本、卖点卡、异议库、知识题库、朗读稿、抽题规则、红线词表、试镜题单、账号 | 已完成 |
| 3 | 视频上传与录制规则：候选人与书面同意登记、可打印题单（工作人员联 / 候选人联）、分片上传与断点续传、边看边标分段和异议时间、媒体读取审计（取代原候选人录制端，见 decisions.md C18） | 已完成 |
| 4 | AI 处理流水线 M3 和自动判定 M4（先用 Mock，含视觉） | 未开始 |
| 5 | 报告 M5 | 未开始 |
| 6 | 校准与看板 M6 | 未开始 |

## 目录

```
scoring/                 计分引擎（纯函数，不依赖数据库、网络或 AI）
config/rubric/           计分配置（YAML）
backend/app/
  api/                   接口：登录、账号、评分标准、产品与题库、朗读稿、红线词表、题单、录制规则、候选人、录像与上传、媒体、审计日志
  content/               录制规则（按版本）
  models/                数据模型（SQLAlchemy）
  security/              密码、会话、字段加密、角色权限矩阵
  services/              审计、评分标准版本公共逻辑、对象存储、视频探测
  cli.py                 建账号、导入演示数据
backend/migrations/      数据库迁移（Alembic）
frontend/                管理后台（React + TypeScript + Ant Design）
tests/scoring/           计分引擎测试
backend/tests/           后端接口与数据模型测试（需要 PostgreSQL）
frontend/e2e/            管理后台端到端测试（Playwright）
scripts/run_e2e.sh       端到端测试一键运行
```

## 本地启动

需要：Python 3.12+、Node.js 20+、PostgreSQL 14+。

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

   服务器上需要安装 ffmpeg（用 ffprobe 检查上传的视频）。

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

   演示数据取自 `docs/rubric.md` 的示例（少儿医疗险卖点卡、4 条异议、6 道题、红线词表草稿），正式使用前须由培训和合规替换。

4. 构建前端并启动：

   ```bash
   cd frontend && npm install && npm run build
   ```

   ```bash
   cd backend && APP_FRONTEND_DIST=../frontend/dist ../.venv/bin/uvicorn app.main:app --port 8000
   ```

   浏览器打开 http://127.0.0.1:8000 。接口文档在 http://127.0.0.1:8000/api/docs 。

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

前端类型检查：

```bash
cd frontend && npm run typecheck
```

## 角色与权限

| 角色 | 能做什么 |
|---|---|
| 管理员 | 维护评分标准、卖点卡、异议库、知识题库、朗读稿、抽题规则；生成题单；管理账号；查看审计日志 |
| 合规 | 维护红线词表和正确说法（只有合规能改） |
| HR | 查看全部内容（含原始视频）；登记候选人和书面同意、上传录像、标分段、标记录用状态 |
| 校准员 | 查看配置；给抽中的样本打金标准（里程碑 6） |
| 新主播 | 只看本人记录的全部内容（里程碑 5） |

完整矩阵见 `backend/app/security/rbac.py`。登录、账号变更、配置导入与发布、题单生成、查看审计日志都会写审计记录。

## 上传一条试镜录像

1. 管理员在“试镜题单”生成题单，打印**工作人员联**给录制时提问的人，**候选人联**（录制规则、流程、卖点卡，不含题目和分值）给候选人。
2. 候选人签署书面同意书，按题单在系统外连续录成一个视频文件。
3. HR 在“试镜录像 → 上传录像”：选候选人（没有就新建），登记书面同意（未登记不能上传），选题单、适用达标线、画面里有无贴片或 KT 板，选文件上传。上传中断后，打开这条录像重新选择同一文件即可续传。
4. 上传完成后边看视频边标出主体段、每道知识题、朗读段的起点，异议时间默认取题单，可按视频修正。保存后点“提交处理”。

## 修改评分配置

评分规则全部在 `config/rubric/rubric-v0.1.yaml`。改分值、免扣次数、封顶、档位表、达标线、临界范围、阈值，都只改配置，不改代码，也不用重跑模型。

1. 复制成新版本文件（例如 `rubric-v0.2.yaml`），修改 `version`。
2. 跑测试：`.venv/bin/python -m pytest tests`。配置不合法（档位表不连续、分值相加不等于满分、题数不对等）会在加载时报错，并说明原因。
3. 在管理后台“评分标准”页导入 YAML。页面会列出全部发布阻碍：带 `pending`（待确认）或 `calibration_required: true`（测试占位值）的节点。也可以在命令行查看：

   ```bash
   .venv/bin/python -c "from scoring import load_config, publish_blockers; print(*publish_blockers(load_config('config/rubric/rubric-v0.2.yaml')), sep='\n')"
   ```

   某项拍板后，修改对应规则、删除标记，并更新 `docs/decisions.md`。阻碍清空后才能发布；标为 published 但仍带标记的配置，导入时会被拒绝。草稿版本可以用来生成题单试用，报告会标注“非正式”。

卖点卡的必讲要点分值合计必须等于配置里产品讲解的要点满分（目前为 30），否则不能保存。

各计分类型的配置写法：

| 类型 | 用于 | 关键参数 |
|---|---|---|
| T1 逐次扣分 | P2、P8、P10、L3 | `per` 单次扣分，`free` 免扣次数，`normalize` 时长换算 |
| T2 逐次加分 | P9、S4、L2、L4、L5、O1、O2、O3 | `award` 或按类别的 `awards`，`cap` 封顶，`labels` 计分类别，`distinct_by_label` 同类只算一次 |
| T3+T4 | S2 | `checklist_max` 要点满分（分值取自卖点卡），`structure_levels` 结构等级，`error_penalty` 讲错扣分 |
| T4 分级锚定 | P1、P3、P5、P7、S1、L1、O4 | `parts[].levels` 等级；等级来源 `source`：`evidence` 检测器直接给、`metric` 指标分段、`count` 计次分段、`rules` 多指标规则；`modifiers` 封顶或降级；`boundary_flag` 边界标低置信 |
| T5 阈值 | P4 | `metric`、`limit`、`score_by_over` 超限段数 → 分数 |
| T6 逐题 | S3、O5 | `count` 题数；`levels` 按等级给分，或 `elements` 按要素给分加 `zero_labels` |

检测配置（P2 词表、抽帧率、提示词等）单独管理，改了需要重跑模型。这部分在里程碑 4 实现。

## P0 验收用例

PRD 第 6 节的 8 条用例。其中两条以系统内录制为前提，已按“上传录好的视频”（C18）改写。

| 用例 | 验证方式 | 状态 |
|---|---|---|
| 不同意授权时无法进入录制 → 改为：未登记候选人书面同意，不能上传和处理（C30） | `backend/tests/test_recordings_api.py::test_no_consent_no_upload`；端到端测试“未登记授权时先登记” | 已完成 |
| 4 条异议按配置时间点弹出 → 改为：题单的异议时间点（可按视频修正）与证据时间戳对得上（C29） | 时间换算已测（`test_segments_and_objection_alignment`：视频时间 = 主体段起点 + 相对时间）；与检测器证据的对齐测试在里程碑 4 | 部分完成 |
| 口头禅在转写中保留，未被顺滑删掉 | 测试检查请求带"关闭顺滑"参数；数据库约束已加（`transcripts.disfluency_removal` 必须为 false）；接真实供应商后用固定样本手动验证 | 约束已完成，其余在里程碑 4 |
| 人设塑造按 95 分满分正确折算 | `tests/scoring/test_dimensions_and_round.py::test_persona_scaled_from_95_with_props`、`::test_persona_no_props_p9_not_applicable_scaled_from_90` | 已完成 |
| 红线命中时结论为"不达标"，报告附原句 | 引擎与汇总：`test_redline_*`、`test_redline_any_round_not_recommend`；报告展示在里程碑 5 | 引擎已完成 |
| 临界样本自动重跑 3 次，报告标"临界"（共 3 轮，首轮参与投票；首轮已命中红线不追加） | 汇总规则：`tests/scoring/test_verdict.py`；流水线自动追加轮次在里程碑 4 | 规则已完成 |
| 报告里的标准版本、模型版本完整 | `test_traceability_fields`、`backend/tests/test_models.py::test_full_chain_and_evidence_round_trip` | 数据层已完成，报告页在里程碑 5 |
| 到期视频自动删除，报告保留 | 到期删除任务测试 | 里程碑 4 |

更换真实 AI 供应商的说明会在里程碑 4 补上。
