#!/usr/bin/env python3
# Hayashi v0.7.1 — no auto render; safe "render visible (x2)" queue; per-page render buttons
# PyQt5 + PyMuPDF

import sys, io, re, collections, traceback, time
from pathlib import Path
from PyQt5 import QtCore, QtGui, QtWidgets
import fitz
import html as _html

APP_NAME = "Hayashi"

def _excepthook(exc_type, exc, tb):
    msg = "".join(traceback.format_exception(exc_type, exc, tb))
    try: QtWidgets.QMessageBox.critical(None, f"{APP_NAME} crashed", msg[:4000])
    except Exception: pass
    print(msg, file=sys.stderr)
sys.excepthook = _excepthook

class LRUCache:
    def __init__(self, max_items=24): self.max=max_items; self.d=collections.OrderedDict()
    def get(self,k):
        if k in self.d: v=self.d.pop(k); self.d[k]=v; return v
        return None
    def put(self,k,v):
        if k in self.d: self.d.pop(k)
        self.d[k]=v
        while len(self.d)>self.max: self.d.popitem(last=False)

class DocModel(QtCore.QObject):
    loaded = QtCore.pyqtSignal()
    def __init__(self, pdf_path: Path, dpi=110, mode="simple", strip_headers=False, parent=None):
        super().__init__(parent)
        self.pdf_path=Path(pdf_path); self.doc=None; self.page_count=0
        self.dpi=max(72,min(dpi,220)); self.mode=mode; self.strip_headers=strip_headers
        self.merged_text=""; self.figures={}; self.page_offsets=[]
        self.page_pix_cache=LRUCache(max_items=20)
    def open(self):
        self.doc=fitz.open(str(self.pdf_path)); self.page_count=len(self.doc)
        (self._build_simple if self.mode=="simple" else self._build_structured)()
        self.loaded.emit()
    def close(self):
        if self.doc: self.doc.close(); self.doc=None
    def _build_simple(self):
        parts=[]; char_count=0; fig_id=0
        self.figures.clear(); self.page_offsets.clear()
        for pno in range(self.page_count):
            page=self.doc[pno]; start=char_count
            txt=(page.get_text("text") or "").strip()
            if txt:
                parts.append(txt); char_count+=len(txt); parts.append("\n\n"); char_count+=2
            try: imgs=page.get_images(full=False)
            except Exception: imgs=[]
            if imgs:
                marks=[]
                for info in imgs:
                    xref=info[0]; fig_id+=1
                    marks.append(f"[FIGURE {fig_id} (p{pno+1})]")
                    self.figures[fig_id]={"page":pno,"xref":xref,"bbox":None}
                m=" ".join(marks); parts.append(m); char_count+=len(m); parts.append("\n\n"); char_count+=2
            self.page_offsets.append((start,char_count))
        self.merged_text="".join(parts).rstrip()
    def _build_structured(self):
        parts=[]; char_count=0; fig_id=0
        self.figures.clear(); self.page_offsets.clear()
        for pno in range(self.page_count):
            page=self.doc[pno]; start=char_count
            raw=page.get_text("rawdict"); page_h=page.rect.height
            top_cut=60 if self.strip_headers else -1e9; bot_cut=page_h-60 if self.strip_headers else 1e9
            wrote=False
            for blk in raw.get("blocks",[]):
                btype=blk.get("type",0)
                if self.strip_headers and btype==0:
                    y0,y1=blk.get("bbox",[0,0,0,0])[1], blk.get("bbox",[0,0,0,0])[3]
                    if y1<=top_cut or y0>=bot_cut: continue
                if btype==0:
                    for line in blk.get("lines",[]):
                        s="".join(sp.get("text","") for sp in line.get("spans",[]))
                        if s.strip():
                            parts.append(s); char_count+=len(s); parts.append("\n"); char_count+=1; wrote=True
                    parts.append("\n"); char_count+=1
                elif btype==1:
                    xref=blk.get("xref") or blk.get("image")
                    if xref:
                        fig_id+=1; mark=f"[FIGURE {fig_id} (p{pno+1})]"
                        parts.append(mark); char_count+=len(mark); parts.append("\n\n"); char_count+=2
                        self.figures[fig_id]={"page":pno,"xref":xref,"bbox":tuple(blk.get("bbox",[0,0,0,0]))}
            if not wrote:
                txt=(page.get_text("text") or "").strip()
                if txt: parts.append(txt); char_count+=len(txt); parts.append("\n\n"); char_count+=2
            self.page_offsets.append((start,char_count))
        self.merged_text="".join(parts).rstrip()
    def _page_key(self,pno,safe): return (pno,self.dpi,int(safe))
    def render_page(self,pno,safe_png=True):
        if self.doc is None or pno<0 or pno>=self.page_count: return None
        key=self._page_key(pno,safe_png); cached=self.page_pix_cache.get(key)
        if cached is not None: return cached
        page=self.doc[pno]
        try:
            scale=min(max(self.dpi/72.0,0.5),3.0); mat=fitz.Matrix(scale,scale)
            pix=page.get_pixmap(matrix=mat, alpha=False)
            if pix.width>6000 or pix.height>8000:
                shrink=max(pix.width/3000.0, pix.height/4000.0)
                mat2=fitz.Matrix(scale/shrink, scale/shrink)
                pix=page.get_pixmap(matrix=mat2, alpha=False)
            if safe_png:
                data=pix.tobytes("png"); img=QtGui.QImage.fromData(data,"PNG").copy()
                self.page_pix_cache.put(key,img); return img
            if pix.n==1: fmt=QtGui.QImage.Format_Grayscale8
            elif pix.n==3: fmt=QtGui.QImage.Format_RGB888
            elif pix.n==4: fmt=QtGui.QImage.Format_RGBA8888
            else:
                data=pix.tobytes("png"); img=QtGui.QImage.fromData(data,"PNG").copy()
                self.page_pix_cache.put(key,img); return img
            img=QtGui.QImage(pix.samples,pix.width,pix.height,pix.stride,fmt).copy()
            self.page_pix_cache.put(key,img); return img
        except Exception:
            tile=QtGui.QImage(320,200,QtGui.QImage.Format_RGB888); tile.fill(QtGui.QColor(40,40,40))
            p=QtGui.QPainter(tile); p.setPen(QtGui.QColor(255,200,0)); p.drawText(10,100,f"Render failed p{pno+1}"); p.end()
            return tile

class ZoomableLabel(QtWidgets.QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop)
        self.setStyleSheet("QLabel { background:#222; color:#aaa; }")
        self.setMinimumHeight(64)

    def wheelEvent(self, event):
        if event.modifiers() & QtCore.Qt.ShiftModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self.parent().zoom_in()
            elif delta < 0:
                self.parent().zoom_out()
            event.accept()
        else:
            event.ignore()  # Pass to parent for scrolling

class PageItem(QtWidgets.QFrame):
    def __init__(self,pdf_view,pno):
        super().__init__(); self.pdf_view=pdf_view; self.pno=pno
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        lay=QtWidgets.QVBoxLayout(self); lay.setContentsMargins(6,6,6,6); lay.setSpacing(4)
        self.img_label=ZoomableLabel(self)
        row=QtWidgets.QHBoxLayout()
        b_render=QtWidgets.QPushButton("Render"); b_render.clicked.connect(self._render_once)
        b_clear=QtWidgets.QPushButton("Clear"); b_clear.clicked.connect(self._clear)
        b_zoom_in=QtWidgets.QPushButton("+"); b_zoom_in.clicked.connect(self.zoom_in)
        b_zoom_out=QtWidgets.QPushButton("-"); b_zoom_out.clicked.connect(self.zoom_out)
        b_fit=QtWidgets.QPushButton("Fit"); b_fit.clicked.connect(self.zoom_fit)
        info=QtWidgets.QLabel(f"p{pno+1}"); info.setStyleSheet("color:#888;")
        row.addWidget(b_render); row.addWidget(b_clear); row.addWidget(b_zoom_in); row.addWidget(b_zoom_out); row.addWidget(b_fit)
        row.addStretch(1); row.addWidget(info)
        lay.addWidget(self.img_label); lay.addLayout(row)
        self.original_img = None
        self.zoom_factor = 1.0

    def _clear(self):
        self.img_label.setPixmap(QtGui.QPixmap()); self.img_label.setText("Text-only mode"); self.img_label.setMinimumHeight(64)
        self.original_img = None
        self.zoom_factor = 1.0

    def _render_once(self):
        self.original_img = self.pdf_view.render_single_page_raw(self.pno)
        if self.original_img:
            self.update_display()

    def update_display(self):
        if not self.original_img:
            return
        w = max(100, self.pdf_view.viewport().width() - 18 - 12)
        scaled_width = int(w * self.zoom_factor)
        qpm = QtGui.QPixmap.fromImage(self.original_img).scaledToWidth(scaled_width, QtCore.Qt.SmoothTransformation)
        self.img_label.setPixmap(qpm)
        self.img_label.setMinimumHeight(qpm.height())
        self.img_label.setText("")

    def zoom_in(self):
        self.zoom_factor = min(3.0, self.zoom_factor + 0.1)
        self.update_display()

    def zoom_out(self):
        self.zoom_factor = max(0.5, self.zoom_factor - 0.1)
        self.update_display()

    def zoom_fit(self):
        self.zoom_factor = 1.0
        self.update_display()

class PdfView(QtWidgets.QScrollArea):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.model=None; self.safe_png=True
        self.render_delay_ms = 100  # Default delay in milliseconds
        self.dpi = 110  # Default DPI
        self.setWidgetResizable(True)
        self.container=QtWidgets.QWidget()
        self.vbox=QtWidgets.QVBoxLayout(self.container); self.vbox.setContentsMargins(0,0,0,0); self.vbox.setSpacing(12)
        self.setWidget(self.container)
        self.page_items=[]

        # --- new: non-blocking "render all" scheduler ---
        self._all_timer = QtCore.QTimer(self)
        self._all_timer.timeout.connect(self._render_all_step)
        self._all_idx = 0
        self._all_active = False

    def set_safe_png(self,on:bool): self.safe_png=bool(on)

    def set_render_delay(self, delay_ms):
        self.render_delay_ms = max(0, min(1000, delay_ms))  # Constrain between 0 and 1000ms
        if self._all_timer.isActive():
            self._all_timer.setInterval(self.render_delay_ms)

    def set_dpi(self, dpi):
        self.dpi = max(72, min(220, dpi))

    def set_model(self,model:DocModel):
        # stop any in-flight "render all"
        if self._all_timer.isActive():
            self._all_timer.stop(); self._all_active = False
            QtWidgets.QApplication.restoreOverrideCursor()

        for i in reversed(range(self.vbox.count())):
            w=self.vbox.itemAt(i).widget()
            if w: w.setParent(None)
        self.page_items.clear(); self.model=model
        if not model:
            p=QtWidgets.QLabel("Open a PDF (File → Open…)"); p.setAlignment(QtCore.Qt.AlignCenter); p.setStyleSheet("color:#888; font-size:14px;")
            self.vbox.addWidget(p); self.vbox.addStretch(1); return
        for pno in range(model.page_count):
            item=PageItem(self,pno); self.vbox.addWidget(item); self.page_items.append(item)
        self.vbox.addStretch(1)

    def _visible_range(self):
        if not self.page_items: return (0,-1)
        vp=self.viewport().rect()
        top=self.viewport().mapTo(self.container, vp.topLeft()).y()
        bot=self.viewport().mapTo(self.container, vp.bottomLeft()).y()
        rng=[]; y=0; spacing=self.vbox.spacing()
        for i,item in enumerate(self.page_items):
            h=item.height() or 120
            if y+h>=top-300 and y<=bot+300: rng.append(i)
            y+=h+spacing
        return (min(rng),max(rng)) if rng else (0,0)

    def render_visible_lite(self, count=2):
        """Render at most `count` visible pages (safe queue)."""
        if not self.model: return
        start,end=self._visible_range()
        done=0
        for pno in range(start, end+1):
            item=self.page_items[pno]
            if item.original_img is None:
                item.original_img = self.render_single_page_raw(pno)
                if item.original_img:
                    item.update_display()
                done+=1
                if done>=count: break

    def render_single_page_raw(self,pno:int):
        if not self.model: return None
        try:
            return self.model.render_page(pno, safe_png=self.safe_png)
        except Exception:
            return None

    def jump_to_page(self,pno):
        if not self.page_items or pno<0 or pno>=len(self.page_items): return
        self.verticalScrollBar().setValue(self.page_items[pno].pos().y())

    # -------- new non-blocking "render all" ----------
    def render_all_pages(self):
        """Render all pages non-blockingly, one per timer tick."""
        if not self.model or self._all_active: return
        self._all_idx = 0
        self._all_active = True
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        self._all_timer.setInterval(self.render_delay_ms)
        self._all_timer.start()

    def _render_all_step(self):
        if not self.model or self._all_idx >= self.model.page_count:
            self._all_timer.stop()
            self._all_active = False
            QtWidgets.QApplication.restoreOverrideCursor()
            return
        pno = self._all_idx
        item = self.page_items[pno]
        if item.original_img is None:
            img = self.render_single_page_raw(pno)
            if img:
                item.original_img = img
                item.update_display()
        self._all_idx += 1

class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.pdf_view = main_window.pdf_view
        layout = QtWidgets.QVBoxLayout()

        delay_label = QtWidgets.QLabel("Render Delay (ms):")
        self.delay_spinbox = QtWidgets.QSpinBox()
        self.delay_spinbox.setRange(0, 1000)
        self.delay_spinbox.setValue(self.pdf_view.render_delay_ms)
        self.delay_spinbox.valueChanged.connect(self.update_delay)

        dpi_label = QtWidgets.QLabel("Render DPI:")
        self.dpi_spinbox = QtWidgets.QSpinBox()
        self.dpi_spinbox.setRange(72, 220)
        self.dpi_spinbox.setValue(self.pdf_view.dpi)
        self.dpi_spinbox.valueChanged.connect(self.update_dpi)

        layout.addWidget(delay_label)
        layout.addWidget(self.delay_spinbox)
        layout.addWidget(dpi_label)
        layout.addWidget(self.dpi_spinbox)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setLayout(layout)

    def update_delay(self, value):
        self.pdf_view.set_render_delay(value)

    def update_dpi(self, value):
        self.pdf_view.set_dpi(value)
        self.main_window.reload_pdf_with_new_dpi()

class TextView(QtWidgets.QTextEdit):
    anchorClickedFigure = QtCore.pyqtSignal(int)
    def __init__(self,parent=None):
        super().__init__(parent); self.model=None; self.setReadOnly(True)
        self.document().setDefaultFont(QtGui.QFont("Consolas",11))
    def set_model(self,model:DocModel):
        self.model=model
        if not model: self.setPlainText(""); return
        text=model.merged_text
        def repl(m): return f'<a href="fig:{m.group(1)}">[FIGURE {m.group(1)} (p{m.group(2)})]</a>'
        safe=_html.escape(text); html=re.sub(r'\[FIGURE\s+(\d+)\s+\(p(\d+)\)\]', repl, safe)
        self.setHtml(f"<html><body style='white-space:pre-wrap;font-family:Consolas,monospace;font-size:11pt'>{html}</body></html>")
    def mousePressEvent(self,ev:QtGui.QMouseEvent):
        if ev.button()==QtCore.Qt.LeftButton:
            a=self.anchorAt(ev.pos())
            if a and a.startswith("fig:"):
                try: self.anchorClickedFigure.emit(int(a.split(':')[1])); ev.accept(); return
                except Exception: pass
        super().mousePressEvent(ev)

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, initial_pdf:Path=None):
        super().__init__(); self.setWindowTitle(APP_NAME); self.resize(1200,800)
        self.splitter=QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.pdf_view=PdfView(); self.text_view=TextView()
        self.splitter.addWidget(self.pdf_view); self.splitter.addWidget(self.text_view)
        self.splitter.setStretchFactor(0,3); self.splitter.setStretchFactor(1,2)
        self.setCentralWidget(self.splitter)
        self.status=self.statusBar(); self.status.showMessage("Ready."); self.model=None

        file_menu=self.menuBar().addMenu("&File")
        act_open=file_menu.addAction("Open PDF…"); act_open.setShortcut("Ctrl+O"); act_open.triggered.connect(self.open_pdf_dialog)
        file_menu.addSeparator(); act_quit=file_menu.addAction("Quit"); act_quit.setShortcut("Ctrl+Q"); act_quit.triggered.connect(self.close)

        view_menu=self.menuBar().addMenu("&View")
        act_render2=view_menu.addAction("Render visible (2 pages)")
        act_render2.triggered.connect(lambda: self.pdf_view.render_visible_lite(count=2))
        view_menu.addSeparator()
        act_render_all=view_menu.addAction("Render all pages")
        act_render_all.triggered.connect(self.pdf_view.render_all_pages)
        view_menu.addSeparator()
        self.act_safe=view_menu.addAction("Render via PNG decoder (safer)")
        self.act_safe.setCheckable(True); self.act_safe.setChecked(True)
        self.act_safe.toggled.connect(lambda on: self.pdf_view.set_safe_png(on))
        act_settings = view_menu.addAction("Settings")
        act_settings.triggered.connect(self.show_settings)

        extract_menu=self.menuBar().addMenu("&Text mode")
        self.act_simple=extract_menu.addAction("Simple (reliable)"); self.act_simple.setCheckable(True)
        self.act_struct=extract_menu.addAction("Structured (beta, inline figures)"); self.act_struct.setCheckable(True)
        self.act_simple.setChecked(True)
        grp=QtWidgets.QActionGroup(self); grp.addAction(self.act_simple); grp.addAction(self.act_struct); grp.setExclusive(True)
        self.act_simple.triggered.connect(lambda: self.rebuild_text(mode="simple"))
        self.act_struct.triggered.connect(lambda: self.rebuild_text(mode="structured"))

        self.text_view.anchorClickedFigure.connect(self.on_anchor_clicked)

        self.pdf_view.set_model(None); self.text_view.set_model(None)
        if initial_pdf: QtCore.QTimer.singleShot(0, lambda: self.load_pdf(initial_pdf))

    def show_settings(self):
        dlg = SettingsDialog(self, self)
        dlg.exec_()

    def open_pdf_dialog(self):
        fn,_=QtWidgets.QFileDialog.getOpenFileName(self,"Open PDF",str(Path.home()),"PDF files (*.pdf)")
        if fn: self.load_pdf(Path(fn))

    def load_pdf(self,pdf_path:Path):
        try:
            self.status.showMessage(f"Opening {pdf_path} …"); QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            if self.model: self.model.close()
            mode="structured" if self.act_struct.isChecked() else "simple"
            self.model=DocModel(pdf_path, dpi=self.pdf_view.dpi, mode=mode)
            self.model.open()
            self.setWindowTitle(f"{APP_NAME} — {pdf_path.name}")
            self.pdf_view.set_model(self.model); self.text_view.set_model(self.model)
            self.pdf_view.set_safe_png(self.act_safe.isChecked())
            self.status.showMessage(f"Loaded {self.model.page_count} pages.")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, APP_NAME, f"Failed to open:\n{pdf_path}\n\n{e}")
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    def rebuild_text(self, mode:str):
        if not self.model: return
        p=self.model.pdf_path; safe=self.act_safe.isChecked()
        self.model.close(); self.model=DocModel(p, dpi=self.pdf_view.dpi, mode=mode)
        self.model.open()
        self.pdf_view.set_model(self.model); self.text_view.set_model(self.model)
        self.pdf_view.set_safe_png(safe)

    def reload_pdf_with_new_dpi(self):
        if not self.model: return
        p = self.model.pdf_path
        mode = "structured" if self.act_struct.isChecked() else "simple"
        safe = self.act_safe.isChecked()
        self.model.close()
        self.model = DocModel(p, dpi=self.pdf_view.dpi, mode=mode)
        self.model.open()
        self.pdf_view.set_model(self.model)
        self.text_view.set_model(self.model)
        self.pdf_view.set_safe_png(safe)

    @QtCore.pyqtSlot(int)
    def on_anchor_clicked(self, fig_id:int):
        if not self.model: return
        info=self.model.figures.get(fig_id)
        if info: self.pdf_view.jump_to_page(info["page"])

    def show_settings(self):
        dialog = SettingsDialog(self, self)
        dialog.exec_()

def main():
    app=QtWidgets.QApplication(sys.argv); app.setApplicationName(APP_NAME); app.setOrganizationName("Hayashi")
    initial=None
    if len(sys.argv)>=2:
        p=Path(sys.argv[1])
        if p.exists() and p.suffix.lower()==".pdf": initial=p
    win=MainWindow(initial_pdf=initial); win.show()
    sys.exit(app.exec_())

if __name__=="__main__": main()