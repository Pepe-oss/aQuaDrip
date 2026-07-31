"""SimHistory — 模拟历史记录管理（sidecar JSON 文件）

每次模拟结果存储在与 GPKG 同目录的 .simhistory 文件中，
用于历史对比和可视化。
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional


class SimHistory:
    """模拟历史记录管理（sidecar JSON 文件）

    存储路径：aquadrip.gpkg → aquadrip.simhistory（同目录同名）
    """

    def __init__(self, gpkg_path: str):
        self.gpkg_path = gpkg_path
        if gpkg_path.endswith(".gpkg"):
            self.path = gpkg_path[:-5] + ".simhistory"
        else:
            self.path = gpkg_path + ".simhistory"

    def load(self) -> List[dict]:
        """加载全部历史记录（最新在前）"""
        if not os.path.exists(self.path):
            return []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                records = json.load(f)
            # 最新的在前（列表末尾是最新，倒序返回）
            return list(reversed(records))
        except (json.JSONDecodeError, OSError):
            return []

    def add(self, cu: float, du: float,
            node_pressure: Dict[str, float],
            link_flow: Dict[str, float],
            link_velocity: Dict[str, float],
            emitter_flow: Dict[str, float],
            node_coords: Dict[str, list],
            message: str = "",
            timestamp: Optional[str] = None) -> dict:
        """新增一条记录

        Args:
            cu: Christiansen 均匀度
            du: 分布均匀度
            node_pressure: {node_id: pressure_m}
            link_flow: {link_id: flow_m3s}
            link_velocity: {link_id: velocity_ms}
            emitter_flow: {emitter_id: flow_Lh}
            node_coords: {node_id: [x, y]}
            message: 模拟引擎消息
            timestamp: 自定义时间戳，缺省用当前时间

        Returns:
            记录摘要
        """
        if timestamp is None:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        records = []
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    records = json.load(f)
            except (json.JSONDecodeError, OSError):
                records = []

        record = {
            "timestamp": timestamp,
            "cu": round(float(cu), 2),
            "du": round(float(du), 2),
            "message": message,
            "node_count": len(node_pressure),
            "pipe_count": len(link_flow),
            "emitter_count": len(emitter_flow),
            "node_pressure": {k: round(float(v), 4)
                              for k, v in node_pressure.items()},
            "link_flow": {k: round(float(v), 6)
                          for k, v in link_flow.items()},
            "link_velocity": {k: round(float(v), 4)
                              for k, v in link_velocity.items()},
            "emitter_flow": {k: round(float(v), 4)
                             for k, v in emitter_flow.items()},
            "node_coords": {k: [round(c[0], 4), round(c[1], 4)]
                            for k, c in node_coords.items()},
        }
        records.append(record)

        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)

        return {
            "timestamp": timestamp,
            "cu": record["cu"],
            "du": record["du"],
        }

    def delete(self, index: int) -> bool:
        """删除指定索引的记录（index 基于 load() 的倒序索引）

        Returns:
            True 表示删除成功
        """
        if not os.path.exists(self.path):
            return False
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                records = json.load(f)
        except (json.JSONDecodeError, OSError):
            return False

        # load() 返回倒序，正向存储中的索引 = len - 1 - index
        real_index = len(records) - 1 - index
        if real_index < 0 or real_index >= len(records):
            return False

        records.pop(real_index)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        return True

    def get(self, index: int) -> Optional[dict]:
        """获取指定索引的完整记录（index 基于 load() 的倒序索引）"""
        records = self.load()
        if 0 <= index < len(records):
            return records[index]
        return None

    @staticmethod
    def summary(record: dict) -> str:
        """生成记录摘要文本（用于列表显示）"""
        ts = record.get("timestamp", "?")
        cu = record.get("cu", 0)
        du = record.get("du", 0)
        n = record.get("emitter_count", 0)
        return f"{ts}  CU={cu:.1f}%  DU={du:.1f}%  滴头={n}"
