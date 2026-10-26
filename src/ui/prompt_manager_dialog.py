"""Diálogo y Widget visual para la gestión de Prompts Maestros y Estilos Narrativos."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.ai.prompt_library import NarrativeStyleDef, PromptItem, PromptLibrary

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROMPTS_MD_FILE = PROJECT_ROOT / "PROMPTS_MAESTROS.md"


class PromptManagerWidget(QWidget):
    """Widget embebible para ver, editar, duplicar, agregar y restaurar Prompts Maestros."""

    prompts_updated = pyqtSignal()

    def __init__(self, library: Optional[PromptLibrary] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.library = library or PromptLibrary()

        self._current_type: str = "mode"  # "mode" | "style" | "custom"
        self._current_id: str = ""
        self.current_orientation: str = "vertical"

        self._init_ui()
        self._populate_selector()

    def set_orientation(self, mode: str):
        self.current_orientation = mode
        if not hasattr(self, "form_box_layout"):
            return

        self.meta_frame.setParent(self.form_box)
        self.editor_frame.setParent(self.form_box)

        def clear_lay(lay):
            while lay.count():
                item = lay.takeAt(0)
                if item.layout():
                    clear_lay(item.layout())

        clear_lay(self.form_box_layout)

        if mode == "vertical":
            self.form_box_layout.addWidget(self.meta_frame, stretch=0)
            self.form_box_layout.addWidget(self.editor_frame, stretch=1)
        else:
            cols = QHBoxLayout()
            cols.setSpacing(12)
            cols.addWidget(self.meta_frame, stretch=42)
            cols.addWidget(self.editor_frame, stretch=58)
            self.form_box_layout.addLayout(cols)

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        # 1. Cabecera
        header_lay = QVBoxLayout()
        title = QLabel("Catálogo Maestro de Prompts y Estilos Narrativos")
        title.setObjectName("titleLabel")
        subtitle = QLabel("Ajusta los System Prompts bajo Meta-Prompting CO-STAR, parámetros de Mistral NeMo y perfil acústico de estilos.")
        subtitle.setObjectName("subtitleLabel")
        header_lay.addWidget(title)
        header_lay.addWidget(subtitle)
        layout.addLayout(header_lay)

        # 2. Barra de Selección y Operaciones Rápidas
        sel_box = QGroupBox("Selección de Prompt o Estilo")
        sel_lay = QHBoxLayout(sel_box)
        sel_lay.setSpacing(8)

        self.combo_items = QComboBox()
        self.combo_items.currentIndexChanged.connect(self._on_item_selected)
        sel_lay.addWidget(QLabel("Elemento Activo:"))
        sel_lay.addWidget(self.combo_items, stretch=1)

        self.btn_duplicate = QPushButton("[ + ] Duplicar como Personalizado")
        self.btn_duplicate.setObjectName("actionButton")
        self.btn_duplicate.clicked.connect(self._duplicate_current)
        sel_lay.addWidget(self.btn_duplicate)

        self.btn_delete = QPushButton("[ × ] Eliminar")
        self.btn_delete.setObjectName("secondaryActionButton")
        self.btn_delete.clicked.connect(self._delete_current)
        sel_lay.addWidget(self.btn_delete)

        layout.addWidget(sel_box)

        # 3. Formulario de Edición Reorganizable (Vertical u Horizontal sin vacíos)
        self.form_box = QGroupBox("Editor de Directrices y Meta-Prompting")
        self.form_box_layout = QVBoxLayout(self.form_box)
        self.form_box_layout.setContentsMargins(10, 8, 10, 8)
        self.form_box_layout.setSpacing(8)

        # Panel izquierdo / superior: Metadatos y Parámetros
        self.meta_frame = QFrame()
        self.meta_lay = QFormLayout(self.meta_frame)
        self.meta_lay.setContentsMargins(0, 0, 0, 0)
        self.meta_lay.setSpacing(6)

        self.edit_name = QLineEdit()
        self.meta_lay.addRow("Nombre descriptivo:", self.edit_name)

        self.lbl_id = QLabel("")
        self.lbl_id.setStyleSheet("color: #64748b; font-family: Consolas, monospace; font-weight: bold;")
        self.meta_lay.addRow("Identificador (ID):", self.lbl_id)

        self.edit_description = QLineEdit()
        self.meta_lay.addRow("Descripción:", self.edit_description)

        self.edit_template = QLineEdit()
        self.edit_template.setPlaceholderText("ej. Texto a enriquecer:\n\n{text}")
        self.meta_lay.addRow("Plantilla de Usuario:", self.edit_template)

        # Hiperparámetros NeMo
        params_row = QHBoxLayout()
        params_row.setSpacing(6)
        self.spin_temp = QDoubleSpinBox()
        self.spin_temp.setRange(0.0, 1.5)
        self.spin_temp.setSingleStep(0.05)
        self.spin_temp.setValue(0.4)

        self.spin_topp = QDoubleSpinBox()
        self.spin_topp.setRange(0.1, 1.0)
        self.spin_topp.setSingleStep(0.05)
        self.spin_topp.setValue(0.9)

        self.spin_ctx = QSpinBox()
        self.spin_ctx.setRange(2048, 32768)
        self.spin_ctx.setSingleStep(1024)
        self.spin_ctx.setValue(4096)

        params_row.addWidget(QLabel("Temp:"))
        params_row.addWidget(self.spin_temp)
        params_row.addWidget(QLabel("Top P:"))
        params_row.addWidget(self.spin_topp)
        params_row.addWidget(QLabel("Context:"))
        params_row.addWidget(self.spin_ctx)
        params_row.addStretch()
        self.meta_lay.addRow("Parámetros IA:", params_row)

        # Parámetros Acústicos del Estilo (Velocidad, Ganancia dB, Pausas)
        acoustic_row = QHBoxLayout()
        acoustic_row.setSpacing(6)
        self.spin_style_speed = QDoubleSpinBox()
        self.spin_style_speed.setRange(0.50, 1.80)
        self.spin_style_speed.setSingleStep(0.02)
        self.spin_style_speed.setValue(1.00)
        self.spin_style_speed.setSuffix("x")

        self.spin_style_gain = QDoubleSpinBox()
        self.spin_style_gain.setRange(-12.0, 12.0)
        self.spin_style_gain.setSingleStep(0.5)
        self.spin_style_gain.setValue(0.0)
        self.spin_style_gain.setSuffix(" dB")

        self.spin_style_pause = QDoubleSpinBox()
        self.spin_style_pause.setRange(0.40, 2.50)
        self.spin_style_pause.setSingleStep(0.05)
        self.spin_style_pause.setValue(1.00)
        self.spin_style_pause.setSuffix("x")

        acoustic_row.addWidget(QLabel("Velocidad:"))
        acoustic_row.addWidget(self.spin_style_speed)
        acoustic_row.addWidget(QLabel("Ganancia:"))
        acoustic_row.addWidget(self.spin_style_gain)
        acoustic_row.addWidget(QLabel("Pausas:"))
        acoustic_row.addWidget(self.spin_style_pause)
        acoustic_row.addStretch()
        self.meta_lay.addRow("Acústica Estilo:", acoustic_row)

        # Panel derecho / inferior: Editor de System Prompt
        self.editor_frame = QFrame()
        ed_lay = QVBoxLayout(self.editor_frame)
        ed_lay.setContentsMargins(0, 0, 0, 0)
        ed_lay.setSpacing(4)
        lbl_sys = QLabel("System Prompt Estructurado (CO-STAR & Directrices TTS):")
        lbl_sys.setStyleSheet("color: #94a3b8; font-weight: 600; font-size: 11px;")
        ed_lay.addWidget(lbl_sys)

        self.edit_system = QTextEdit()
        self.edit_system.setPlaceholderText("System Prompt estructurado (CO-STAR, reglas duras, etiquetas TTS)...")
        self.edit_system.setStyleSheet("""
            font-family: Consolas, monospace;
            font-size: 12px;
            background-color: #0b0f16;
            color: #38bdf8;
            border: 1px solid #1e2633;
            border-radius: 5px;
        """)
        self.edit_system.setMinimumHeight(200)
        self.edit_system.verticalScrollBar().setStyleSheet("QScrollBar:vertical { width: 0px; height: 0px; background: transparent; }")
        self.edit_system.horizontalScrollBar().setStyleSheet("QScrollBar:horizontal { height: 0px; background: transparent; }")
        ed_lay.addWidget(self.edit_system, stretch=1)

        layout.addWidget(self.form_box, stretch=1)
        self.set_orientation("vertical")

        # 4. Barra de Acciones Inferior con Sincronización Markdown
        bottom_bar = QHBoxLayout()
        bottom_bar.setSpacing(8)

        self.btn_reset = QPushButton("[ ⟳ ] Restaurar Fábrica")
        self.btn_reset.setObjectName("secondaryActionButton")
        self.btn_reset.clicked.connect(self._reset_defaults)
        bottom_bar.addWidget(self.btn_reset)

        self.btn_sync_md = QPushButton("[ ⟳ ] Sincronizar desde PROMPTS_MAESTROS.md")
        self.btn_sync_md.setObjectName("secondaryActionButton")
        self.btn_sync_md.setToolTip("Carga y aplica de inmediato los prompts y estilos editados en el documento Markdown")
        self.btn_sync_md.clicked.connect(self._sync_from_markdown)
        bottom_bar.addWidget(self.btn_sync_md)

        self.btn_export_md = QPushButton("[ ↗ ] Exportar a PROMPTS_MAESTROS.md")
        self.btn_export_md.setObjectName("secondaryActionButton")
        self.btn_export_md.setToolTip("Guarda los prompts y estilos actuales al documento Markdown maestro")
        self.btn_export_md.clicked.connect(self._export_to_markdown)
        bottom_bar.addWidget(self.btn_export_md)

        bottom_bar.addStretch()

        self.btn_save = QPushButton("[ ⤓ ] Guardar Cambios")
        self.btn_save.setObjectName("primaryButton")
        self.btn_save.clicked.connect(self._save_changes)
        bottom_bar.addWidget(self.btn_save)

        layout.addLayout(bottom_bar)

    def _populate_selector(self) -> None:
        """Puebla el ComboBox con todos los modos, estilos y prompts personalizados."""
        self.combo_items.blockSignals(True)
        self.combo_items.clear()

        # 1. Modos Maestros de IA
        for mode in self.library.list_modes():
            label = f"[Modo IA] {mode.name} ({mode.id})"
            self.combo_items.addItem(label, ("mode", mode.id))

        # 2. Prompts Personalizados
        for custom in self.library.custom_prompts.values():
            label = f"[Personalizado] {custom.name} ({custom.id})"
            self.combo_items.addItem(label, ("custom", custom.id))

        # 3. Estilos Narrativos CO-STAR
        for style in self.library.list_styles():
            label = f"[Estilo Narrativo] {style.name} ({style.id})"
            self.combo_items.addItem(label, ("style", style.id))

        self.combo_items.blockSignals(False)
        if self.combo_items.count() > 0:
            self._load_item_into_form(0)

    def _on_item_selected(self, index: int) -> None:
        if index >= 0:
            self._load_item_into_form(index)

    def _load_item_into_form(self, index: int) -> None:
        item_data = self.combo_items.itemData(index)
        if not item_data:
            return

        cat, item_id = item_data
        self._current_type = cat
        self._current_id = item_id
        self.lbl_id.setText(f"{item_id} ({cat})")

        if cat in ("mode", "custom"):
            prompt = self.library.get_prompt(item_id)
            if not prompt:
                return

            self.edit_name.setText(prompt.name)
            self.edit_description.setText(prompt.description)
            self.edit_system.setPlainText(prompt.system_prompt)
            self.edit_template.setText(prompt.user_template)

            params = prompt.parameters or {}
            self.spin_temp.setValue(float(params.get("temperature", 0.4)))
            self.spin_topp.setValue(float(params.get("top_p", 0.9)))
            self.spin_ctx.setValue(int(params.get("num_ctx", 4096)))

            self.btn_delete.setEnabled(cat == "custom")
            self.edit_template.setEnabled(True)
            self.spin_temp.setEnabled(True)
            self.spin_topp.setEnabled(True)
            self.spin_ctx.setEnabled(True)

            self.spin_style_speed.setValue(1.0)
            self.spin_style_gain.setValue(0.0)
            self.spin_style_pause.setValue(1.0)
            self.spin_style_speed.setEnabled(False)
            self.spin_style_gain.setEnabled(False)
            self.spin_style_pause.setEnabled(False)

        elif cat == "style":
            style = self.library.get_style(item_id)
            if not style:
                return

            self.edit_name.setText(style.name)
            self.edit_description.setText(f"Tono: {style.tone}")
            self.edit_system.setPlainText(style.get_full_guidance())
            self.edit_template.setText("")
            self.edit_template.setEnabled(False)

            self.spin_temp.setValue(0.4)
            self.spin_topp.setValue(0.9)
            self.spin_ctx.setValue(4096)
            self.spin_temp.setEnabled(False)
            self.spin_topp.setEnabled(False)
            self.spin_ctx.setEnabled(False)
            self.btn_delete.setEnabled(False)

            self.spin_style_speed.setValue(float(style.speed_multiplier))
            self.spin_style_gain.setValue(float(style.gain_db))
            self.spin_style_pause.setValue(float(style.pause_multiplier))
            self.spin_style_speed.setEnabled(True)
            self.spin_style_gain.setEnabled(True)
            self.spin_style_pause.setEnabled(True)

    def _save_changes(self) -> None:
        """Guarda los cambios del formulario en la biblioteca y persiste a JSON."""
        if not self._current_id:
            return

        try:
            if self._current_type in ("mode", "custom"):
                params = {
                    "temperature": round(self.spin_temp.value(), 2),
                    "top_p": round(self.spin_topp.value(), 2),
                    "num_ctx": self.spin_ctx.value(),
                }
                self.library.update_prompt(
                    self._current_id,
                    name=self.edit_name.text().strip(),
                    description=self.edit_description.text().strip(),
                    system_prompt=self.edit_system.toPlainText(),
                    user_template=self.edit_template.text().strip(),
                    parameters=params,
                )
            elif self._current_type == "style":
                self.library.update_style(
                    self._current_id,
                    name=self.edit_name.text().strip(),
                    system_prompt_addon=self.edit_system.toPlainText(),
                    speed_multiplier=round(self.spin_style_speed.value(), 2),
                    gain_db=round(self.spin_style_gain.value(), 1),
                    pause_multiplier=round(self.spin_style_pause.value(), 2),
                )

            self.prompts_updated.emit()
            QMessageBox.information(self, "Guardado Exitoso", "Prompt y perfil acústico guardados correctamente en JSON.")
        except Exception as e:
            QMessageBox.critical(self, "Error al Guardar", f"No se pudo guardar el prompt: {e}")

    def _duplicate_current(self) -> None:
        """Crea un duplicado del prompt actual para edición personalizada."""
        if not self._current_id:
            return

        new_id, ok1 = QInputDialog.getText(
            self,
            "Duplicar Prompt",
            "Introduce un identificador único (ej. mi_prompt_narrador):",
        )
        if not ok1 or not new_id.strip():
            return
        new_id = new_id.strip().lower().replace(" ", "_")

        new_name, ok2 = QInputDialog.getText(
            self,
            "Nombre del Prompt",
            "Introduce el nombre descriptivo:",
            text=f"{self.edit_name.text()} (Copia)",
        )
        if not ok2 or not new_name.strip():
            return

        try:
            if self._current_type in ("mode", "custom"):
                self.library.duplicate_prompt(self._current_id, new_id, new_name.strip())
            elif self._current_type == "style":
                style = self.library.get_style(self._current_id)
                if not style:
                    return
                item = PromptItem(
                    id=new_id,
                    category="custom",
                    name=new_name.strip(),
                    description=f"Basado en estilo {style.name}",
                    system_prompt=self.edit_system.toPlainText(),
                    user_template="{text}",
                    parameters={"temperature": 0.45, "top_p": 0.9, "num_ctx": 4096},
                    is_builtin=False,
                )
                self.library.add_prompt(item)

            self._populate_selector()
            for i in range(self.combo_items.count()):
                data = self.combo_items.itemData(i)
                if data and data[1] == new_id:
                    self.combo_items.setCurrentIndex(i)
                    break

            self.prompts_updated.emit()
            QMessageBox.information(self, "Prompt Duplicado", f"Se ha creado el prompt '{new_id}' satisfactoriamente.")
        except Exception as e:
            QMessageBox.warning(self, "Error al Duplicar", f"No se pudo duplicar: {e}")

    def _delete_current(self) -> None:
        """Elimina un prompt personalizado."""
        if self._current_type != "custom":
            QMessageBox.warning(self, "Acción Denegada", "Solo se pueden eliminar prompts personalizados.")
            return

        reply = QMessageBox.question(
            self,
            "Confirmar Eliminación",
            f"¿Estás seguro de eliminar el prompt '{self._current_id}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.library.delete_prompt(self._current_id)
            self._populate_selector()
            self.prompts_updated.emit()

    def _reset_defaults(self) -> None:
        """Restaura todos los prompts a sus valores de fábrica."""
        reply = QMessageBox.question(
            self,
            "Restaurar Valores de Fábrica",
            "¿Deseas restaurar todos los prompts maestros a sus valores de fábrica predeterminados?\nEsta acción sobreescribirá los cambios no respaldados.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.library.reset_to_defaults()
            self._populate_selector()
            self.prompts_updated.emit()
            QMessageBox.information(self, "Restaurado", "Prompts maestros restaurados a valores de fábrica.")

    def _sync_from_markdown(self) -> None:
        """Sincroniza y recarga los prompts y estilos directamente desde PROMPTS_MAESTROS.md."""
        try:
            count = self.library.import_from_markdown(PROMPTS_MD_FILE)
            self._populate_selector()
            self.prompts_updated.emit()
            QMessageBox.information(
                self,
                "Sincronización Completada",
                f"Se han sincronizado y actualizado exitosamente {count} modos y estilos desde PROMPTS_MAESTROS.md.",
            )
        except Exception as e:
            QMessageBox.critical(self, "Error de Sincronización", f"No se pudo sincronizar desde Markdown:\n{e}")

    def _export_to_markdown(self) -> None:
        """Exporta la configuración actual a PROMPTS_MAESTROS.md."""
        try:
            self.library.export_to_markdown(PROMPTS_MD_FILE)
            QMessageBox.information(
                self,
                "Exportación Completada",
                "El catálogo maestro se ha exportado y actualizado exitosamente en PROMPTS_MAESTROS.md.",
            )
        except Exception as e:
            QMessageBox.critical(self, "Error al Exportar", f"No se pudo exportar a Markdown:\n{e}")


class PromptManagerDialog(QDialog):
    """Diálogo emergente para ver, editar, duplicar y restaurar Prompts Maestros."""

    def __init__(self, library: Optional[PromptLibrary] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Gestor de Prompts Maestros e Inferencia Local")
        self.resize(850, 650)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        self.widget = PromptManagerWidget(library=library, parent=self)
        layout.addWidget(self.widget)

        close_btn = QPushButton("Cerrar")
        close_btn.setObjectName("secondaryActionButton")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)

    @property
    def prompts_updated(self):
        return self.widget.prompts_updated
