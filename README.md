# 主播试镜 AI 评分系统

候选人按录制规则录好约 17 分钟的试镜视频，员工上传到系统，系统按《主播评分标准 · 机器可执行版》自动打分、出报告，供 HR 做录用参考。

- 需求：[`docs/prd.md`](docs/prd.md)
- 评分标准：[`docs/rubric.md`](docs/rubric.md)
- 原始评分表：[`docs/source/主播评分标准-20241025.xls`](docs/source/)
- 冲突、决定、待确认项：[`docs/decisions.md`](docs/decisions.md)

## 当前进度

| 里程碑 | 内容 | 状态 |
|---|---|---|
| 1 | 计分引擎、23 条计分配置、配置校验与发布检查、数据模型与迁移、单元测试 | 已完成 |
| 2 | 平台底座（登录、权限、审计、加密）和配置后台 M1 | 未开始 |
| 3 | 视频上传与录制规则（取代原候选人录制端 M2，见 decisions.md C18） | 未开始 |
| 4 | AI 处理流水线 M3 和自动判定 M4（先用 Mock） | 未开始 |
| 5 | 报告 M5 | 未开始 |
| 6 | 校准与看板 M6 | 未开始 |

## 目录

```
scoring/                 计分引擎（纯函数，不依赖数据库、网络或 AI）
  config.py              计分配置模型、加载、校验、发布检查
  engine.py              一轮计分：证据 + 配置 + 上下文 → 条目分、维度分、档位、总档位、红线、低置信、缺失证据
  verdict.py             多轮汇总：临界三轮、多数结论、展示轮、结论标签与原因
  ranking.py             批次排名
  types.py               证据结构（rubric 第 9 节）与结果类型
config/rubric/           计分配置（YAML）
backend/app/models/      数据模型（SQLAlchemy）
backend/migrations/      数据库迁移（Alembic）
tests/scoring/           计分引擎测试
backend/tests/           数据模型测试（需要 PostgreSQL）
```

## 本地运行测试

需要 Python 3.12 或更高版本。

```bash
python3 -m venv .venv
```

```bash
.venv/bin/pip install -e ".[dev]"
```

只跑计分引擎测试（不需要数据库）：

```bash
.venv/bin/python -m pytest tests
```

连同数据模型测试一起跑，需要一个**可以清空的** PostgreSQL 库：

```bash
TEST_DATABASE_URL=postgresql+psycopg://audition:audition@localhost/audition_test .venv/bin/python -m pytest
```

对数据库执行迁移：

```bash
cd backend && DATABASE_URL=postgresql+psycopg://user:pass@host/db ../.venv/bin/alembic upgrade head
```

## 修改评分配置

评分规则全部在 `config/rubric/rubric-v0.1.yaml`。改分值、免扣次数、封顶、档位表、达标线、临界范围、阈值，都只改这个文件，不改代码，也不用重跑模型。

1. 复制成新版本文件（例如 `rubric-v0.2.yaml`），修改 `version`。
2. 跑测试：`.venv/bin/python -m pytest tests`。配置不合法（档位表不连续、分值相加不等于满分、题数不对等）会在加载时报错，并说明原因。
3. 查看发布阻碍：

   ```bash
   .venv/bin/python -c "from scoring import load_config, publish_blockers; print(*publish_blockers(load_config('config/rubric/rubric-v0.2.yaml')), sep='\n')"
   ```

   带 `pending`（待确认）或 `calibration_required: true`（测试占位值）的节点都会列出来。某项拍板后，修改对应规则并删除标记，同时更新 `docs/decisions.md`。列表清空后才能把 `status` 改成 `published`；标为 published 但仍带标记的配置，加载时会被拒绝。

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

| 用例（PRD 第 6 节） | 验证方式 | 状态 |
|---|---|---|
| 不同意授权时无法进入录制 → 改为：未登记候选人授权不能上传和处理（待 P-UP-CONSENT） | 接口测试 | 里程碑 3 |
| 4 条异议按配置时间点弹出 → 改为：登记的异议时间点与证据时间戳对得上（待 P-UP-OBJ） | 后端对齐测试 | 里程碑 3–4 |
| 口头禅在转写中保留，未被顺滑删掉 | 测试检查请求带"关闭顺滑"参数；数据库约束已加（`transcripts.disfluency_removal` 必须为 false）；接真实供应商后用固定样本手动验证 | 约束已完成，其余在里程碑 4 |
| 人设塑造按 95 分满分正确折算 | `tests/scoring/test_dimensions_and_round.py::test_persona_scaled_from_95_studio`、`::test_persona_home_p9_not_applicable_scaled_from_90` | 已完成 |
| 红线命中时结论为"不达标"，报告附原句 | 引擎与汇总：`test_redline_*`、`test_redline_any_round_not_recommend`；报告展示在里程碑 5 | 引擎已完成 |
| 临界样本自动重跑 3 次，报告标"临界"（共 3 轮，首轮参与投票；首轮已命中红线不追加） | 汇总规则：`tests/scoring/test_verdict.py`；流水线自动追加轮次在里程碑 4 | 规则已完成 |
| 报告里的标准版本、模型版本完整 | `test_traceability_fields`、`backend/tests/test_models.py::test_full_chain_and_evidence_round_trip` | 数据层已完成，报告页在里程碑 5 |
| 到期视频自动删除，报告保留 | 到期删除任务测试 | 里程碑 4 |

启动方式和更换真实 AI 供应商的说明会在后续里程碑补上。
