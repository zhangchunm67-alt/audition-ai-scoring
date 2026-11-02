"""命令行工具。

  python -m app.cli create-user --username admin --role admin --display-name 管理员   # 密码从环境变量 NEW_USER_PASSWORD 或交互输入
  python -m app.cli seed-demo                                                          # 导入评分标准 v0.1 和一套演示数据

演示数据取自 docs/rubric.md 的示例，标明“演示”，正式使用前须由培训、合规审定替换。
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from scoring import config_hash, parse_config

from .db import get_engine
from .models.entities import DrawRule, Objection, Product, ProductCard, Question, ReadingScript, RedlineLexiconVersion, RubricVersion, User
from .security.passwords import hash_password
from .security.rbac import Role

ROOT = Path(__file__).resolve().parents[2]
RUBRIC_PATH = ROOT / "config" / "rubric" / "rubric-v0.1.yaml"

DEMO_CHECKLIST = [
    ("coverage", "保障范围", 5, False), ("deductible", "免赔额", 4, True), ("ratio", "报销比例", 3, False),
    ("waiting", "等待期", 4, True), ("health", "健康告知", 4, True), ("exclusion", "责任免除", 3, True),
    ("renewal", "续保条件", 4, False), ("price", "价格", 3, False),
]
DEMO_OBJECTIONS = [
    ("孩子有医保了，还需要买吗？", ["医保有报销范围和比例限制，医保外的部分要自己付"], ["能报医保外的自费部分（以条款为准）"], "先看看家里现有的保障，缺这块再补"),
    ("之前得过肺炎，还能买吗？", ["以健康告知为准，如实告知；有疑问走人工核保"], [], "先对照一下健康告知，符合再给孩子安排"),
    ("这么便宜，理赔会不会很难？", ["理赔按合同条款和流程办理"], ["承保公司正规"], "有疑问可以先看理赔流程说明"),
    ("为什么比别家贵？", ["客观对比条款差异，不诋毁同业"], [], "对照条款选适合自家的"),
]
DEMO_QUESTIONS = [
    ("什么是等待期？", ["合同生效后的一段时间（天数以条款为准）", "这段时间内因疾病出险，按合同约定不赔或有限赔付", "意外导致的一般不受等待期限制（以条款为准）"]),
    ("医疗险和重疾险有什么区别？", ["医疗险按实际花费报销，重疾险确诊约定疾病后一次性给付", "医疗险管医疗费用，重疾险可弥补收入损失和康复费用", "两者是互补关系"]),
    ("什么是免赔额？（演示题，待培训审定）", ["先自己承担的那部分费用，超过的部分才报销"]),
    ("什么是健康告知？（演示题，待培训审定）", ["投保前须如实回答的健康问题", "不如实告知可能影响理赔"]),
    ("什么是责任免除？（演示题，待培训审定）", ["合同约定不赔的情形"]),
    ("社保内和社保外有什么区别？（演示题，待培训审定）", ["社保目录内的费用和目录外的自费部分"]),
]
DEMO_REDLINES = {
    "R1": ("承诺收益或保本", ["稳赚不赔", "保本保息"], ["如实讲合同约定的给付"]),
    "R2": ("夸大保障、隐瞒重要条件", ["什么都能报", "100% 赔", "没有等待期"], ["按条款讲，并说明免赔额、等待期、责任免除"]),
    "R3": ("制造焦虑、恐吓营销", ["后悔一辈子", "出事你就"], ["用真实费用场景讲风险"]),
    "R4": ("限时、停售、涨价施压", ["最后", "明天停售", "马上涨价"], ["产品确有调整时，按公司统一口径说明"]),
    "R5": ("虚构背书、绝对化用语", ["国家推荐", "政府补贴", "全网第一", "最好的保险"], ["引用真实的承保公司、真实获奖信息"]),
    "R6": ("诋毁同业", ["都是坑", "理赔就是骗人"], ["客观对比条款差异"]),
    "R7": ("诱导不如实告知", ["随便填", "先买了再说"], ["提醒如实告知，有疑问走人工核保"]),
    "R8": ("引导私下联系", ["加我微信", "私下转账"], ["引导到官方投保页面或官方客服"]),
}


def create_user(db: Session, username: str, role: str, display_name: str, password: str) -> User:
    if db.scalar(select(User).where(User.username == username)):
        raise SystemExit(f"用户 {username} 已存在")
    u = User(username=username, role=Role(role).value, display_name=display_name, password_hash=hash_password(password))
    db.add(u)
    db.commit()
    return u


def seed_demo(db: Session) -> None:
    text = RUBRIC_PATH.read_text("utf-8")
    cfg = parse_config(yaml.safe_load(text))
    if not db.scalar(select(RubricVersion).where(RubricVersion.version == cfg.version)):
        db.add(RubricVersion(version=cfg.version, status="draft", yaml_text=text, config_hash=config_hash(cfg)))
    if db.scalar(select(Product).where(Product.code == "demo-kids-medical")):
        db.commit()
        print("演示产品已存在，跳过")
        return
    p = Product(code="demo-kids-medical", name="少儿医疗险（演示）")
    db.add(p)
    db.flush()
    db.add(ProductCard(product_id=p.id, version=1, status="published", content={
        "checklist": [{"id": i, "name": n, "points": pts, "compliance_required": c} for i, n, pts, c in DEMO_CHECKLIST],
        "targeted_points": ["儿童医院可以用", "门急诊不限次数", "雾化可以报"],
        "scenarios": ["带孩子去缴费，不用盯着收费员看哪些是医保内、哪些是医保外"],
        "glossary": [{"term": t, "plain": pl} for t, pl in [("免赔额", "先自己掏的那部分钱，超过的才给报"), ("等待期", "合同生效后的一段观察期")]],
        "key_numbers": [], "banned_phrases": ["什么都能报", "稳赚不赔"],
    }))
    for text_, pts, adv, closing in DEMO_OBJECTIONS:
        db.add(Objection(product_id=p.id, text=text_, answer_points=pts, advantages=adv, closing=closing))
    for text_, pts in DEMO_QUESTIONS:
        db.add(Question(product_id=p.id, text=text_, full_points=pts))
    db.add(DrawRule(product_id=p.id, objection_times_ms=[240_000, 330_000, 420_000, 480_000]))
    db.add(ReadingScript(title="演示朗读稿（待培训提供正式稿）", text="各位家长大家好，今天和大家聊一聊孩子看病的费用问题。" * 8))
    if not db.scalar(select(RedlineLexiconVersion)):
        db.add(RedlineLexiconVersion(version="lexicon-demo-1", status="draft", content={
            k: {"name": n, "keywords": kw, "examples": kw, "not_redline": [], "correct": c} for k, (n, kw, c) in DEMO_REDLINES.items()
        }))
    db.commit()
    print("已导入评分标准 v0.1（草稿）和演示产品、卖点卡、异议、知识题、抽题规则、朗读稿、红线词表（草稿）")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    cu = sub.add_parser("create-user")
    cu.add_argument("--username", required=True)
    cu.add_argument("--role", required=True, choices=[r.value for r in Role])
    cu.add_argument("--display-name", required=True)
    sub.add_parser("seed-demo")
    args = ap.parse_args(argv)
    with Session(get_engine()) as db:
        if args.cmd == "create-user":
            pw = os.environ.get("NEW_USER_PASSWORD") or getpass.getpass("密码（至少 10 位）：")
            u = create_user(db, args.username, args.role, args.display_name, pw)
            print(f"已创建 {u.username}（{u.role}）")
        else:
            seed_demo(db)


if __name__ == "__main__":
    sys.exit(main())
