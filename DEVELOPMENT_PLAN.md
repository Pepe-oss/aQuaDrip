# aQuaDrip 开发规划文档

> 基于 QGIS + WNTR 的智能滴灌设计与水肥一体化分析平台  
> 版本：v0.3-draft  
> 日期：2025-07-02

---

## 目录

1. [项目概述](#1-项目概述)
2. [背景调研](#2-背景调研)
3. [需求分析](#3-需求分析)
4. [系统架构](#4-系统架构)
5. [设计哲学](#5-设计哲学)
6. [数据模型设计](#6-数据模型设计)
7. [自动管网布局算法](#7-自动管网布局算法)
8. [分阶段实施计划](#8-分阶段实施计划)
9. [技术栈与依赖](#9-技术栈与依赖)
10. [界面原型设计](#10-界面原型设计)
11. [测试策略](#11-测试策略)
12. [发布与维护](#12-发布与维护)
13. [风险与缓解](#13-风险与缓解)
14. [架构评审与后续改进建议](#14-架构评审与后续改进建议)

---

## 1. 项目概述

### 1.1 项目背景

滴灌（Drip Irrigation）是一种高效节水灌溉方式，其管网系统由干管（Mainline）、支管（Submain）、毛管（Lateral）和滴头（Emitter/Dripper）组成。设计一个高效、均匀的滴灌系统涉及水力计算、地形适应和农艺参数匹配等多方面因素。

现代农业对**水肥一体化（Fertigation）**的需求日益增长，即通过滴灌系统同步施用肥料，这需要在水力模拟基础上进一步进行水质/溶质运移模拟。

**WNTR**（Water Network Tool for Resilience）是美国环保署（EPA）开发的开源 Python 包，基于 EPANET 引擎，提供管网水力模拟、水质分析和韧性评估能力。WNTR 已有滴灌模拟的研究案例，但其通用 API 需要用户手动构建每个节点和管道，流程繁琐。

**当前工作区已有三个参考项目：**

| 项目 | 类型 | 可借鉴内容 |
|------|------|-----------|
| QEPANET | QGIS 3.x 插件 | dockwidget 模式、地图交互工具、结果可视化 |
| GHydraulics | QGIS 2.x 插件 | INP 读写、模型检查、结果回读 |
| qgis-epanet | Processing 框架 | 算法注册、参数定义 |

这些项目均面向**通用供水管网**，缺乏针对**滴灌场景**的自动化构建能力。

### 1.2 项目定位

**aQuaDrip** 定位为：

> **基于 QGIS + WNTR 的智能滴灌设计与水肥一体化分析平台（Intelligent Drip Irrigation Design and Fertigation Analysis Platform）**

- **QGIS** 为交互平台
- **WNTR** 为计算引擎（仅作为 Solver）
- **wdrip-core** 为核心算法库

### 1.3 项目目标

开发 **aQuaDrip**，一个两层架构的完整解决方案：

1. **wdrip-core**（Python 库）：封装 WNTR，提供滴灌管网专用的数据模型、布局算法、拓扑引擎、模拟封装、分析优化工具。可独立于 QGIS 使用，支持 Jupyter Notebook 工作流。
2. **aQuaDrip 插件**（QGIS 插件）：提供图形化界面，允许用户结合地理数据快速构建真实农田滴灌管网，支持自动生成与手动绘制混合工作流。

### 1.4 目标用户

- **灌溉设计师**：需要快速设计或改造现有农田滴灌系统，进行水力验证
- **农业工程师**：评估不同灌溉方案（含施肥）的均匀度和效率
- **研究人员**：进行滴灌管网的模拟实验、参数优化和算法研究
- **QGIS 用户**：已有农场地块 GIS 数据，需要集成灌溉分析

### 1.5 核心创新点

| 维度 | 通用 EPANET 插件 | aQuaDrip |
|------|------------------|-----------|
| **建网方式** | 全手动逐个添加 | **农艺参数自动生成 + 手动绘制混合** |
| **管网结构** | 平面节点-管道 | **层级拓扑**（干管→支管→毛管→滴头） |
| **发射器** | 手动设 Emitter 系数 | **内置滴头参数库**，选型即用 |
| **结果分析** | 水头/流量 | **CU/DU 均匀度**、流量分布、灌溉指标 |
| **地形适配** | 手动输入高程 | **DEM 自动提取**，坡度分析 |
| **灌溉制度** | 时变模式手动定义 | **轮灌分组**，间歇灌溉预设 |
| **设备系统** | 无集成 | **泵/阀/过滤器/施肥罐/传感器**一体化 |
| **水肥模拟** | 无 | **WNTR 水质模拟**实现肥液运移分析 |
| **布局算法** | 无 | **规则/不规则/等高线/骨架/MST/最短路**多种策略 |
| **优化能力** | 无 | **多目标优化**（成本-压力-均匀度） |

---

## 2. 背景调研

### 2.1 WNTR 能力分析

WNTR（v2.x）提供的关键功能：

- **WaterNetworkModel**：管网模型定义
  - **节点**：`Junction`, `Reservoir`, `Tank`
  - **Link（管道类）**：`Pipe`, `Pump`, `Valve`
- **Hydraulic Simulation**：稳态和延时段水力模拟
- **Emitter 支持**：`Node.emitter_coefficient` 和 `Node.emitter_exponent`（用于滴头）
- **Pressure-Demand 模型**：支持压力依赖型用水（PDD）
- **Water Quality Simulation**：水质/溶质运移模拟（可用于肥液扩散分析）
- **结果访问**：`node['pressure']`、`link['flow']`、`node['demand']`、`node['quality']` 等
- **Change 接口**：批量修改属性，支持场景对比

**关键概念澄清：WNTR/EPANET 中 Pump 和 Valve 均为 Link（管道类）**，连接两个节点，而非节点本身。这与工程直觉一致：水泵和阀门都是安装在管道上的设备。

**WNTR 在滴灌场景的不足：**
- 无滴头组件抽象，需手动为每个节点设 emitter 参数
- 无层级管网（干/支/毛管）概念
- 无均匀度指标直接计算
- 无地理坐标到管网坐标的映射
- 无灌溉设备和施肥系统的领域抽象

### 2.2 滴灌管网建模要点

**物理模型：**
- 滴头出水公式：$q = K \cdot H^x$
  - $q$：滴头流量（L/h）
  - $K$：流量系数
  - $H$：工作水头（m）
  - $x$：流态指数（x=0.5 全紊流，x=1.0 层流，PC滴头 x≈0）
- 压力补偿式（PC）滴头：$x \approx 0$，流量基本不随压力变化
- 非压力补偿式（Non-PC）滴头：$x \approx 0.5$，流量随压力变化

**均匀度指标：**
- **CU**（Christiansen Uniformity）：$CU = 100\left(1 - \frac{\sum|q_i-\bar{q}|}{n\bar{q}}\right)$
- **DU**（Lower Quarter Distribution Uniformity）：$DU = \frac{\bar{q}_{lq}}{\bar{q}} \times 100\%$
- **EU**（Emission Uniformity）：考虑最小压力的 EU 计算

**地形影响：**
- 坡度影响压力分布 → 影响滴头流量均匀度
- 陡坡需要压力调节（PRV 阀、压力补偿滴头）
- DEM 精度建议 ≤5m，平坦地区可放宽

---

## 3. 需求分析

### 3.1 功能需求

#### F1: 农田定义
- F1.1 在地图上绘制农田多边形边界
- F1.2 导入已有地块 Shapefile / GeoPackage
- F1.3 输入农田属性：面积、作物类型、种植行向等

#### F2: 管网构建（自动 + 手动混合）
- **自动生成**
  - F2.1 毛管自动生成，支持多种耕作模式：
    - **等行距模式**：输入行距、滴头间距、毛管间距
    - **宽窄行模式**：输入行距序列（如[0.3, 0.15, 0.3, 0.15...]）
    - **自定义行距模式**：用户逐行指定位置
    - **垄数模式**：输入垄数，系统自动计算毛管位置
  - F2.2 不规则地块弹性和适配生成
  - F2.3 沿等高线布局（适用于坡地）
  - F2.4 自动拓扑检查与修复
- **手动绘制**
  - F2.5 手动绘制干管（作为 LineString 图层）
  - F2.6 手动绘制支管（连接干管与毛管区）
  - F2.7 手动添加水泵（绘制为 Link，连接两个节点）
  - F2.8 手动添加阀门（绘制为 Link，连接两个节点）
  - F2.9 手动添加节点/水源/出水口/其他设备
  - F2.10 移动/删除/编辑已有组件
- **混合模式**
  - F2.11 毛管自动生成 + 干管手动绘制 + **支管自动交叉连接**（支管与毛管相交处自动生成节点）
  - F2.12 现有管网导入后的编辑与扩展
- **毛管管理（灌溉分区）**
  - F2.13 毛管生成后，根据毛管对地块进行灌溉分区划分
  - F2.14 删除整根毛管（移除不需要灌溉的行）
  - F2.15 **按垄数调整：指定垄数后自动调整毛管数量**
  - F2.16 截断毛管（从指定位置切断，仅保留部分区段）
  - F2.17 合并/拆分灌溉分区
  - F2.18 分区命名与染色（不同颜色显示不同分区）

#### F3: 滴头与管道选型
- F3.1 内置滴头参数库（品牌型号、K/x 值、工作压力范围、推荐流量）
- F3.2 支持自定义滴头参数
- F3.3 管道选型：PVC/PE 管、管径、壁厚、C 值/HW 系数
- F3.4 按流量自动推荐管径
- **F3.5 耕作模式与种植参数**
  - 耕作模式：等行距 / 宽窄行 / 自定义
  - 行距序列：如等行距0.3m，或宽窄行[0.3, 0.15]
  - 垄数（ridge count）：用户直接指定垄数代替行距
  - 种植方向：角度或沿等高线

#### F4: 地形集成
- F4.1 从 DEM 栅格自动提取节点高程
- F4.2 管段坡度计算
- F4.3 压力分区建议（陡坡区域）
- F4.4 自动推荐 PRV 减压阀位置

#### F5: 水源与灌溉制度
- F5.1 水源定义
  - 蓄水池/机井/河流等自然水源：位置、可用流量、扬程
  - **出水口（Outlet）**：从地下主管道引到地面的出水点，作为水源的特殊类型
- **F5.2 轮灌分区（通过阀门控制）**
  - 在管网中布设分区阀门
  - 为每个阀门分配 ID 和所属轮灌组
  - 不同阀门在不同时段开启，实现分区灌溉
- **F5.3 阀门时间表配置**
  - 用户为每个阀门设置开启时段，例如：
    - 阀门1：`0~0.5h` 开启
    - 阀门2：`0.5~1h` 开启
    - 阀门3：`1~1.5h` 开启
    - 阀门4：`1.5~2h` 开启
  - 在 WNTR 中通过 Valve.status + TimePattern 实现
- F5.4 灌溉制度：灌水时长、频率、起止时间
- F5.5 间歇灌溉支持

#### F6: 设备系统
- **F6.1 水源设备（Source）**
  - 机井（Well）：位置、静水位、动水位、出水量
  - 蓄水池（Reservoir）：库容、水位、补水方式
  - 河渠（Canal）：取水点、可用流量
  - **出水口（Outlet）**：从地下主管道引到地面的出水点（位置受硬件限制，需手动绘制）
- **F6.2 水泵设备（Pumping）**
  - 离心泵/潜水泵：扬程、流量、效率、功率、运行曲线
  - 变频器（VFD）：变频控制、节能计算
  - **WNTR 映射**：作为 Link（Pump）
- **F6.3 过滤设备（Filtration）**
  - 砂石过滤器（Sand Filter）
  - 筛网过滤器（Screen Filter）
  - 叠片过滤器（Disc Filter）
  - 参数：过滤精度、额定流量、压损曲线
  - **WNTR 映射**：简化为 Pipe + 局部水头损失
- **F6.4 施肥设备（Fertigation）**
  - 施肥罐（Fertilizer Tank）：容积、浓度
  - 注肥泵（Injector）：注入速率、工作压力
  - **WNTR 映射**：Junction + 水质初始条件
- **F6.5 控制设备（Control）**
  - 手动阀（Gate/Ball Valve）
  - 减压阀（PRV）
  - 电磁阀（Solenoid Valve）
  - 流量控制阀（FCV）、持压阀（PSV）
  - **WNTR 映射**：作为 Link（Valve）
- **F6.6 传感器（Sensor）**
  - 压力传感器（Pressure）
  - 流量计（Flow Meter）
  - EC 传感器
  - pH 传感器
  - **WNTR 映射**：监测点，不参与水力计算

#### F7: 模拟运行
- F7.1 一键运行 WNTR 水力模拟（稳态 + 延时）
- F7.2 WNTR 水质模拟（肥液浓度变化追踪）
- F7.3 运行进度显示
- F7.4 运行日志输出
- F7.5 错误检测与友好的错误提示

#### F8: 结果分析
- F8.1 节点压力分布图（热力图）
- F8.2 管段流速/流量分布图
- F8.3 滴头流量分布散点图/直方图
- F8.4 CU/DU/EU 均匀度报告
- F8.5 压力-流量关系曲线
- F8.6 水肥浓度时空变化图（基于水质模拟结果）
- F8.7 不同轮灌组浓度差异分析
- F8.8 结果导出（CSV、GeoJSON、PDF 报告）

#### F9: 项目管理
- F9.1 保存/加载项目（.aqd 工程文件，含版本号）
- F9.2 导出/导入管网配置（JSON）
- F9.3 导出 EPANET INP 文件（兼容 EPANET 2.2）

#### F10: Processing 集成
- F10.1 注册为 QGIS Processing Provider
- F10.2 提供独立算法供模型构建器使用
- F10.3 支持批处理多个地块

#### F11: 拓扑验证
- F11.1 自动检测孤立节点、重复节点、死管
- F11.2 环路检测
- F11.3 水源连接性验证
- F11.4 设备配置一致性检查

#### F12: 模型验证与校准（Model Calibration）
- F12.1 选择观测节点：手动在管网中选择关键节点作为观测点
- F12.2 输入实测值：为每个观测节点输入实测压力/流量值
- F12.3 模拟值与实测值对比：自动计算偏差（绝对/相对误差）
- F12.4 参数校准
  - 管道糙率系数（C值）自动校正
  - 滴头 K/x 值校正
  - 局部水头损失系数校正
- F12.5 校准报告：误差统计、修正建议、校准前后对比
- F12.6 校准后的管网另存为新方案

#### F13: 方案优化（V3+）
- F13.1 多目标优化（成本-压力-均匀度 Pareto）
- F13.2 管径组合优化
- F13.3 布局方案对比
- F13.4 经济分析（投资回报）

---

## 4. 系统架构

### 4.1 总览 Architecture Diagram

```
┌══════════════════════════════════════════════════════════════════╗
║                       aQuaDrip  Platform                        ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  ┌──────────────────────────────────────────────────────────┐   ║
║  │                QGIS Plugin Layer (UI)                     │   ║
║  │  ┌────────────┐  ┌──────────┐  ┌────────────────────┐   │   ║
║  │  │ DockWidget  │  │ MapTools │  │ Processing Provider │   │   ║
║  │  │ (主面板)    │  │ (绘制/编辑)│  │ (算法注册)         │   │   ║
║  │  └──────┬─────┘  └────┬─────┘  └─────────┬──────────┘   │   ║
║  │         │              │                  │              │   ║
║  │  ┌──────┴──────────────┴──────────────────┴─────────┐    │   ║
║  │  │              Plugin Core Layer                    │    │   ║
║  │  │  ┌──────────┐ ┌──────────┐ ┌────────┐ ┌────────┐ │    │   ║
║  │  │  │Project   │ │ Layer    │ │Style   │ │EventBus│ │    │   ║
║  │  │  │Manager   │ │ Manager  │ │Manager │ │状态管理 │ │    │   ║
║  │  │  └──────────┘ └──────────┘ └────────┘ └────────┘ │    │   ║
║  │  └───────────────────────────────────────────────────┘    │   ║
║  └──────────────────────────┬───────────────────────────────┘   ║
║                             │                                    ║
║  ┌──────────────────────────▼───────────────────────────────┐   ║
║  │                    wdrip-core Library                      │   ║
║  │                                                           │   ║
║  │  ┌────────────────────────────────────────────────────┐   │   ║
║  │  │               Data Model (数据模型层)               │   │   ║
║  │  │  DripNetwork / DripNode / DripLink(Pipe/Pump/Valve)│   │   ║
║  │  │  FieldInfo / EquipmentSet / IrrigationSchedule      │   │   ║
║  │  └────────────────────────────────────────────────────┘   │   ║
║  │                                                           │   ║
║  │  ┌────────────────────────────────────────────────────┐   │   ║
║  │  │               Geometry Layer (几何层)               │   │   ║
║  │  │  QgsGeometry / Shapely / Coordinate Transforms     │   │   ║
║  │  │  DEM Raster Handling / Elevation Extraction        │   │   ║
║  │  └────────────────────────────────────────────────────┘   │   ║
║  │                                                           │   ║
║  │  ┌────────────────────────────────────────────────────┐   │   ║
║  │  │           Topology Graph (拓扑图层)                 │   │   ║
║  │  │  TopologyNode / TopologyEdge / Connectivity        │   │   ║
║  │  │  TreeStructure / Hierarchy / LoopDetection         │   │   ║
║  │  └────────────────────────────────────────────────────┘   │   ║
║  │                                                           │   ║
║  │  ┌────────────────────────────────────────────────────┐   │   ║
║  │  │         Hydraulic Graph (水力计算图)               │   │   ║
║  │  │  EmitterAssignment / PipeDiameter / Roughness      │   │   ║
║  │  │  PumpCurve / ValveSetting / DemandPattern          │   │   ║
║  │  └────────────────────────────────────────────────────┘   │   ║
║  │                                                           │   ║
║  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │   ║
║  │  │ Builder  │ │Equipment │ │Simulation│ │ Analyzer │   │   ║
║  │  │ 布局算法  │ │ 设备系统  │ │ WNTR封装  │ │ 结果分析  │   │   ║
║  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘   │   ║
║  │                                                           │   ║
║  │  ┌────────────────────────────────────────────────────┐   │   ║
║  │  │           Optimizer (优化器, V3+)                   │   │   ║
║  │  │  MultiObjective / Pareto / Cost-Pressure-Uniformity │   │   ║
║  │  └────────────────────────────────────────────────────┘   │   ║
║  │                                                           │   ║
║  └──────────────────────────┬───────────────────────────────┘   ║
║                             │                                    ║
║  ┌──────────────────────────▼───────────────────────────────┐   ║
║  │              WNTR (Solver — 仅作为求解器)                 │   ║
║  │  ┌────────────────────────────────────────────────────┐   │   ║
║  │  │  WaterNetworkModel                                  │   │   ║
║  │  │  ├── Nodes: Junction, Reservoir, Tank               │   │   ║
║  │  │  ├── Links: Pipe, Pump, Valve                       │   │   ║
║  │  │  ├── Hydraulic Simulation                            │   │   ║
║  │  │  └── Water Quality Simulation                        │   │   ║
║  │  └────────────────────────────────────────────────────┘   │   ║
║  └──────────────────────────────────────────────────────────┘   ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
```

### 4.2 核心架构分层

```
┌──────────────────────────────────────────────────┐
│  ① Geometry Layer（几何层）                       │
│  作用：管理地理坐标、投影转换、DEM 高程提取        │
│  产出：带坐标的点/线/面                           │
├──────────────────────────────────────────────────┤
│  ② Topology Graph（拓扑图层）                     │
│  作用：节点连接关系、树状层级、连通性验证          │
│  产出：无坐标的图结构（谁连接谁）                 │
├──────────────────────────────────────────────────┤
│  ③ Hydraulic Graph（水力计算图）                 │
│  作用：在水力拓扑上附加工程参数（管径/糙率/      │
│        泵曲线/阀设置/发射器系数/需水量模式）      │
│  产出：可转换为 WNTR 的完整水力模型              │
├──────────────────────────────────────────────────┤
│  ④ WNTR Model（求解器模型）                     │
│  作用：WNTR 原生 WaterNetworkModel                │
│  注意：wdrip-core 不直接操作此层，通过转换接口    │
└──────────────────────────────────────────────────┘
```

**关键原则：每一层只依赖其下层，不跨层调用。**

### 4.3 模块划分详述

#### 4.3.1 wdrip-core 模块

**`wdrip.network`** — 数据模型

```
DripNetwork (唯一数据源)
├── nodes: Dict[str, DripNode]
│   ├── SourceNode     (水源: 蓄水池/机井/河渠)
│   ├── Junction       (普通节点/三通/弯头)
│   └── EmitterNode    (滴头节点 — 带有 Emitter 参数)
├── links: Dict[str, DripLink]
│   ├── Pipe (基类)
│   │   ├── Mainline       (干管)
│   │   ├── Submain        (支管)
│   │   └── Lateral        (毛管)
│   ├── Pump              (水泵 — Link 类型)
│   └── Valve             (阀门 — Link 类型)
│       ├── PRV            (减压阀)
│       ├── FCV            (流量控制阀)
│       ├── PSV            (持压阀)
│       └── GateValve      (手动阀)
├── field: FieldInfo
├── topology: TopologyGraph
├── equipment: EquipmentSet  (工程配置信息)
├── schedule: IrrigationSchedule
```

**重要修正**：Pump 和 Valve 是 **DripLink 的子类**，不是 Node。这与 WNTR/EPANET 一致。在 QGIS 中它们展示为线要素（LineString），而非点要素。

**`wdrip.topology`** — 拓扑引擎

```
TopologyGraph
├── TopologyNode: {id, adjacency_list, parent, children, level}
├── TopologyEdge: {id, from_node, to_node, edge_type, level}
├── validate()       → 连通性/环路/孤立节点/死管
├── hierarchy()      → 按层级分组 (0干管/1支管/2毛管)
├── to_hydraulic()   → 生成 HydraulicGraph (附加工程参数)
└── optimize()       → 拓扑优化 (V3+)
```

**`wdrip.builder`** — 布局算法

```python
class LayoutBuilder(ABC):
    """所有Builder输出TopologyGraph，不是Geometry"""
    @abstractmethod
    def build_topology(self, field: FieldInfo, params: LayoutParams) -> TopologyGraph:
        ...

class RectangularBuilder(LayoutBuilder):
    """矩形规则布局"""
    # Polygon → Rotate → Grid → Clip → AssignLevels → Topology

class ContourBuilder(LayoutBuilder):
    """等高线布局"""
    # DEM → Contour → Simplify → Project → Topology

class SkeletonBuilder(LayoutBuilder):
    """骨架线布局（不规则地块）"""
    # Polygon → MedialAxis → Simplify → Branches → Topology

class MSTBuilder(LayoutBuilder):
    """最小生成树布局（自由节点连接）"""
    # NodeSet → Delaunay → MST → Topology

class ShortestPathBuilder(LayoutBuilder):
    """最短路布局（给定起终点）"""
    # Grid → ShortestPath → Topology
```

**`wdrip.equipment`** — 设备系统（工程配置层）

```
EquipmentSet
├── Source
│   ├── Well         (机井)
│   ├── Reservoir    (蓄水池)
│   └── Canal        (河渠)
├── Pumping
│   ├── Pump         (水泵 → 映射为 DripLink.Pump)
│   └── VFD          (变频器 → 附加属性)
├── Filtration
│   ├── SandFilter   (砂石过滤器)
│   ├── ScreenFilter (筛网过滤器)
│   └── DiscFilter   (叠片过滤器)
├── Fertigation
│   ├── FertilizerTank (施肥罐)
│   └── Injector       (注肥泵)
├── Control
│   ├── Valve          (阀门 → 映射为 DripLink.Valve)
│   ├── PRV            (减压阀)
│   ├── Solenoid       (电磁阀)
│   └── ...            (FCV/PSV/GPV)
└── Sensor
    ├── PressureGauge  (压力表)
    ├── FlowMeter      (流量计)
    ├── ECProbe        (EC 传感器)
    └── pHProbe        (pH 传感器)
```

**`wdrip.simulation`** — WNTR 封装

```python
class DripSimulation:
    def __init__(self, hydraulic_graph: HydraulicGraph):
        self.model = self._to_wntr(hydraulic_graph)
        # 转换过程:
        #   DripNode.Junction     → wntr.Junction
        #   DripNode.SourceNode   → wntr.Reservoir
        #   DripNode.EmitterNode  → wntr.Junction + emitter_coefficient
        #   DripLink.Pipe         → wntr.Pipe
        #   DripLink.Pump         → wntr.Pump      (Link!)
        #   DripLink.Valve        → wntr.Valve     (Link!)
    
    def run_hydraulic(self, duration=3600) -> SimulationResult
    def run_water_quality(self, duration, pattern) -> SimulationResult
```

**`wdrip.analysis`** — 结果分析

```python
class UniformityAnalyzer:
    @staticmethod
    def cu(q) -> float
    @staticmethod
    def du(q) -> float
    @staticmethod 
    def eu(q, h_min) -> float

class FertigationAnalyzer:
    def concentration_curve(self, nodes) -> Dict
    def travel_time(self, source, target) -> float
    def uniformity(self, concentrations) -> float

class EnergyAnalyzer:
    def pump_energy(self, results, pump_ids) -> Dict  # V2+
    def cost_analysis(self, results, prices) -> Dict   # V2+
```

**`wdrip.optimizer`** — 优化器（V3+）

```python
class OptimizationObjective(Enum):
    MIN_COST = 1
    MAX_UNIFORMITY = 2
    MIN_PRESSURE_VARIATION = 3
    MIN_ENERGY = 4

class DripOptimizer:
    def optimize(self, base_network, objectives: List[OptimizationObjective],
                 constraints: Dict) -> List[DripNetwork]:
        """多目标优化，返回 Pareto 前沿"""
```

#### 4.3.2 aQuaDrip 插件模块

**UI 层：**
- `DockWidget`：主控制面板
- `FieldWizard`：农田设置向导
- `ParameterDialog`：参数配置
- `ResultViewer`：结果查看

**地图交互层：**
- `FieldDrawTool`：绘制农田边界
- `PipeDrawTool`：手动绘制管道（干管/支管/毛管）
- `PumpDrawTool`：手动绘制水泵（作为 Link 绘制，**先点击进水端→再点击出水端**）
- `ValveDrawTool`：手动绘制阀门（作为 Link 绘制，**注意方向约束**）
- **`ReverseDirectionTool`：反转 Link 方向（交换 from_node 和 to_node）**
- `NodeEditTool`：微调节点位置
- `SelectionTool`：选择/查看属性
- `DeleteTool`：删除组件

**状态管理层：**
```
ProjectStateMachine:
  New → FieldImported → LayoutGenerated → ParametersAssigned 
  → SimulationReady → SimulationRunning → SimulationFinished → Export
  
  # 手动编辑在任何状态下均可进行
  # 任何编辑操作 → 回到 ParametersAssigned
```

**事件系统（EventBus）：**
- `FieldChanged` / `NetworkChanged` / `EquipmentChanged`
- `SimulationStarted` / `SimulationFinished`
- `LayerUpdated` / `ProjectSaved`
- `SelectionChanged`

**桥接层：**
- `PluginCore`：管理 wdrip-core 实例
- `LayerManager`：自动创建/管理 QGIS 图层
- `StyleManager`：管网渲染样式

**插件生命周期：**
```
PluginLoad → CreateDockWidget → LoadProject → LoadLayers 
→ UserEditing（自动+手动混合）→ Simulation → SaveProject → PluginUnload
```

### 4.4 数据流图

```
┌──────────────┐    ┌──────────────┐     ┌──────────────┐
│  自动生成流程  │    │ 手动绘制流程  │     │ 现有管网导入  │
│ (农艺参数驱动) │    │ (QGIS MapTool)│     │ (Shapefile)  │
└──────┬───────┘    └──────┬───────┘     └──────┬───────┘
       │                   │                    │
       └───────────────────┼────────────────────┘
                           ▼
                  ┌─────────────────┐
                  │   Geometry      │
                  │  (坐标/形状)     │
                  └────────┬────────┘
                           │
                           ▼
                  ┌─────────────────┐
                  │  TopologyGraph  │  ← 所有Builder都输出拓扑
                  │  (谁连接谁)      │
                  └────────┬────────┘
                           │ DEM
                           ▼
                  ┌─────────────────┐
                  │  HydraulicGraph │  ← 附加工程参数
                  │  (管径/泵/阀等)  │
                  └────────┬────────┘
                           │
                  ┌────────▼────────┐
                  │  to_wntr()      │
                  │  转换接口        │
                  └────────┬────────┘
                           │
                  ┌────────▼────────┐
                  │  WNTR Solver   │
                  └────────┬────────┘
                           │
                  ┌────────▼────────┐
                  │  Simulation    │
                  │  Result         │
                  └────────┬────────┘
                           │
              ┌────────────┼────────────┬──────────────────┐
              ▼            ▼            ▼                  ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐
        │Uniformity│ │Fertigation│ │  Energy  │ │  Calibration     │
        │ Analyzer │ │ Analyzer  │ │ Analyzer │ │  校准分析器       │
        └──────────┘ └──────────┘ └──────────┘ │ 实测vs模拟对比   │
                           │                  │  参数自动校正     │
                           ▼                  └──────────────────┘
                  ┌─────────────────┐                  │
                  │   Optimizer     │                  ▼
                  │  多目标优化      │          ┌──────────────────┐
                  └─────────────────┘          │  校正后管网       │
                                                │  (新 DripNetwork) │
                                                └──────────────────┘
```

### 4.5 项目文件格式（.aqd）

自定工程文件格式，打包为 ZIP：

```
project.aqd
├── VERSION                  # 文件格式版本号 (如 "1.0")
├── metadata.json            # 项目元数据
├── field.geojson            # 农田边界 GeoJSON
├── network.json             # 管网拓扑与几何 (含 Pump/Valve 作为 Link)
├── equipment.json           # 设备配置
├── simulation.json          # 模拟参数
├── results/                 # 结果缓存
│   ├── node_pressure.csv
│   ├── link_flow.csv
│   └── emitter_flow.csv
└── style.qml                # QGIS 样式
```

版本管理：
- v1.0：初始版本（V1 发布）
- v1.5：水肥一体化扩展（V2）
- v2.0：优化器引入（V3）

---

## 5. 设计哲学

> 本章是 aQuaDrip 的灵魂。随着代码量增长，原则永远不变。

### 5.1 十大设计原则

```
┌─────────────────────────────────────────────────────────────┐
│               aQuaDrip Design Philosophy                     │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│ ①  Geometry is not Network                                  │
│    几何坐标 ≠ 管网拓扑。同一拓扑可映射到不同几何排列。         │
│                                                              │
│ ②  Network is not Simulation                                │
│    管网模型 ≠ 模拟求解器。模型是数据，模拟是计算过程。        │
│                                                              │
│ ③  Simulation never edits Geometry                          │
│    模拟层只读。绝不因模拟结果而修改管网几何或拓扑。            │
│                                                              │
│ ④  Everything is Serializable                               │
│    所有模型支持 JSON/GeoPackage 序列化。任何时刻可保存/恢复。  │
│                                                              │
│ ⑤  Everything can be Exported                               │
│    任何中间产物可导出：拓扑图、水力图、INP、报告。            │
│                                                              │
│ ⑥  Every Builder outputs Topology                           │
│    所有布局算法输出的是 TopologyGraph，不是 Geometry。         │
│    几何由单独的 Geometry Layer 处理。                         │
│                                                              │
│ ⑦  Every Layer has a DataModel                              │
│    每个 QGIS 图层背后有对应的数据模型类，不直接操作图层。      │
│                                                              │
│ ⑧  Core independent of QGIS                                 │
│    wdrip-core 零依赖 QGIS。可在 CLI / Jupyter / Web 中使用。  │
│                                                              │
│ ⑨  UI never performs calculations                           │
│    插件 UI 层只做展示和事件转发，所有计算在 wdrip-core 中。    │
│                                                              │
│ ⑩  WNTR is only the Solver                                  │
│    WNTR 仅作为求解器调用。所有业务逻辑在 wdrip-core 中。      │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 架构层级关系

```
Geometry         →     "在哪里"     →   QGIS / Shapely
     ↓
Topology         →     "谁连接谁"   →   wdrip-core
     ↓
HydraulicGraph   →     "参数是什么"  →   wdrip-core
     ↓
WNTR             →     "结果是什么"  →   求解器
     ↓
Analysis         →     "意味着什么"  →   wdrip-core
     ↓
Optimization     →     "怎么更好"   →   wdrip-core (V3+)
```

**每一层只依赖其下层，不跨层调用。**

### 5.3 核心工作流哲学

```
自动生成 ≠ 全自动接管
手动绘制 ≠ 回到原点

aQuaDrip 采用 "智能辅助设计" 哲学：
  - 重复的 → 自动化（毛管、滴头、编号）
  - 决策的 → 辅助推荐（管径、泵、PRV）
  - 经验的 → 手工绘制（干管走向、设备选型）
  - 全局的 → 优化求解（V3+）
```

---

## 6. 数据模型设计

### 6.1 领域模型（Domain Model）

```
                        ┌──────────────────────┐
                        │    DripProject        │
                        │  (工程根对象)          │
                        └────────┬─────────────┘
                                 │ 1
                                 │ contains
                                 ▼
              ┌──────────────────────────────────────────┐
              │            DripNetwork                    │
              │  (滴灌管网 — 唯一数据源 One Source of Truth) │
              └────┬─────────┬─────────┬────────┬────────┘
                   │         │         │        │
          ┌────────┘         │         │        └──────────────┐
          ▼                  ▼         ▼                       ▼
   ┌────────────┐   ┌────────────┐ ┌──────────┐   ┌──────────────────┐
   │  FieldInfo │   │ Topology   │ │Equipment │   │ Irrigation       │
   │  农田信息   │   │  Graph     │ │ 设备配置  │   │ Schedule         │
   │  (几何等)   │   │ (拓扑连接)  │ │ (工程参数) │   │ 灌溉制度          │
   └────────────┘   └────────────┘ └──────────┘   └──────────────────┘
                           │
                           ▼
                  ┌──────────────────┐
                  │  HydraulicGraph  │
                  │  (水力计算模型)    │
                  │  管径/糙率/泵曲线 │
                  │  阀门设置/射流器  │
                  └────────┬─────────┘
                           │ to_wntr()
                           ▼
                  ┌──────────────────┐
                  │  WNTR Model      │
                  │  (求解器)         │
                  └──────────────────┘
```

### 6.2 核心类（已修正 Pump/Valve 为 Link）

```python
@dataclass
class EmitterSpec:
    """滴头规格"""
    name: str
    manufacturer: str
    k: float                     # 流量系数 (L/h / m^x)
    x: float                     # 流态指数
    working_pressure_min: float
    working_pressure_max: float
    nominal_flow: float          # 额定流量 (L/h)
    is_pressure_compensating: bool = False
    recommended_pressure: float = 10.0

@dataclass
class DripNode(ABC):
    id: str
    x: float                     # 地理坐标 X
    y: float                     # 地理坐标 Y
    elevation: float = 0.0       # 高程

class SourceNode(DripNode):      # → wntr.Reservoir
    source_type: str              # well/reservoir/canal
    available_flow: float
    head: float

class Junction(DripNode):         # → wntr.Junction
    demand: float = 0.0
    demand_pattern: str = None

class EmitterNode(Junction):      # → wntr.Junction + emitter
    emitter_k: float              # 滴头 K 值
    emitter_x: float              # 滴头 x 值
    emitter_spec: EmitterSpec = None  # 关联的滴头型号

@dataclass
class DripLink(ABC):
    id: str
    from_node: str                # 起点节点 ID（定义正方向）
    to_node: str                  # 终点节点 ID
    
    @property
    def direction(self) -> str:
        """正方向：from_node → to_node"""
        return f"{self.from_node} → {self.to_node}"
    
    def reverse(self):
        """反转方向：交换 from_node 和 to_node"""
        self.from_node, self.to_node = self.to_node, self.from_node

class Pipe(DripLink):             # → wntr.Pipe
    """管道 — 双向流通，方向仅用于定义拓扑
    
    毛管（Lateral）的特殊说明：
    - 毛管是一条 Pipe，由沿线的节点序列定义
    - 毛管的 from_node：如果没有支管连接则为第一个 EmitterNode，
      如果有支管交叉连接则为交叉点生成的 Junction
    - 毛管的 to_node：最后一个 EmitterNode（末端）
    - 沿毛管均匀分布的是 EmitterNode（滴头节点）
    - 转换为 WNTR 时，毛管被展开为多段 Pipe：每段连接两个相邻节点
    - 支管通过"交叉-连接"方式与毛管在任何位置连接：
      支管与毛管求交 → 交叉点生成 Junction → 毛管在交叉点分段 → 建立连接
    """
    pipe_type: str                # mainline/submain/lateral
    diameter: float               # 管径 (mm)
    length: float                 # 长度 (m)
    roughness: float = 130        # C 值 (HW) 或 糙率 (DW)
    material: str = "PE"          # 材质
    minor_loss: float = 0.0       # 局部水头损失系数

class Pump(DripLink):             # → wntr.Pump (Link!)
    """水泵 — 方向固定，水流只能从 from_node 流向 to_node
    
    方向约束：
    - from_node = 进水侧（吸入端）
    - to_node   = 出水侧（压出端）
    - WNTR 中 Pump 不允许反向流动
    - 用户绘制时：先点击进水端 → 再点击出水端
    """
    pump_type: str                # 离心泵/潜水泵
    rated_head: float             # 额定扬程 (m)
    rated_flow: float             # 额定流量 (m³/h)
    rated_power: float            # 额定功率 (kW)
    efficiency: float             # 效率 (%)
    speed: float = 1.0            # 转速比 (VFD 控制)
    curve: List[Tuple[float, float]] = None  # Q-H 曲线点集
    is_reversible: bool = False   # 是否可反转（大多数泵不可反转）

class Valve(DripLink):            # → wntr.Valve (Link!)
    """阀门 — 部分类型有方向约束
    
    方向约束：
    - PRV (减压阀)：from_node = 高压侧, to_node = 低压侧
    - FCV (流量控制阀)：有方向性
    - PSV (持压阀)：有方向性
    - 手动阀 (Gate/Ball)：双向无方向约束
    - 电磁阀 (Solenoid)：有方向性
    - 止回阀 (Check Valve)：from_node → to_node 为正向
    """
    valve_type: ValveType         # PRV/FCV/PSV/Gate/Solenoid/Check
    setting: float                # 设定值
    status: ValveStatus           # OPEN/CLOSED
    diameter: float               # 口径
    has_direction: bool = True    # 是否有方向约束

@dataclass
class FieldInfo:
    """农田信息与耕作参数"""
    geometry: object               # 多边形几何
    area: float                    # 面积 (m²)
    crop_type: str                 # 作物类型
    # 耕作模式
    planting_pattern: str = "uniform"  # uniform(等行距) / wide_narrow(宽窄行) / custom / ridge_count
    row_spacings: List[float] = field(default_factory=lambda: [0.5])
        # 行距序列：
        #   uniform模式: [0.5]  — 单个值代表等行距
        #   wide_narrow模式: [0.3, 0.15]  — 宽行30cm, 窄行15cm 交替
        #   custom模式: [0.3, 0.6, 0.3, 0.6, ...]  — 逐行指定
        #   ridge_count模式: 由垄数自动计算
    ridge_count: int = None        # 垄数（ridge_count模式下使用）
    plant_spacing: float = 0.3     # 株距 (m)
    lateral_spacing: float = None  # 毛管间距（等行距模式下使用，默认=行距）
    row_direction: float = 0.0     # 种植行向 (度)
    irrigation_method: str = "surface_drip"  # 地表/地下滴灌
    emitter_spacing: float = 0.3   # 滴头间距 (m)

@dataclass 
class IrrigationSchedule:
    """灌溉制度"""
    cycles: List[IrrigationCycle]  # 灌水周期列表
    shift_groups: List[ShiftGroup] # 轮灌分组

@dataclass
class DripNetwork:
    """唯一数据源 (One Source of Truth)"""
    name: str
    field: FieldInfo
    nodes: Dict[str, DripNode]    # 含 SourceNode, Junction, EmitterNode
    links: Dict[str, DripLink]    # 含 Pipe, Pump, Valve
    topology: TopologyGraph
    equipment: EquipmentSet
    schedule: IrrigationSchedule
    units: str = "SI"
    
    def validate(self) -> List[str]:
        """连通性/孤立节点/设备一致性"""
    
    def to_hydraulic_graph(self) -> HydraulicGraph:
        """生成水力计算图"""
    
    def to_wntr(self) -> 'wntr.Network':
        """转换为 WNTR 模型 (通过 HydraulicGraph)"""
```

### 6.3 校准数据模型

```python
@dataclass
class CalibrationObservation:
    """校准观测点"""
    node_id: str                    # 管网中对应的节点 ID
    measured_pressure: float        # 实测压力 (m)
    measured_flow: float = None     # 实测流量 (m³/s, 可选)
    simulated_pressure: float = None  # 模拟压力（自动填充）
    simulated_flow: float = None    # 模拟流量（自动填充）
    pressure_error_pct: float = None  # 压力偏差百分比（自动计算）
    flow_error_pct: float = None    # 流量偏差百分比（自动计算）
    is_active: bool = True          # 是否参与校准计算

@dataclass
class CalibrationResult:
    """校准结果"""
    observations: List[CalibrationObservation]
    rmse: float                    # 均方根误差
    mape: float                    # 平均绝对百分比误差
    adjusted_roughness: Dict[str, float]  # 校正后的糙率系数
    adjusted_loss_coeffs: Dict[str, float] # 校正后的局部水头损失
    original_network: str          # 原始管网快照
    calibrated_network: str        # 校准后管网
    timestamp: str                 # 校准时间

@dataclass
class DripNetwork:
    """唯一数据源 (One Source of Truth)"""
    ...  # 已有字段
    calibration: CalibrationResult = None  # 校准结果（可选）
```

### 6.4 QGIS 数据图层设计

| 图层 | 几何类型 | WNTR 映射 | 主要属性 |
|------|---------|-----------|---------|
| 农田地块 | Polygon | — | id, 作物, 面积, 行距, **耕作模式**, **垄数**, 行向 |
| 干管 | **LineString** | Pipe | id, 管径, 材质, C值, 长度, 流量, 流速 |
| 支管 | **LineString** | Pipe | id, 所属干管, 管径, 材质, 长度, 流量 |
| 毛管 | **LineString** | Pipe | id, **所属支管**, 管径, 材质, 滴头间距, 流量, **连接方式(交叉/端接)**, **交叉节点ID**, 垄号 |
| 节点/Junction | Point | Junction | id, 高程, 压力, 需水量, **类型(支管连接点/毛管起点/普通)** |
| 滴头 | Point | Junction+Emitter | id, 型号, K, x, 工作压力, 流量, **所属毛管ID**, **所属毛管段序号** |
| 滴头 | Point | Junction+Emitter | id, 型号, K, x, 工作压力, 流量 |
| 水源 | Point | Reservoir | 类型, 可用流量, 水头 |
| **水泵** | **LineString** | **Pump (Link)** | 型号, 扬程, 流量, 功率, 曲线, **from_node(进水)**, **to_node(出水)**, 方向箭头渲染 |
| **阀门** | **LineString** | **Valve (Link)** | 类型, 设定值, 状态, **from_node(高压侧)**, **to_node(低压侧)**, 有方向约束否 |
| 过滤器 | Point | Pipe+损失 | 类型, 精度, 额定流量 |
| 施肥罐 | Point | Junction+水质 | 容积, 浓度, 注入速率 |
| 观测节点 | Point | Junction(监测) | id, 实测压力, 模拟压力, 偏差%, 是否活动 |

**重要提示**：水泵和阀门在 QGIS 中展示为 **LineString**（线要素），因为它们本质上是连接两个节点的 Link。用户绘制时是画一条线连接两个节点。

**方向管理要点：**
- 绘制顺序决定方向：**先点击的节点为 from_node，后点击的为 to_node**
- 水泵方向：from_node=进水端(吸入)，to_node=出水端(压出)
- PRV 方向：from_node=高压侧，to_node=低压侧
- 图层渲染：使用**箭头符号**显示 Link 方向，Pump 用特殊泵图标箭头
- 右键菜单提供 **[反转方向]** 功能，交换 from_node/to_node
- 拓扑检查会自动验证：有方向约束的设备是否安装正确

### 6.4 文件格式版本管理

```python
# VERSION 文件内容
AQUADRIP_PROJECT_VERSION = "1.0"
# 升级策略：
# 1.0 → 1.5: 增加 equipment section + calibration section
# 1.5 → 2.0: 增加 optimization section
# 向后兼容：旧版本文件可被新版本读取，反之不可
```

---

## 7. 自动管网布局算法

> 本章是 aQuaDrip 的核心研究价值所在。自动生成干管和支管，是拉开与现有灌溉设计软件差距的关键创新点。

### 7.1 问题定义

给定：
- 农田多边形边界 $P$
- 农艺参数（行距 $r_s$、株距 $p_s$、滴头间距 $e_s$、毛管间距 $l_s$）
- 水源位置 $S$
- 地形 DEM $D$

求：
- 最优管网拓扑 $T$（含干管、支管、毛管、滴头的完整层级）
- 使：均匀度最大化、成本最小化、压力分布最均匀

### 7.2 实际工程工作流

根据真实农田滴灌系统构建流程，完整工作流如下：

```
输入: 农田多边形, 农艺参数
         │
         ▼
    ┌─────────────────────┐
    │   Step 1: 毛管生成   │ ← 确定性算法（农艺参数直接计算）
    │  Laterals Generation │     行距/种植方向 → 自动生成
    └──────────┬──────────┘
               │
               ▼
    ┌─────────────────────┐
    │ Step 1.5: 毛管管理   │ ← ★ 关键工程步骤
    │  Lateral Management  │     根据毛管划分灌溉分区
    │  ├─ 删除部分毛管     │     （完整几根或某根的部分区段）
    │  └─ 截断毛管        │     为后续阀门分区做准备
    └──────────┬──────────┘
               │
               ▼
    ┌─────────────────────┐
    │   Step 2: 干管布局   │ ← 多种策略可选
    │  Mainline Layout     │     含出水口作为特殊水源
    │  (沿边/中央/用户绘)  │     用户手动绘制为主
    └──────────┬──────────┘
               │
               ▼
    ┌──────────────────────────────────┐
    │   Step 3: 支管连接              │ ← "交叉-连接"模式
    │  Submain Connection            │    支管与毛管求交
    │  ├─ 确定支管几何（自动/手动）   │    在交叉点自动生成节点
    │  └─ 交叉点检测→节点生成→连接   │    不限连接位置（起点/中部/尾部）
    └──────────────────────────────────┘
               │
               ▼
    ┌─────────────────────┐
    │   Step 4: 拓扑优化   │ ← 去除冗余/死管检查
    │  Topology Optimize   │
    └──────────┬──────────┘
               │
               ▼
    ┌─────────────────────┐
    │   Step 5: 参数赋值   │ ← 管径/泵/PRV 推荐
    │  Parameter Assgn    │
    └──────────┬──────────┘
               │
               ▼
          TopologyGraph
```

**工程流程与算法流程的对应关系：**

| 实际工程步骤 | 算法/工具 | 模式 |
|-------------|-----------|------|
| 1. 确定地块 | FieldDrawTool / FieldImportTool | 手动 |
| 2. 毛管整体布置 | RectangularBuilder / ContourBuilder | **自动** |
| 3. 毛管管理（分区） | LateralManageTool（删除/截断） | **手动** |
| 4. 连接水源→干管 | PipeDrawTool + OutletSource | **手动** |
| 5. 支管连接（交叉-连接） | SubmainBuilder（与毛管求交→生成节点→建立连接） | **自动** |
| 6. 阀门安装 | ValveDrawTool + 分区分配 | 手动 |
| 7. 参数设置 | ParameterDialog | 手动 |
| 8. 运行模拟 | DripSimulation | 自动 |
| 9. 验证校准 | CalibrationTool（对比+校正） | 手动+自动 |

### 7.3 算法策略详解

#### 7.3.1 毛管生成（支持多种耕作模式）

毛管布局由农艺参数驱动，根据不同的耕作模式采用不同的算法。

**⚠️ 关键节点类型：毛管上存在两种节点**

每根毛管在拓扑上由以下几种节点构成：

```
支管方向
   │
   ▼
┌─ Junction_A ──┬── Emitter_1 ──┬── Emitter_2 ──┬── ... ──┬── Emitter_N ──┐
│  (连接节点)    │  (滴头1)      │  (滴头2)       │          │  (滴头N)      │
│  from_node     │              │               │          │  to_node      │
└────────────────┴──────────────┴───────────────┴──────────┴───────────────┘
       ↑                                                                  ↑
   支管连接点                                                          毛管末端
```

- **Junction（连接节点）**：毛管的起点（from_node），用于连接支管。**每个毛管必须有一个**
- **EmitterNode（滴头节点）**：沿毛管分布，带有发射器参数。Junction 的子类
- **毛管末端节点**：最后一颗滴头同时也是毛管的终点（to_node）

所以在生成毛管时，除了 EmitterNode，还必须在靠近支管侧生成一个起始 Junction。

```
算法A: 等行距模式 (planting_pattern = "uniform")
  输入: 多边形P, 行距rs, 毛管间距ls, 滴头间距es, 行向角度θ
  
  1. 将多边形P旋转-θ对齐坐标轴
  2. 在旋转后的边界框内生成平行线（间距=ls, ls默认=rs）
  3. 裁剪到多边形内，每条线即为毛管
  4. 在**每条毛管靠近支管侧**生成一个起始 Junction（连接节点）
  5. 沿毛管从起始 Junction 起，以间距=es 生成 EmitterNode（滴头节点）
  6. 最后一个 EmitterNode 同时也是毛管的末端节点（to_node）
  7. 逆旋转回原坐标系
  8. 返回:
       毛管集合L = {l₁, l₂, ..., lₙ}   ← 每条毛管引用 start_node(Junction) + emitter_nodes列表
       滴头集合E = {e₁, e₂, ..., eₘ}    ← 所有 EmitterNode
       连接节点集合J = {j₁, j₂, ..., jₙ} ← 起始 Junction（支管连接点）


算法B: 宽窄行模式 (planting_pattern = "wide_narrow")
  输入: 多边形P, 行距序列R=[r₀, r₁, r₂, ...], 滴头间距es, 行向角度θ
  说明: 宽窄行交替排列，如小麦宽行30cm、窄行15cm
  
  1. 将多边形P旋转-θ对齐坐标轴
  2. 从多边形一侧起始线开始，按行距序列R循环递进：
       位置 p₀ = 起始偏移
       位置 p₁ = p₀ + R[0]
       位置 p₂ = p₁ + R[1]
       位置 p₃ = p₂ + R[0]  （循环）
       位置 p₄ = p₃ + R[1]  
       ...直到超出多边形范围
  3. 在每条位置线上生成管道（作为毛管）
  4. 裁剪到多边形内
  5. 在**每条毛管靠近支管侧**生成起始 Junction
  6. 从起始 Junction 起，以间距=es 沿毛管生成 EmitterNode
  7. 逆旋转回原坐标系
  8. 返回: 毛管集合L, 滴头集合E, 连接节点集合J
         每根毛管标记行距类型（宽行/窄行）


算法C: 垄数模式 (planting_pattern = "ridge_count")
  输入: 多边形P, 垄数N, 行向角度θ, 滴头间距es
  说明: 用户指定垄数，系统自动将多边形N等分后生成毛管
  
  1. 将多边形P旋转-θ对齐坐标轴
  2. 计算多边形在垂直于种植方向上的投影宽度W
  3. 计算毛管间距 ls = W / N
  4. 等间距生成N条平行线（间距=ls）
  5. 裁剪到多边形内
  6. 在**每条毛管靠近支管侧**生成起始 Junction
  7. 从起始 Junction 起，以间距=es 沿毛管生成 EmitterNode
  8. 逆旋转回原坐标系
  9. 返回: 毛管集合L, 滴头集合E, 连接节点集合J
         每根毛管附带垄号 {ridge_1, ridge_2, ..., ridge_N}


算法D: 自定义行距模式 (planting_pattern = "custom")
  输入: 多边形P, 精确位置列表positions=[p₀, p₁, p₂, ...], 滴头间距es
  
  1. 在用户指定的每个位置生成毛管线
  2. 裁剪到多边形内
  3. 在**每条毛管靠近支管侧**生成起始 Junction
  4. 从起始 Junction 起，以间距=es 沿毛管生成 EmitterNode
  5. 返回: 毛管集合L, 滴头集合E, 连接节点集合J
```

**耕作模式选择指南：**

| 模式 | 适用场景 | 用户输入 | 毛管排列 |
|------|---------|---------|---------|
| 等行距 | 玉米、蔬菜等标准种植 | 行距 | 均匀排列 |
| 宽窄行 | 小麦、水稻等密植作物 | 行距序列（如[0.3, 0.15]） | 宽窄交替 |
| 垄数 | 已有项目分析、垄作农业 | 垄数N | 均匀排列，带垄号 |
| 自定义 | 复杂种植模式、果园 | 每行精确位置 | 按需排列 |

#### 7.3.2 毛管管理（灌溉分区）

这是实际工程中极其关键但在现有软件中常被忽视的一步。毛管生成后，用户需要根据农艺需求对毛管进行管理，将地块划分为多个灌溉分区：

**操作类型：**

```
操作1: 删除整根毛管
  场景：该种植行不需要灌溉（如走道、边界缓冲带）
  结果：从 TopologyGraph 中移除该毛管及其滴头

操作2: 截断毛管
  场景：某根毛管仅前段需要灌溉，后段不需要
       或不同区段属于不同灌溉分区
  结果：一根毛管被切断为两段（或多段）
       切断处生成新的 Junction 节点
       各段可分配不同的分区 ID

操作3: 合并分区
  场景：若干相邻毛管属于同一灌溉分区
  结果：为这些毛管分配相同的分区标签
```

**用户交互：**

```
1. 在 QGIS 画布上显示所有毛管
2. 用户使用 SelectionTool 选择要操作的毛管
3. 右键菜单：
   ├─ 删除（整根移除）
   ├─ 截断...（弹出对话框：输入截断位置或在地图上点选）
   └─ 划分分区...（选择将此毛管归入哪个分区）
4. 不同分区以不同颜色显示
5. 分区的结果将影响后续阀门布局和轮灌制度设置
```

**数据模型：**

```python
@dataclass
class IrrigationZone:
    id: str                          # 分区 ID
    name: str                        # 分区名称
    color: str                       # 显示颜色
    lateral_ids: List[str]           # 所属毛管 ID 列表
    # 每个毛管可以有部分区段属于此分区
    lateral_segments: Dict[str, List[Tuple[float, float]]]
    # 如 {'L001': [(0, 0.6)]} 表示毛管L001的前60%属于此分区
```

用户可选择以下策略，或手动绘制：

```
Strategy 1: 沿长边（Along Long Edge）
  沿多边形最长边布置干管
  适用：矩形地块、狭长地块

Strategy 2: 沿短边（Along Short Edge）
  沿多边形最短边布置干管
  适用：水源在短边方向

Strategy 3: 中央（Center）
  沿多边形中轴线布置干管
  适用：对称地块、水源在中央

Strategy 4: 边界（Boundary）
  沿多边形边界布置干管（闭合或半闭合）
  适用：地块边界已有管道

Strategy 5: 用户绘制（Manual）
  用户在 QGIS 画布上手绘干管
  适用：复杂地形、改造现有管网
```

#### 7.3.3 支管连接算法（"交叉-连接"模式）

**核心思路：** 毛管生成后，支管（不论自动生成还是手动绘制）与毛管相交的位置自动生成连接节点。不限定支管必须连接毛管起点，也不限定支管走向。

```                                              ← 斜支管
      ↗                                               ↗
      ├──────●──────●──────●──────●──...  毛管L1     ↑
      │      滴头    滴头    滴头                       │
      │                                                 │ 斜支管（不垂直）
      ├──────●──────●──────●──────●──...  毛管L2
      │      滴头    滴头    滴头
      │                 ╳                               ← 交叉点
      ├──────●──────●──────●──────●──...  毛管L3
      │      滴头    滴头    滴头
├─────┴─────┴─────┴─────┴─────┴─────┴...  支管（水平）
│
干管
```

**算法流程：**

```
输入: 干管M, 毛管集合L={L₁, L₂, ..., Lₙ}, 支管生成策略（自动/手动）

Step 1: 确定支管几何
  - 自动模式：根据干管位置和支管策略生成支管线（可以是任意方向）
  - 手动模式：用户在 QGIS 画布上绘制支管 LineString（任意角度、任意路径）
  - 斜支管：用户可绘制斜线连接多个毛管

Step 2: 支管与毛管求交
  对每条支管 Sᵢ：
    对每条毛管 Lⱼ：
      计算 Sᵢ 与 Lⱼ 的几何交点 P
      如果 P 存在于 Lⱼ 上（包含端点）:
        → 在交点 P 处生成或复用节点

Step 3: 节点生成规则
  Case A: 交点 P 恰好落在毛管的一个已有节点上（如 EmitterNode）
    → 直接复用该节点，将支管连接到它
    
  Case B: 交点 P 在毛管中间（不在任何已有节点）
    → 在 P 处创建一个新的 Junction 节点
    → 将毛管在此点切断为两段 Pipe
    → 支管连接到新 Junction
    
  Case C: 交点 P 落在毛管端点
    → 直接连接该端点节点

Step 4: 支管分段
  支管 Sᵢ 从干管节点出发到每个交叉点分段
  每段 Pipe 有独立的 from_node / to_node

Step 5: 拓扑校验
  验证所有毛管都通过支管连接到干管
  验证无孤立节点
```

**节点生成规则详细说明：**

```
毛管 Lⱼ 原始结构（已有节点）:
  J_start ── E₁ ── E₂ ── E₃ ── ... ── E_n (末端)

Case B 示例: 支管在 E₂ 和 E₃ 之间与毛管交叉
  
  插入新节点 J_new:
  J_start ── E₁ ── E₂ ── J_new ── E₃ ── ... ── E_n
  
  毛管 Lⱼ 被切断为两段:
    段1: J_start → J_new (包含 E₁, E₂)
    段2: J_new → E_n (包含 E₃, ..., E_n)
  
  支管连接到 J_new
```

**支管走向策略：**

```
策略A: 垂直于干管（常见于规则农田）
  支管从干管垂直引出，所有与毛管交叉点自动连接
  
策略B: 沿多边形中轴线
  支管沿骨架线布置，交叉连接毛管
  
策略C: 用户绘制（任意角度）
  用户画斜线连接毛管，交叉点自动连接
  适用：地形复杂、已有道路/沟渠需要绕行

策略D: 最短路径
  以干管为起点，连接所有毛管的最短路线
  支管可以有转角，不一定是直线
```

#### 7.3.4 拓扑优化

```python
def optimize_topology(graph: TopologyGraph) -> TopologyGraph:
    """
    1. 移除死管（度数为1且不是水源或滴头的节点）
    2. 合并共线管道（减少节点数）
    3. 检测和移除冗余环（滴灌管网应为树状）
    4. 检查所有滴头是否连通到水源
    5. 返回优化后的拓扑
    """
```

### 7.4 算法选择矩阵

| 场景 | 毛管 | 干管 | 支管 | 推荐策略 |
|------|------|------|------|---------|
| 矩形农田+平坦 | 自动(平行线) | 沿长边 | 等距 | 全自动 |
| 矩形农田+坡地 | 自动(沿等高线) | 沿短边(垂直等高线) | 等距+坡度调整 | 半自动 |
| 不规则农田 | 自动(自适应) | 用户绘制 | 骨架线/MST | 手动+自动 |
| 现有管网改造 | 自动(补充) | 从现有导入 | 自动连接 | 导入+自动 |
| 大面积农场 | 自动 | 边界+中央 | MST优化 | 自动+优化 |

### 7.5 算法复杂度

| 算法 | 时间复杂度 | 空间复杂度 |
|------|-----------|-----------|
| 毛管平行线 | $O(n)$ | $O(n)$ |
| 骨架线 | $O(n^2)$ | $O(n)$ |
| 最短路径 (Dijkstra) | $O(E \log V)$ | $O(V+E)$ |
| MST (Kruskal) | $O(E \log E)$ | $O(V+E)$ |
| Delaunay 三角网 | $O(n \log n)$ | $O(n)$ |

---

## 8. 分阶段实施计划

### 长期发展路线

| 阶段 | 定位 | 核心能力 |
|------|------|---------|
| **Version 1.x** | 滴灌设计工具 | 自动建网+手动绘制混合、水力模拟、结果分析、基础设备（泵/阀） |
| **Version 2.x** | 水肥一体化平台 | 施肥系统、过滤系统、水质模拟、设备优化选型、能耗分析 |
| **Version 3.x** | 智能设计平台 | 多目标优化、自动布网算法升级、经济分析、变量灌溉、数字孪生 |

### Phase 0 — 项目初始化（预估：1周）

- [ ] 0.1 整理工作区
- [ ] 0.2 创建 `wdrip-core` 包结构
- [ ] 0.3 创建 `aquadrip-plugin` 插件骨架
- [ ] 0.4 初始化 Git 仓库
- [ ] 0.5 编写 AGENTS.md
- [ ] 0.6 验证开发环境
- [ ] 0.7 定稿开发文档

### Phase 1 — wdrip-core 核心库（预估：6-7周）

#### Sprint 1.1: 数据模型（1周）
- [ ] 1.1.1 实现 `DripNode` / `Junction` / `SourceNode` / `EmitterNode`
- [ ] 1.1.2 实现 `DripLink` / `Pipe` / **`Pump` (Link)** / **`Valve` (Link)**
- [ ] 1.1.3 实现 `DripNetwork`（唯一数据源）
- [ ] 1.1.4 实现 `EmitterSpec` 和滴头参数库（10+ 型号）
- [ ] 1.1.5 实现 `FieldInfo` / `IrrigationSchedule`
- [ ] 1.1.6 实现 `DripNetwork.validate()`
- [ ] 1.1.7 实现 `SettingsManager`
- [ ] 1.1.8 单元测试

#### Sprint 1.2: 拓扑引擎（1周）
- [ ] 1.2.1 实现 `TopologyNode` / `TopologyEdge` / `TopologyGraph`
- [ ] 1.2.2 实现拓扑验证（连通性/环路/孤立节点/死管）
- [ ] **1.2.3 方向验证：Pump 正向连通性、PRV 高压→低压约束检查**
- [ ] 1.2.4 实现层级导出（干/支/毛管分层）
- [ ] 1.2.4 实现 `HydraulicGraph`（在 Topology 上附加工程参数）
- [ ] 1.2.5 实现 `to_wntr()` 转换（含 Pump/Valve 的 Link 映射）
- [ ] 1.2.6 单元测试

#### Sprint 1.3: 布局算法（1.5周）
- [ ] 1.3.1 毛管自动生成（支持等行距/宽窄行/垄数/自定义四种模式）
- [ ] 1.3.2 `FieldInfo` 耕作模式参数集成（`planting_pattern`, `row_spacings`, `ridge_count`）
- [ ] 1.3.3 干管布局策略（沿长边/短边/中央/边界 4 种）
- [ ] 1.3.4 支管等距连接
- [ ] 1.3.5 支管 MST 连接
- [ ] 1.3.6 支管骨架线连接
- [ ] **1.3.7 毛管管理工具：`LateralManageTool`（删除/截断/分区）**
- [ ] 1.3.8 拓扑优化（死管移除/共线合并）
- [ ] 1.3.9 单元测试

#### Sprint 1.4: 地形适配（0.5周）
- [ ] 1.4.1 `TerrainAdapter`：DEM 高程提取
- [ ] 1.4.2 管段坡度计算
- [ ] 1.4.3 压力分区建议
- [ ] 1.4.4 自动推荐 PRV 位置

#### Sprint 1.5: 设备系统（1周）
- [ ] 1.5.1 `EquipmentSet` 容器（Source/Pumping/Filtration/Fertigation/Control/Sensor）
- [ ] 1.5.2 各设备类实现
- [ ] 1.5.3 设备→Wntr 映射规则
  - Pump → wntr.Pump (Link)
  - Valve → wntr.Valve (Link)
  - Filter → 附加水头损失
  - FertilizerTank → Junction + 水质条件
- [ ] 1.5.4 单元测试

#### Sprint 1.6: 模拟封装（1周）
- [ ] 1.6.1 `DripSimulation`（水力模拟：稳态+延时）
- [ ] 1.6.2 Emitter 参数自动设置
- [ ] 1.6.3 **轮灌分组模拟（阀门时间表 → WNTR TimePattern）**
- [ ] 1.6.4 WNTR 水质模拟封装（肥液运移）
- [ ] 1.6.5 错误处理与日志
- [ ] 1.6.6 与 WNTR 官方案例对比验证

#### Sprint 1.7: 结果分析（0.5周）
- [ ] 1.7.1 `UniformityAnalyzer`（CU/DU/EU）
- [ ] 1.7.2 `FertigationAnalyzer`（浓度曲线/运移时间）
- [ ] **1.7.3 `CalibrationAnalyzer`（实测vs模拟对比、参数校正）**
- [ ] 1.7.4 `SimulationResult` 整理

#### Sprint 1.8: 项目文件（0.5周）
- [ ] 1.8.1 `.aqd` 工程文件（含 VERSION）
- [ ] 1.8.2 INP 文件导出
- [ ] 1.8.3 Shapefile 地块导入
- [ ] 1.8.4 现有管网 Shapefile 导入（管道+节点→DripNetwork）
- [ ] 1.8.5 单元测试

#### Sprint 1.9: 集成测试（0.5周）
- [ ] 1.9.1 端到端测试
- [ ] 1.9.2 API 文档生成

### Phase 2 — QGIS 插件基础（预估：3周）

#### Sprint 2.1: 插件骨架（0.5周）
- [ ] 2.1.1 `classFactory()` + 插件主类
- [ ] 2.1.2 菜单和工具栏
- [ ] 2.1.3 i18n 国际化

#### Sprint 2.2: 状态机与事件（0.5周）
- [ ] 2.2.1 `ProjectStateMachine`
- [ ] 2.2.2 `EventBus`

#### Sprint 2.3: 主面板（0.5周）
- [ ] 2.3.1 DockWidget 布局
- [ ] 2.3.2 项目树

#### Sprint 2.4: 图层管理（0.5周）
- [ ] 2.4.1 `LayerManager`
- [ ] 2.4.2 `StyleManager`

#### Sprint 2.5: 地图交互工具（1周）
- [ ] 2.5.1 `FieldDrawTool`（绘制农田）
- [ ] 2.5.2 `PipeDrawTool`（手动绘制管道，选择层级类型）
- [ ] 2.5.3 **`PumpDrawTool`（绘制水泵，作为 Link）**
- [ ] 2.5.4 **`ValveDrawTool`（绘制阀门，作为 Link）**
- [ ] 2.5.5 `LateralManageTool`（毛管删除/截断/分区）
- [ ] 2.5.6 **`ReverseDirectionTool`（反转 Link 方向，交换 from_node/to_node）**
- [ ] 2.5.7 `NodeEditTool` / `SelectionTool` / `DeleteTool`
- [ ] 2.5.8 `CalibrationObservationTool`（选择观测节点）
- [ ] 2.5.9 农田属性表单

### Phase 3 — 核心功能集成（预估：4周）

#### Sprint 3.1: 智能管网生成向导（1周）
- [ ] 3.1.1 分步向导：毛管→干管策略选择→支管→拓扑检查
- [ ] 3.1.2 画布预览
- [ ] 3.1.3 混合模式支持

#### Sprint 3.2: 自动推荐（0.5周）
- [ ] 3.2.1 管径推荐
- [ ] 3.2.2 水泵推荐
- [ ] 3.2.3 PRV 推荐

#### Sprint 3.3: 参数配置（0.5周）
- [ ] 3.3.1 滴头/管道/水源/设备/灌溉制度对话框
- [ ] 3.3.2 **阀门轮灌时间表配置**（为每个阀门分配开启时段）

#### Sprint 3.4: DEM 集成（0.5周）
- [ ] 3.4.1 DEM 选择→高程提取→地形预览

#### Sprint 3.5: 模拟运行（0.5周）
- [ ] 3.5.1 进度对话框 + 后台线程 + 日志

#### Sprint 3.6: 模型验证与校准（0.5周）
- [ ] 3.6.1 校准对话框（观测节点列表+实测值输入）
- [ ] 3.6.2 模拟值自动填充与偏差计算
- [ ] 3.6.3 糙率系数自动校正算法
- [ ] 3.6.4 校准报告生成

#### Sprint 3.7: 结果可视化（1周）
- [ ] 3.6.1 压力/流量/均匀度/水肥浓度可视化
- [ ] 3.6.2 结果导出

### Phase 4 — Processing 集成（1周）

### Phase 5 — 测试、文档与发布（2周）

### Phase 6 — V2/V3 扩展路线

---

## 9. 技术栈与依赖

### 9.1 核心依赖

| 包 | 版本 | 用途 |
|----|------|------|
| `WNTR` | ≥ 0.3.0 | 管网水力/水质模拟引擎（仅作为 Solver） |
| `numpy` | ≥ 1.21 | 科学计算 |
| `scipy` | ≥ 1.7 | 插值/优化 |
| `shapely` | ≥ 2.0 | 几何操作 |
| `rasterio` | ≥ 1.3 | DEM 栅格读取 |
| `pandas` | ≥ 1.3 | 数据处理 |
| `matplotlib` | ≥ 3.5 | 图表生成 |
| `geopandas` | ≥ 0.12 | 地理数据读写 |
| `networkx` | ≥ 2.8 | 拓扑图算法 |

### 9.2 QGIS 插件依赖

内建于 QGIS：PyQt5/6, qgis.core, qgis.gui, processing

### 9.3 开发工具

pytest, flake8/black, sphinx, pb_tool, mkdocs

---

## 10. 界面原型设计

### 10.1 主面板

```
┌───────────────────────────────────────┐
│ aQuaDrip 智能滴灌设计                  │
├───────────────────────────────────────┤
│ [新建] [打开] [保存] [导出] [INP]     │
├───────────────────────────────────────┤
│ ▼ 项目树                              │
│  ├─ 📍 农田1 (3.2 ha)                │
│  │  ├─ 🔵 水源: 机井                 │
│  │  ├─ 🟢 干管 (120m)    ← LineString│
│  │  ├─ 🟡 支管 × 8      ← LineString│
│  │  ├─ 🟣 毛管 × 120    ← LineString│
│  │  ├─ 💧 滴头 × 3600   ← Point     │
│  │  ├─ ⚡ 水泵           ← LineString│
│  │  ├─ 🔧 阀门 × 3      ← LineString│
│  │  ├─ 🧪 施肥罐                    │
│  │  └─ 🌀 过滤器                    │
│  ├─ 📊 模拟结果                      │
│  └─ ...                               │
├───────────────────────────────────────┤
│ 🔽 方向状态                          │
│  ├─ ⚡ 水泵 P01: 进水(N01)→出水(N08)│
│  ├─ 🔧 阀门 V1:  高压(N12)→低压(N15)│
│  ├─ 🔧 阀门 V2:  双向(无约束)       │
│  └─ [选中Link后按 R 反转方向]        │
├───────────────────────────────────────┤
│ [自动生成] [手动绘制] [参数配置]      │
│ [运行模拟] [结果分析] [导出报告]      │
├───────────────────────────────────────┤
│ 📋 日志                              │
└───────────────────────────────────────┘
```

### 10.2 管网参数配置

```
┌───────────────────────────────────────────┐
│ 智能滴灌管网参数配置                      │
├───────────────────────────────────────────┤
│ 📍 农田: 农田1 (3.2 ha)                  │
│                                           │
│ ┌─ Step 1: 毛管 ──────────────────────┐  │
│ │ 耕作模式: [等行距     ▼]           │  │
│ │          ├─ 等行距                  │  │
│ │          ├─ 宽窄行                  │  │
│ │          ├─ 按垄数                  │  │
│ │          └─ 自定义                  │  │
│ │                                     │  │
│ │  ▸ 等行距模式：                      │  │
│ │    行距: [0.5] m  毛管间距: [0.5] m │  │
│ │  ▸ 宽窄行模式：                      │  │
│ │    宽行距: [0.3] m  窄行距: [0.15] m│  │
│ │  ▸ 按垄数模式：                      │  │
│ │    垄数: [40] 垄                    │  │
│ │  ▸ 自定义：                          │  │
│ │    点击地图指定毛管位置              │  │
│ │                                     │  │
│ │ 通用：滴头间距: [0.3] m             │  │
│ │      种植方向: [45 °]   [沿等高线] │  │
│ │ [生成毛管预览]                       │  │
│ └──────────────────────────────────────┘  │
│                                           │
│ ┌─ Step 2: 干管 ──────────────────────┐  │
│ │ 策略: [沿长边 ▼] / [用户绘制]      │  │
│ │ 干管位置: [沿地块长边  ▼]          │  │
│ │ [自动生成] 或 [手动绘制]           │  │
│ └──────────────────────────────────────┘  │
│                                           │
│ ┌─ Step 3: 支管 ──────────────────────┐  │
│ │ 连接算法: [等距 ▼] / [MST] / [骨架线]│  │
│ │ 支管间距: [50.0] m                  │  │
│ │ [自动连接]                           │  │
│ └──────────────────────────────────────┘  │
│                                           │
│ ┌─ Step 4: 检查 ──────────────────────┐  │
│ │ ✅ 连通性   ✅ 无死管               │  │
│ │ ✅ 水源连接   ⚠️ 1处冗余 → [修复]  │  │
│ └──────────────────────────────────────┘  │
│                                           │
│ ┌─ 滴头选型 ─────────────────────────┐   │
│ │ [耐特菲姆 ▼] [DripperNet 1.6L/h ▼]│   │
│ └─────────────────────────────────────┘   │
│                                           │
│ ┌─ 自动推荐 ─────────────────────────┐   │
│ │ [管径] DN63/DN40/DN16               │   │
│ │ [水泵] 离心泵 扬程45m 流量15m³/h   │   │
│ │ [PRV]  节点N12                      │   │
│ └─────────────────────────────────────┘   │
│                                           │
│ ┌─ 设备 ───────────┐ ┌─ 地形 ────────┐  │
│ │ ☑ 施肥系统       │ │ ☑ DEM提取高程 │  │
│ │ ☑ 过滤器         │ │ DEM: [DEM_5m ▼]│  │
│ └───────────────────┘ └───────────────┘  │
│                                           │
│ ┌─ 阀门轮灌时间表 ────────────────────┐   │
│ │ 总时长: [2] 小时                    │   │
│ │ ┌──────┬────────┬──────────┐      │   │
│ │ │阀门ID│ 所属分区 │ 开启时段   │      │   │
│ │ ├──────┼────────┼──────────┤      │   │
│ │ │ V1   │ Zone A │ 0 ~ 0.5h │      │   │
│ │ │ V2   │ Zone B │ 0.5~1.0h │      │   │
│ │ │ V3   │ Zone C │ 1.0~1.5h │      │   │
│ │ │ V4   │ Zone D │ 1.5~2.0h │      │   │
│ │ └──────┴────────┴──────────┘      │   │
│ │ [添加阀门时段] [自动分配]         │   │
│ └──────────────────────────────────┘   │
│                                           │
│        [取消]           [确认生成]        │
└───────────────────────────────────────────┘

### 10.3 模型验证与校准

```
┌───────────────────────────────────────────┐
│ 模型验证与校准                            │
├───────────────────────────────────────────┤
│ 📍 项目: 农田1                            │
│                                           │
│ ┌─ 观测节点列表 ──────────────────────┐   │
│ │ [选择观测节点] 点击地图上的节点      │   │
│ │ ┌──────┬────────┬────────┬────────┐ │   │
│ │ │节点ID│ 实测压力 │ 模拟压力 │ 偏差%  │ │   │
│ │ ├──────┼────────┼────────┼────────┤ │   │
│ │ │ N12  │ 22.5 m │ 23.1 m │ +2.7% │ │   │
│ │ │ N35  │ 18.2 m │ 17.6 m │ -3.3% │ │   │
│ │ │ N58  │ 15.0 m │ 15.8 m │ +5.3% │ │   │
│ │ │ N72  │ 12.1 m │ 12.0 m │ -0.8% │ │   │
│ │ └──────┴────────┴────────┴────────┘ │   │
│ │ [添加观测点] [导入实测数据CSV]      │   │
│ └─────────────────────────────────────┘   │
│                                           │
│ ┌─ 参数校正 ──────────────────────────┐   │
│ │ ☑ 糙率系数 C 值自动校正            │   │
│ │ ☑ 局部水头损失系数校正              │   │
│ │ [执行校正]   [查看校正结果]         │   │
│ │ 校正后预估 CU: 91.2% → 92.8%      │   │
│ └─────────────────────────────────────┘   │
│                                           │
│ ┌─ 校准结果 ──────────────────────────┐   │
│ │ RMSE: 0.85 m   MAPE: 3.2%          │   │
│ │ 校正参数: C(干管)=135, C(支管)=125 │   │
│ │ [另存为校正方案] [导出校准报告]     │   │
│ └─────────────────────────────────────┘   │
│                                           │
│        [返回]           [完成校准]        │
└───────────────────────────────────────────┘
```
```

---

## 11. 测试策略

### 11.1 单元测试

```
tests/
├── test_network.py        # 数据模型 (含 Pump/Valve 为 Link 的验证)
├── test_topology.py       # 拓扑引擎
├── test_builder/
│   ├── test_laterals.py   # 毛管生成
│   ├── test_mainline.py   # 干管策略
│   └── test_submain.py    # 支管连接 (等距/MST/骨架线)
├── test_equipment.py      # 设备系统
├── test_simulation.py     # 模拟封装
├── test_analysis.py       # 均匀度/水肥分析
├── test_io.py             # .aqd/INP/Shapefile 导入导出
└── test_integration.py    # 端到端
```

### 11.2 插件测试

```
test/
├── test_init.py
├── test_plugin.py
├── test_state_machine.py
├── test_event_bus.py
├── test_dockwidget.py
├── test_draw_tools.py     # 手动绘制工具测试
├── test_layer_manager.py
└── test_processing.py
```

### 11.3 示例场景

| 场景 | 模式 | 地形 | 规模 | 预期 |
|------|------|------|------|------|
| 矩形+自动 | 全自动 | 平坦 | 1ha | CU>90% |
| 不规则+混合 | 毛管自动+干管手动 | 平坦 | 2ha | CU>85% |
| 坡地+辅助 | 半自动 | 5%坡度 | 1ha | CU>85%(PC) |
| 现有管网改造 | 导入+编辑 | 平坦 | 5ha | 与原设计一致 |
| 水肥模拟 | 自动+设备 | 平坦 | 1ha | 浓度偏差<5% |

---

## 12. 发布与维护

### 12.1 版本命名

- v1.0.0: 滴灌设计工具
- v2.0.0: 水肥一体化平台
- v3.0.0: 智能设计平台

### 12.2 发布渠道

| 组件 | 渠道 |
|------|------|
| wdrip-core | PyPI + GitHub |
| 插件 | QGIS 仓库 + GitHub |
| 文档 | GitHub Pages |
| 示例 | GitHub Release |

---

## 13. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| WNTR 滴灌模拟精度 | 中 | 高 | 物理实验对比 |
| Pump/Valve 作为 Link 的 UI 交互复杂度 | 中 | 中 | 参考 QEPANET 的 Link 绘制模式 |
| 不规则算法复杂度 | 高 | 中 | 先矩形+手动，V1.2 加不规则 |
| 用户上手 | 中 | 中 | 教程+示例 |

---

## 14. 架构评审与后续改进建议

### 14.1 架构评审要点

| 要点 | 状态 | 说明 |
|------|------|------|
| 三层架构 | ✅ 已实现 | Plugin → wdrip-core → WNTR |
| Geometry ≠ Topology | ✅ 已实现 | 独立 TopologyGraph 层 |
| Topology → HydraulicGraph → WNTR | ✅ 已实现 | 四层模型 |
| Pump/Valve 为 Link | ✅ 已修正 | 继承自 DripLink |
| Equipment 分级 | ✅ 已实现 | 6 大类设备 |
| 自动+手动混合 | ✅ 已实现 | 毛管自动 + 干管手绘 + 支管自动连接 |
| 设计哲学 | ✅ 已新增 | 第5章 10 条原则 |
| 布局算法详细设计 | ✅ 已新增 | 第7章 |
| Optimizer | 🟡 规划中 | V3+ 实现 |
| **实际工程工作流** | **✅ 已修正** | **7.2 毛管→毛管管理→干管→支管** |
| **毛管管理（分区）** | **✅ 已新增** | **F2.13-F2.17, 7.3.2** |
| **出水口作为水源** | **✅ 已补充** | **F5.1, F6.1** |
| **阀门轮灌时间表** | **✅ 已补充** | **F5.2-F5.3, 10.2 UI** |
| **模型验证与校准** | **✅ 已新增** | **F12, 6.3, 10.3** |

### 14.2 已采纳的改进建议

| 建议来源 | 改进内容 | 对应章节 |
|---------|---------|---------|
| 评审 #1 | 数据模型补全、拓扑分离 | 第5、6章 |
| 评审 #2 | Equipment 分类升级、项目定位升级 | 第1、3章 |
| 本次 | Pump/Valve 修正为 Link | 第6章（核心修正） |
| 本次 | 手动绘制工具体系 | 第4、8章 |
| 本次 | Architecture Diagram 正式图 | 第4章 |
| 本次 | Equipment 6 大类分级 | 第3、6章 |
| 本次 | Geometry→Topology→Hydraulic→WNTR 四层 | 第4、5章 |
| 本次 | Optimizer 模块设计 | 第4章 |
| 本次 | .aqd 版本号管理 | 第4章 |
| 本次 | 设计哲学独立章节 | 第5章（新增） |
| 本次 | 自动管网布局算法章节 | 第7章（新增） |

### 14.3 后续改进建议

1. **V2/V3 规划**：水肥一体化验证、多目标优化算法
2. **算法研究**：不规则地块的 MST 优化、坡地等高线自适应算法
3. **性能**：10000+ 节点的管网简化策略
4. **生态**：滴头参数库社区贡献机制
5. **国际**：英文版文档和界面

---

## 附录

### A. 术语表

| 术语 | 英文 | 解释 |
|------|------|------|
| 滴灌 | Drip/Trickle Irrigation | 通过滴头将水缓慢滴入作物根部 |
| 水肥一体化 | Fertigation | 灌溉同时施肥 |
| 毛管 | Lateral | 安装滴头的细管道 |
| 支管 | Submain | 连接干管和毛管的中间管道 |
| 干管 | Mainline | 从水源到支管的主管道 |
| 滴头 | Emitter/Dripper | 控制出水的装置 |
| CU/DU/EU | Uniformity Indices | 均匀度指标 |
| PC | Pressure Compensating | 压力补偿式滴头 |
| PRV/FCV/PSV | Valve Types | 阀门类型 |
| VFD | Variable Frequency Drive | 变频器 |
| **Link** | **WNTR/EPANET 中的管道类** | **Pump, Valve 均属此类** |
| Topology | 拓扑 | 连接关系，独立于坐标 |
| HydraulicGraph | 水力计算图 | 含工程参数的拓扑 |
| .aqd | aQuaDrip Project | 本插件工程文件 |
| MST | Minimum Spanning Tree | 最小生成树（布局算法） |

### B. 参考资源

- WNTR: https://usepa.github.io/WNTR/
- EPANET: https://epanet22.readthedocs.io/
- QGIS Plugin Dev: https://docs.qgis.org/latest/en/docs/pyqgis_developer_cookbook/
- QEPANET: https://gitlab.com/albertodeluca/qepanet
- GHydraulics: https://epanet.de/ghydraulics/
- ASAE EP405.1: Drip Irrigation Design Standard
- NetworkX: https://networkx.org/

### C. 已有 QGIS 插件借鉴分析

工作区 `已有示例/` 包含三个参考项目。以下是针对 aQuaDrip 的系统性借鉴分析，按**可复用程度**排序。

#### C.1 QEPANET（QGIS 3.x 插件，可借鉴度 ★★★★★）

**定位：** 最现代的 QGIS-EPANET 集成插件，与 aQuaDrip 的技术栈最接近。

**目录结构：**
```
qepanet/
├── qepanet.py               # 主插件类
├── ui/qepanet_dockwidget.py # 主停靠窗口（核心 UI 控制器）
├── tools/                   # 地图交互工具
│   ├── add_junction_tool.py # 添加节点工具
│   ├── add_pipe_tool.py     # 添加管道工具
│   ├── add_pump_tool.py     # 添加水泵工具
│   ├── add_valve_tool.py    # 添加阀门工具
│   ├── move_tool.py         # 移动工具
│   ├── select_tool.py       # 选择工具
│   ├── delete_tool.py       # 删除工具
│   ├── data_stores.py       # 图层存储（MemoryDS/ShapefileDS）
│   └── parameters.py        # 全局状态 + 观察者模式
├── model/
│   ├── network.py           # 管网数据模型（6 种元素类）
│   ├── network_handling.py  # NodeHandler / LinkHandler
│   ├── inp_reader/writer.py # INP 文件读写
│   ├── runner.py            # EPANET 模拟运行器
│   └── binary_out_reader.py # 二进制结果读取
├── geo_utils/
│   ├── utils.py             # 图层 CRUD
│   ├── vector_utils.py      # 矢量操作
│   └── raster_utils.py      # DEM 高程提取（可直接复用思路）
├── rendering/symbology.py   # 符号化（节点/管道分级渲染）
└── test/
```

**对 aQuaDrip 有直接借鉴价值的模块：**

| 模块 | 借鉴方式 | 对应 aQuaDrip 需求 |
|------|---------|-------------------|
| **`tools/data_stores.py`** | 六层独立图层的 MemoryDS 创建模式：每种元素独立图层 + 空间索引 | 6 种 QGIS 图层管理 |
| **`tools/*_tool.py`** | canvasPress/Move/Release 三件套模式 + snapping 精细化配置 | 手动绘制工具（Pipe/Pump/ValveDrawTool） |
| **`model/network_handling.py`** | `NodeHandler`/`LinkHandler` 静态类 + `find_next_id()` 自动 ID + `split_pipe()` 分割管道 | 交叉连接时管道分割 |
| **`model/network.py`** | 字段定义与 `QgsField` 列表的映射方式 + 图层属性对应的 Python 类 | 滴灌管网数据模型 |
| **`geo_utils/raster_utils.py`** | `read_layer_val_from_coord()` 从 DEM 提取高程 | DEM 地形集成 |
| **`rendering/symbology.py`** | `NodeSymbology`/`LinkSymbology` + `QgsGraduatedSymbolRenderer` | 结果热力图渲染 |
| **`ui/qepanet_dockwidget.py`** | DockWidget 作为核心 UI 控制器的架构（按钮→工具→图层→模拟） | 主面板整体架构 |
| **`ui/output_ui.py`** | 结果查看器双通道：Matplotlib 图表 + QGIS 专题图 | 结果查看器 |
| **`ui/graphs.py`** | `StaticMplCanvas` 嵌入 Qt 对话框 | Matplotlib 嵌入 |
| **`tools/parameters.py` + `observable.py`** | 观察者模式：参数变化自动通知 UI 更新 | EventBus / 状态管理 |
| **`model/binary_out_reader.py`** | 二进制结果文件解析 | 结果回读（如果使用 WNTR 则不需要） |

**关键设计模式（建议直接采用）：**
1. **六层分离**：Junctions/Reservoirs/Tanks/Pipes/Pumps/Valves 各占独立图层 → aQuaDrip 同样适用
2. **Snapping 动态配置**：每个 Tool 的 `activate()` 中设置 snapping，工具切换自动恢复
3. **泵阀块逻辑**：移动泵阀时连带两端节点一起移动，保持拓扑结构
4. **管道 3D 几何**：使用 `LineStringZ` 存储高程，结合 DEM 自动赋值
5. **惰性结果层**：仅在首次请求时创建结果图层，后续复用

#### C.2 GHydraulics（QGIS 2.x 插件，可借鉴度 ★★★★☆）

**定位：** 最完整的 EPANET 数据模型与 INP 读写实现。

**对 aQuaDrip 有直接借鉴价值的模块：**

| 模块 | 借鉴方式 | 对应 aQuaDrip 需求 |
|------|---------|-------------------|
| **`GHydraulicsModelChecker.py`** | 字段完整性检查、ID 唯一性、CRS 一致性、多部件检测 | 拓扑检查与验证 |
| **`GHydraulicsModelMaker.py`** | `QgsSpatialIndex` 构建空间索引、`nearestNeighbor()` 查找最近节点、自动创建 Junction | 交叉连接时节点查找 |
| **`GHydraulicsInpWriter.py`** | 模板替换式 INP 写入：保持模板复杂段不变，只替换数据段 | INP 文件导出 |
| **`EpanetResultReader.py`** | `array.array('i')` 读取二进制文件头部、固定长度字符串解析 | 结果回读（备选方案） |
| **`GHydraulicsCommon.py`** | `getLayers()` + `eachLayer(callback, sections)` 遍历模式 | 图层遍历工具函数 |
| **`GHydraulicsModelRunner.py`** | `setStepResults()` 通用方法：传入不同 getter 处理节点/链路 | 结果写入 QGIS 图层 |
| **`EpanetModel.py`** | 纯常量类（零运行时开销），集中管理所有字段名称 | 常量定义规范 |

**关键设计模式：**
1. **模板替换式 INP 写入**：保持 `[OPTIONS]` `[TIMES]` `[CURVES]` 等复杂段不变，只替换 `[JUNCTIONS]` `[PIPES]` 等数据段
2. **双层结果回读**：`EpanetResultReader`（纯二进制解析层） + `GHydraulicsModelRunner.setStepResults`（QGIS 写入层）分离
3. **虚拟线处理**：QGIS 中点要素（泵/阀）映射为 EPANET 中的短线 + 虚拟节点
4. **配置持久化**：通过 `QgsProject.writeEntry("ghydraulics", "key", value)` 存储图层配置

#### C.3 qgis-epanet（Processing 框架，可借鉴度 ★★★☆☆）

**定位：** 最精简的 Processing 框架集成示例，7 个 Python 文件约 450 行代码。

**对 aQuaDrip 有直接借鉴价值的模块：**

| 模块 | 借鉴方式 | 对应 aQuaDrip 需求 |
|------|---------|-------------------|
| **`EpanetAlgorithmProvider.py`** | Processing Provider 注册模式（`Processing.addProvider()` / `_loadAlgorithms()`） | Processing 集成 |
| **`EpanetAlgorithm.py`** | `defineCharacteristics()` 参数声明 + `processAlgorithm()` 执行逻辑 | Processing 算法封装 |
| **`EpanetOutputTable.py`** | 自定义 Output 类型（继承 `OutputTable` + `TableWriter`） | 自定义输出格式 |
| **`gui.py` 的 `layerAdded()`** | 模拟结果通过 JOIN 自动关联到源图层 | 结果可视化关联 |

**关键设计模式：**
1. **输出自动 JOIN**：模拟结果通过字段名与源图层自动关联，用户无需手动关联即可在原地图上着色
2. **声明式参数**：用 `self.addParameter(ParameterVector(...))` 声明输入，Processing 自动生成对话框
3. **进度反馈**：`progress.setText()` + `progress.setPercentage()`

#### C.4 借鉴优先级矩阵

| 借鉴内容 | 来源 | 优先级 | 原因 |
|---------|------|--------|------|
| DockWidget 为主控制器的架构 | QEPANET | ★★★★★ | 直接影响插件整体框架 |
| 六层独立图层 + 空间索引 | QEPANET | ★★★★★ | 直接影响数据模型设计 |
| MapTool 三件套模式 | QEPANET | ★★★★★ | 直接影响手动绘制工具 |
| "交叉-连接"节点生成 | aQuaDrip 独创 | ★★★★★ | 核心创新点 |
| 模板替换式 INP 写入 | GHydraulics | ★★★★☆ | INP 导出功能 |
| 模型检查器 | GHydraulics | ★★★★☆ | 拓扑验证功能 |
| Processing Provider 注册 | qgis-epanet | ★★★★☆ | Processing 集成 |
| 输出自动 JOIN | qgis-epanet | ★★★☆☆ | 结果可视化 |
| 泵阀块逻辑 | QEPANET | ★★★☆☆ | 地图编辑 |
| DEM 高程提取 | QEPANET/GHydraulics | ★★★☆☆ | 地形集成 |
| 结果双通道（图表+专题图）| QEPANET | ★★★☆☆ | 结果可视化 |
| 观察者模式 | QEPANET | ★★☆☆☆ | 状态管理（已有 EventBus）|
| 经济管径计算 | GHydraulics | ★★☆☆☆ | V2 扩展 |

#### C.5 直接可复用的代码参考

以下代码片段可直接参考实现方式（非复制，需根据 aQuaDrip 需求改写）：

```python
# 1. QEPANET: 创建内存图层的工厂方法 (tools/data_stores.py)
class MemoryDS:
    @staticmethod
    def create_junctions_lay(name, crs):
        lay = QgsVectorLayer(f'Point?crs={crs.authid()}', name, 'memory')
        lay.dataProvider().addAttributes(Junction.fields)
        lay.updateFields()
        return lay

# 2. QEPANET: Snapping 统一配置 (model/network_handling.py)
@staticmethod
def set_up_snapper(canvas, snap_layers, tolerance=12):
    config = QgsSnappingConfig(project)
    config.setMode(QgsSnappingConfig.AdvancedConfiguration)
    for layer, snap_type in snap_layers.items():
        settings = QgsSnappingConfig.IndividualLayerSettings(
            True, snap_type, tolerance, QgsTolerance.Pixels)
        config.setIndividualLayerSettings(layer, settings)
    snapper.setConfig(config)

# 3. GHydraulics: 模板替换式 INP 写入 (GHydraulicsInpWriter.py)
# 核心思路：遍历模板行，遇到 [SECTION] 时替换为收集的数据
# 未替换的段保持模板原样

# 4. qgis-epanet: Processing Provider 注册 (gui.py)
def initGui(self):
    self.provider = EpanetAlgorithmProvider()
    QgsApplication.processingRegistry().addProvider(self.provider)
```

#### C.6 与已有项目的关键区别

| 维度 | QEPANET / GHydraulics | aQuaDrip |
|------|----------------------|----------|
| **模拟引擎** | EPANET 2.x 命令行（C 语言） | **WNTR（Python，可直接 import）** |
| **管网构建** | 全手动逐个添加 | **农艺参数驱动自动生成** |
| **管网层级** | 平面节点-管道 | **干管→支管→毛管→滴头 四层** |
| **滴头处理** | 作为普通节点 | **EmitterNode 专用类型，内置滴头库** |
| **支管连接** | 手动绘制 | **"交叉-连接"自动模式** |
| **均匀度分析** | 无 | **CU/DU/EU 专业灌溉指标** |
| **水肥模拟** | 无 | **WNTR 水质模拟（V2）** |
| **耕作模式** | 无 | **4 种模式（等行距/宽窄行/垄数/自定义）** |
