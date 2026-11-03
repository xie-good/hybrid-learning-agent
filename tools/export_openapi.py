"""从生产路由导出可版本管理的机器接口文档，不启动服务或读写业务数据。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.main import create_app


def main():
    output = ROOT / 'docs/openapi.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    spec = create_app().openapi()
    output.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    reopened = json.loads(output.read_text('utf-8'))
    operations = sum(method in {'get', 'post', 'delete'} for methods in reopened['paths'].values() for method in methods)
    print(f'OPENAPI PASS: paths={len(reopened["paths"])}, operations={operations}, version={reopened["info"]["version"]}')


if __name__ == '__main__':
    main()
