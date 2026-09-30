"""App de janela: escolher o PDF, marcar as páginas e gerar o Journal."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .convert import (ConversionError, Settings, convert, default_name, format_pages,
                      open_pdf, parse_pages)
from .extract import Options
from .foundry import macro_script

THUMB_W = 120
CELL_W = THUMB_W + 18
SPLITS = {
    "Uma por página do PDF": "page",
    "Uma por título": "heading",
    "Tudo numa página só": "none",
}
SEL_COLOR = "#2f6fd6"
IDLE_COLOR = "#d0d0d0"


def config_path() -> Path:
    base = os.environ.get("APPDATA") or os.path.join(Path.home(), ".config")
    return Path(base) / "pdf2journal" / "settings.json"


class App(tk.Tk):
    def __init__(self, pdf: str | None = None):
        super().__init__()
        self.title(f"pdf2journal {__version__} — PDF para Journal do Foundry")
        self.geometry("1180x760")
        self.minsize(920, 580)

        self.doc = None
        self.pdf_path: Path | None = None
        self.selected: set[int] = set()
        self.anchor: int | None = None
        self.cells: list[tk.Frame] = []
        self.photos: dict[int, tk.PhotoImage] = {}
        self.render_next = 0
        self.cols = 0
        self.result = None
        self.events: queue.Queue = queue.Queue()

        self.v_path = tk.StringVar(value="Nenhum PDF aberto")
        self.v_name = tk.StringVar()
        self.v_pages = tk.StringVar()
        self.v_count = tk.StringVar(value="")
        self.v_split = tk.StringVar(value=next(iter(SPLITS)))
        self.v_level = tk.IntVar(value=1)
        self.v_out = tk.StringVar()
        self.v_prefix = tk.StringVar()
        self.v_images = tk.BooleanVar(value=True)
        self.v_tables = tk.BooleanVar(value=True)
        self.v_boxes = tk.BooleanVar(value=True)
        self.v_headers = tk.BooleanVar(value=True)
        self.v_dpi = tk.IntVar(value=150)
        self.v_format = tk.StringVar(value="webp")
        self._load_config()

        self._build()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(100, self._poll)
        if pdf:
            self.after(50, lambda: self.open_pdf(Path(pdf)))

    # ------------------------------------------------------------------ #
    # Layout
    # ------------------------------------------------------------------ #
    def _build(self):
        top = ttk.Frame(self, padding=(10, 8))
        top.pack(fill="x")
        ttk.Button(top, text="Abrir PDF…", command=self.choose_pdf).pack(side="left")
        ttk.Label(top, textvariable=self.v_path, foreground="#555").pack(side="left", padx=10)

        body = ttk.PanedWindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # --- miniaturas ------------------------------------------------- #
        left = ttk.Frame(body)
        body.add(left, weight=3)
        bar = ttk.Frame(left)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Button(bar, text="Selecionar todas", command=self.select_all).pack(side="left")
        ttk.Button(bar, text="Limpar seleção", command=self.clear_selection).pack(side="left", padx=6)
        ttk.Label(bar, textvariable=self.v_count).pack(side="left", padx=6)
        ttk.Label(left, text="Clique numa página para marcar · Shift+clique marca um intervalo",
                  foreground="#777").pack(side="bottom", anchor="w", pady=(4, 0))

        wrap = ttk.Frame(left, relief="sunken", borderwidth=1)
        wrap.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(wrap, background="#f3f3f3", highlightthickness=0)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.grid_frame = tk.Frame(self.canvas, background="#f3f3f3")
        self.canvas.create_window((0, 0), window=self.grid_frame, anchor="nw")
        self.grid_frame.bind("<Configure>",
                             lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self._relayout())
        self.empty_label = tk.Label(self.canvas, text="Abra um PDF para ver as páginas",
                                    background="#f3f3f3", foreground="#888", font=("", 12))
        self.empty_label.place(relx=0.5, rely=0.5, anchor="center")
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.canvas.bind_all(seq, self._wheel, add="+")

        # --- configurações ---------------------------------------------- #
        right = ttk.Frame(body, padding=(10, 0, 0, 0))
        body.add(right, weight=2)

        jf = ttk.LabelFrame(right, text="Journal", padding=8)
        jf.pack(fill="x")
        jf.columnconfigure(1, weight=1)
        self._row(jf, 0, "Nome", ttk.Entry(jf, textvariable=self.v_name))
        pages = ttk.Entry(jf, textvariable=self.v_pages)
        pages.bind("<Return>", lambda e: self._pages_typed())
        pages.bind("<FocusOut>", lambda e: self._pages_typed())
        self._row(jf, 1, "Páginas", pages)
        ttk.Label(jf, text="Ex.: 12-20,25. Vazio = todas.", foreground="#777").grid(
            row=2, column=1, sticky="w")
        split = ttk.Combobox(jf, textvariable=self.v_split, values=list(SPLITS), state="readonly")
        split.bind("<<ComboboxSelected>>", lambda e: self._split_changed())
        self._row(jf, 3, "Dividir", split)
        self.level = ttk.Spinbox(jf, from_=1, to=3, textvariable=self.v_level, width=5)
        self._row(jf, 4, "Nível do título", self.level, sticky="w")
        self._split_changed()

        of = ttk.LabelFrame(right, text="Saída", padding=8)
        of.pack(fill="x", pady=8)
        of.columnconfigure(1, weight=1)
        out = ttk.Frame(of)
        out.columnconfigure(0, weight=1)
        ttk.Entry(out, textvariable=self.v_out).grid(row=0, column=0, sticky="ew")
        ttk.Button(out, text="…", width=3, command=self.choose_out).grid(row=0, column=1, padx=(4, 0))
        self._row(of, 0, "Pasta", out)
        self._row(of, 1, "Caminho no Foundry", ttk.Entry(of, textvariable=self.v_prefix))
        ttk.Label(of, text="Pasta das imagens dentro de Data. Vazio = pdf2journal/<nome>",
                  foreground="#777").grid(row=2, column=1, sticky="w")

        xf = ttk.LabelFrame(right, text="Conversão", padding=8)
        xf.pack(fill="x")
        ttk.Checkbutton(xf, text="Extrair imagens", variable=self.v_images).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(xf, text="Detectar tabelas", variable=self.v_tables).grid(row=0, column=1, sticky="w")
        ttk.Checkbutton(xf, text="Quadros como citação", variable=self.v_boxes).grid(row=1, column=0, sticky="w")
        ttk.Checkbutton(xf, text="Remover cabeçalho/rodapé", variable=self.v_headers).grid(
            row=1, column=1, sticky="w")
        img = ttk.Frame(xf)
        img.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Label(img, text="Imagens:").pack(side="left")
        ttk.Combobox(img, textvariable=self.v_format, values=["webp", "jpg", "png"],
                     state="readonly", width=6).pack(side="left", padx=4)
        ttk.Spinbox(img, from_=72, to=400, increment=25, textvariable=self.v_dpi, width=5).pack(side="left")
        ttk.Label(img, text="dpi").pack(side="left", padx=(2, 0))

        self.go = ttk.Button(right, text="Gerar Journal (.json)", command=self.run)
        self.go.pack(fill="x", pady=(12, 4), ipady=6)
        self.progress = ttk.Progressbar(right, mode="determinate", value=0)
        self.progress.pack(fill="x")

        acts = ttk.Frame(right)
        acts.pack(fill="x", pady=6)
        self.b_folder = ttk.Button(acts, text="Abrir pasta", command=self.open_folder, state="disabled")
        self.b_preview = ttk.Button(acts, text="Ver prévia", command=self.open_preview, state="disabled")
        self.b_macro = ttk.Button(acts, text="Copiar macro", command=self.copy_macro, state="disabled")
        for b in (self.b_folder, self.b_preview, self.b_macro):
            b.pack(side="left", expand=True, fill="x", padx=2)

        self.log = tk.Text(right, height=10, wrap="word", relief="flat", background="#fafafa",
                           font=("Consolas", 9) if sys.platform == "win32" else ("TkFixedFont", 9))
        self.log.pack(fill="both", expand=True)
        self.log.configure(state="disabled")
        self._say("1. Abra um PDF.\n2. Marque as páginas.\n3. Clique em Gerar Journal.")

    @staticmethod
    def _row(parent, r, label, widget, sticky="ew"):
        ttk.Label(parent, text=label).grid(row=r, column=0, sticky="w", padx=(0, 8), pady=3)
        widget.grid(row=r, column=1, sticky=sticky, pady=3)

    def _split_changed(self):
        self.level.configure(state="normal" if SPLITS[self.v_split.get()] == "heading" else "disabled")

    # ------------------------------------------------------------------ #
    # PDF e miniaturas
    # ------------------------------------------------------------------ #
    def choose_pdf(self):
        path = filedialog.askopenfilename(title="Escolha o PDF",
                                          filetypes=[("PDF", "*.pdf"), ("Todos", "*.*")])
        if path:
            self.open_pdf(Path(path))

    def open_pdf(self, path: Path):
        password = None
        while True:
            try:
                doc = open_pdf(path, password)
                break
            except ConversionError as e:
                if "senha" not in str(e):
                    messagebox.showerror("pdf2journal", str(e))
                    return
                from tkinter import simpledialog
                password = simpledialog.askstring("PDF protegido", "Senha do PDF:", show="*", parent=self)
                if password is None:
                    return
        if self.doc is not None:
            self.doc.close()
        self.doc, self.pdf_path, self.password = doc, path, password
        self.v_path.set(f"{path}  ({doc.page_count} páginas)")
        self.v_name.set(default_name(doc, path) or path.stem)
        if not self.v_out.get():
            self.v_out.set(str(path.parent / "pdf2journal"))
        self.selected.clear()
        self.anchor = None
        self.result = None
        for b in (self.b_folder, self.b_preview, self.b_macro):
            b.configure(state="disabled")

        for c in self.cells:
            c.destroy()
        self.cells, self.photos = [], {}
        self.empty_label.place_forget()
        page0 = doc[0].rect if doc.page_count else None
        ratio = (page0.height / page0.width) if page0 else 1.3
        for i in range(doc.page_count):
            cell = tk.Frame(self.grid_frame, background=IDLE_COLOR, padx=3, pady=3)
            img = tk.Label(cell, width=THUMB_W, height=int(THUMB_W * ratio), background="white",
                           image=self._blank(ratio))
            img.pack()
            cap = tk.Label(cell, text=str(i + 1), background=IDLE_COLOR)
            cap.pack(fill="x")
            for w in (cell, img, cap):
                w.bind("<Button-1>", lambda e, i=i: self._click(i, e))
            self.cells.append(cell)
        self.cols = 0
        self._relayout()
        self.canvas.yview_moveto(0)
        self._sync_selection()
        self.render_next = 0
        self.after(10, self._render_some)

    def _blank(self, ratio):
        key = -1
        if key not in self.photos:
            self.photos[key] = tk.PhotoImage(width=THUMB_W, height=int(THUMB_W * ratio))
        return self.photos[key]

    def _render_some(self):
        """Renderiza poucas miniaturas por vez para a janela não travar."""
        doc = self.doc
        if doc is None or self.render_next >= min(doc.page_count, len(self.cells)):
            return
        import pymupdf
        for _ in range(4):
            i = self.render_next
            if i >= doc.page_count:
                break
            page = doc[i]
            zoom = THUMB_W / page.rect.width
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            photo = tk.PhotoImage(data=pix.tobytes("ppm"))
            self.photos[i] = photo
            label = self.cells[i].winfo_children()[0]
            label.configure(image=photo, width=photo.width(), height=photo.height())
            self.render_next += 1
        self.after(1, self._render_some)

    def _relayout(self):
        width = max(self.canvas.winfo_width(), CELL_W)
        cols = max(1, width // CELL_W)
        if cols == self.cols:
            return
        self.cols = cols
        for i, c in enumerate(self.cells):
            c.grid(row=i // cols, column=i % cols, padx=6, pady=6)

    def _wheel(self, e):
        if not self.cells:
            return
        w = self.winfo_containing(e.x_root, e.y_root)
        while w is not None and w is not self.canvas:
            w = w.master
        if w is None:
            return
        step = -1 if (getattr(e, "num", 0) == 4 or e.delta > 0) else 1
        self.canvas.yview_scroll(step * 3, "units")

    # ------------------------------------------------------------------ #
    # Seleção
    # ------------------------------------------------------------------ #
    def _click(self, i, e):
        if e.state & 0x0001 and self.anchor is not None:      # Shift
            a, b = sorted((self.anchor, i))
            self.selected.update(range(a, b + 1))
        else:
            self.selected.symmetric_difference_update({i})
            self.anchor = i
        self._sync_selection()

    def select_all(self):
        if self.doc:
            self.selected = set(range(self.doc.page_count))
            self._sync_selection()

    def clear_selection(self):
        self.selected.clear()
        self._sync_selection()

    def _pages_typed(self):
        if not self.doc:
            return
        spec = self.v_pages.get()
        try:
            pages = parse_pages(spec, self.doc.page_count) if spec.strip() else []
        except ValueError as e:
            self.v_count.set(f"⚠ {e}")
            return
        self.selected = set(pages)
        self._sync_selection()

    def _sync_selection(self):
        for i, c in enumerate(self.cells):
            color = SEL_COLOR if i in self.selected else IDLE_COLOR
            c.configure(background=color)
            cap = c.winfo_children()[1]
            cap.configure(background=color, foreground="white" if i in self.selected else "black")
        self.v_pages.set(format_pages(sorted(self.selected)))
        n = len(self.selected)
        if not self.doc:
            self.v_count.set("")
        elif n == 0:
            self.v_count.set("Nenhuma marcada: todas serão convertidas")
        else:
            self.v_count.set(f"{n} página(s) marcada(s)")

    # ------------------------------------------------------------------ #
    # Conversão
    # ------------------------------------------------------------------ #
    def choose_out(self):
        path = filedialog.askdirectory(title="Pasta de saída", initialdir=self.v_out.get() or None)
        if path:
            self.v_out.set(path)

    def run(self):
        if not self.pdf_path:
            messagebox.showinfo("pdf2journal", "Abra um PDF primeiro.")
            return
        self._pages_typed()
        if not self.v_out.get().strip():
            messagebox.showinfo("pdf2journal", "Escolha a pasta de saída.")
            return
        try:
            dpi = int(self.v_dpi.get())
            level = int(self.v_level.get())
        except (tk.TclError, ValueError):
            messagebox.showerror("pdf2journal", "DPI e nível do título precisam ser números.")
            return
        settings = Settings(
            pdf=self.pdf_path,
            pages=sorted(self.selected) or None,
            name=self.v_name.get(),
            out=Path(self.v_out.get()),
            split=SPLITS[self.v_split.get()],
            split_level=min(3, max(1, level)),
            asset_prefix=self.v_prefix.get(),
            password=getattr(self, "password", None),
            options=Options(
                images=self.v_images.get(),
                tables=self.v_tables.get(),
                boxes=self.v_boxes.get(),
                strip_headers=self.v_headers.get(),
                dpi=min(600, max(36, dpi)),
                image_format=self.v_format.get(),
            ),
        )
        self.go.configure(state="disabled")
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        self._say("Convertendo…")
        threading.Thread(target=self._worker, args=(settings,), daemon=True).start()

    def _worker(self, settings):
        try:
            result = convert(settings, warn=lambda m: self.events.put(("warn", m)))
            self.events.put(("done", result))
        except ConversionError as e:
            self.events.put(("error", str(e)))
        except Exception as e:  # noqa: BLE001 - mostrar qualquer falha ao usuário
            self.events.put(("error", f"{type(e).__name__}: {e}"))

    def _poll(self):
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == "warn":
                    self._say(f"Aviso: {data}", append=True)
                    continue
                self.progress.stop()
                self.progress.configure(mode="determinate", value=0)
                self.go.configure(state="normal")
                if kind == "error":
                    self._say(f"Erro: {data}")
                    messagebox.showerror("pdf2journal", data)
                else:
                    self._done(data)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _done(self, r):
        self.result = r
        for b in (self.b_folder, self.b_preview, self.b_macro):
            b.configure(state="normal")
        lines = [
            f"Pronto: {r.pages} página(s) de Journal, {r.images} imagem(ns).",
            f"Arquivo: {r.json_path.name}",
            f"Pasta:   {r.json_path.parent}",
            "",
            "No Foundry:",
            (f"1. Copie a pasta \"{r.asset_dir.name}\" para Data/{r.asset_prefix}"
             if r.images else "1. (sem imagens para copiar)"),
            "2. Aba Journal → crie um Journal vazio → botão direito →",
            "   Importar Dados → escolha o .json",
            "   ou: Copiar macro → nova macro do tipo Script → colar → executar.",
        ]
        self._say("\n".join(lines))
        self._save_config()

    def _say(self, text, append=False):
        self.log.configure(state="normal")
        if not append:
            self.log.delete("1.0", "end")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def open_folder(self):
        if self.result:
            _open(self.result.json_path.parent)

    def open_preview(self):
        if self.result:
            _open(self.result.preview_path)

    def copy_macro(self):
        if not self.result:
            return
        entry = json.loads(self.result.json_path.read_text(encoding="utf-8"))
        self.clipboard_clear()
        self.clipboard_append(macro_script(entry))
        self._say("Macro copiada. No Foundry: nova macro do tipo Script → colar → executar.",
                  append=True)

    # ------------------------------------------------------------------ #
    # Preferências
    # ------------------------------------------------------------------ #
    def _load_config(self):
        try:
            cfg = json.loads(config_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for key, var in self._persisted().items():
            if key in cfg:
                try:
                    var.set(cfg[key])
                except tk.TclError:
                    pass

    def _save_config(self):
        try:
            p = config_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({k: v.get() for k, v in self._persisted().items()},
                                    ensure_ascii=False, indent=2), encoding="utf-8")
        except (OSError, tk.TclError):
            pass

    def _persisted(self):
        return {
            "out": self.v_out, "prefix": self.v_prefix, "split": self.v_split,
            "level": self.v_level, "images": self.v_images, "tables": self.v_tables,
            "boxes": self.v_boxes, "headers": self.v_headers, "dpi": self.v_dpi,
            "format": self.v_format,
        }

    def _close(self):
        self._save_config()
        self.destroy()


def _open(path: Path):
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def selftest() -> int:
    """Converte um PDF mínimo; usado pelo CI para validar o executável."""
    import tempfile

    import pymupdf

    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "t.pdf"
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Titulo", fontsize=20)
        page.insert_text((72, 110), "Texto de teste.", fontsize=10)
        doc.save(pdf)
        r = convert(Settings(pdf=pdf, out=Path(tmp) / "out"))
        data = json.loads(r.json_path.read_text(encoding="utf-8"))
        ok = "Texto de teste." in data["pages"][0]["text"]["content"]
    return 0 if ok else 1


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        sys.exit(selftest())
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            pass
    pdf = sys.argv[1] if len(sys.argv) > 1 else None
    App(pdf).mainloop()


if __name__ == "__main__":
    main()
