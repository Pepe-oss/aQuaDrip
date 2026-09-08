"""SimHistory — 模拟历史记录管理（v2 分片存储）

历史架构问题（v1）：所有记录存在单个 JSON 数组文件（.simhistory）中，
每次模拟 add() 都要"读全文件 → append → 重写全文件"。管网展开后单条
记录可达 65MB（每个滴头的压力/流量/坐标/几何），轮灌多轮次后文件涨到
1GB+，导致：
  - add() 读 1GB + 写 1GB（每次模拟结束卡 1~2 分钟）
  - load() 解析 1GB（可视化/承压/校准等任何读取都卡几十秒）
  - 数 GB Python 对象压爆内存，整个 QGIS 都变慢

v2 架构："一条记录一个 gzip 分片 + 轻量索引"：
  <base>.simhistory.d/index.json          摘要索引（KB 级，毫秒读取）
  <base>.simhistory.d/rec_000001.json.gz  单条完整记录（紧凑 JSON + gzip）

各操作代价：
  add()       追加一个分片（O(1)，不再重写全文件）
  summaries() 只读索引（毫秒级，列表 UI 用）
  latest()/get(i) 只解压一条分片（百毫秒级）
  load()      顺序读全部分片（兼容保留，仅诊断用）

旧版单文件在首次访问时自动流式迁移（逐条解析，不整载入内存），
原文件保留为 .simhistory.bak，确认无误后可手动删除。
"""

import gzip
import json
import os
from datetime import datetime
from typing import Dict, Iterator, List, Optional


class SimHistory:
    """模拟历史记录管理（v2 分片存储）

    存储路径：aquadrip.gpkg → aquadrip.simhistory.d/（目录）
    自动裁剪：超过 MAX_RECORDS 条时自动保留最新记录
    """

    MAX_RECORDS = 100  # 自动保留的最大记录数

    def __init__(self, gpkg_path: str):
        self.gpkg_path = gpkg_path
        if gpkg_path.endswith(".gpkg"):
            base = gpkg_path[:-5]
        else:
            base = gpkg_path
        self.path = base + ".simhistory"       # v1 单文件路径（迁移源）
        self.dir = base + ".simhistory.d"      # v2 分片目录
        self.index_path = os.path.join(self.dir, "index.json")
        self._index = None  # {"next_seq": int, "records": [summary...]}

    # ── 内部：索引与分片 ──

    def _ensure_ready(self):
        """加载（必要时迁移/重建）索引。幂等。"""
        if self._index is not None:
            return
        if os.path.exists(self.index_path):
            try:
                with open(self.index_path, "r", encoding="utf-8") as f:
                    self._index = json.load(f)
                if not isinstance(self._index, dict) \
                        or "records" not in self._index:
                    raise ValueError("bad index")
            except (json.JSONDecodeError, OSError, ValueError):
                # 索引损坏 → 从分片重建（保留可能已加载的部分）
                self._index = None
                self._rebuild_index()
            # v2 索引存在但又出现了旧版单文件：迁移期间用户未重启
            # QGIS、旧版插件代码又写入了新记录 → 追加合并，不丢数据
            if os.path.exists(self.path):
                self._migrate_legacy()
            return
        if os.path.exists(self.path):
            self._migrate_legacy()
            return
        self._index = {"next_seq": 1, "records": []}

    def _shard_path(self, seq: int) -> str:
        return os.path.join(self.dir, f"rec_{seq:06d}.json.gz")

    def _write_shard(self, seq: int, record: dict, level: int = 6):
        os.makedirs(self.dir, exist_ok=True)
        tmp = self._shard_path(seq) + ".tmp"
        with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=level) as f:
            json.dump(record, f, ensure_ascii=False,
                      separators=(",", ":"))
        os.replace(tmp, self._shard_path(seq))

    def _read_shard(self, seq: int) -> Optional[dict]:
        p = self._shard_path(seq)
        if not os.path.exists(p):
            return None
        try:
            with gzip.open(p, "rt", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, EOFError, json.JSONDecodeError):
            return None

    def _write_index(self):
        os.makedirs(self.dir, exist_ok=True)
        tmp = self.index_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._index, f, ensure_ascii=False,
                      separators=(",", ":"))
        os.replace(tmp, self.index_path)

    def _rebuild_index(self):
        """从分片文件重建索引（索引损坏时的自愈路径，较慢但保数据）"""
        os.makedirs(self.dir, exist_ok=True)
        records = []
        max_seq = 0
        for name in sorted(os.listdir(self.dir)):
            if not (name.startswith("rec_")
                    and name.endswith(".json.gz")):
                continue
            try:
                seq = int(name[4:10])
            except ValueError:
                continue
            rec = self._read_shard(seq)
            if rec is not None:
                records.append({**_summary_of(rec), "seq": seq})
                max_seq = max(max_seq, seq)
        records.sort(key=lambda s: s["seq"])
        self._index = {"next_seq": max_seq + 1, "records": records}
        self._write_index()

    def _trim_to_cap(self):
        """超过 MAX_RECORDS 时删除最老分片"""
        changed = False
        recs = self._index["records"]
        while len(recs) > self.MAX_RECORDS:
            oldest = recs.pop(0)
            try:
                os.remove(self._shard_path(oldest["seq"]))
            except OSError:
                pass
            changed = True
        if changed:
            self._write_index()

    # ── v1 迁移 ──

    def _migrate_legacy(self):
        """把 v1 单文件 JSON 数组流式迁移为 v2 分片

        逐条 raw_decode（不整载入内存——1GB 文件整载会吃 5GB+ 内存）。
        v2 索引已存在时（迁移期间旧版插件又写入了单文件）追加合并。
        迁移成功后原文件改名为 .simhistory.bak（保留用户数据）。
        """
        t0 = datetime.now()
        appending = self._index is not None
        print(f"[aQuaDrip] 历史文件迁移中（一次性）: {self.path} "
              f"({os.path.getsize(self.path) / 1e6:.0f} MB)…")
        seq = self._index["next_seq"] if appending else 1
        if not appending:
            self._index = {"next_seq": 1, "records": []}
        records = self._index["records"]
        corrupt = False
        try:
            for rec in _iter_json_array(self.path):
                summary = _summary_of(rec)
                summary["seq"] = seq
                # 压缩级别 1：一次性大文件迁移以速度优先（快 ~40%）
                self._write_shard(seq, rec, level=1)
                records.append(summary)
                seq += 1
        except (json.JSONDecodeError, OSError) as e:
            # 损坏的 v1 文件：保留已迁移出的记录，原文件留 .corrupt.bak
            corrupt = True
            print(f"[aQuaDrip] ⚠️ 旧历史文件解析中断（{e}），"
                  f"已迁移 {len(records)} 条")
        self._index["next_seq"] = seq
        self._trim_to_cap()
        self._write_index()
        bak = self.path + (".corrupt.bak" if corrupt else ".bak")
        try:
            os.replace(self.path, bak)
        except OSError:
            pass
        dt = (datetime.now() - t0).total_seconds()
        print(f"[aQuaDrip] 历史文件迁移完成: 本次 {len(records)} 条，"
              f"耗时 {dt:.0f}s。原文件已保留为 {bak}，"
              f"确认无误后可手动删除")

    # ── 公共 API ──

    def summaries(self) -> List[dict]:
        """全部记录的轻量摘要（最新在前，毫秒级）

        摘要字段：timestamp/cu/du/message/计数/rotation_id/shift_index，
        不含压力/流量/坐标等大数据——列表 UI 用它，不解析分片。
        """
        self._ensure_ready()
        return list(reversed(self._index["records"]))

    def latest(self) -> Optional[dict]:
        """最新一条完整记录（只读一个分片，百毫秒级）"""
        self._ensure_ready()
        recs = self._index["records"]
        if not recs:
            return None
        return self._read_shard(recs[-1]["seq"])

    def load(self) -> List[dict]:
        """加载全部历史记录（最新在前）。仅诊断用——会读全部分片。"""
        self._ensure_ready()
        out = []
        for s in reversed(self._index["records"]):
            rec = self._read_shard(s["seq"])
            if rec is not None:
                out.append(rec)
        return out

    def add(self, cu: float, du: float,
            node_pressure: Dict[str, float],
            link_flow: Dict[str, float],
            link_velocity: Dict[str, float],
            emitter_flow: Dict[str, float],
            node_coords: Dict[str, list],
            message: str = "",
            timestamp: Optional[str] = None,
            link_endpoints: Optional[Dict[str, list]] = None,
            link_geometry: Optional[Dict[str, list]] = None,
            rotation_id: Optional[str] = None,
            shift_index: Optional[int] = None) -> dict:
        """新增一条记录（O(1)：写一个分片 + 更新 KB 级索引）

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
            link_endpoints: {link_id: [from_node, to_node]}，
                用于可视化时重建分段管道几何（拓扑切段产生的
                L{fid}_p{n} 不在 aqd_pipes 中）
            link_geometry: {link_id: [[x,y], ...]}，每个 link 的折线
                顶点（含转弯），可视化时按此画线以保留管道真实形状

        Returns:
            记录摘要
        """
        if timestamp is None:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        self._ensure_ready()
        record = {
            "timestamp": timestamp,
            "cu": round(float(cu), 2),
            "du": round(float(du), 2),
            "message": message,
            "node_count": len(node_pressure),
            "pipe_count": len(link_flow),
            "emitter_count": len(emitter_flow),
            "rotation_id": rotation_id,
            "shift_index": shift_index,
            "node_pressure": {k: round(float(v), 4)
                              for k, v in node_pressure.items()},
            # link_flow / link_velocity 存储为 L/h 和 m/s 便于可视化直接显示。
            # 原始 WNTR 单位为 m³/s（毛管段流量低至 1e-7），标签显示全是 0；
            # 转换为 L/h 后量级合理（单毛管段 1~50 L/h）。
            "link_flow": {k: float(v) * 3600 * 1000  # m³/s → L/h
                          for k, v in link_flow.items()},
            "link_velocity": {k: float(v) for k, v in link_velocity.items()},
            "emitter_flow": {k: round(float(v), 4)
                             for k, v in emitter_flow.items()},
            "node_coords": {k: [round(c[0], 7), round(c[1], 7)]
                            for k, c in node_coords.items()},
            "link_endpoints": {k: list(v)
                               for k, v in (link_endpoints or {}).items()},
            # 坐标保留 7 位小数：经纬度下 0.0001°≈11m，4 位小数会让
            # 相邻滴头（间距 0.3m）叠合到同一点。7 位 ≈ 1cm 精度。
            "link_geometry": {k: [[round(p[0], 7), round(p[1], 7)]
                                  for p in pts]
                              for k, pts in (link_geometry or {}).items()},
        }

        seq = self._index["next_seq"]
        self._index["next_seq"] = seq + 1
        self._write_shard(seq, record)
        self._index["records"].append({**_summary_of(record), "seq": seq})
        self._trim_to_cap()
        self._write_index()

        return {
            "timestamp": timestamp,
            "cu": record["cu"],
            "du": record["du"],
        }

    def delete(self, index: int) -> bool:
        """删除指定索引的记录（index 基于 summaries()/load() 的倒序索引）

        Returns:
            True 表示删除成功
        """
        self._ensure_ready()
        recs = self._index["records"]
        real_index = len(recs) - 1 - index
        if real_index < 0 or real_index >= len(recs):
            return False
        summary = recs.pop(real_index)
        try:
            os.remove(self._shard_path(summary["seq"]))
        except OSError:
            pass
        self._write_index()
        return True

    def get(self, index: int) -> Optional[dict]:
        """获取指定索引的完整记录（index 基于倒序索引，只读一个分片）"""
        self._ensure_ready()
        recs = self._index["records"]
        real_index = len(recs) - 1 - index
        if 0 <= real_index < len(recs):
            return self._read_shard(recs[real_index]["seq"])
        return None

    def purge_all(self) -> int:
        """清空全部历史记录，返回删除条数"""
        self._ensure_ready()
        count = len(self._index["records"])
        for s in self._index["records"]:
            try:
                os.remove(self._shard_path(s["seq"]))
            except OSError:
                pass
        self._index = {"next_seq": self._index["next_seq"], "records": []}
        self._write_index()
        return count

    @property
    def count(self) -> int:
        """当前记录总数"""
        self._ensure_ready()
        return len(self._index["records"])

    @staticmethod
    def summary(record: dict) -> str:
        """生成记录摘要文本（用于列表显示）"""
        # 函数内导入：保持本模块纯 stdlib（可在无 QGIS 环境测试/复用）
        from qgis.PyQt.QtWidgets import QApplication
        ts = record.get("timestamp", "?")
        cu = record.get("cu", 0)
        du = record.get("du", 0)
        n = record.get("emitter_count", 0)
        rid = record.get("rotation_id")
        si = record.get("shift_index")
        if rid is not None and si is not None:
            return QApplication.translate("SimHistory", "{0}  [轮灌 {1} 轮次{2}]  CU={3:.1f}%  DU={4:.1f}%  滴头={5}").format(ts, rid, si+1, cu, du, n)
        return QApplication.translate("SimHistory", "{0}  CU={1:.1f}%  DU={2:.1f}%  滴头={3}").format(ts, cu, du, n)


# ── 模块级辅助 ──

_SUMMARY_KEYS = ("timestamp", "cu", "du", "message", "node_count",
                 "pipe_count", "emitter_count", "rotation_id", "shift_index")


def _summary_of(record: dict) -> dict:
    """从完整记录提取轻量摘要字段"""
    return {k: record.get(k) for k in _SUMMARY_KEYS}


def _iter_json_array(path: str, chunk_size: int = 1 << 20) -> Iterator[dict]:
    """流式迭代 JSON 数组文件，逐条 yield（不整载入内存）

    配合 json.JSONDecoder.raw_decode 增量解析。1GB 的 v1 历史文件
    用 json.load 整载会吃 5GB+ 内存，必须流式。
    """
    dec = json.JSONDecoder()
    with open(path, "r", encoding="utf-8") as f:
        buf = f.read(chunk_size)
        # 跳到数组开始
        while True:
            i = buf.find("[")
            if i >= 0:
                buf = buf[i + 1:]
                break
            if not buf:
                return  # 不是数组
            buf = f.read(chunk_size)
            if not buf:
                return

        while True:
            # 跳过空白与记录间的分隔逗号（可能跨越 chunk 边界）
            while True:
                buf = buf.lstrip()
                if not buf:
                    buf = f.read(chunk_size)
                    if not buf:
                        return
                    continue
                if buf[0] == ",":
                    buf = buf[1:]
                    continue
                break
            if buf.startswith("]"):
                return
            # 增量取一个对象
            while True:
                try:
                    obj, end = dec.raw_decode(buf)
                    break
                except json.JSONDecodeError:
                    more = f.read(chunk_size)
                    if not more:
                        raise
                    buf += more
            yield obj
            buf = buf[end:]
