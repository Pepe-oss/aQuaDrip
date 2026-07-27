# aQuaDrip

基于 QGIS + WNTR 的智能滴灌设计与水肥一体化分析平台。

## 项目结构

```
aQuaDrip/
├── wdrip-core/          # 核心 Python 库（可独立于 QGIS 使用）
│   ├── wdrip/
│   │   ├── network/     # 数据模型
│   │   ├── topology/    # 拓扑引擎
│   │   ├── builder/     # 管网构建器
│   │   ├── equipment/   # 设备系统
│   │   ├── simulation/  # WNTR 模拟封装
│   │   ├── analysis/    # 结果分析
│   │   ├── io/          # 数据导入导出
│   │   ├── emitter_db/  # 滴头参数库
│   │   ├── optimizer/   # 优化器（V3+）
│   │   └── settings/    # 配置管理
│   └── setup.py
├── aquadrip-plugin/     # QGIS 插件
├── docs/                # 文档
└── examples/            # 示例数据
```

## 开发状态

- 版本：0.1.0.dev — 项目骨架搭建中
- 详细规划见：`DEVELOPMENT_PLAN.md`
