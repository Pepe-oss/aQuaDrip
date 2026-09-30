#!/usr/bin/env bash
# 运行 aQuaDrip 插件全部 headless 测试。
#
# macOS :自动定位 QGIS.app 自带 Python(需要 PYTHONHOME 覆盖层定位 stdlib)
# Linux :用系统 python3(qgis 需可在 PYTHONPATH 中导入,如 /usr/share/qgis/python)
# 环境变量:
#   QGIS_PYTHON   指定 QGIS Python 解释器(优先于自动探测)
#   QGIS_PREFIX_PATH  QGIS 安装前缀(默认按 macOS 路径)
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"

PY_PLAIN="${PYTHON:-python3}"

if [ -n "${QGIS_PYTHON:-}" ]; then
  PY="$QGIS_PYTHON"
elif [ -x "/Applications/QGIS.app/Contents/MacOS/python3.12" ]; then
  PY="/Applications/QGIS.app/Contents/MacOS/python3.12"
else
  PY="$PY_PLAIN"
fi

# macOS QGIS 自带解释器需要 PYTHONHOME 覆盖层(其 stdlib 在 Resources 下);
# 注意:必须先跑完纯 stdlib 测试再设置——系统 python3 加载 3.12 stdlib 会崩
rc=0
echo "== 纯 stdlib 测试($PY_PLAIN) =="
"$PY_PLAIN" "$HERE/test_sim_history.py" || rc=1

if [ "$PY" = "/Applications/QGIS.app/Contents/MacOS/python3.12" ]; then
  ROOT="$(mktemp -d)"
  mkdir -p "$ROOT/lib"
  ln -s "/Applications/QGIS.app/Contents/Resources/python3.12" "$ROOT/lib/python3.12"
  export PYTHONHOME="$ROOT"
  trap 'rm -rf "$ROOT"' EXIT
fi

echo "== QGIS headless 测试($PY) =="
for t in test_trim_units test_manual_lateral test_export_nodes test_zone_group test_save_as; do
  echo "-- $t"
  "$PY" "$HERE/$t.py" || rc=1
done

if [ $rc -eq 0 ]; then
  echo "== ALL PASSED =="
else
  echo "== FAILED =="
fi
exit $rc
