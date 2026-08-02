"""NewProjectDialog — 新建 aQuaDrip 项目对话框

选择保存位置、可选导入正射影像和 DEM，确定后生成 GPKG + QGZ。
"""

import os
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QMessageBox, QGroupBox,
)
from qgis.PyQt.QtCore import Qt


class NewProjectDialog(QDialog):
    """新建 aQuaDrip 项目对话框

    收集:
      - 项目名称（用于生成 .gpkg / .qgz 文件名）
      - 保存目录
      - 可选正射影像路径
      - 可选 DEM 路径

    使用方式:
        dlg = NewProjectDialog(iface)
        if dlg.exec() == QDialog.Accepted:
            gpkg = dlg.gpkg_path()
            qgz  = dlg.qgz_path()
            ortho = dlg.orthophoto_path()
            dem  = dlg.dem_path()
    """

    def __init__(self, iface, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface

        self.setWindowTitle("aQuaDrip 新建项目")
        self.setMinimumWidth(480)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        self._build_ui()
        self._load_defaults()
        self._connect_signals()

    # ── UI 构建 ──

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ── 项目名称 ──
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("项目名称:"))
        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("输入项目名称")
        name_layout.addWidget(self.edit_name)
        layout.addLayout(name_layout)

        # ── 保存位置 ──
        dir_layout = QHBoxLayout()
        dir_layout.addWidget(QLabel("保存位置:"))
        self.edit_dir = QLineEdit()
        self.edit_dir.setPlaceholderText("选择保存目录")
        self.edit_dir.setReadOnly(True)
        dir_layout.addWidget(self.edit_dir)
        self.btn_browse_dir = QPushButton("浏览...")
        self.btn_browse_dir.clicked.connect(self._on_browse_dir)
        dir_layout.addWidget(self.btn_browse_dir)
        layout.addLayout(dir_layout)

        # ── 可选栅格 ──
        raster_group = QGroupBox("可选栅格数据")
        raster_layout = QVBoxLayout(raster_group)

        # 正射影像
        ortho_layout = QHBoxLayout()
        ortho_layout.addWidget(QLabel("正射影像:"))
        self.edit_ortho = QLineEdit()
        self.edit_ortho.setPlaceholderText("选择 GeoTIFF / 影像文件（可选）")
        self.edit_ortho.setReadOnly(True)
        ortho_layout.addWidget(self.edit_ortho)
        self.btn_browse_ortho = QPushButton("浏览...")
        self.btn_browse_ortho.clicked.connect(self._on_browse_ortho)
        ortho_layout.addWidget(self.btn_browse_ortho)
        raster_layout.addLayout(ortho_layout)

        # DEM
        dem_layout = QHBoxLayout()
        dem_layout.addWidget(QLabel("DEM 高程:"))
        self.edit_dem = QLineEdit()
        self.edit_dem.setPlaceholderText("选择 DEM GeoTIFF 文件（可选）")
        self.edit_dem.setReadOnly(True)
        dem_layout.addWidget(self.edit_dem)
        self.btn_browse_dem = QPushButton("浏览...")
        self.btn_browse_dem.clicked.connect(self._on_browse_dem)
        dem_layout.addWidget(self.btn_browse_dem)
        raster_layout.addLayout(dem_layout)

        layout.addWidget(raster_group)

        # ── 路径预览 ──
        self.label_preview = QLabel()
        self.label_preview.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(self.label_preview)

        # ── 按钮 ──
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)
        self.btn_ok = QPushButton("确定")
        self.btn_ok.setStyleSheet("font-weight: bold;")
        self.btn_ok.clicked.connect(self._on_accept)
        btn_layout.addWidget(self.btn_ok)
        layout.addLayout(btn_layout)

    # ── 默认值 ──

    def _load_defaults(self):
        self.edit_name.setText("aquadrip_project")
        default_dir = os.path.join(os.path.expanduser("~"), "Documents")
        if os.path.isdir(default_dir):
            self.edit_dir.setText(default_dir)
        self._update_preview()

    # ── 信号连接 ──

    def _connect_signals(self):
        self.edit_name.textChanged.connect(self._update_preview)
        self.edit_dir.textChanged.connect(self._update_preview)

    # ── 路径计算 ──

    def project_name(self) -> str:
        return self.edit_name.text().strip()

    def save_directory(self) -> str:
        return self.edit_dir.text().strip()

    def gpkg_path(self) -> str:
        return os.path.join(self.save_directory(),
                           self.project_name() + ".gpkg")

    def qgz_path(self) -> str:
        return os.path.join(self.save_directory(),
                           self.project_name() + ".qgz")

    def orthophoto_path(self) -> str:
        return self.edit_ortho.text().strip()

    def dem_path(self) -> str:
        return self.edit_dem.text().strip()

    # ── 预览更新 ──

    def _update_preview(self):
        name = self.project_name()
        d = self.save_directory()
        if name and d:
            preview = (
                f"将创建:\n"
                f"  📁 {os.path.join(d, name + '.gpkg')}\n"
                f"  📁 {os.path.join(d, name + '.qgz')}"
            )
        elif name:
            preview = "请选择保存位置"
        else:
            preview = "请输入项目名称并选择保存位置"
        self.label_preview.setText(preview)

    # ── 文件浏览 ──

    def _on_browse_dir(self):
        d = QFileDialog.getExistingDirectory(
            self, "选择保存目录",
            self.edit_dir.text() or os.path.expanduser("~"))
        if d:
            self.edit_dir.setText(d)

    def _on_browse_ortho(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择正射影像",
            self.edit_dir.text() or os.path.expanduser("~"),
            "影像文件 (*.tif *.tiff *.img *.png *.jpg);;所有文件 (*)")
        if path:
            self.edit_ortho.setText(path)

    def _on_browse_dem(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 DEM 高程文件",
            self.edit_dir.text() or os.path.expanduser("~"),
            "GeoTIFF (*.tif *.tiff);;所有文件 (*)")
        if path:
            self.edit_dem.setText(path)

    # ── 确定 ──

    def _on_accept(self):
        """校验输入 → 检查文件冲突 → accept"""
        # 校验项目名称
        if not self.project_name():
            QMessageBox.warning(self, "aQuaDrip", "请输入项目名称")
            self.edit_name.setFocus()
            return

        # 校验保存位置
        if not self.save_directory():
            QMessageBox.warning(self, "aQuaDrip", "请选择保存目录")
            return
        if not os.path.isdir(self.save_directory()):
            QMessageBox.warning(
                self, "aQuaDrip",
                f"保存目录不存在:\n{self.save_directory()}")
            return

        # 校验项目名称不含非法字符
        illegal = set(r'\/:*?"<>|')
        if any(c in self.project_name() for c in illegal):
            QMessageBox.warning(
                self, "aQuaDrip",
                "项目名称不能包含以下字符: \\ / : * ? \" < > |")
            self.edit_name.setFocus()
            return

        # 检查 GPKG 文件冲突
        gpkg = self.gpkg_path()
        if os.path.exists(gpkg):
            reply = QMessageBox.question(
                self, "aQuaDrip",
                f"项目文件已存在:\n{gpkg}\n\n是否覆盖？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return

        self.accept()
