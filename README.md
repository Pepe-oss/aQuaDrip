# aQuaDrip

基于 QGIS + WNTR 的智能滴灌设计与水肥一体化分析平台。

An intelligent drip irrigation design & fertigation analysis platform built on QGIS + WNTR.

## 界面语言 / UI Language

插件内置**简体中文**与 **English** 双语界面(单一安装包):

- 默认跟随 QGIS 界面语言 / Follows the QGIS UI language by default
- 手动切换:QGIS 菜单 `插件 → aQuaDrip → 语言 Language`,选择后**重启 QGIS** 生效
- Switch manually via `Plugins → aQuaDrip → 语言 Language`, then restart QGIS

翻译源文件位于 `aquadrip-plugin/i18n/`(`.ts` 为源,`.qm` 为编译产物,二者均随插件分发)。更新翻译流程:

```bash
# 1. 重新提取字符串(改了 UI 文案后)
python -m PyQt5.pylupdate_main <插件 py 文件...> -ts aquadrip-plugin/i18n/aquadrip_en_US.ts
# 2. 编辑 .ts 中的 <translation>
# 3. 编译
lrelease aquadrip-plugin/i18n/aquadrip_en_US.ts
```

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
