import tkinter as tk
from tkinter import messagebox, scrolledtext, filedialog, ttk
from tkinter import font as tkfont
import sys
import requests
import ghostscript
import webbrowser
from pathlib import Path
from typing import List, Iterable
from PIL import Image, ImageTk
import threading
import queue
from tkinterdnd2 import DND_FILES, TkinterDnD
import tempfile # For safe in-place overwrites
import os       # For the atomic replace operation
import json     # For persisting settings

# --- Constants ---
APP_NAME = "PDF to PDF/A Converter"
APP_VERSION = "1.2.0" # Version updated to reflect changes
WINDOW_WIDTH = 650
WINDOW_HEIGHT = 550
AUTH_URL = "https://raw.githubusercontent.com/str-ucture/str-key/refs/heads/main/key_25.txt"
AUTH_FILE_PATH = Path("utils/auth.bin")
ICON_PATH = Path("utils/str.ico")
COPY_ICON_PATH = Path("utils/btn_copy.ico")
SETTINGS_FILE = Path("settings.json") # For persisting user settings
MIN_PANE_HEIGHT = 75

PDFA_MAP = {
    "PDF/A-1b": "-dPDFA=1",
    "PDF/A-2b": "-dPDFA=2",
    "PDF/A-3b": "-dPDFA=3",
}
DEFAULT_PDFA_VERSION = "PDF/A-2b"

# --- Helper Classes & Functions ---
class BatchConfirmDialog(tk.Toplevel):
    """A custom modal dialog for the batch file conflict."""
    def __init__(self, parent, title, conflicting_files):
        super().__init__(parent)
        self.title(title)
        self.result = "cancel"
        self.transient(parent)
        self.grab_set()
        main_frame = ttk.Frame(self, padding=20)
        main_frame.pack(expand=True, fill="both")
        file_list_str = "\n".join(f"- {name}" for name in conflicting_files[:5])
        if len(conflicting_files) > 5:
            file_list_str += f"\n- ...and {len(conflicting_files) - 5} more"
        message = f"The following {len(conflicting_files)} file(s) already exist in the destination:\n\n{file_list_str}\n\nWhat would you like to do?"
        ttk.Label(main_frame, text=message, wraplength=400, justify="left").pack(pady=(0, 20))
        button_frame = ttk.Frame(main_frame)
        button_frame.pack()
        ttk.Button(button_frame, text="Overwrite All", command=lambda: self._set_result("overwrite")).pack(side="left", padx=5)
        ttk.Button(button_frame, text="Create Copies", command=lambda: self._set_result("copy")).pack(side="left", padx=5)
        ttk.Button(button_frame, text="Cancel", command=lambda: self._set_result("cancel")).pack(side="left", padx=5)
        self.protocol("WM_DELETE_WINDOW", lambda: self._set_result("cancel"))
        self._center_window(parent)
        self.wait_window(self)

    def _set_result(self, result):
        self.result = result
        self.destroy()

    def _center_window(self, parent):
        self.update_idletasks()
        parent_x, parent_y = parent.winfo_x(), parent.winfo_y()
        parent_width, parent_height = parent.winfo_width(), parent.winfo_height()
        dialog_width, dialog_height = self.winfo_width(), self.winfo_height()
        x = parent_x + (parent_width - dialog_width) // 2
        y = parent_y + (parent_height - dialog_height) // 2
        self.geometry(f"+{x}+{y}")

class TextRedirector:
    def __init__(self, text_widget: scrolledtext.ScrolledText):
        self.text_widget = text_widget
    def write(self, string: str):
        self.text_widget.configure(state='normal')
        self.text_widget.insert(tk.END, string)
        self.text_widget.see(tk.END)
        self.text_widget.configure(state='disabled')
    def flush(self):
        pass

def center_window(win: tk.Tk, width: int, height: int):
    screen_width = win.winfo_screenwidth()
    screen_height = win.winfo_screenheight()
    x = (screen_width - width) // 2
    y = (screen_height - height) // 2
    win.geometry(f'{width}x{height}+{x}+{y}')

def check_authentication(url: str, local_path: Path) -> bool:
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        expected_str_key = response.text.strip()
    except requests.exceptions.RequestException as e:
        print(f"Authentication Error: Could not fetch remote key. {e}")
        return False
    if not local_path.exists():
        print(f"Authentication Error: Local key file not found at '{local_path}'.")
        return False
    try:
        stored_str_key = local_path.read_text(encoding='utf-8').strip()
    except IOError as e:
        print(f"Authentication Error: Could not read local key file. {e}")
        return False
    return stored_str_key == expected_str_key

# --- Main Application Class ---

class PdfConverterApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.copy_icon = None
        self.files_to_convert: List[Path] = []
        self.path_to_iid_map = {}
        self.log_visible = False
        self.is_converting = False
        self.output_directory: Path = None
        self.placeholder_label = None
        
        # --- New attributes for added features ---
        self.cancel_event = threading.Event()
        self.overwrite_originals_var = tk.BooleanVar(value=False)
        
        self._setup_window()
        self._configure_styles()
        self._setup_ui()
        self._redirect_output()
        self._load_settings() # Load settings on startup

    def _setup_window(self):
        self.root.title(f"{APP_NAME} (v{APP_VERSION})")
        center_window(self.root, WINDOW_WIDTH, WINDOW_HEIGHT)
        self.root.resizable(True, True)
        self.root.minsize(650, 500)
        if ICON_PATH.exists():
            self.root.iconbitmap(ICON_PATH)
        # --- New: Handle window closing to save settings ---
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

    def _configure_styles(self):
        style = ttk.Style(self.root)
        style.configure("Treeview", background="white", foreground="black", rowheight=25, fieldbackground="white")
        style.map("Treeview", background=[('selected', '#0078d7')])
        style.configure("Treeview.Heading", font=('Calibri', 10, 'bold'), background="#E1E1E1", relief="groove", borderwidth=1)
        style.configure("Placeholder.TLabel", foreground="grey", background="white", font=('Calibri', 11))
        style.configure("TPanedWindow.Sash", background="#c0c0c0", sashwidth=6, relief="flat")
        style.layout("Treeview", [('Treeview.treearea', {'sticky': 'nswe'})])

    def _setup_ui(self):
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(1, weight=1)
        self._create_menu()
        self._create_file_selection_ui()
        self.main_paned_window = ttk.PanedWindow(self.root, orient=tk.VERTICAL)
        self.main_paned_window.grid(row=1, column=0, sticky="nsew", padx=20, pady=10)
        self._create_file_list_ui()
        self._create_log_display_ui()
        self.main_paned_window.add(self.file_list_frame, weight=3)
        if self.log_visible:
            self.main_paned_window.add(self.log_frame, weight=1)
        self._create_conversion_ui()
        self._create_progress_ui()
        separator = ttk.Separator(self.root, orient='horizontal')
        separator.grid(row=3, column=0, sticky='ew', padx=10, pady=10)
        self.root.bind("<Escape>", self._clear_selection)
        self._update_placeholder_visibility()

    def _create_menu(self):
        menu = tk.Menu(self.root)
        filemenu = tk.Menu(menu, tearoff=0)
        menu.add_cascade(label="File", menu=filemenu)
        filemenu.add_command(label="About", command=self.show_about)
        filemenu.add_command(label="License", command=self.show_license)
        filemenu.add_separator()
        filemenu.add_command(label="Exit", command=self._on_closing)
        self.root.config(menu=menu)

    def _create_file_selection_ui(self):
        frame = ttk.Frame(self.root, padding="10 10 0 0")
        frame.grid(row=0, column=0, sticky="ew", padx=10)
        self.add_files_btn = ttk.Button(frame, text="Add PDF(s)", command=self._add_files)
        self.add_files_btn.pack(side="left")
        self.add_folder_btn = ttk.Button(frame, text="Add from Folder", command=self._add_from_folder)
        self.add_folder_btn.pack(side="left", padx=5)
        self.clear_list_btn = ttk.Button(frame, text="Clear List", command=self._clear_list)
        self.clear_list_btn.pack(side="right", padx=(0, 10))
        self.remove_selected_btn = ttk.Button(frame, text="Remove Selected", command=self._remove_selected_files)
        self.remove_selected_btn.pack(side="right", padx=(0, 5))

    def _create_file_list_ui(self):
        self.file_list_frame = ttk.Frame(self.main_paned_window, height=MIN_PANE_HEIGHT, relief="solid", borderwidth=1, padding=2)
        self.file_list_frame.grid_propagate(False)
        self.file_list_frame.grid_rowconfigure(0, weight=1)
        self.file_list_frame.grid_columnconfigure(0, weight=1)
        columns = ("sn", "name", "size", "path", "status")
        self.file_tree = ttk.Treeview(self.file_list_frame, columns=columns, show="headings", height=10)
        self.file_tree.heading("sn", text="S.N.")
        self.file_tree.heading("name", text="File Name")
        self.file_tree.heading("size", text="File Size")
        self.file_tree.heading("path", text="File Path")
        self.file_tree.heading("status", text="Status")
        self.file_tree.column("sn", width=30, stretch=False, anchor="center")
        self.file_tree.column("name", width=150, stretch=False)
        self.file_tree.column("size", width=70, stretch=False, anchor="center")
        self.file_tree.column("path", width=235, stretch=False)
        self.file_tree.column("status", width=100, stretch=False, anchor="center")
        self.file_tree.tag_configure('oddrow', background='#F0F0F0')
        self.file_tree.tag_configure('evenrow', background='white')
        self.file_tree.grid(row=0, column=0, sticky="nsew")
        self.file_tree.drop_target_register(DND_FILES)
        self.file_tree.dnd_bind('<<Drop>>', self._handle_drop)
        self.context_menu = tk.Menu(self.file_tree, tearoff=0)
        self.context_menu.add_command(label="Remove File", command=self._remove_selected_files)
        self.file_tree.bind("<Button-3>", self._show_context_menu)
        v_scroll = ttk.Scrollbar(self.file_list_frame, orient=tk.VERTICAL, command=self.file_tree.yview)
        v_scroll.grid(row=0, column=1, sticky="ns")
        self.file_tree.configure(yscrollcommand=v_scroll.set)
        h_scroll = ttk.Scrollbar(self.file_list_frame, orient=tk.HORIZONTAL, command=self.file_tree.xview)
        h_scroll.grid(row=1, column=0, sticky="ew")
        self.file_tree.configure(xscrollcommand=h_scroll.set)
        placeholder_text = "Drag and drop PDF files here,\nor use the buttons above to add them."
        self.placeholder_label = ttk.Label(self.file_list_frame, text=placeholder_text, style="Placeholder.TLabel", justify="center")

    def _create_conversion_ui(self):
        frame = ttk.Frame(self.root, padding="10 5 10 0")
        frame.grid(row=2, column=0, sticky="ew", padx=10)
        frame.grid_columnconfigure(1, weight=1)
        self.output_path_label = ttk.Label(frame, text="Output Folder: Not Selected")
        self.output_path_label.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.save_folder_btn = ttk.Button(frame, text="Output Folder", command=self._select_output_folder)
        self.save_folder_btn.grid(row=0, column=2, sticky="e", padx=(0, 5))
        # --- New: Overwrite checkbox ---
        self.overwrite_checkbox = ttk.Checkbutton(
            frame, text="Overwrite original files", variable=self.overwrite_originals_var,
            command=self._toggle_output_folder_state
        )
        self.overwrite_checkbox.grid(row=1, column=0, columnspan=2, sticky="w", pady=(5,0))
        combo_label = ttk.Label(frame, text="Conversion Format:")
        combo_label.grid(row=2, column=0, sticky="w", pady=(10,0))
        self.combobox = ttk.Combobox(frame, values=list(PDFA_MAP.keys()), width=20, state="readonly")
        self.combobox.set(DEFAULT_PDFA_VERSION)
        self.combobox.grid(row=2, column=1, sticky="w", pady=(10,0))
        actions_frame = ttk.Frame(frame)
        actions_frame.grid(row=2, column=2, sticky="e", pady=(10,0))
        self.log_toggle_btn = ttk.Button(actions_frame, text="Show Log ▼", command=self._toggle_log_display)
        self.log_toggle_btn.pack(side="left")
        self.convert_btn = ttk.Button(actions_frame, text="Convert PDF(s)", command=self._start_conversion)
        self.convert_btn.pack(side="left", padx=(5, 5))
        # --- New: Cancel button, initially hidden ---
        self.cancel_btn = ttk.Button(actions_frame, text="Cancel", command=self._cancel_conversion)
        # self.cancel_btn will be packed later when conversion starts

    def _create_progress_ui(self):
        frame = ttk.Frame(self.root, padding="10 0 10 5")
        frame.grid(row=4, column=0, sticky="ew", padx=10)
        frame.grid_columnconfigure(0, weight=1)
        self.status_label = ttk.Label(frame, text="Status: Idle")
        self.status_label.grid(row=0, column=0, sticky="w")
        self.progress_bar = ttk.Progressbar(frame, orient='horizontal', mode='determinate')
        self.progress_bar.grid(row=1, column=0, sticky="ew", pady=(5,0))

    def _create_log_display_ui(self):
        self.log_frame = ttk.Frame(self.main_paned_window, height=MIN_PANE_HEIGHT, relief="solid", borderwidth=1, padding=2)
        self.log_frame.grid_propagate(False)
        self.log_frame.grid_rowconfigure(0, weight=1)
        self.log_frame.grid_columnconfigure(0, weight=1)
        self.log_display = scrolledtext.ScrolledText(self.log_frame, wrap=tk.WORD, height=8, relief="flat", borderwidth=0)
        self.log_display.configure(font=("Courier New", 8), state='disabled')
        self.log_display.grid(row=0, column=0, sticky="nsew")

    def _update_placeholder_visibility(self):
        if not self.files_to_convert:
            self.placeholder_label.place(relx=0.5, rely=0.5, anchor="center")
        else:
            self.placeholder_label.place_forget()

    # --- New Methods for Added Features ---
    
    def _on_closing(self):
        """Handle window close event to save settings."""
        if self.is_converting:
            if messagebox.askyesno("Confirm Exit", "A conversion is in progress. Are you sure you want to exit?", parent=self.root):
                self._cancel_conversion()
                self._save_settings()
                self.root.destroy()
        else:
            self._save_settings()
            self.root.destroy()
            
    def _save_settings(self):
        """Saves current settings to a JSON file."""
        settings = {
            "output_directory": str(self.output_directory) if self.output_directory else "",
            "pdfa_version": self.combobox.get()
        }
        try:
            SETTINGS_FILE.write_text(json.dumps(settings, indent=4))
        except Exception as e:
            print(f"Warning: Could not save settings. {e}")

    def _load_settings(self):
        """Loads settings from JSON file on startup."""
        try:
            if SETTINGS_FILE.exists():
                settings = json.loads(SETTINGS_FILE.read_text())
                output_dir = settings.get("output_directory")
                if output_dir and Path(output_dir).is_dir():
                    self.output_directory = Path(output_dir)
                    display_path = self._truncate_path(self.output_directory)
                    self.output_path_label.config(text=f"Output Folder: {display_path}")

                pdfa_version = settings.get("pdfa_version")
                if pdfa_version in PDFA_MAP:
                    self.combobox.set(pdfa_version)
        except Exception as e:
            print(f"Warning: Could not load settings. {e}")

    def _toggle_output_folder_state(self):
        """Disables the output folder button when overwrite is checked."""
        if self.overwrite_originals_var.get():
            self.save_folder_btn.config(state="disabled")
            self.output_path_label.config(text="Output: Overwriting original files")
        else:
            self.save_folder_btn.config(state="normal")
            if self.output_directory:
                display_path = self._truncate_path(self.output_directory)
                self.output_path_label.config(text=f"Output Folder: {display_path}")
            else:
                self.output_path_label.config(text="Output Folder: Not Selected")

    def _cancel_conversion(self):
        """Signals the worker thread to stop."""
        if self.is_converting:
            print("\n--- Cancellation requested by user. Finishing current file... ---\n")
            self.cancel_event.set()
            self.cancel_btn.config(state="disabled", text="Cancelling...")

    # --- End of New Methods ---

    def _toggle_log_display(self):
        if self.log_visible:
            self.main_paned_window.forget(self.log_frame)
            self.log_toggle_btn.configure(text="Show Log ▼")
            self.log_visible = False
        else:
            self.main_paned_window.add(self.log_frame, weight=1)
            self.log_toggle_btn.configure(text="Hide Log ▲")
            self.log_visible = True

    def _show_context_menu(self, event):
        iid = self.file_tree.identify_row(event.y)
        if iid:
            if iid not in self.file_tree.selection():
                self.file_tree.selection_set(iid)
            self.context_menu.post(event.x_root, event.y_root)

    def _clear_selection(self, event=None):
        self.file_tree.selection_remove(self.file_tree.selection())

    def _redirect_output(self):
        redirector = TextRedirector(self.log_display)
        sys.stdout = redirector
        sys.stderr = redirector
        print(f"Welcome to {APP_NAME}!\n")
    
    def _select_output_folder(self):
        if self.is_converting: return
        output_dir_str = filedialog.askdirectory(title="Select a folder to save converted files")
        if output_dir_str:
            self.output_directory = Path(output_dir_str)
            display_path = self._truncate_path(self.output_directory)
            self.output_path_label.config(text=f"Output Folder: {display_path}")
            print(f"Output folder set to: {self.output_directory}\n")

    def _truncate_path(self, path: Path, max_len: int = 50) -> str:
        path_str = str(path)
        if len(path_str) > max_len:
            return f"...{path_str[-max_len:]}"
        return path_str

    def _write_to_log(self, message: str):
        self.log_display.configure(state='normal')
        self.log_display.insert(tk.END, message)
        self.log_display.see(tk.END)
        self.log_display.configure(state='disabled')
        
    def _format_size(self, size_bytes: int) -> str:
        if size_bytes < 1024: return f"{size_bytes} B"
        elif size_bytes < 1024**2: return f"{size_bytes/1024:.1f} KB"
        elif size_bytes < 1024**3: return f"{size_bytes/1024**2:.1f} MB"
        else: return f"{size_bytes/1024**3:.1f} GB"

    def _update_file_list_display(self):
        for item in self.file_tree.get_children():
            self.file_tree.delete(item)
        self.path_to_iid_map.clear()
        for i, fpath in enumerate(self.files_to_convert, start=1):
            try:
                size_formatted = self._format_size(fpath.stat().st_size)
            except FileNotFoundError:
                size_formatted = "N/A"
            tag = 'oddrow' if i % 2 != 0 else 'evenrow'
            values = (i, fpath.name, size_formatted, str(fpath.parent), '-')
            iid = self.file_tree.insert('', tk.END, values=values, tags=(tag,))
            self.path_to_iid_map[fpath] = iid

    def _add_paths_to_list(self, paths: Iterable[str]):
        added_count = 0
        for path_str in paths:
            fpath = Path(path_str)
            if fpath.is_file() and fpath.suffix.lower() == '.pdf' and fpath not in self.files_to_convert:
                self.files_to_convert.append(fpath)
                added_count += 1
        if added_count > 0: self._update_file_list_display()
        self._update_placeholder_visibility()

    def _add_files(self):
        filepaths = filedialog.askopenfilenames(title="Select PDF files", filetypes=[("PDF files", "*.pdf")])
        if filepaths: self._add_paths_to_list(filepaths)

    def _add_from_folder(self):
        folder_path = filedialog.askdirectory(title="Select a folder containing PDFs")
        if not folder_path: return
        self._add_paths_to_list(str(p) for p in sorted(Path(folder_path).glob("*.pdf")))
    
    def _handle_drop(self, event):
        paths = self.root.tk.splitlist(event.data)
        self._add_paths_to_list(paths)

    def _clear_list(self):
        if self.is_converting: return
        self.files_to_convert.clear()
        self._update_file_list_display()
        print("File list cleared.\n")
        self._update_placeholder_visibility()
    
    def _remove_selected_files(self):
        if self.is_converting: return
        selected_iids = self.file_tree.selection()
        if not selected_iids:
            messagebox.showinfo("Information", "Please select one or more files to remove.", parent=self.root)
            return
        paths_to_remove = {Path(self.file_tree.item(iid, 'values')[3]) / self.file_tree.item(iid, 'values')[1] for iid in selected_iids}
        self.files_to_convert = [path for path in self.files_to_convert if path not in paths_to_remove]
        self._update_file_list_display()
        print(f"Removed {len(paths_to_remove)} file(s) from the list.\n")
        self._update_placeholder_visibility()
    
    def _toggle_controls_state(self, state: str):
        self.add_files_btn.config(state=state)
        self.add_folder_btn.config(state=state)
        self.clear_list_btn.config(state=state)
        self.remove_selected_btn.config(state=state)
        self.save_folder_btn.config(state=state)
        self.combobox.config(state=state if state == 'normal' else 'readonly')
        self.overwrite_checkbox.config(state=state)
        # Re-apply logic for output folder button if state is 'normal'
        if state == 'normal':
             self._toggle_output_folder_state()

    def _start_conversion(self):
        if self.is_converting: return
        if not self.files_to_convert:
            messagebox.showinfo("No Files", "Please add files to the list before converting.", parent=self.root)
            return
            
        is_overwrite_mode = self.overwrite_originals_var.get()
        if not is_overwrite_mode and not self.output_directory:
            messagebox.showerror("Error", "Please select an output folder or check 'Overwrite original files'.", parent=self.root)
            return

        conflict_choice = "overwrite" # Default
        if not is_overwrite_mode:
            conflicting_files = [p.name for p in self.files_to_convert if (self.output_directory / p.name).exists()]
            if conflicting_files:
                dialog = BatchConfirmDialog(self.root, "Confirm File Copies", conflicting_files)
                choice = dialog.result
                if choice == "cancel":
                    print("Conversion cancelled by user.\n")
                    return
                conflict_choice = choice
        
        self.is_converting = True
        self.cancel_event.clear() # Reset cancel event
        self._toggle_controls_state('disabled')
        self.convert_btn.pack_forget() # Hide convert button
        self.cancel_btn.pack(side="left", padx=(5, 5)) # Show cancel button
        self.cancel_btn.config(state="normal", text="Cancel")
        self._update_file_list_display()
        self.progress_bar['value'] = 0
        self.progress_bar['maximum'] = len(self.files_to_convert)

        self.comm_queue = queue.Queue()
        worker_thread = threading.Thread(
            target=self._conversion_worker,
            args=(
                self.files_to_convert, self.output_directory, PDFA_MAP[self.combobox.get()],
                self.comm_queue, conflict_choice, self.cancel_event, is_overwrite_mode
            )
        )
        worker_thread.start()
        self.root.after(100, self._check_progress_queue)
        
    def _finalize_conversion(self, summary_msg: str, show_popup: bool = True):
        """Resets the UI after conversion is complete or cancelled."""
        self.is_converting = False
        self._toggle_controls_state('normal')
        self.cancel_btn.pack_forget()
        self.convert_btn.pack(side="left", padx=(5, 5))
        self.status_label.config(text=f"Status: {summary_msg}")
        self._write_to_log(f"\n--- Conversion Finished ---\n{summary_msg}\n")
        if show_popup:
            messagebox.showinfo("Process Finished", summary_msg, parent=self.root)

    def _check_progress_queue(self):
        try:
            while True:
                message = self.comm_queue.get_nowait()
                msg_type = message.get('type')
                
                if msg_type == 'log':
                    self._write_to_log(message['message'])
                elif msg_type == 'progress':
                    self.status_label.config(text=f"Converting {message['current']}/{message['total']}: {message['filename']}")
                    self.progress_bar['value'] = message['current']
                elif msg_type in ('success', 'error'):
                    path = message.get('path')
                    iid = self.path_to_iid_map.get(path)
                    if iid:
                        status_text = "Completed" if msg_type == 'success' else "Failed"
                        self.file_tree.set(iid, column='status', value=status_text)
                    if msg_type == 'error':
                        self._write_to_log(f"--- ERROR converting '{path.name}'. See details above. ---\n")
                elif msg_type == 'complete':
                    self._finalize_conversion(message['summary'])
                    return # Stop checking the queue
                elif msg_type == 'cancelled':
                    self._finalize_conversion(message['summary'], show_popup=False)
                    return # Stop checking the queue
        except queue.Empty:
            pass
        finally:
            if self.is_converting:
                self.root.after(100, self._check_progress_queue)

    def _conversion_worker(self, files: List[Path], output_dir: Path, version_flag: str, q: queue.Queue, conflict_choice: str, cancel_event: threading.Event, is_overwrite_mode: bool):
        total_files = len(files)
        success_count = 0
        processed_count = 0
        output_location_msg = "overwriting original files" if is_overwrite_mode else f"folder: {output_dir}"
        q.put({'type': 'log', 'message': f"Starting conversion for {total_files} file(s)...\nOutput: {output_location_msg}\n\n"})
        
        for i, input_path in enumerate(files):
            if cancel_event.is_set():
                break

            processed_count += 1
            q.put({'type': 'progress', 'current': i + 1, 'total': total_files, 'filename': input_path.name})
            
            temp_output_path = None
            try:
                # Determine the correct output directory for this file
                current_output_dir = input_path.parent if is_overwrite_mode else output_dir
                final_output_path = current_output_dir / input_path.name
                
                is_inplace_overwrite = (is_overwrite_mode or 
                                       (conflict_choice == "overwrite" and input_path.resolve() == final_output_path.resolve()))
                
                if final_output_path.exists() and not is_overwrite_mode:
                    if conflict_choice == "copy":
                        new_name = f"{input_path.stem}-pdf-a-copy.pdf"
                        final_output_path = current_output_dir / new_name
                        q.put({'type': 'log', 'message': f"Creating a copy: '{new_name}'.\n"})
                    elif conflict_choice == "overwrite" and not is_inplace_overwrite:
                        q.put({'type': 'log', 'message': f"Overwriting existing file: '{final_output_path.name}'.\n"})

                if is_inplace_overwrite:
                    q.put({'type': 'log', 'message': f"Performing safe in-place overwrite for: '{final_output_path.name}'.\n"})
                    with tempfile.NamedTemporaryFile(mode='wb', dir=current_output_dir, delete=False, suffix=".pdf") as tmp_file:
                        temp_output_path = Path(tmp_file.name)
                    conversion_target_path = temp_output_path
                else:
                    conversion_target_path = final_output_path

                self._pdf_to_pdfa(input_path, conversion_target_path, version_flag, q)
                
                if is_inplace_overwrite:
                    os.replace(temp_output_path, final_output_path)
                    temp_output_path = None

                q.put({'type': 'success', 'path': input_path})
                success_count += 1
            except Exception as e:
                q.put({'type': 'error', 'path': input_path, 'message': str(e)})
            finally:
                if temp_output_path and temp_output_path.exists():
                    temp_output_path.unlink()
        
        if cancel_event.is_set():
            summary = f"Cancelled. {success_count} of {processed_count} file(s) processed."
            q.put({'type': 'cancelled', 'summary': summary})
        else:
            summary = f"{success_count} of {total_files} files converted successfully."
            q.put({'type': 'complete', 'summary': summary})

    def _pdf_to_pdfa(self, input_pdf_path: Path, output_pdf_path: Path, version_flag: str, q: queue.Queue):
        args = [ "gs", "-dSAFER", "-dBATCH", "-dNOPAUSE", version_flag, "-sDEVICE=pdfwrite", "-sColorConversionStrategy=UseDeviceIndependentColor", "-dPDFACompatibilityPolicy=1", "-dCompressFonts=false", f"-sOutputFile={output_pdf_path}", str(input_pdf_path) ]
        q.put({'type': 'log', 'message': f"Converting '{input_pdf_path.name}'...\n"})
        ghostscript.Ghostscript(*args)
        q.put({'type': 'log', 'message': f" -> Saved to '{output_pdf_path.name}'\n\n"})
    
    def run_auth_check(self):
        if not check_authentication(AUTH_URL, AUTH_FILE_PATH):
            messagebox.showerror("Authentication Failed", "Please verify the authentication key.", parent=self.root)
            self.root.after(100, self.root.destroy)
            return False
        return True

    def _copy_to_clipboard(self, window: tk.Toplevel, text_to_copy: str):
        window.clipboard_clear()
        window.clipboard_append(text_to_copy)
        print(f"Copied to clipboard: {text_to_copy}")

    def _center_child_window(self, child_window: tk.Toplevel):
        child_window.update_idletasks()
        root_x, root_y = self.root.winfo_x(), self.root.winfo_y()
        root_width, root_height = self.root.winfo_width(), self.root.winfo_height()
        child_width, child_height = child_window.winfo_width(), child_window.winfo_height()
        x = root_x + (root_width - child_width) // 2
        y = root_y + (root_height - child_height) // 2
        child_window.geometry(f"+{x}+{y}")
        
    def show_about(self):
        about_win = tk.Toplevel(self.root)
        about_win.title("About")
        about_win.resizable(False, False)
        about_win.transient(self.root)
        about_win.grab_set()
        frame = tk.Frame(about_win, padx=20, pady=10)
        frame.pack(expand=True, fill="both")
        info = { "Application Name:": "str-pdf", "Version:": "1.2.0", "Company:": "str.ucture GmbH", "Website:": "https://str-ucture.com", "Contact:": "info@str-ucture.com", "Developed by:": "@shailesh-stha" }
        try:
            img = Image.open(COPY_ICON_PATH).resize((16, 16), Image.Resampling.LANCZOS)
            self.copy_icon = ImageTk.PhotoImage(img)
        except FileNotFoundError:
            self.copy_icon = None
        link_font = tkfont.Font(family="Helvetica", size=10, underline=True)
        for i, (key, value) in enumerate(info.items()):
            key_label = tk.Label(frame, text=key, justify="left")
            key_label.grid(row=i, column=0, sticky="ne", pady=2, padx=5)
            if key == "Website:" or key == "Developed by:":
                url = "https://github.com/shailesh-stha" if key == "Developed by:" else value
                value_label = tk.Label(frame, text=value, fg="blue", cursor="hand2", font=link_font)
                value_label.bind("<Button-1>", lambda e, u=url: webbrowser.open_new_tab(u))
                value_label.grid(row=i, column=1, sticky="nw", pady=2, padx=5)
            elif key == "Contact:":
                contact_frame = tk.Frame(frame)
                contact_frame.grid(row=i, column=1, sticky="nw")
                email_label = tk.Label(contact_frame, text=value)
                email_label.pack(side="left", pady=2, padx=5)
                if self.copy_icon:
                    copy_button = tk.Button(contact_frame, image=self.copy_icon, borderwidth=0, cursor="hand2", command=lambda v=value: self._copy_to_clipboard(about_win, v))
                else:
                    copy_button = ttk.Button(contact_frame, text="Copy", width=5, command=lambda v=value: self._copy_to_clipboard(about_win, v))
                copy_button.pack(side="left", padx=(5, 0))
            else:
                value_label = tk.Label(frame, text=value, justify="left")
                value_label.grid(row=i, column=1, sticky="nw", pady=2, padx=5)
        ok_button = ttk.Button(frame, text="OK", command=about_win.destroy)
        ok_button.grid(row=len(info), column=0, columnspan=2, pady=(15, 5))
        self._center_child_window(about_win)
        self.root.wait_window(about_win)

    def show_license(self):
        license_win = tk.Toplevel(self.root)
        license_win.title("License")
        license_win.resizable(False, False)
        license_win.transient(self.root)
        license_win.grab_set()
        frame = tk.Frame(license_win, padx=20, pady=10)
        frame.pack(expand=True, fill="both")
        license_text = ( "This software is licensed under the GNU AGPLv3.\n\n" "This product includes Ghostscript, free software licensed under the GPLv3.\n" "Ghostscript copyright © 1988-2023 Artifex Software, Inc.\n\n" "For more details, please visit:\n" "https://www.gnu.org/licenses/agpl-3.html" )
        text_label = tk.Label(frame, text=license_text, justify="left", wraplength=400)
        text_label.pack(pady=(0, 15))
        ok_button = ttk.Button(frame, text="OK", command=license_win.destroy)
        ok_button.pack()
        self._center_child_window(license_win)
        self.root.wait_window(license_win)


if __name__ == "__main__":
    main_root = TkinterDnD.Tk()
    app = PdfConverterApp(main_root)
    main_root.after(100, app.run_auth_check)
    main_root.mainloop()