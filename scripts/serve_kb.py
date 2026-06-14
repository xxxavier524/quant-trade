#!/usr/bin/env python3
"""知识库静态站本地服务 — 读 PORT 环境变量（兼容 preview autoPort）。

用法：
    PORT=8767 python3 scripts/serve_kb.py
    PORT=0    python3 scripts/serve_kb.py    # 系统自动分配
"""

import os
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SITE_DIR = PROJECT_ROOT / "docs" / "knowledge_site"


def main():
    if not SITE_DIR.exists():
        sys.exit(f"站点目录不存在: {SITE_DIR}")
    os.chdir(SITE_DIR)
    port = int(os.environ.get("PORT", 8767))
    server = HTTPServer(("0.0.0.0", port), SimpleHTTPRequestHandler)
    actual = server.server_address[1]
    print(f"知识库站点 http://localhost:{actual}/ (serving {SITE_DIR})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
