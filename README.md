# aQuaDrip

**中文 | [English](README_EN.md)**

基于 QGIS + WNTR 的智能滴灌设计与水肥一体化分析平台。

An intelligent drip irrigation design & fertigation analysis platform built on QGIS + WNTR.

## 安装 / Installation

### 前置要求 / Requirements

| 依赖 | 说明 |
|---|---|
| QGIS ≥ 3.28 | LTR 或更新版本 / LTR or newer |
| Python 依赖 `wntr` | 水力模拟引擎 / hydraulic engine(QGIS 自带 numpy/pandas,只需补装 wntr) |

### 方式一:ZIP 安装(推荐普通用户)/ Install from ZIP

1. **下载**:从 GitHub `Releases` 页面下载最新的 `aquadrip-<版本>.zip`
   (ZIP 内已包含核心库 wdrip 与中英翻译文件,无需额外下载)
2. **安装**:QGIS 菜单 `插件 → 管理并安装插件 → 从 ZIP 安装`,
   选择下载的 zip → `安装插件`
3. **补装模拟依赖**:在 QGIS 自带的 Python 环境中安装 wntr——

   | 平台 | 命令 |
   |---|---|
   | macOS | `/Applications/QGIS.app/Contents/MacOS/bin/python3 -m pip install wntr` |
   | Windows(OSGeo4W Shell) | `python-o4w -m pip install wntr` |
   | Linux | `python3 -m pip install wntr --user`(用 QGIS 使用的解释器) |

4. **启用**:插件管理器中勾选 `aQuaDrip`,顶部工具栏出现 aQuaDrip 按钮即安装成功

> 未安装 wntr 时插件仍可加载,但「运行模拟」等功能会提示缺依赖。

### 方式二:源码部署(推荐开发者)/ From source

```bash
git clone https://github.com/Pepe-oss/aQuaDrip.git
```

将仓库中的 `aquadrip-plugin` 目录**软链接**到 QGIS 插件目录
(插件会自动识别同仓库的 `wdrip-core`,且代码改动重启 QGIS 即生效):

| 平台 | QGIS 插件目录(默认 profile) |
|---|---|
| macOS | `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins` |
| Windows | `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins` |
| Linux | `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins` |

```bash
# macOS 示例
ln -s "$(pwd)/aquadrip-plugin" \
  "$HOME/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/aquadrip"
```

wntr 依赖同样按方式一第 3 步安装。

### 打包新版本 ZIP / Build a release ZIP

维护者从仓库根目录执行(输出到 `dist/`):

```bash
python scripts/make_zip.py
```

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
