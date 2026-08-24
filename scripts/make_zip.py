# -*- coding: utf-8 -*-
"""make_zip — 打包 aQuaDrip QGIS 插件为可安装的单一 ZIP

产物结构(QGIS「从 ZIP 安装」兼容,顶层即插件文件夹):

    aquadrip/
    ├── metadata.txt / __init__.py / aquadrip_plugin.py / icon.svg
    ├── icons/  i18n/  (含编译好的 .qm)
    ├── tools/  ui/
    └── wdrip/          ← wdrip-core 核心库随包分发,免同级依赖

用法:
    python scripts/make_zip.py            # 输出 dist/aquadrip-<版本>.zip
    python scripts/make_zip.py -o out.zip
"""

import argparse
import os
import re
import shutil
import sys
import tempfile
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(REPO, "aquadrip-plugin")
CORE = os.path.join(REPO, "wdrip-core")

EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", "help", "geo_utils",
                "processing", "test"}          # 空脚手架/开发资源不分发
EXCLUDE_SUFFIX = (".pyc", ".pyo", ".DS_Store")


def plugin_version() -> str:
    meta = open(os.path.join(PLUGIN, "metadata.txt"), encoding="utf-8").read()
    m = re.search(r"^version\s*=\s*(.+)$", meta, re.M)
    return m.group(1).strip() if m else "0.0.0"


def copy_tree(src: str, dst: str, exclude_dirs=None):
    exclude_dirs = exclude_dirs or set()
    shutil.copytree(
        src, dst,
        ignore=shutil.ignore_patterns(
            *[d for d in exclude_dirs] + [f"*{s}" for s in EXCLUDE_SUFFIX]),
        dirs_exist_ok=True)


def build(staging: str):
    # 1. 插件本体
    copy_tree(PLUGIN, staging, EXCLUDE_DIRS)

    # 2. wdrip 核心库(仅 wdrip 包,不带 tests/临时文件)
    copy_tree(os.path.join(CORE, "wdrip"), os.path.join(staging, "wdrip"))

    # 3. 结构自检
    must_exist = [
        os.path.join(staging, "metadata.txt"),
        os.path.join(staging, "__init__.py"),
        os.path.join(staging, "wdrip", "network", "network.py"),
        os.path.join(staging, "wdrip", "simulation", "__init__.py"),
        os.path.join(staging, "i18n", "aquadrip_en_US.qm"),
    ]
    missing = [p for p in must_exist if not os.path.isfile(p)]
    if missing:
        raise RuntimeError("打包不完整,缺失: " + "; ".join(missing))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output",
                    default=os.path.join(REPO, "dist",
                                         f"aquadrip-{plugin_version()}.zip"))
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        staging = os.path.join(tmp, "aquadrip")
        build(staging)

        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        if os.path.exists(args.output):
            os.remove(args.output)
        with zipfile.ZipFile(args.output, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(staging):
                dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
                for fn in files:
                    if fn.endswith(EXCLUDE_SUFFIX):
                        continue
                    full = os.path.join(root, fn)
                    rel = os.path.join("aquadrip",
                                       os.path.relpath(full, staging))
                    zf.write(full, rel)

    n = len(zipfile.ZipFile(args.output).namelist())
    size_kb = os.path.getsize(args.output) // 1024
    print(f"OK {args.output}  ({n} files, {size_kb} KB)")


if __name__ == "__main__":
    sys.exit(main())
