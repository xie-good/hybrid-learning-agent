from __future__ import annotations

import re
import sys
from pathlib import Path


REQUIRED_SECTIONS = [
    "## 1. 引言",
    "## 2. 项目目标与范围",
    "## 3. 用户角色与使用场景",
    "## 4. 总体业务流程",
    "## 5. 功能需求",
    "## 6. 检索与生成规则",
    "## 7. 数据需求",
    "## 8. 接口需求",
    "## 9. 非功能需求",
    "## 10. 约束与假设",
    "## 11. 验收标准",
    "## 12. 测试与评估需求",
    "## 13. 风险与应对",
    "## 14. 交付物",
]


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in {"baseline", "modified"}:
        print("usage: validate_requirements.py <baseline|modified> <file>")
        return 2

    mode = sys.argv[1]
    path = Path(sys.argv[2])
    text = path.read_text(encoding="utf-8")

    section_count = sum(section in text for section in REQUIRED_SECTIONS)
    functional_count = len(set(re.findall(r"(?<!N)FR-[A-Z]+-\d{3}", text)))
    acceptance_count = len(set(re.findall(r"AC-\d{3}", text)))
    placeholders = sum(token in text for token in ("TODO", "待补充", "TBD", "BASELINE_TEMPLATE"))

    if mode == "baseline":
        ok = section_count == 0 and "BASELINE_TEMPLATE" in text
        print(
            f"BASELINE {'PASS' if ok else 'FAIL'}: "
            f"required_sections={section_count}, baseline_marker={str('BASELINE_TEMPLATE' in text).lower()}"
        )
        return 0 if ok else 1

    ok = (
        section_count == len(REQUIRED_SECTIONS)
        and functional_count >= 30
        and acceptance_count >= 12
        and placeholders == 0
        and text.startswith("# 基于混合检索增强生成的课程学习助手")
    )
    print(
        f"MODIFIED {'PASS' if ok else 'FAIL'}: "
        f"required_sections={section_count}/{len(REQUIRED_SECTIONS)}, "
        f"functional_requirements={functional_count}, "
        f"acceptance_criteria={acceptance_count}, placeholders={placeholders}"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
