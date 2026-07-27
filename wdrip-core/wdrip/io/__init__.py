"""io — 数据导入导出

- ProjectFile: .aqd 工程文件 (ZIP+JSON)
- InpWriter: EPANET INP 文件导出
- ShapeReader: Shapefile 导入（需 geopandas）
"""

from .project import ProjectFile, ProjectMetadata, PROJECT_VERSION
from .inp_writer import InpWriter
from .shape_reader import ShapeReader

__all__ = [
    "ProjectFile",
    "ProjectMetadata",
    "PROJECT_VERSION",
    "InpWriter",
    "ShapeReader",
]
