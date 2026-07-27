"""校准分析器 — 实测 vs 模拟对比 / 参数校正"""

import numpy as np
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from wdrip.simulation import SimulationResult


class CalibrationAnalyzer:
    """模型校准分析器
    
    将实测水力值与模拟值对比，计算偏差，
    提供参数校正建议。
    """
    
    @staticmethod
    def compare(measured: Dict[str, float],
                simulated: Dict[str, float]) -> Dict:
        """对比实测值与模拟值
        
        Args:
            measured: {节点ID: 实测压力值 (m)}
            simulated: {节点ID: 模拟压力值 (m)}
            
        Returns:
            对比结果，包含每个节点的偏差和整体统计
        """
        if not measured or not simulated:
            return {"error": "缺少实测或模拟数据"}
        
        comparisons = []
        abs_errors = []
        rel_errors = []
        
        for nid, meas_val in measured.items():
            sim_val = simulated.get(nid)
            if sim_val is None:
                continue
            
            abs_err = sim_val - meas_val
            rel_err = abs_err / meas_val * 100 if meas_val != 0 else 0
            
            comparisons.append({
                "节点": nid,
                "实测值": meas_val,
                "模拟值": float(sim_val),
                "绝对偏差": round(abs_err, 3),
                "相对偏差(%)": round(rel_err, 2),
            })
            abs_errors.append(abs(abs_err))
            rel_errors.append(abs(rel_err))
        
        if not comparisons:
            return {"error": "无匹配的节点"}
        
        abs_errs = np.array(abs_errors)
        rel_errs = np.array(rel_errors)
        
        return {
            "节点对比": comparisons,
            "统计": {
                "RMSE": round(float(np.sqrt(np.mean(abs_errs**2))), 3),
                "MAE": round(float(np.mean(abs_errs)), 3),
                "MAPE(%)": round(float(np.mean(rel_errs)), 2),
                "最大绝对偏差": round(float(np.max(abs_errs)), 3),
                "最大相对偏差(%)": round(float(np.max(rel_errs)), 2),
            },
            "节点数": len(comparisons),
        }
    
    @staticmethod
    def suggest_roughness_adjustment(
        measured: Dict[str, float],
        simulated: Dict[str, float],
        network
    ) -> List[Dict]:
        """建议糙率系数 C 值调整
        
        如果模拟值普遍高于实测值（模拟压力偏高），
        说明实际管道比模拟的更粗糙 → 降低 C 值。
        反之则提高 C 值。
        
        Args:
            measured: 实测压力
            simulated: 模拟压力
            network: DripNetwork（用于获取管道信息）
            
        Returns:
            调整建议列表
        """
        if not measured or not simulated:
            return []
        
        suggestions = []
        
        # 计算平均偏差方向
        bias = np.mean([
            simulated.get(nid, 0) - meas
            for nid, meas in measured.items()
            if nid in simulated
        ])
        
        # 偏差方向决定 C 值调整方向
        if abs(bias) < 0.5:
            return [{"建议": "偏差较小，无需调整"}]
        
        direction = "提高" if bias < 0 else "降低"
        delta = min(abs(bias) * 5, 20)  # 每米偏差调整 5 个 C 值，上限 20
        
        for lid, link in network.links.items():
            if hasattr(link, "roughness"):
                old_c = link.roughness
                new_c = old_c + (delta if bias < 0 else -delta)
                new_c = max(80, min(150, new_c))  # C 值合理范围 80~150
                suggestions.append({
                    "管道": lid,
                    "当前C值": old_c,
                    "建议C值": round(new_c, 0),
                    "调整": f"{direction} {abs(old_c - new_c):.0f}",
                })
        
        return suggestions
    
    @staticmethod
    def report(measured: Dict[str, float],
               simulated: Dict[str, float],
               network=None) -> Dict:
        """生成完整校准报告"""
        comparison = CalibrationAnalyzer.compare(measured, simulated)
        
        if "error" in comparison:
            return comparison
        
        suggestions = []
        if network:
            suggestions = CalibrationAnalyzer.suggest_roughness_adjustment(
                measured, simulated, network
            )
        
        stats = comparison["统计"]
        
        # 评价
        mape = stats["MAPE(%)"]
        if mape < 5:
            grade = "✅ 优秀"
            note = "模型模拟结果与实测高度一致"
        elif mape < 10:
            grade = "✅ 良好"
            note = "模拟结果在可接受范围内"
        elif mape < 20:
            grade = "⚠️ 一般"
            note = "建议进行参数校正"
        else:
            grade = "❌ 差"
            note = "模型需要重新校准"
        
        return {
            "评价": grade,
            "说明": note,
            "统计": stats,
            "节点详情": comparison["节点对比"],
            "校正建议": suggestions,
        }
