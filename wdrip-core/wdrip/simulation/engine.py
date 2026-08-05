"""模拟引擎策略 — 支持切换不同的求解器"""

from abc import ABC, abstractmethod
import logging
from typing import Optional, TYPE_CHECKING

import numpy as np

from .result import SimulationResult

if TYPE_CHECKING:
    import wntr

logger = logging.getLogger(__name__)


class SimulationEngine(ABC):
    """模拟引擎基类"""
    
    name = "base"
    display_name = "Base Engine"
    description = ""
    
    def __init__(self):
        self._wn: Optional['wntr.network.WaterNetworkModel'] = None
    
    @abstractmethod
    def run(self, wn_model) -> SimulationResult:
        ...


class WNTRSimulatorEngine(SimulationEngine):
    """WNTRSimulator — Python 原生求解器
    
    优点: 无需外部依赖，跨平台
    局限: 不支持 emitter_coefficient，忽略滴头引起的沿程损失
    """
    
    name = "wntr"
    display_name = "WNTRSimulator (Python原生)"
    description = "纯 Python 求解器，无需 EPANET 依赖，但不计算滴头沿程损失"
    
    def run(self, wn_model) -> SimulationResult:
        import wntr
        self._wn = wn_model
        sim = wntr.sim.WNTRSimulator(wn_model)
        wntr_results = sim.run_sim()
        return wntr_results


class EpanetSimulatorEngine(SimulationEngine):
    """EpanetSimulator — 调用 EPANET C 库
    
    优点: 完全精确，支持 emitter_coefficient，计算沿程损失
    局限: 需要系统安装 EPANET 库
    """
    
    name = "epanet"
    display_name = "EpanetSimulator (EPANET库)"
    description = "调用 EPANET C 库，结果精确，需安装 EPANET"
    
    def run(self, wn_model) -> SimulationResult:
        import tempfile, os, wntr
        self._wn = wn_model
        # WNTR EpanetSimulator 默认把 temp.inp/.bin/.rpt 写到当前目录，
        # 在 macOS QGIS 插件沙箱中当前目录可能只读（Errno 30）。
        # 改为写到系统临时目录。
        tmpdir = tempfile.mkdtemp(prefix='aquadrip_epanet_')
        logger.debug(f"EPANET 临时目录: {tmpdir}")
        try:
            file_prefix = os.path.join(tmpdir, 'temp')
            sim = wntr.sim.EpanetSimulator(wn_model)
            # 显式禁用 hydraulics file 的 load/save，避免在某些环境下
            # EPANET 内部尝试打开 hydraulics 文件失败（Error 305）
            wntr_results = sim.run_sim(file_prefix=file_prefix,
                                       use_hyd=False, save_hyd=False)
        finally:
            # 清理临时文件
            import shutil
            try:
                shutil.rmtree(tmpdir)
            except Exception:
                pass
        return wntr_results


class IterativeWNTRSimulatorEngine(SimulationEngine):
    """迭代式 WNTRSimulator — 通过迭代逼近 emitter 真实流量
    
    在 WNTRSimulator 基础上，通过"设置 demand→求解→修正→再求解"迭代，
    逼近包含沿程损失的正确结果，无需 EPANET 库。
    """
    
    name = "iterative"
    display_name = "WNTR迭代求解器"
    description = "通过迭代逼近 emitter 沿程损失，无需 EPANET，但速度较慢"
    
    def __init__(self, max_iter: int = 10, tolerance: float = 1e-7,
                 progress_callback=None):
        super().__init__()
        # tolerance 单位 m³/s：1e-7 ≈ 0.36 L/h，与滴头流量量级匹配
        #（原默认 0.001 m³/s = 3.6 m³/h，远大于滴头流量会假收敛）
        self.max_iter = max_iter
        self.tolerance = tolerance
        # 可选进度回调: callback(percent: int, message: str)
        self.progress_callback = progress_callback
    
    def run(self, wn_model) -> SimulationResult:
        import wntr
        self._wn = wn_model
        
        # 识别 emitter 节点并记录原始参数
        emitter_nodes = []
        for nid in wn_model.node_name_list:
            node = wn_model.get_node(nid)
            if hasattr(node, 'emitter_coefficient') and node.emitter_coefficient is not None and node.emitter_coefficient > 0:
                emitter_nodes.append({
                    'id': nid,
                    'coeff': node.emitter_coefficient,
                    'exponent': getattr(node, 'emitter_exponent', 0.5),
                })
                # 初始 demand = 0（通过 demand_timeseries_list）
                wn_node_start = wn_model.get_node(nid)
                if wn_node_start and wn_node_start.demand_timeseries_list:
                    wn_node_start.demand_timeseries_list[0].base_value = 0
        
        prev_flows = {n['id']: 0.0 for n in emitter_nodes}
        
        for iteration in range(self.max_iter):
            sim = wntr.sim.WNTRSimulator(wn_model)
            wntr_results = sim.run_sim()
            
            # 从压力计算真实 emitter 流量，更新 base_demand
            max_change = 0
            for n in emitter_nodes:
                try:
                    # 用 iloc[0] 取首个时间步：WNTR 1.5 在同一模型上重复
                    # run_sim() 时结果时间戳会推进（0→3600→7200…），
                    # loc[0] 只在首次求解有效，后续会 KeyError 误判 p=0
                    p = float(wntr_results.node['pressure'][n['id']].iloc[0])
                except (KeyError, IndexError):
                    p = 0
                
                if p > 0:
                    # 流量 = coeff × P^exponent (WNTR 单位 m³/s)
                    q_cms = n['coeff'] * (p ** n['exponent'])
                else:
                    q_cms = 0
                
                change = abs(q_cms - prev_flows[n['id']])
                max_change = max(max_change, change)
                prev_flows[n['id']] = q_cms
                # WNTR 1.x: base_demand 是只读属性，通过 demand_timeseries_list 修改
                wn_node = wn_model.get_node(n['id'])
                if wn_node and wn_node.demand_timeseries_list:
                    wn_node.demand_timeseries_list[0].base_value = q_cms
            
            logger.debug(f"  迭代{iteration+1}: max_change={max_change:.6f}")
            if self.progress_callback:
                pct = int((iteration + 1) / self.max_iter * 100)
                self.progress_callback(pct, f"迭代 {iteration+1}/{self.max_iter}")
            if max_change < self.tolerance:
                logger.debug(f"  收敛于迭代{iteration+1}")
                break
        
        # 最终结果
        sim = wntr.sim.WNTRSimulator(wn_model)
        return sim.run_sim()


def auto_detect_engine() -> SimulationEngine:
    """自动检测可用的最佳引擎

    滴灌场景含 emitter 滴头，WNTRSimulator 会忽略 emitter_coefficient
    （管网静压、不出水），因此 EPANET 库缺失时回退到迭代求解器
    而非 WNTRSimulator。

    检测策略：
    1. 尝试通过 WNTR 内置的 EPANET toolkit 加载库（WNTR pip 安装时自带
       各平台的预编译 libepanet2，无需额外安装）
    2. 如果 WNTR 自带库不可用，回退到迭代求解器
    """
    try:
        from wntr.epanet.toolkit import ENepanet
        en = ENepanet()
        if en.ENlib is not None:
            logger.info("检测到 WNTR 内置 EPANET 库，使用 EpanetSimulator")
            return EpanetSimulatorEngine()
    except Exception:
        pass
    logger.info("WNTR 内置 EPANET 库不可用，使用 WNTR 迭代求解器（逼近 emitter 出水）")
    return IterativeWNTRSimulatorEngine()
