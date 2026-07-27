"""水肥分析器 — 浓度运移 / 均匀度"""

import numpy as np
from typing import Dict, List, Optional, Tuple


class FertigationAnalyzer:
    """水肥一体化分析器
    
    基于 WNTR 水质模拟结果，分析肥液浓度变化、
    运移时间和分布均匀度。
    """
    
    @staticmethod
    def concentration_curve(node_quality: Dict[str, np.ndarray],
                            node_id: str) -> Dict:
        """指定节点的浓度-时间曲线
        
        Args:
            node_quality: {node_id: 浓度数组}
            node_id: 目标节点
            
        Returns:
            {time: 浓度} 字典或错误信息
        """
        if node_id not in node_quality:
            return {"error": f"节点 {node_id} 无水质数据"}
        
        arr = node_quality[node_id]
        if len(arr) == 0:
            return {"error": "无数据"}
        
        return {
            "节点": node_id,
            "初始浓度": float(arr[0]),
            "最终浓度": float(arr[-1]),
            "最大浓度": float(np.max(arr)),
            "平均浓度": float(np.mean(arr)),
            "浓度曲线": arr.tolist(),
        }
    
    @staticmethod
    def travel_time(node_quality: Dict[str, np.ndarray],
                    source_node: str, target_node: str,
                    threshold: float = 0.5) -> Optional[float]:
        """计算溶质运移时间
        
        从施肥开始到目标节点浓度达到 threshold × 最大浓度 的时间。
        
        Args:
            node_quality: 水质结果
            source_node: 施肥点
            target_node: 观测点
            threshold: 浓度阈值比例
            
        Returns:
            运移时间（秒），无法计算返回 None
        """
        if target_node not in node_quality:
            return None
        
        arr = node_quality[target_node]
        if len(arr) <= 1:
            return None
        
        max_conc = np.max(arr)
        if max_conc <= 0:
            return None
        
        target_conc = max_conc * threshold
        for i, c in enumerate(arr):
            if c >= target_conc:
                return float(i)  # 时间步索引作为近似
        
        return None
    
    @staticmethod
    def uniformity(concentrations: np.ndarray) -> float:
        """肥液分布均匀度
        
        在施肥稳定后，各节点浓度的克里斯琴森均匀度。
        """
        if concentrations is None or len(concentrations) == 0:
            return 0.0
        arr = np.asarray(concentrations, dtype=float)
        mean_c = np.mean(arr)
        if mean_c <= 0:
            return 0.0
        n = len(arr)
        return 100.0 * (1.0 - np.sum(np.abs(arr - mean_c)) / (n * mean_c))
    
    @staticmethod
    def analyze(node_quality: Dict[str, np.ndarray],
                emitter_nodes: Optional[List[str]] = None) -> Dict:
        """综合分析水肥模拟结果
        
        Args:
            node_quality: 水质结果 {node_id: 浓度数组}
            emitter_nodes: 滴头节点列表（可选，用于计算滴头处均匀度）
            
        Returns:
            分析结果字典
        """
        if not node_quality:
            return {"error": "无水质数据"}
        
        result = {}
        
        # 各节点最终浓度
        final_concs = {}
        for nid, arr in node_quality.items():
            if len(arr) > 0:
                final_concs[nid] = float(arr[-1])
        result["各节点最终浓度"] = final_concs
        
        # 整体浓度统计
        all_final = list(final_concs.values())
        if all_final:
            result["平均浓度"] = float(np.mean(all_final))
            result["最大浓度"] = float(np.max(all_final))
            result["最小浓度"] = float(np.min(all_final))
            result["浓度均匀度"] = round(
                FertigationAnalyzer.uniformity(np.array(all_final)), 1
            )
        
        # 滴头处浓度均匀度
        if emitter_nodes:
            em_concs = [final_concs[nid] for nid in emitter_nodes
                       if nid in final_concs]
            if em_concs:
                result["滴头处浓度均匀度"] = round(
                    FertigationAnalyzer.uniformity(np.array(em_concs)), 1
                )
        
        return result
