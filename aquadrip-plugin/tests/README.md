# 插件 headless 测试

不启动 QGIS GUI 的自动化测试,覆盖近期修复过的关键回归:

| 测试 | 覆盖 |
|---|---|
| `test_sim_history.py` | 历史记录 v2 分片存储:add/summaries/latest/容量裁剪/v1 流式迁移/损坏容错/索引自愈/追加合并/大记录性能(纯 stdlib,任意 python3) |
| `test_trim_units.py` | 切割工具米制换算:度/米混用、650m 长管比例阈值回归、折线各向异性、端部点击、cut=0 仅分割 |
| `test_manual_lateral.py` | 手动放置毛管:无效几何 makeValid、断续行多段返回与按点击选段、min_len 单位换算 |
| `test_zone_group.py` | 分区:单阀细分/手动标签/多阀合并/按流量编组/轮灌分组联动/反向画线回归 |
| `test_save_as.py` | 项目另存为:WAL 安全复制、历史随迁、图层重指(含重复图层)、同路径与无项目边界 |
| `test_export_nodes.py` | 节点矢量导出:三格式字段值、NULL 语义与 is_emitter、CRS 兜底 |

## 运行

```bash
bash run_all.sh
```

- **macOS**:自动使用 QGIS.app 自带 Python(含 PYTHONHOME 覆盖层处理);
- **Linux**:`qgis` 需可被系统 python3 导入(如 `export PYTHONPATH=/usr/share/qgis/python`);
- **Windows**:在 OSGeo4W Shell 中逐个运行 `python test_xxx.py`(qgis 已在路径中);
- 可用 `QGIS_PYTHON`/`QGIS_PREFIX_PATH` 环境变量覆盖探测。

核心库(wdrip-core)的 pytest 单元测试见 `wdrip-core/tests/`,
引擎基准(论文引用数字的复现脚本)见 `wdrip-core/benchmarks/`。
