from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import webbrowser
from collections import Counter
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, scrolledtext, ttk
import tkinter as tk

from str_pdf import __version__
from str_pdf.conversion import Cancelled, FORMATS, VerificationError, app_dir, convert, find_ghostscript, find_verapdf, validate

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:
    DND_FILES = None
    TkinterDnD = None

APP_NAME = "str-pdf"
APP_VERSION = __version__
TITLE = "PDF to PDF/A Converter"
COPYRIGHT = "Copyright © str.ucture GmbH"
NEXT_SUFFIX = "_pdfa"
COLUMNS = (("file", "File", 220), ("size", "Size", 80), ("folder", "Source Folder", 260), ("status", "Status", 130), ("output", "Output File", 220))
STATUS_TAGS = {
    "Verified": "ok", "Validation failed": "bad", "Verification error": "bad", "Conversion failed": "bad",
    "Converting": "busy", "Verifying": "busy", "Cancelled": "muted",
}
FORMAT_HINTS = {
    "PDF/A-1b": "Oldest standard. Use only if an archive system requires it.",
    "PDF/A-2b": "Recommended for most archiving.",
    "PDF/A-3b": "Like 2b, but also allows embedded file attachments.",
}


def settings_path() -> Path:
    if os.name == "nt":
        root = Path(os.getenv("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / APP_NAME / "settings.json"


def path_key(path: Path) -> str:
    return str(path.resolve()).casefold()


def target_for(source: Path, mode: str, output_dir: Path | None) -> Path:
    if mode == "overwrite":
        return source
    if mode == "folder" and output_dir is not None:
        return output_dir / source.name
    return source.with_name(f"{source.stem}{NEXT_SUFFIX}{source.suffix}")


def unique_name(target: Path, suffix: str, reserved: set[str]) -> Path:
    index = 1
    while True:
        candidate = target.with_name(f"{target.stem}{suffix}{'' if index == 1 else f'-{index}'}{target.suffix}")
        if not candidate.exists() and path_key(candidate) not in reserved:
            return candidate
        index += 1


def open_path(path: Path, reveal: bool = False) -> None:
    if os.name == "nt":
        if reveal:
            subprocess.Popen(f'explorer /select,"{path}"')
        else:
            os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)] if reveal else ["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path.parent if reveal else path)])


class ConflictDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, names: list[str]):
        super().__init__(parent)
        self.result = "cancel"
        self.title("Files already exist")
        self.transient(parent)
        self.grab_set()
        panel = ttk.Frame(self, padding=16)
        panel.pack(fill="both", expand=True)
        visible = "\n".join(f"• {name}" for name in names[:6])
        if len(names) > 6:
            visible += f"\n… and {len(names) - 6} more"
        ttk.Label(panel, text=f"{len(names)} output file(s) already exist:\n\n{visible}\n\nChoose how to continue:", justify="left").pack(anchor="w", pady=(0, 14))
        buttons = ttk.Frame(panel)
        buttons.pack()
        for label, result in (("Overwrite All", "overwrite"), ("Create Copies", "copy"), ("Cancel", "cancel")):
            ttk.Button(buttons, text=label, command=lambda value=result: self.finish(value)).pack(side="left", padx=4)
        self.protocol("WM_DELETE_WINDOW", lambda: self.finish("cancel"))
        self.bind("<Escape>", lambda _event: self.finish("cancel"))
        self.update_idletasks()
        self.geometry(f"+{parent.winfo_rootx() + 40}+{parent.winfo_rooty() + 70}")
        parent.wait_window(self)

    def finish(self, value: str) -> None:
        self.result = value
        self.destroy()


class PdfConverterApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.rows: dict[str, dict] = {}  # Treeview item id -> path, size, status, output, details
        self.next_id = 0
        self.output_dir: Path | None = None
        self.running = False
        self.closing = False
        self.cancel_event = threading.Event()
        self.messages: queue.Queue = queue.Queue()
        self.sort_state: tuple[str, bool] | None = None
        self.log_visible = False
        self.mode = tk.StringVar(value="next")
        self.include_subfolders = tk.BooleanVar(value=False)
        self._setup_window()
        self._setup_ui()
        self._load_settings()
        self._log(f"Welcome to {TITLE} v{APP_VERSION}. Conversion and validation run locally.\n")

    def _setup_window(self) -> None:
        self.root.title(f"{TITLE} (v{APP_VERSION})")
        scale = self.root.winfo_fpixels("1i") / 96
        self.root.geometry(f"{int(1100 * scale)}x{int(720 * scale)}")
        self.root.minsize(int(860 * scale), int(560 * scale))
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)
        icon = app_dir() / "assets" / "str.ico"
        if icon.is_file() and os.name == "nt":
            try:
                self.root.iconbitmap(icon)
            except tk.TclError:
                pass
        style = ttk.Style(self.root)
        style.configure("Treeview", rowheight=int(tkfont.nametofont("TkDefaultFont").metrics("linespace") * 1.6))
        style.configure("Muted.TLabel", foreground="#666")
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.bind("<Control-o>", lambda _event: self._add_files())
        self.root.bind("<Escape>", lambda _event: self.tree.selection_set(()))

    def _setup_ui(self) -> None:
        self._make_menu()
        top = ttk.Frame(self.root, padding=(12, 10, 12, 0))
        top.grid(row=0, column=0, sticky="ew")
        self.add_button = ttk.Button(top, text="Add PDF(s)…", command=self._add_files)
        self.add_button.pack(side="left")
        self.folder_button = ttk.Button(top, text="Add Folder…", command=self._add_folder)
        self.folder_button.pack(side="left", padx=5)
        self.subfolder_box = ttk.Checkbutton(top, text="Include subfolders", variable=self.include_subfolders)
        self.subfolder_box.pack(side="left", padx=5)
        self.clear_button = ttk.Button(top, text="Clear List", command=self._clear)
        self.clear_button.pack(side="right")
        self.remove_button = ttk.Button(top, text="Remove Selected", command=self._remove_selected)
        self.remove_button.pack(side="right", padx=5)

        middle = ttk.Frame(self.root, padding=(12, 10, 12, 0))
        middle.grid(row=1, column=0, sticky="nsew")
        middle.columnconfigure(0, weight=1)
        middle.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(middle, columns=[key for key, _, _ in COLUMNS], show="headings", selectmode="extended")
        for key, label, width in COLUMNS:
            self.tree.heading(key, text=label, anchor="w", command=lambda column=key: self._sort(column))
            self.tree.column(key, width=width, minwidth=60, stretch=key in ("file", "folder", "output"))
        self.tree.tag_configure("ok", foreground="#1a7f37")
        self.tree.tag_configure("bad", foreground="#cf222e")
        self.tree.tag_configure("busy", foreground="#0969da")
        self.tree.tag_configure("muted", foreground="#666")
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll = ttk.Scrollbar(middle, orient="vertical", command=self.tree.yview)
        yscroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._on_select())
        self.tree.bind("<Double-1>", lambda _event: self._open_selected())
        self.tree.bind("<Return>", lambda _event: self._open_selected())
        self.tree.bind("<Delete>", lambda _event: self._remove_selected())
        self.tree.bind("<Control-a>", lambda _event: (self.tree.selection_set(self.tree.get_children()), "break")[1])
        self.tree.bind("<Button-3>", self._context_menu)
        self.empty_label = ttk.Label(self.tree, text="Drag and drop PDF files here,\nor use Add PDF(s)… (Ctrl+O).", style="Muted.TLabel", justify="center")
        if DND_FILES:
            for widget in (self.tree, self.empty_label):
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._drop)
        else:
            self.empty_label.configure(text="Use Add PDF(s)… (Ctrl+O) to add files.\nDrag and drop is unavailable in this build.")

        self.details = tk.Text(middle, height=4, wrap="word", state="disabled", relief="flat", font="TkDefaultFont", background=self.root.cget("background"))
        self.details.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.log_frame = ttk.Frame(middle)
        self.log_frame.columnconfigure(0, weight=1)
        self.log_frame.rowconfigure(0, weight=1)
        self.log = scrolledtext.ScrolledText(self.log_frame, height=8, wrap="word", state="disabled", font=("Consolas", 9))
        self.log.grid(row=0, column=0, sticky="nsew")

        self.context = tk.Menu(self.root, tearoff=False)
        self.context.add_command(label="Open Output", command=self._open_selected)
        self.context.add_command(label="Show in Folder", command=lambda: self._open_selected(reveal=True))
        self.context.add_separator()
        self.context.add_command(label="Convert", command=self._convert_selected)
        self.context.add_command(label="Remove from List", command=self._remove_selected)

        controls = ttk.Frame(self.root, padding=(12, 10, 12, 0))
        controls.grid(row=2, column=0, sticky="ew")
        controls.columnconfigure(0, weight=1)
        save = ttk.LabelFrame(controls, text="Save to", padding=(10, 6))
        save.grid(row=0, column=0, sticky="nsew")
        save.columnconfigure(1, weight=1)
        self.mode_buttons = [
            ttk.Radiobutton(save, text=f"Next to original  (adds {NEXT_SUFFIX} to the name)", variable=self.mode, value="next"),
            ttk.Radiobutton(save, text="Folder:", variable=self.mode, value="folder", command=self._folder_mode),
            ttk.Radiobutton(save, text="Overwrite original  (only after verification passes)", variable=self.mode, value="overwrite"),
        ]
        self.mode_buttons[0].grid(row=0, column=0, columnspan=3, sticky="w")
        self.mode_buttons[1].grid(row=1, column=0, sticky="w", pady=2)
        self.output_label = ttk.Label(save, text="Not selected", style="Muted.TLabel")
        self.output_label.grid(row=1, column=1, sticky="w", padx=4)
        self.output_button = ttk.Button(save, text="Browse…", command=self._select_output)
        self.output_button.grid(row=1, column=2, sticky="e")
        self.mode_buttons[2].grid(row=2, column=0, columnspan=3, sticky="w")

        fmt = ttk.LabelFrame(controls, text="PDF/A format", padding=(10, 6))
        fmt.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        self.format_box = ttk.Combobox(fmt, values=list(FORMATS), width=14, state="readonly")
        self.format_box.set("PDF/A-2b")
        self.format_box.grid(row=0, column=0, sticky="w")
        self.format_box.bind("<<ComboboxSelected>>", lambda _event: self._update_format_hint())
        self.format_hint = ttk.Label(fmt, wraplength=240, style="Muted.TLabel")
        self.format_hint.grid(row=1, column=0, sticky="w", pady=(6, 0))

        actions = ttk.Frame(controls)
        actions.grid(row=1, column=0, columnspan=2, sticky="e", pady=(10, 0))
        self.log_button = ttk.Button(actions, text="Show Log ▼", command=self._toggle_log)
        self.log_button.pack(side="left")
        self.convert_selected_button = ttk.Button(actions, text="Convert Selected", command=self._convert_selected)
        self.convert_selected_button.pack(side="left", padx=5)
        self.convert_button = ttk.Button(actions, text="Convert All & Verify", command=self._start)
        self.convert_button.pack(side="left")
        self.cancel_button = ttk.Button(actions, text="Cancel", command=self._cancel)

        ttk.Separator(self.root).grid(row=3, column=0, sticky="ew", padx=10, pady=10)
        footer = ttk.Frame(self.root, padding=(12, 0, 12, 10))
        footer.grid(row=4, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        self.status = ttk.Label(footer, text="Ready")
        self.status.grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(footer, mode="determinate")
        self.progress.grid(row=1, column=0, sticky="ew", pady=(5, 0))

        self._update_format_hint()
        self._update_output_label()
        self._refresh_state()

    def _make_menu(self) -> None:
        menu = tk.Menu(self.root)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="Add PDF(s)…", accelerator="Ctrl+O", command=self._add_files)
        file_menu.add_command(label="Add Folder…", command=self._add_folder)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._close)
        menu.add_cascade(label="File", menu=file_menu)
        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="About", command=self._about)
        help_menu.add_command(label="License", command=self._license)
        menu.add_cascade(label="Help", menu=help_menu)
        self.root.configure(menu=menu)

    def _log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    @staticmethod
    def _size(path: Path) -> tuple[int, str]:
        try:
            size = path.stat().st_size
        except OSError:
            return 0, "N/A"
        value = float(size)
        for unit in ("B", "KB", "MB"):
            if value < 1024:
                return size, f"{size} B" if unit == "B" else f"{value:.1f} {unit}"
            value /= 1024
        return size, f"{value:.1f} GB"

    def _add_paths(self, paths: list[str]) -> None:
        if self.running:
            return
        known = {path_key(row["path"]) for row in self.rows.values()}
        added = skipped = 0
        for value in paths:
            path = Path(value.strip().strip("{}"))
            if not (path.is_file() and path.suffix.lower() == ".pdf") or path_key(path) in known:
                skipped += 1
                continue
            known.add(path_key(path))
            iid = f"r{self.next_id}"
            self.next_id += 1
            size, size_text = self._size(path)
            self.rows[iid] = {"path": path, "bytes": size, "size": size_text, "status": "Queued", "output": None, "details": ""}
            self.tree.insert("", "end", iid=iid)
            self._update_row(iid)
            added += 1
        self._refresh_state()
        if paths:
            detail = f"Added {added} PDF file(s)."
            if skipped:
                detail += f" Skipped {skipped} duplicate, missing, or non-PDF item(s)."
            self.status.configure(text=detail)
            self._log(detail + "\n")

    def _add_files(self) -> None:
        if not self.running:
            self._add_paths(list(filedialog.askopenfilenames(title="Select PDF files", filetypes=(("PDF files", "*.pdf"),))))

    def _add_folder(self) -> None:
        if self.running:
            return
        folder = filedialog.askdirectory(title="Select a folder containing PDFs")
        if not folder:
            return
        root = Path(folder)
        candidates = root.rglob("*") if self.include_subfolders.get() else root.iterdir()
        items = [str(path) for path in sorted(candidates) if path.is_file() and path.suffix.lower() == ".pdf"]
        if items:
            self._add_paths(items)
        else:
            detail = f"No PDFs found in {root}{' or its subfolders' if self.include_subfolders.get() else ''}."
            self.status.configure(text=detail)
            self._log(detail + "\n")

    def _drop(self, event: tk.Event) -> None:
        self._add_paths(list(self.root.tk.splitlist(event.data)))

    def _update_row(self, iid: str) -> None:
        row = self.rows[iid]
        output = row["output"]
        self.tree.item(iid, values=(row["path"].name, row["size"], str(row["path"].parent), row["status"], output.name if output else ""), tags=(STATUS_TAGS.get(row["status"], ""),))
        if iid in self.tree.selection()[:1]:
            self._show_details(iid)

    def _sort(self, column: str) -> None:
        reverse = self.sort_state == (column, False)
        key = (lambda iid: self.rows[iid]["bytes"]) if column == "size" else (lambda iid: self.tree.set(iid, column).casefold())
        for index, iid in enumerate(sorted(self.tree.get_children(), key=key, reverse=reverse)):
            self.tree.move(iid, "", index)
        self.sort_state = (column, reverse)

    def _on_select(self) -> None:
        selection = self.tree.selection()
        self._show_details(selection[0] if selection else None)
        self._refresh_state()

    def _show_details(self, iid: str | None) -> None:
        text = ""
        if iid in self.rows:
            row = self.rows[iid]
            text = f"{row['path'].name}: {row['status']}\nSource: {row['path']}"
            if row["output"]:
                text += f"\nOutput: {row['output']}"
            if row["details"]:
                text += f"\n{row['details']}"
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")

    def _context_menu(self, event: tk.Event) -> None:
        iid = self.tree.identify_row(event.y)
        if not iid or self.running:
            return
        if iid not in self.tree.selection():
            self.tree.selection_set(iid)
        self.context.tk_popup(event.x_root, event.y_root)

    def _convert_selected(self) -> None:
        selection = list(self.tree.selection())
        if selection:
            self._start(selection)

    def _remove_selected(self) -> None:
        if self.running:
            return
        for iid in self.tree.selection():
            self.tree.delete(iid)
            self.rows.pop(iid, None)
        self._refresh_state()

    def _open_selected(self, reveal: bool = False) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        output = self.rows[selection[0]]["output"]
        if output is None or not output.is_file():
            self.status.configure(text="This file has no saved output yet. Convert it first.")
            return
        try:
            open_path(output, reveal)
        except OSError as exc:
            messagebox.showerror("Could not open output", f"{output}\n\n{exc}", parent=self.root)

    def _clear(self) -> None:
        if not self.running:
            self.tree.delete(*self.tree.get_children())
            self.rows.clear()
            self._refresh_state()

    def _folder_mode(self) -> None:
        if self.output_dir is None:
            self._select_output()

    def _select_output(self) -> None:
        folder = filedialog.askdirectory(title="Select a folder to save verified files")
        if folder:
            self.output_dir = Path(folder)
            self.mode.set("folder")
            self._log(f"Output folder: {self.output_dir}\n")
        elif self.output_dir is None and self.mode.get() == "folder":
            self.mode.set("next")
        self._update_output_label()

    def _update_output_label(self) -> None:
        self.output_label.configure(text=str(self.output_dir) if self.output_dir else "Not selected")

    def _update_format_hint(self) -> None:
        self.format_hint.configure(text=FORMAT_HINTS.get(self.format_box.get(), ""))

    def _refresh_state(self) -> None:
        idle = "disabled" if self.running else "normal"
        has_rows = bool(self.rows)
        has_selection = bool(self.tree.selection()) and not self.running
        for widget in (self.add_button, self.folder_button, self.subfolder_box, self.output_button, *self.mode_buttons):
            widget.configure(state=idle)
        self.clear_button.configure(state="normal" if has_rows and not self.running else "disabled")
        self.convert_button.configure(state="normal" if has_rows and not self.running else "disabled")
        self.remove_button.configure(state="normal" if has_selection else "disabled")
        self.convert_selected_button.configure(state="normal" if has_selection else "disabled")
        self.format_box.configure(state="disabled" if self.running else "readonly")
        if has_rows:
            self.empty_label.place_forget()
        else:
            self.empty_label.place(relx=0.5, rely=0.5, anchor="center")

    def _start(self, iids: list[str] | None = None) -> None:
        if self.running:
            return
        iids = list(iids or self.tree.get_children())
        if not iids:
            messagebox.showinfo("No files", "Add one or more PDF files first.", parent=self.root)
            return
        mode = self.mode.get()
        if mode == "folder" and self.output_dir is None:
            self._select_output()
            if self.output_dir is None:
                return
        if not find_ghostscript():
            messagebox.showerror("Ghostscript not found", "This portable app is missing its bundled Ghostscript engine.", parent=self.root)
            return
        if not find_verapdf():
            messagebox.showerror("veraPDF not found", "This portable app is missing its bundled PDF/A validator.", parent=self.root)
            return
        if mode == "overwrite" and not messagebox.askyesno(
            "Overwrite original files?",
            f"Replace the original PDF file(s) for this batch ({len(iids)} total)?\n\nEach original is replaced only after conversion and PDF/A verification both succeed.",
            parent=self.root,
        ):
            return
        jobs = [(iid, self.rows[iid]["path"], target_for(self.rows[iid]["path"], mode, self.output_dir)) for iid in iids]
        groups: dict[str, list[str]] = {}
        for _, _, target in jobs:
            groups.setdefault(path_key(target), []).append(target.name)
        duplicates = [names for names in groups.values() if len(names) > 1]
        if duplicates:
            examples = "\n".join(f"• {names[0]} ({len(names)} inputs)" for names in duplicates[:5])
            more = f"\n… and {len(duplicates) - 5} more name collision(s)" if len(duplicates) > 5 else ""
            if not messagebox.askyesno(
                "Duplicate output names",
                f"Different inputs would target the same filename in {len(duplicates)} group(s):\n\n{examples}{more}\n\nContinue? Later results in each group will be saved with a numbered copy name.",
                parent=self.root,
            ):
                return
        choice = "overwrite"
        if mode != "overwrite":
            conflicts = list(dict.fromkeys(target.name for _, _, target in jobs if target.exists()))
            if conflicts:
                choice = ConflictDialog(self.root, conflicts).result
                if choice == "cancel":
                    return
        self.running = True
        self.cancel_event.clear()
        self._refresh_state()
        self.convert_button.pack_forget()
        self.cancel_button.pack(side="left")
        self.cancel_button.configure(state="normal", text="Cancel")
        self.progress.configure(maximum=len(jobs), value=0)
        self.status.configure(text="Starting conversion and verification…")
        threading.Thread(target=self._worker, args=(jobs, self.format_box.get(), choice), daemon=True).start()
        self.root.after(100, self._poll)

    def _worker(self, jobs: list[tuple[str, Path, Path]], output_format: str, conflict_choice: str) -> None:
        gs, validator = find_ghostscript(), find_verapdf()
        if not gs or not validator:
            self.messages.put(("complete", "Bundled Ghostscript or veraPDF is missing."))
            return
        counts: Counter[str] = Counter()
        reserved = {path_key(target) for _, _, target in jobs}
        written: set[str] = set()
        for index, (iid, source, target) in enumerate(jobs, 1):
            if self.cancel_event.is_set():
                for pending, _, _ in jobs[index - 1:]:
                    self.messages.put(("result", pending, "Cancelled", "Not started.", None))
                break
            if (conflict_choice == "copy" and target.exists()) or path_key(target) in written:
                target = unique_name(target, "-pdf-a-copy", reserved | written)
            written.add(path_key(target))
            try:
                state, details, output = self._process(iid, index, len(jobs), source, target, output_format, gs, validator, reserved | written)
            except Cancelled:
                for offset, (pending, _, _) in enumerate(jobs[index - 1:]):
                    self.messages.put(("result", pending, "Cancelled", "Cancelled while processing." if offset == 0 else "Not started.", None))
                break
            except Exception as exc:
                state, details, output = "Conversion failed", str(exc), None
            counts[state] += 1
            self.messages.put(("result", iid, state, details, output))
        summary = (
            f"{counts['Verified']} of {len(jobs)} file(s) converted and verified."
            f" {counts['Validation failed']} failed validation, {counts['Verification error']} verification errors, {counts['Conversion failed']} conversion failures."
        )
        self.messages.put(("complete", (summary, self.cancel_event.is_set(), counts["Verified"] < len(jobs))))

    def _process(self, iid: str, index: int, total: int, source: Path, target: Path, output_format: str, gs: Path, validator: Path, reserved: set[str]) -> tuple[str, str, Path | None]:
        self.messages.put(("status", index, total, iid, "Converting"))
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{target.stem}-", suffix=".pdf", dir=target.parent)
        os.close(fd)
        temporary = Path(tmp_name)
        try:
            conversion_log = convert(source, temporary, output_format, gs, self.cancel_event)
            if conversion_log.strip():
                self.messages.put(("log", conversion_log))
            self.messages.put(("status", index, total, iid, "Verifying"))
            try:
                valid, details = validate(temporary, FORMATS[output_format], validator, self.cancel_event)
                state = "Verified" if valid else "Validation failed"
            except VerificationError as exc:
                valid, details, state = False, str(exc), "Verification error"
            if self.cancel_event.is_set():
                raise Cancelled()
            if valid:
                os.replace(temporary, target)
                return state, details, target
            if target.resolve() == source.resolve():
                return state, details + "\nOriginal left unchanged.", None
            failed = unique_name(target, "-validation-failed", reserved)
            os.replace(temporary, failed)
            return state, details + f"\nCandidate retained at: {failed}", failed
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def _poll(self) -> None:
        try:
            while True:
                item = self.messages.get_nowait()
                kind = item[0]
                if kind == "log":
                    self._log(item[1] + ("\n" if not item[1].endswith("\n") else ""))
                elif kind == "status":
                    _, current, total, iid, state = item
                    row = self.rows[iid]
                    self.status.configure(text=f"{state} {current}/{total}: {row['path'].name}")
                    self.progress.configure(value=current - (0.5 if state == "Verifying" else 1))
                    row["status"] = state
                    if state == "Converting":
                        row["output"], row["details"] = None, ""
                    self._update_row(iid)
                elif kind == "result":
                    _, iid, state, details, output = item
                    row = self.rows[iid]
                    saved_line = f"Saved to: {output}\n" if output else ""
                    self._log(f"{row['path'].name}: {state}\nSource: {row['path']}\n{saved_line}{details}\n\n")
                    row.update(status=state, output=output, details=details)
                    self._update_row(iid)
                elif kind == "complete":
                    self._finish(item[1])
                    return
        except queue.Empty:
            pass
        if self.running:
            self.root.after(100, self._poll)

    def _finish(self, result: tuple[str, bool, bool] | str) -> None:
        self.running = False
        self.cancel_button.pack_forget()
        self.convert_button.pack(side="left")
        self._refresh_state()
        if isinstance(result, tuple):
            summary, cancelled, had_problems = result
            self.progress.configure(value=self.progress.cget("maximum"))
            self.status.configure(text=f"{'Cancelled. ' if cancelled else ''}{summary}")
            self._log(f"{self.status.cget('text')}\n")
            # Only interrupt the user when something needs attention; a clean run is shown in the status bar.
            if had_problems and not cancelled and not self.closing:
                messagebox.showwarning("Some files need attention", f"{summary}\n\nSelect a red row to see why.", parent=self.root)
        else:
            self.status.configure(text=result)
            messagebox.showerror("Could not start", result, parent=self.root)
        if self.closing:
            self._save_settings()
            self.root.destroy()

    def _cancel(self) -> None:
        if self.running:
            self.cancel_event.set()
            self.cancel_button.configure(state="disabled", text="Cancelling…")
            self._log("Cancellation requested; stopping the current engine process…\n")

    def _toggle_log(self) -> None:
        self.log_visible = not self.log_visible
        if self.log_visible:
            self.log_frame.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(6, 0))
            self.log_button.configure(text="Hide Log ▲")
        else:
            self.log_frame.grid_forget()
            self.log_button.configure(text="Show Log ▼")

    def _save_settings(self) -> None:
        # ponytail: overwrite mode is never persisted, so a restart always starts in a non-destructive mode.
        mode = self.mode.get() if self.mode.get() != "overwrite" else ("folder" if self.output_dir else "next")
        data = {
            "output_directory": str(self.output_dir or ""), "output_mode": mode,
            "pdfa_version": self.format_box.get(), "include_subfolders": self.include_subfolders.get(),
        }
        target = settings_path()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError as exc:
            self._log(f"Could not save preferences: {exc}\n")

    def _load_settings(self) -> None:
        try:
            data = json.loads(settings_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        output = data.get("output_directory")
        if output and Path(output).is_dir():
            self.output_dir = Path(output)
        if data.get("output_mode") == "folder" and self.output_dir:
            self.mode.set("folder")
        if data.get("pdfa_version") in FORMATS:
            self.format_box.set(data["pdfa_version"])
        self.include_subfolders.set(bool(data.get("include_subfolders", False)))
        self._update_output_label()
        self._update_format_hint()

    def _close(self) -> None:
        if self.running:
            if messagebox.askyesno("Conversion in progress", "Cancel the current conversion and exit?", parent=self.root):
                self.closing = True
                self._cancel()
            return
        self._save_settings()
        self.root.destroy()

    def _about(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("About")
        window.resizable(False, False)
        panel = ttk.Frame(window, padding=18)
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text=f"{TITLE}\nVersion {APP_VERSION}\n{COPYRIGHT}\n\nOffline conversion and veraPDF conformance validation.").pack(anchor="w")
        ttk.Button(panel, text="Website", command=lambda: webbrowser.open("https://str-ucture.com")).pack(anchor="w", pady=(10, 0))
        ttk.Button(panel, text="Developer", command=lambda: webbrowser.open("https://github.com/shailesh-stha")).pack(anchor="w", pady=4)
        ttk.Label(panel, text="Contact: info@str-ucture.com").pack(anchor="w")
        ttk.Button(panel, text="Copy contact email", command=lambda: self._copy_email(window)).pack(anchor="w", pady=4)
        ttk.Button(panel, text="OK", command=window.destroy).pack(anchor="e", pady=(6, 0))
        window.bind("<Escape>", lambda _event: window.destroy())
        window.transient(self.root)
        window.grab_set()

    @staticmethod
    def _copy_email(window: tk.Toplevel) -> None:
        window.clipboard_clear()
        window.clipboard_append("info@str-ucture.com")
        window.update()

    def _license(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("License and notices")
        window.geometry("560x330")
        text = scrolledtext.ScrolledText(window, wrap="word")
        text.pack(fill="both", expand=True, padx=10, pady=10)
        root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else app_dir()
        license_file = root / ("LICENSE.txt" if getattr(sys, "frozen", False) else "LICENSE")
        notice_file = root / "THIRD_PARTY_NOTICES.txt" if getattr(sys, "frozen", False) else root / "THIRD_PARTY_NOTICES.md"
        parts = []
        for path in (license_file, notice_file):
            try:
                parts.append(path.read_text(encoding="utf-8"))
            except OSError:
                continue
        text.insert("1.0", "\n\n".join(parts) or "See the bundled license and third-party notices.")
        text.configure(state="disabled")
        ttk.Button(window, text="Close", command=window.destroy).pack(pady=(0, 10))
        window.bind("<Escape>", lambda _event: window.destroy())
        window.transient(self.root)
        window.grab_set()


def main() -> None:
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # sharp text on scaled displays
        except (AttributeError, OSError):
            pass
    root = (TkinterDnD.Tk if TkinterDnD else tk.Tk)()
    PdfConverterApp(root)
    root.mainloop()

