"""主播试镜计分引擎：证据 + 配置 → 分数、档位、结论。不依赖数据库、网络或任何 AI。"""
from .config import ConfigError, RubricConfig, config_hash, ensure_publishable, load_config, parse_config, publish_blockers
from .engine import EvidenceError, ScoringInputError, round_half_up, score_round
from .ranking import RankEntry, rank
from .types import ChecklistPoint, Evidence, FinalVerdict, RoundResult, ScoringContext
from .verdict import VerdictError, finalize, rounds_required

__all__ = [
    "ChecklistPoint",
    "ConfigError",
    "Evidence",
    "EvidenceError",
    "FinalVerdict",
    "RankEntry",
    "RoundResult",
    "RubricConfig",
    "ScoringContext",
    "ScoringInputError",
    "VerdictError",
    "config_hash",
    "ensure_publishable",
    "finalize",
    "load_config",
    "parse_config",
    "publish_blockers",
    "rank",
    "round_half_up",
    "rounds_required",
    "score_round",
]
