"""均匀度分析器 — CU / DU / EU"""

import numpy as np
from typing import Dict, List, Optional, Tuple


class UniformityAnalyzer:
    """滴灌均匀度分析器
    
    提供克里斯琴森均匀度(CU)、低四分之一均匀度(DU)、
    灌水均匀度(EU)三种指标。
    """
    
    @staticmethod
    def cu(flows: np.ndarray) -> float:
        """克里斯琴森均匀度 Christiansen Uniformity (%)
        
        CU = 100 × (1 - Σ|qᵢ - q̄| / (n × q̄))
        
        ASAE EP405.1 标准: CU ≥ 85%
        """
        if flows is None or len(flows) == 0:
            return 0.0
        flows = np.asarray(flows, dtype=float)
        mean_q = np.mean(flows)
        if mean_q <= 0:
            return 0.0
        n = len(flows)
        return 100.0 * (1.0 - np.sum(np.abs(flows - mean_q)) / (n * mean_q))
    
    @staticmethod
    def du(flows: np.ndarray) -> float:
        """低四分之一均匀度 Distribution Uniformity (%)
        
        DU = 100 × q̄_lq / q̄
        q̄_lq = 流量最低的 1/4 部分的平均流量
        """
        if flows is None or len(flows) == 0:
            return 0.0
        flows = np.asarray(flows, dtype=float)
        mean_q = np.mean(flows)
        if mean_q <= 0:
            return 0.0
        # 取最低 1/4
        sorted_q = np.sort(flows)
        n_lq = max(1, len(sorted_q) // 4)
        mean_lq = np.mean(sorted_q[:n_lq])
        return 100.0 * mean_lq / mean_q
    
    @staticmethod
    def eu(flows: np.ndarray, pressures: np.ndarray, emitter_x: float = 0.5) -> float:
        """灌水均匀度 Emission Uniformity (%)
        
        考虑压力变异和发射器流态指数的影响。
        EU = 100 × (q_min / q_avg)
        其中 q_min 是最小压力下滴头的流量
        """
        if flows is None or len(flows) == 0:
            return 0.0
        flows = np.asarray(flows, dtype=float)
        pressures = np.asarray(pressures, dtype=float)
        mean_q = np.mean(flows)
        if mean_q <= 0 or len(pressures) == 0:
            return 0.0
        # 取最小压力对应的 1/4 最低压力节点
        sorted_idx = np.argsort(pressures)
        n_lq = max(1, len(sorted_idx) // 4)
        low_p_idx = sorted_idx[:n_lq]
        mean_flow_low_p = np.mean(flows[low_p_idx])
        return 100.0 * mean_flow_low_p / mean_q
    
    @staticmethod
    def evaluate(cu: float) -> Dict[str, str]:
        """评价 CU 等级 (ASAE EP405.1)"""
        if cu >= 95:
            return {"等级": "优秀", "评价": "Excellent", "建议": ""}
        elif cu >= 90:
            return {"等级": "良好", "评价": "Good", "建议": ""}
        elif cu >= 85:
            return {"等级": "合格", "评价": "Acceptable", "建议": "满足 ASAE 标准"}
        elif cu >= 75:
            return {"等级": "较差", "评价": "Poor", "建议": "建议检查: 毛管长度/管径/压力"}
        else:
            return {"等级": "不可接受", "评价": "Unacceptable", "建议": "必须调整设计: 加大管径/缩短毛管/提高压力或使用PC滴头"}
    
    @staticmethod
    def analyze_all(emitter_flows: Dict[str, np.ndarray],
                    node_pressures: Optional[Dict[str, np.ndarray]] = None,
                    emitter_x: float = 0.5) -> Dict:
        """综合分析所有滴头
        
        Args:
            emitter_flows: {node_id: 流量数组}
            node_pressures: {node_id: 压力数组}（可选，用于 EU）
            emitter_x: 滴头流态指数
            
        Returns:
            包含所有均匀度指标的字典
        """
        if not emitter_flows:
            return {"error": "无滴头流量数据"}
        
        # 收集稳态流量（取第一个时间步）
        flows = np.array([float(v[0]) for v in emitter_flows.values() if len(v) > 0])
        
        cu = UniformityAnalyzer.cu(flows)
        du_val = UniformityAnalyzer.du(flows)
        
        result = {
            "滴头数": len(flows),
            "首端流量": float(np.max(flows)),
            "末端流量": float(np.min(flows)),
            "平均流量": float(np.mean(flows)),
            "流量标准差": float(np.std(flows)),
            "CU": round(cu, 1),
            "DU": round(du_val, 1),
            "CU评价": UniformityAnalyzer.evaluate(cu),
            "衰减率": round((1 - np.min(flows) / np.max(flows)) * 100, 1) if np.max(flows) > 0 else 0,
        }
        
        # EU（如果有压力数据）
        if node_pressures and emitter_x is not None:
            pressures = np.array([float(v[0]) for v in node_pressures.values() if len(v) > 0])
            if len(pressures) == len(flows):
                eu_val = UniformityAnalyzer.eu(flows, pressures, emitter_x)
                result["EU"] = round(eu_val, 1)
        
        return result
