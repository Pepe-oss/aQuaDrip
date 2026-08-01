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
    """
    
    def __init__(self, network: 'DripNetwork', engine: Optional['SimulationEngine'] = None):
        from .engine import auto_detect_engine, SimulationEngine
        self.network = network
        self._wn = None  # WNTR WaterNetworkModel
        self._wntr_results = None
        self._engine: SimulationEngine = engine or auto_detect_engine()
        
        if engine is not None:
            self._engine = engine
    
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
            # Pump (Link!)
            wn.add_pump(lid, link.from_node, link.to_node,
                       pump_type="HEAD",
                       pump_parameters=[(link.rated_flow or 0, link.rated_head or 0)])
            logger.debug(f"  Pump: {lid} {link.from_node}→{link.to_node}")
        
        elif hasattr(link, "valve_type"):
            # Valve (Link!)
            vtype = str(link.valve_type.name).upper()
            # links 约定 diameter 为 mm，WNTR 需要 m
            diameter_m = link.diameter / 1000.0 if link.diameter > 0 else None
            wn.add_valve(lid, link.from_node, link.to_node,
                        valve_type=vtype,
                        diameter=diameter_m,
                        setting=link.setting)
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

    def run(self, duration: int = 0, timestep: int = 3600) -> 'SimulationResult':
        """运行水力模拟
        
        Args:
            duration: 模拟时长（seconds）。0=稳态，>0=延时
            timestep: 报告时间步长（seconds）
            
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
            
            # 设置模拟时间
            if duration > 0:
                self._wn.options.time.duration = duration
                self._wn.options.time.report_timestep = timestep
            else:
                self._wn.options.time.duration = 0
            
            # 使用当前引擎运行
            logger.info(f"使用引擎: {self._engine.display_name}")
            wntr_results = self._engine.run(self._wn)
            
            # 提取结果
            result = self._extract_results(wntr_results, duration)
            result.success = True
            result.message = f"模拟成功 (引擎: {self._engine.display_name})"
            
            return result
        
        except Exception as e:
            logger.exception("模拟失败")
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
        
        # 时间步
        result.time_steps = np.array(wntr_results.time)
        
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
                    # q (L/h) = k * P^x  （k 单位 L/h, P 单位 m）
                    # 对于 PC 滴头 (x≈0)，流量 ≈ nominal_flow
                    if node.emitter_x < 0.1:
                        flow_arr = np.full_like(pressure_arr, node.emitter_k)
                    else:
                        flow_arr = node.emitter_k * (np.maximum(pressure_arr, 0) ** node.emitter_x)
                    result.emitter_flow[nid] = flow_arr
        
        return result
