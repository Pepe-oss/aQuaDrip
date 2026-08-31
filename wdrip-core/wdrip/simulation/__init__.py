"""DripSimulation — WNTR 模拟封装

将 DripNetwork 转换为 WNTR 模型，运行水力/水质模拟。
"""

import logging
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

import numpy as np

from .result import SimulationResult

if TYPE_CHECKING:
    from wdrip.network import DripNetwork, EmitterNode, Pipe, Pump, Valve
    from wdrip.network import SourceNode

logger = logging.getLogger(__name__)


class DripSimulation:
    """滴灌管网模拟器
    
    封装 WNTR，提供滴灌专用的模拟接口。
    支持切换不同的模拟引擎：WNTRSimulator / EpanetSimulator / 迭代求解器。
    
    Args:
        network: 滴灌管网
        engine: 模拟引擎实例。不指定则调用 auto_detect_engine()
        precision: 精度预设 "fast"/"standard"/"high"（仅对迭代引擎生效）
    """

    # 精度预设
    PRESETS = {
        "fast":     {"max_iter": 5,  "tolerance": 1e-6},
        "standard": {"max_iter": 8,  "tolerance": 1e-7},
        "high":     {"max_iter": 15, "tolerance": 1e-8},
    }
    
    def __init__(self, network: 'DripNetwork', engine: Optional['SimulationEngine'] = None,
                 precision: str = "fast"):
        from .engine import auto_detect_engine, SimulationEngine
        self.network = network
        self._wn = None  # WNTR WaterNetworkModel
        self._wntr_results = None

        if engine is not None:
            self._engine = engine
        else:
            self._engine = auto_detect_engine()
            # 对迭代引擎注入精度参数
            params = self.PRESETS.get(precision, self.PRESETS["fast"])
            if hasattr(self._engine, 'max_iter'):
                self._engine.max_iter = params["max_iter"]
                self._engine.tolerance = params["tolerance"]

        self._precision = precision
    
    @property
    def engine_name(self) -> str:
        """当前使用的引擎名称"""
        return self._engine.display_name
    
    # ---- 模型转换 ----
    
    def _build_wntr_model(self) -> object:
        """构建 WNTR 模型"""
        import wntr
        
        wn = wntr.network.WaterNetworkModel()
        
        # 1. 创建节点
        for nid, node in self.network.nodes.items():
            self._add_wntr_node(wn, nid, node)
        
        # 2. 创建管道
        for lid, link in self.network.links.items():
            self._add_wntr_link(wn, lid, link)
        
        # 3. 设置模拟选项
        wn.options.time.duration = 0  # 稳态模拟
        wn.options.hydraulic.headloss = "H-W"  # Hazen-Williams
        # PDD（压力依赖用水）：emitter 滴头才能按 q=k·P^x 出水；
        # 默认 DDA 模式下 emitter 被忽略，管网不出水、全静压
        wn.options.hydraulic.demand_model = "PDD"
        # 消除 EPANET "REQUIRED PRESSURE below lower limit" 警告
        # 滴灌场景中 emitter 流量由 emitter_coefficient 公式 q=k·P^x 计算，
        # base_demand 均为 0，required_pressure 数值不影响 emitter 结果
        wn.options.hydraulic.required_pressure = 0.1

        # 3.1 emitter 流态指数(EPANET/WNTR 的 emitter 指数是全局 option,
        # 节点上挂的 emitter_exponent 仅供迭代引擎逐节点读取):
        # - 全网滴头 x 一致 → 写入全局 option,EPANET 引擎路径也精确
        # - x 混合(PC 0.05 + 普通 0.5) → 单一全局指数无法表达,挂标记,
        #   run() 检测后把 EPANET 引擎切换为迭代引擎
        xs = {round(n.emitter_x, 4) for n in self.network.nodes.values()
              if getattr(n, "emitter_k", 0) > 0
              and getattr(n, "emitter_x", None) is not None}
        wn._aquadrip_mixed_emitter_exponent = len(xs) > 1
        if len(xs) == 1:
            wn.options.hydraulic.emitter_exponent = next(iter(xs))
            logger.debug(f"全局 emitter 指数 = {next(iter(xs))}")

        return wn
    
    def _add_wntr_node(self, wn, nid: str, node):
        """添加 WNTR 节点"""
        from wdrip.network import SourceNode
        import wntr

        if isinstance(node, SourceNode):
            # SourceNode → wntr.Reservoir
            # 用类型而非 head>0 判定：head≤0 时水源仍必须有水头边界条件，
            # 否则会落入 Junction 分支导致全网无压力源、压力全为 0。
            head = node.head
            if head <= 0:
                head = 10.0
                logger.warning(
                    f"水源 {nid} 的 head={node.head}≤0，已回退为默认 {head}m，"
                    f"请在属性表修正水头值")
            wn.add_reservoir(nid, base_head=head,
                             coordinates=(node.x, node.y))
            logger.debug(f"  Reservoir: {nid} head={head}")

        elif hasattr(node, "emitter_k"):
            # EmitterNode → wntr.Junction + emitter
            wn.add_junction(nid, base_demand=node.demand,
                           elevation=node.elevation,
                           coordinates=(node.x, node.y))
            # 设置发射器参数
            # WNTR 使用 SI 单位 (m³/s)，我们的 k 是 L/h / m^x
            # 转换: 1 L/h = 2.77778e-7 m³/s
            emitter_coeff_si = node.emitter_k * 2.77778e-7
            wn.get_node(nid).emitter_coefficient = emitter_coeff_si
            # 挂自定义属性：迭代求解器通过 getattr(node, 'emitter_exponent', 0.5)
            # 读取每个滴头的流态指数（WNTR Junction 原生无此属性）
            wn.get_node(nid).emitter_exponent = node.emitter_x
            logger.debug(f"  Emitter: {nid} k={node.emitter_k} x={node.emitter_x}")
        
        else:
            # Junction → wntr.Junction
            wn.add_junction(nid, base_demand=getattr(node, "demand", 0),
                           elevation=node.elevation,
                           coordinates=(node.x, node.y))
            logger.debug(f"  Junction: {nid} elev={node.elevation}")
    
    def _add_wntr_link(self, wn, lid: str, link):
        """添加 WNTR 链路"""
        import wntr
        
        if hasattr(link, "pump_type"):
            # Pump (Link!) — 用 POWER 模式（功率），无需曲线
            # Q-H 曲线模式（HEAD）需要先创建 Curve，复杂且数据可能缺失；
            # POWER 模式只需功率值，WNTR 内部自动求解。
            # 功率 P(kW) ≈ ρgQH/η = 9.81 × Q(m³/s) × H(m) / η
            # 若用户未提供 rated_power，从 rated_flow/rated_head 估算
            q_cms = (link.rated_flow or 0) / 3600.0  # m³/h → m³/s
            h_m = link.rated_head or 0
            if getattr(link, "rated_power", 0) and link.rated_power > 0:
                power_kw = link.rated_power
            elif q_cms > 0 and h_m > 0:
                eff = (getattr(link, "efficiency", 0) or 60) / 100.0
                power_kw = 9.81 * q_cms * h_m / max(eff, 0.1)
            else:
                power_kw = 0.5  # 兜底 0.5 kW
            wn.add_pump(lid, link.from_node, link.to_node,
                       pump_type="POWER",
                       pump_parameter=power_kw)
            logger.debug(f"  Pump: {lid} {link.from_node}→{link.to_node} P={power_kw:.2f}kW")
        
        elif hasattr(link, "valve_type"):
            # Valve (Link!)
            vtype = str(link.valve_type.name).upper()
            # WNTR 支持的阀门类型（与 ValveType 枚举一致）
            WNTR_VALVE_TYPES = {"PRV", "PSV", "FCV"}
            needs_downgrade = vtype not in WNTR_VALVE_TYPES

            # PRV/PSV/FCV 不能直连 Reservoir/Tank，否则 WNTR 报错
            if not needs_downgrade:
                src_node = self.network.get_node(link.from_node)
                dst_node = self.network.get_node(link.to_node)
                from wdrip.network import SourceNode
                if (isinstance(src_node, SourceNode)
                        or isinstance(dst_node, SourceNode)):
                    logger.warning(
                        f"阀门 {lid} 类型 '{vtype}' 直连水源，已降级为普通管道")
                    needs_downgrade = True

            if needs_downgrade:
                logger.warning(
                    f"阀门 {lid} 类型 '{vtype}' 不被当前引擎支持，已降级为普通管道")
                diameter_m = link.diameter / 1000.0 if link.diameter > 0 else 0.02
                wn.add_pipe(lid, link.from_node, link.to_node,
                           length=1,  # 阀门视为短管道
                           diameter=diameter_m,
                           roughness=130,
                           minor_loss=link.minor_loss)
            else:
                diameter_m = link.diameter / 1000.0 if link.diameter > 0 else None
                # 映射 ValveStatus → WNTR initial_status
                from wdrip.network.links import ValveStatus
                wn_status = "CLOSED" if link.status == ValveStatus.CLOSED else "ACTIVE"
                wn.add_valve(lid, link.from_node, link.to_node,
                            valve_type=vtype,
                            diameter=diameter_m,
                            initial_setting=link.setting,
                            initial_status=wn_status)
                logger.debug(f"  Valve: {lid} type={vtype} setting={link.setting}")
        
        else:
            # Pipe
            diameter_m = link.diameter / 1000.0 if link.diameter > 0 else 0.02
            wn.add_pipe(lid, link.from_node, link.to_node,
                       length=max(link.length, 1),
                       diameter=diameter_m,
                       roughness=link.roughness,
                       minor_loss=link.minor_loss)
            logger.debug(f"  Pipe: {lid} {link.from_node}→{link.to_node} L={link.length}")
    
    def build_wntr_model(self):
        """将 DripNetwork 构建为 WNTR WaterNetworkModel（不运行模拟）

        用于 INP 导出 / 独立模型检查等场景。需要 wntr 已安装。
        """
        self._wn = self._build_wntr_model()
        return self._wn

    # ---- 运行模拟 ----

    def run(self, duration: int = 0, timestep: int = 3600,
            progress_callback=None) -> 'SimulationResult':
        """运行水力模拟
        
        Args:
            duration: 模拟时长（seconds）。0=稳态，>0=延时
            timestep: 报告时间步长（seconds）
            progress_callback: 可选进度回调 (percent: int, message: str)
            
        Returns:
            模拟结果
        """
        try:
            import wntr
        except ImportError:
            return SimulationResult(
                success=False,
                message="WNTR 未安装。请运行: pip install wntr"
            )
        
        try:
            # 构建模型
            self._wn = self._build_wntr_model()
            if progress_callback:
                progress_callback(5, "构建 WNTR 模型完成")

            # 设置模拟时间
            if duration > 0:
                self._wn.options.time.duration = duration
                self._wn.options.time.report_timestep = timestep
            else:
                self._wn.options.time.duration = 0

            # 注入进度回调到引擎
            if progress_callback and hasattr(self._engine, 'progress_callback'):
                self._engine.progress_callback = progress_callback

            # 混合滴头流态指数(PC/非PC 并存)时,EPANET 的单一全局
            # emitter 指数无法表达逐节点 x → 切换为逐节点指数的迭代引擎
            if getattr(self._wn, "_aquadrip_mixed_emitter_exponent", False) \
                    and self._engine.name == "epanet":
                from .engine import IterativeWNTRSimulatorEngine
                logger.info("管网混合滴头流态指数(PC/非PC),"
                            "EPANET 全局指数无法表达,切换迭代引擎")
                self._engine = IterativeWNTRSimulatorEngine()
                if self._precision in self.PRESETS:
                    params = self.PRESETS[self._precision]
                    self._engine.max_iter = params["max_iter"]
                    self._engine.tolerance = params["tolerance"]
                if progress_callback:
                    self._engine.progress_callback = progress_callback

            # 使用当前引擎运行
            logger.info(f"使用引擎: {self._engine.display_name}")
            wntr_results = self._engine.run(self._wn)

            if progress_callback:
                progress_callback(95, "提取模拟结果...")

            # 提取结果
            result = self._extract_results(wntr_results, duration)
            result.success = True
            result.message = f"模拟成功 (引擎: {self._engine.display_name}, 精度: {self._precision})"

            if progress_callback:
                progress_callback(100, "完成")

            return result
        
        except Exception as e:
            logger.exception("模拟失败")
            # EPANET 引擎失败时自动回退到迭代引擎
            if self._engine.name == "epanet":
                from .engine import IterativeWNTRSimulatorEngine
                logger.warning(f"EPANET 引擎失败 ({e})，回退到迭代求解器")
                try:
                    self._engine = IterativeWNTRSimulatorEngine()
                    if self._precision in self.PRESETS:
                        params = self.PRESETS[self._precision]
                        self._engine.max_iter = params["max_iter"]
                        self._engine.tolerance = params["tolerance"]
                    # 注入进度回调，否则迭代引擎不会上报迭代进度
                    if progress_callback:
                        self._engine.progress_callback = progress_callback
                    wntr_results = self._engine.run(self._wn)
                    result = self._extract_results(wntr_results, duration)
                    result.success = True
                    result.message = f"模拟成功 (引擎: {self._engine.display_name}, 精度: {self._precision})"
                    return result
                except Exception as e2:
                    logger.exception("迭代引擎也失败")
                    return SimulationResult(
                        success=False,
                        message=f"模拟失败: {e2}"
                    )
            return SimulationResult(
                success=False,
                message=f"模拟失败: {e}"
            )
    
    def run_water_quality(self, duration: int = 7200, timestep: int = 3600) -> 'SimulationResult':
        """运行水质（水肥）模拟
        
        Args:
            duration: 模拟时长（seconds）
            timestep: 报告时间步长（seconds）
            
        Returns:
            含水质结果的模拟结果
        """
        try:
            import wntr
        except ImportError:
            return SimulationResult(success=False, message="WNTR 未安装")
        
        try:
            self._wn = self._build_wntr_model()
            self._wn.options.time.duration = duration
            self._wn.options.time.report_timestep = timestep
            
            # 设置水质模拟
            self._wn.options.quality.parameter = "CHEMICAL"
            self._wn.options.quality.trace_node = None
            
            # 为水源节点设置水质边界条件
            for nid, node in self.network.nodes.items():
                if hasattr(node, "water_quality") and node.water_quality > 0:
                    wntr_node = self._wn.get_node(nid)
                    if wntr_node:
                        wntr_node.initial_quality = node.water_quality
            
            self._sim = wntr.sim.WNTRSimulator(self._wn)
            wntr_results = self._sim.run_sim()
            
            result = self._extract_results(wntr_results, duration)
            # 提取水质结果
            if 'quality' in wntr_results.node:
                for nid in self.network.nodes:
                    arr = wntr_results.node['quality'].loc[:, nid].values
                    result.node_quality[nid] = arr
            
            result.success = True
            result.message = "水肥模拟成功"
            return result
        
        except Exception as e:
            logger.exception("水质模拟失败")
            return SimulationResult(success=False, message=f"水质模拟失败: {e}")
    
    # ---- 结果提取 ----
    
    def _extract_results(self, wntr_results, duration: int) -> 'SimulationResult':
        """从 WNTR 结果提取滴灌专用结果"""
        result = SimulationResult(duration_seconds=duration)
        
        # 时间步 — EpanetSimulator 结果没有 .time 属性，从 DataFrame index 提取
        if hasattr(wntr_results, 'time'):
            result.time_steps = np.array(wntr_results.time)
        else:
            try:
                # 从任意节点或管段数据的 index 获取时间序列
                sample_df = next(iter(wntr_results.node.values()))
                result.time_steps = np.array(sample_df.index)
            except (StopIteration, AttributeError):
                result.time_steps = np.array([0])
        
        # 节点压力
        for nid, node in self.network.nodes.items():
            try:
                arr = wntr_results.node['pressure'].loc[:, nid].values
                result.node_pressure[nid] = arr
            except (KeyError, AttributeError):
                pass
        
        # 节点流量（用水量）
        for nid, node in self.network.nodes.items():
            try:
                arr = wntr_results.node['demand'].loc[:, nid].values
                result.node_demand[nid] = arr
            except (KeyError, AttributeError):
                pass
        
        # 管段流量
        for lid, link in self.network.links.items():
            try:
                arr = wntr_results.link['flowrate'].loc[:, lid].values
                result.link_flow[lid] = arr
            except (KeyError, AttributeError):
                pass
        
        # 管段流速
        for lid, link in self.network.links.items():
            try:
                arr = wntr_results.link['velocity'].loc[:, lid].values
                result.link_velocity[lid] = arr
            except (KeyError, AttributeError):
                pass
        
        # 滴头流量（从压力手动计算，WNTRSimulator 不自动计算 emitter flow）
        for nid, node in self.network.nodes.items():
            if hasattr(node, "emitter_k") and node.emitter_k > 0:
                pressure_arr = result.node_pressure.get(nid)
                if pressure_arr is not None and len(pressure_arr) > 0:
                    # q (L/h) = k * max(P, 0)^x  （k 单位 L/h, P 单位 m）
                    # 统一公式，与迭代引擎(IterativeWNTRSimulatorEngine)一致：
                    # PC 滴头(x≈0.05)在工作压力下 P^x≈1 结果近似额定值，
                    # 压力为 0 时正确归零——原先恒报 k 会虚报无压滴头流量
                    flow_arr = node.emitter_k * (
                        np.maximum(pressure_arr, 0) ** node.emitter_x)
                    result.emitter_flow[nid] = flow_arr
        
        return result
