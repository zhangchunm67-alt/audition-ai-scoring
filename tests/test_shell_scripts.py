"""部署脚本的静态检查：在 Mac 上用系统自带的 bash 3.2 运行时不能出错。"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = sorted(p for p in (ROOT / "scripts").rglob("*.sh"))

# macOS 自带的 bash 3.2 按字节判断变量名在哪结束，并把中文、全角标点的首字节（0xE3–0xEF）当成字母：
# “$DIR。”会被读成变量“DIR\xe3”，配合 set -u 报 unbound variable 后退出。变量后紧跟非 ASCII 字符时必须写成 ${DIR}。
BARE_VAR_THEN_NON_ASCII = re.compile(r"(?<!\\)\$[A-Za-z_][A-Za-z0-9_]*[^\x00-\x7f]")


def test_scripts_found():
    assert SCRIPTS


@pytest.mark.parametrize("path", SCRIPTS, ids=lambda p: str(p.relative_to(ROOT)))
def test_no_bare_variable_before_non_ascii(path):
    bad = []
    for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        for m in BARE_VAR_THEN_NON_ASCII.finditer(line):
            bad.append(f"{path.relative_to(ROOT)}:{no}: {m.group(0)}")
    assert not bad, "变量名后紧跟非 ASCII 字符，要写成 ${名字}：\n" + "\n".join(bad)
