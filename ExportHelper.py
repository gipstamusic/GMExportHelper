# -*- coding: utf-8 -*-
import os
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
import tkinter.font as tkFont
import shutil
import zipfile
import threading
from datetime import datetime
import sys
import subprocess
import webbrowser
import logging

# --- Platform Specific Imports ---
try:
    import winsound
except ImportError:
    winsound = None

try:
    import ctypes
except ImportError:
    ctypes = None

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logging.info("Script started")

# --- High DPI Awareness (Windows) ---
try:
    if sys.platform == "win32" and ctypes:
        errorCode = ctypes.windll.shcore.SetProcessDpiAwareness(2)
        if errorCode == 0:
             logging.info("Process DPI Awareness set to Per Monitor Aware.")
        else:
             logging.warning(f"Failed to set DPI Awareness, Error Code: {errorCode}")
except Exception as e:
    logging.warning(f"Could not set DPI awareness: {e}")

# --- Determine Application Base & Resource Directory ---
def get_base_dir():
    if getattr(sys, 'frozen', False):
        application_path = os.path.dirname(sys.executable)
    else:
        application_path = os.path.dirname(os.path.abspath(__file__))
    return application_path

def resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller"""
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except AttributeError:
        # Fall back to the directory of the script, NOT the current working directory
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

APP_BASE_DIR = get_base_dir()
logging.info(f"APP_BASE_DIR (Output/Working): {APP_BASE_DIR}")

# --- Constants ---
CONFIG_FILENAME = "_config.txt"
CONFIG_FILE = os.path.join(APP_BASE_DIR, CONFIG_FILENAME)
ICON_FILENAME = "local.ico"
ICON_PATH = resource_path(ICON_FILENAME)
DUMMY_FOLDER_NAME = "_dummyfiles"

# --- Core Logic Functions ---

def read_config():
    if not os.path.exists(CONFIG_FILE):
        return None
    try:
        with open(CONFIG_FILE, "r", encoding='utf-8') as f:
            content = f.read().strip()
        if content:
            return content
        return None
    except Exception as e:
        logging.error(f"Read config unexpected error '{CONFIG_FILE}': {e}", exc_info=True)
    return None

def write_config(producer):
    try:
        with open(CONFIG_FILE, "w", encoding='utf-8') as f:
            f.write(producer)
        return True
    except Exception as e:
        logging.error(f"Write config unexpected error '{CONFIG_FILE}': {e}", exc_info=True)
    return False

def parse_flp_name(flp_name):
    if not isinstance(flp_name, str) or not flp_name.lower().endswith(".flp"):
        return None, "Not a valid .flp filename."

    base = flp_name[:-4]
    parts = [p.strip() for p in base.split("-")]

    if len(parts) < 4:
        return None, "Filename does not have enough parts. Expected format: TITLE - BPM - KEY - ARTIST.flp"

    try:
        artist = parts[-1].strip()
        key = parts[-2].strip()
        bpm_str = parts[-3].strip()
        title = " - ".join(parts[:-3]).strip()

        if not title: raise ValueError("Title part is missing.")
        if not bpm_str.isdigit(): raise ValueError(f"BPM must be a number, found '{bpm_str}'.")
        if not key: raise ValueError("Key part is missing.")
        if not any(note in key.upper() for note in "CDEFGAB"): raise ValueError(f"Key part ('{key}') doesn't seem to contain a valid note (C-B).")
        if not artist: raise ValueError("Artist part is missing.")

        metadata = {"title": title, "bpm": bpm_str, "key": key, "artist": artist}
        return metadata, None

    except ValueError as e:
        return None, f"Filename Parse Error: {e}. Expected format: TITLE - BPM - KEY - ARTIST.flp"
    except Exception as e:
        return None, f"Unexpected error parsing filename: {e}"

def create_dummy_files(base_folder, metadata, producer):
    dummy_path = os.path.join(base_folder, DUMMY_FOLDER_NAME)
    base_filename = f"{metadata['title']} - {metadata['bpm']} - {metadata['key']}"
    stems_folder_name = f"{base_filename} - Stems"
    stems_folder_path = os.path.join(dummy_path, stems_folder_name)

    try:
        os.makedirs(stems_folder_path, exist_ok=True)
    except OSError as e:
         raise IOError(f"Failed to create directory: {stems_folder_path}") from e

    dummy_files_info = {}
    relative_paths = {
        "mp3_tagged": f"{base_filename} - {metadata['artist']} Type Beat - Prod {producer}.mp3",
        "wav_tagged": f"{base_filename} - Tagged.wav",
        "wav_untagged": f"{base_filename} - Untagged.wav",
        "stem_placeholder": os.path.join(stems_folder_name, f"{base_filename}.wav")
    }

    for key, rel_path in relative_paths.items():
        full_path = os.path.join(dummy_path, rel_path)
        try:
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "wb") as f:
                f.write(b"\x00" * 1024)

            stats = os.stat(full_path)
            dummy_files_info[key] = {
                'rel_path': rel_path, 'full_path': full_path, 'mtime': stats.st_mtime,
                'size': stats.st_size, 'is_stem_placeholder': key == "stem_placeholder"
            }
        except (IOError, OSError) as e:
            raise IOError(f"Failed to create dummy file: {rel_path}") from e

    return dummy_path, stems_folder_path, dummy_files_info

def check_exported_files(dummy_path, original_info, stems_folder_path):
    updates = {}
    missing = []
    not_updated = []
    exported_stems = []

    placeholder_info = original_info.get("stem_placeholder")
    placeholder_full_path = placeholder_info['full_path'] if placeholder_info else None

    for key, orig_data in original_info.items():
        if orig_data.get('is_stem_placeholder', False): continue

        current_path = orig_data['full_path']
        if not os.path.exists(current_path):
            missing.append(orig_data['rel_path'])
            continue

        try:
            current_stat = os.stat(current_path)
            if current_stat.st_mtime > orig_data['mtime'] + 1 or current_stat.st_size != orig_data['size']:
                updates[key] = current_path
            else:
                not_updated.append(orig_data['rel_path'])
        except (OSError, FileNotFoundError):
            not_updated.append(orig_data['rel_path'])

    if os.path.isdir(stems_folder_path):
        try:
            items_in_stems_folder = os.listdir(stems_folder_path)
        except OSError:
            items_in_stems_folder = []

        for item_name in items_in_stems_folder:
            item_path = os.path.join(stems_folder_path, item_name)
            try:
                if os.path.isfile(item_path) and item_name.lower().endswith(".wav"):
                    norm_item_path = os.path.normpath(item_path)
                    norm_placeholder_path = os.path.normpath(placeholder_full_path) if placeholder_full_path else None
                    if norm_item_path != norm_placeholder_path:
                         exported_stems.append(item_path)
            except (OSError, FileNotFoundError):
                pass
    else:
        if placeholder_info:
             missing.append(os.path.basename(stems_folder_path) + "/")

    return updates, missing, not_updated, exported_stems

def zip_stems(stems_to_zip, output_zip_path, progress_bar=None, root_window=None):
    if not stems_to_zip: return 0, None
    num_stems = len(stems_to_zip)
    if progress_bar: 
        progress_bar['maximum'] = num_stems
        progress_bar['value'] = 0

    try:
        with zipfile.ZipFile(output_zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for i, full_path in enumerate(stems_to_zip):
                if not os.path.exists(full_path):
                    continue
                filename = os.path.basename(full_path)
                zf.write(full_path, arcname=filename)
                if progress_bar: 
                    progress_bar['value'] = i + 1
                if root_window: 
                    root_window.update_idletasks()
        return num_stems, output_zip_path
    except Exception as e:
        raise e

def move_final_files(files_to_move_dict, destination_folder):
    moved_filenames = []
    try:
        os.makedirs(destination_folder, exist_ok=True)
    except OSError:
        return []

    for key, source_path in files_to_move_dict.items():
        if not os.path.exists(source_path):
             continue
        filename = os.path.basename(source_path)
        destination_path = os.path.join(destination_folder, filename)
        try:
            shutil.move(source_path, destination_path)
            moved_filenames.append(filename)
        except (IOError, OSError, shutil.Error):
             pass

    return moved_filenames

def cleanup(dummy_path, parent=None):
    if not dummy_path or not os.path.exists(dummy_path):
        return

    try:
        if os.path.isdir(dummy_path):
            shutil.rmtree(dummy_path)
        else:
            os.remove(dummy_path)
    except Exception as e:
        if parent: 
            messagebox.showwarning("Cleanup Error", f"Could not automatically remove:\n{dummy_path}\n\nPlease remove it manually.\nError: {e}", parent=parent)

# --- GUI Class ---
class ExportHelperGUI:

    def __init__(self, master):
        self.master = master
        master.title("GM - Export Helper Tool")
        master.geometry("670x630")
        master.configure(bg="#1E1E1E")
        master.resizable(False, False)
        master.after(50, self._center_window)

        try:
            if os.path.exists(ICON_PATH):
                master.iconbitmap(ICON_PATH)
            else:
                logging.warning(f"Icon file not found at expected resource path: {ICON_PATH}")
        except Exception as e:
            logging.error("An unexpected error occurred while setting icon.", exc_info=True)

        # Styles
        self.style = ttk.Style()
        self.style.theme_use('clam')
        s = self.style
        f_bold = ("Consolas", 10, "bold")
        f_normal = ("Consolas", 10)
        f_log = tkFont.Font(family="Consolas", size=9)
        f_link = ("Consolas", 8, "underline")
        
        s.configure("TButton", padding=6, relief="flat", background="#2D2D30", foreground="#F5F5F5", font=f_bold)
        s.map("TButton", foreground=[('pressed', 'white'), ('active', 'white')], background=[('pressed', '#007ACC'), ('active', '#3B3B3B')])
        s.configure("TLabel", background="#1E1E1E", foreground="#F5F5F5", font=f_normal)
        s.configure("Link.TLabel", foreground="#6495ED", font=f_link)
        s.configure("Custom.Horizontal.TProgressbar", troughcolor='#151515', background='#00FF99', bordercolor="#1E1E1E", lightcolor="#00FF99", darkcolor="#00FF99", thickness=12)

        # --- State Variables ---
        self.producer_name = None
        self.flp_path = None
        self.flp_metadata = None
        self.dummy_path = None
        self.stems_folder_path = None
        self.original_info = None
        self.exported_stems = []
        self.log_font = f_log
        self.last_output_folder = None

        # --- Widget layout ---
        cf = tk.Frame(master, bg="#1E1E1E")
        cf.pack(pady=(10, 5), fill='x', padx=10)
        
        self.p_label = ttk.Label(cf, text="Producer Name: - Not Set -", wraplength=450)
        self.p_label.pack(side=tk.LEFT, padx=(0, 10), fill='x', expand=True)
        
        self.btn_upd_p = ttk.Button(cf, text="⚙️ Change", command=self.update_producer, width=10)
        self.btn_upd_p.pack(side=tk.RIGHT, padx=0)

        ttk.Label(master, text="Overall Progress:").pack(pady=(5, 0), padx=10, anchor='w')
        self.p_overall = ttk.Progressbar(master, orient='horizontal', length=600, mode='determinate', maximum=3, style="Custom.Horizontal.TProgressbar")
        self.p_overall.pack(pady=(0, 10), padx=10, fill='x')

        # Custom Log Area with Scrollbar
        log_frame = tk.Frame(master, bg='#151515')
        log_frame.pack(pady=5, padx=10, fill="both", expand=True)
        
        self.scrollbar = ttk.Scrollbar(log_frame)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        ts_prefix = "[HH:MM:SS] "
        prefix_width = self.log_font.measure(ts_prefix)
        indent_pixels = prefix_width + 5
        
        self.log = tk.Text(log_frame, height=14, width=80, state='disabled', wrap=tk.WORD, bg='#151515', fg='#00FF99', font=self.log_font, relief="solid", bd=0, padx=5, pady=5, yscrollcommand=self.scrollbar.set)
        self.log.tag_configure("timestamp", foreground="#AAAAAA")
        self.log.tag_configure("indent", lmargin1=indent_pixels, lmargin2=indent_pixels)
        self.scrollbar.config(command=self.log.yview)
        self.log.pack(side=tk.LEFT, fill="both", expand=True)

        af = tk.Frame(master, bg="#1E1E1E")
        af.pack(pady=(10, 5), fill='x', padx=10)
        
        bf = tk.Frame(af, bg="#1E1E1E")
        bf.pack(fill='x')

        self.btn_sel = ttk.Button(bf, text="1. Select FLP", command=self.select_flp, state=tk.DISABLED)
        self.btn_sel.pack(side=tk.LEFT, padx=(0, 5), expand=True, fill='x')
        
        self.btn_conf = ttk.Button(bf, text="2. Confirm Exports", command=self.check_exports, state=tk.DISABLED)
        self.btn_conf.pack(side=tk.LEFT, padx=5, expand=True, fill='x')
        
        self.btn_zip = ttk.Button(bf, text="3. Zip & Finalize", command=self.zip_and_finalize, state=tk.DISABLED)
        self.btn_zip.pack(side=tk.LEFT, padx=(5, 0), expand=True, fill='x')
        
        self.btn_open = ttk.Button(bf, text="📂 Open Folder", command=self.open_project_folder, state=tk.DISABLED, width=14)
        self.btn_open.pack(side=tk.RIGHT, padx=(5, 0))

        # We keep this packed always, just hide the text and reset to 0 to prevent UI jumping
        self.zip_p_label_var = tk.StringVar()
        self.zip_p_label_var.set("")
        self.zip_p_label = ttk.Label(af, textvariable=self.zip_p_label_var)
        self.zip_p_label.pack(pady=(5, 0), padx=10, anchor='w')
        
        self.p_zip = ttk.Progressbar(af, orient='horizontal', length=600, mode='determinate', style="Custom.Horizontal.TProgressbar")
        self.p_zip.pack(pady=(0, 10), padx=10, fill='x')

        self.footer_link = "https://lnk.bio/gipstamusic"
        foot = ttk.Label(master, text="Made by Gipstamusic ♥", style="Link.TLabel", cursor="hand2")
        foot.pack(side='bottom', pady=(5, 10))
        foot.bind("<Button-1>", self.open_link)

        self._log("Welcome to GM - Export Helper!")
        master.after(100, self.initialize_app)

    def _center_window(self):
        try:
            self.master.update_idletasks()
            w = self.master.winfo_width()
            h = self.master.winfo_height()
            sw = self.master.winfo_screenwidth()
            sh = self.master.winfo_screenheight()
            x = (sw // 2) - (w // 2)
            y = (sh // 2) - (h // 2)
            self.master.geometry(f'{w}x{h}+{x}+{y}')
        except Exception as e:
            pass

    def _log(self, message):
        now_str = datetime.now().strftime("%H:%M:%S")
        timestamp_prefix = f"[{now_str}] "
        log_entry = f"{message}\n"
        try:
            self.log.configure(state='normal')
            self.log.insert('end', timestamp_prefix, "timestamp")
            self.log.insert('end', log_entry, "indent")
            self.log.configure(state='disabled')
            self.log.see('end')
            self.master.update_idletasks()
        except Exception as e:
            logging.error(f"ERROR logging to GUI: {e}")

    def update_producer(self):
        self._log("⚙️ Requesting Producer Name update...")
        current_name = self.producer_name or ""
        m = self.master
        m.lift()
        m.attributes('-topmost', True)
        new_name = simpledialog.askstring("Update Producer Name", "Enter your Producer Name:", initialvalue=current_name, parent=m)
        m.attributes('-topmost', False)

        if new_name is None:
            self._log("❌ Producer name update cancelled.")
            if not self.producer_name: 
                self.btn_sel.config(state=tk.DISABLED)
            return

        new_name = new_name.strip()

        if new_name == current_name:
            self._log("ℹ️ Producer name unchanged.")
            self.btn_sel.config(state=tk.NORMAL if self.producer_name else tk.DISABLED)
            return

        if not new_name:
            self._log("⚠️ Producer name cleared. It's required to proceed.")
            messagebox.showwarning("Name Required", "Producer name cannot be empty.", parent=m)
            self.producer_name = None
            self.p_label.config(text="Producer Name: - Not Set -")
            write_config("")
            self.btn_sel.config(state=tk.DISABLED)
            return

        if write_config(new_name):
            self.producer_name = new_name
            self._log(f"💾 Producer name updated and saved: '{new_name}'")
            self.p_label.config(text=f"Producer Name: {new_name}")
            self.btn_sel.config(state=tk.NORMAL)
            self._log("✅ Ready to select FLP.")
        else:
            self._log("❌ Failed to save producer name to config file.")
            messagebox.showerror("Save Error", f"Could not save producer name to:\n{CONFIG_FILE}\n\nPlease check file permissions.", parent=m)
            if not self.producer_name: 
                self.btn_sel.config(state=tk.DISABLED)

    def open_link(self, event=None):
        try:
            webbrowser.open_new(self.footer_link)
            self._log(f"🌍 Opening link: {self.footer_link}")
        except Exception as ex:
            self._log(f"❌ Failed to open link: {ex}")

    def open_project_folder(self):
        folder_to_open = None
        if self.last_output_folder and os.path.isdir(self.last_output_folder):
             folder_to_open = self.last_output_folder
             self._log(f"📂 Opening last output folder: {folder_to_open}")
        elif self.flp_path and os.path.isdir(os.path.dirname(self.flp_path)):
             folder_to_open = os.path.dirname(self.flp_path)
             self._log(f"📂 Opening current FLP folder: {folder_to_open}")
        else:
             self._log("❌ Cannot open folder: No project context available.")
             messagebox.showwarning("Open Folder", "No project folder context available (select an FLP or complete a run first).", parent=self.master)
             return

        try:
            platform = sys.platform
            norm_path = os.path.normpath(folder_to_open)
            if platform == "win32": 
                subprocess.Popen(['explorer', norm_path])
            elif platform == "darwin": 
                subprocess.Popen(["open", norm_path])
            else: 
                subprocess.Popen(["xdg-open", norm_path])
        except Exception as e:
            self._log(f"❌ Failed to open folder: {e}")
            messagebox.showerror("Error", f"Could not open the folder using the default file manager:\n{e}", parent=self.master)

    def initialize_app(self):
        self._log("⏳ Initializing application...")
        self.reset_state(clear_last_folder=True)

        try:
            self.producer_name = read_config()
            if not self.producer_name:
                self._log("👤 Producer name not found in config. Please set it using '⚙️ Change'.")
                self.p_label.config(text="Producer Name: - Not Set -")
                self.btn_sel.config(state=tk.DISABLED)
            else:
                self._log(f"👍 Producer loaded from config: '{self.producer_name}'")
                self.p_label.config(text=f"Producer Name: {self.producer_name}")
                self._log("✅ Initialization complete. Ready to select FLP.")
                self.btn_sel.config(state=tk.NORMAL)

        except Exception as e:
             self._log(f"❌ CRITICAL INIT FAILED: {e}")
             messagebox.showerror("Initialization Error", f"A critical error occurred during initialization:\n{e}\n\nPlease check '{CONFIG_FILENAME}'.", parent=self.master)
             self.btn_sel.config(state=tk.DISABLED)
             self.btn_upd_p.config(state=tk.DISABLED)

    def select_flp(self):
        if not self.producer_name:
             messagebox.showerror("Missing Info", "Please set your Producer Name first using '⚙️ Change'.", parent=self.master)
             return

        m = self.master
        m.lift()
        m.attributes('-topmost', True)
        selected_path = filedialog.askopenfilename(
            title="Select FL Studio Project File", 
            filetypes=[("FL Studio Project", "*.flp")],
            initialdir=self.last_output_folder or (os.path.dirname(self.flp_path) if self.flp_path else None),
            parent=m 
        )
        m.attributes('-topmost', False)

        if not selected_path: 
            self._log("⚠️ FLP selection cancelled.")
            return

        self.reset_state(keep_producer=True)
        self.flp_path = selected_path
        filename = os.path.basename(selected_path)
        self._log(f"📄 FLP selected: {filename}")
        self._log(f"🧐 Validating filename format...")

        metadata, error_msg = parse_flp_name(filename)
        if error_msg:
            self._log(f"❌ Invalid FLP Filename: {error_msg}")
            messagebox.showerror("Invalid Filename", f"Invalid FLP filename:\n'{filename}'\n\nError: {error_msg}\nPlease rename and try again.", parent=m)
            self.flp_path = None
            self.reset_state(keep_producer=True)
            self.btn_sel.config(state=tk.NORMAL)
            return

        self.flp_metadata = metadata
        self._log(f"✔️ Filename OK: Title='{metadata['title']}', BPM='{metadata['bpm']}', Key='{metadata['key']}', Artist='{metadata['artist']}'")
        self.btn_open.config(state=tk.NORMAL)
        self.create_and_prepare_dummies()

    def create_and_prepare_dummies(self):
        if not (self.flp_path and self.flp_metadata and self.producer_name):
            self._log("❌ Cannot create dummies: Missing required info. Internal error.")
            messagebox.showerror("Internal Error", "Cannot create dummies due to missing internal state.", parent=self.master)
            self.reset_state(keep_producer=True)
            return

        self._log("🛠️ Creating dummy file structure...")
        flp_directory = os.path.dirname(self.flp_path)

        try:
            dummy_base_path, stems_folder_full_path, original_files_info = create_dummy_files(
                flp_directory, self.flp_metadata, self.producer_name )

            self.dummy_path = dummy_base_path
            self.stems_folder_path = stems_folder_full_path
            self.original_info = original_files_info

            self._log(f"✅ Dummy structure created successfully in: '{os.path.basename(self.dummy_path)}'")
            stems_subfolder_name = os.path.basename(self.stems_folder_path)
            self._log("👉 ACTION REQUIRED: Export your files from FL Studio now.")
            self._log(f"   - Export main MP3/WAVs into: '{os.path.basename(self.dummy_path)}'")
            self._log(f"   - Export STEMS (WAV) into subfolder: '{stems_subfolder_name}'")
            self._log("   - IMPORTANT: OVERWRITE the dummy files.")
            self._log("🔴 Click '2. Confirm Exports' when finished exporting.")

            self.btn_sel.config(state=tk.DISABLED)
            self.btn_conf.config(state=tk.NORMAL)
            self.btn_zip.config(state=tk.DISABLED)
            self.p_overall['value'] = 1

        except Exception as e:
             self._log(f"❌ Unexpected error during dummy creation: {e}")
             messagebox.showerror("Unexpected Error", f"An unexpected error occurred:\n{e}", parent=self.master)
             self.reset_state(keep_producer=True)

    def check_exports(self):
        if not (self.dummy_path and self.original_info and self.stems_folder_path):
            self._log("❌ Cannot check exports: Internal state error.")
            messagebox.showerror("Internal Error", "Cannot check exports due to missing internal state.", parent=self.master)
            self.reset_state(keep_producer=True)
            self.btn_sel.config(state=tk.NORMAL if self.producer_name else tk.DISABLED)
            return

        self._log("🔍 Checking exported files for updates...")
        try:
            updated_files, missing_files, not_updated_files, found_stems = check_exported_files(
                self.dummy_path, self.original_info, self.stems_folder_path )
            self.exported_stems = found_stems
            proceed_to_zip = True

            if missing_files:
                msg = "Missing expected files/folders:\n- " + "\n- ".join(missing_files)
                self._log(f"⚠️ WARNING: {msg}")
                if not messagebox.askyesno("Missing Files Found", msg + "\n\nIncomplete export?\nContinue anyway?", default=messagebox.NO, parent=self.master):
                     self._log("✋ User chose not to proceed (missing files).")
                     proceed_to_zip = False
                else: 
                     self._log("🤔 User chose to proceed despite missing files.")

            if not_updated_files and proceed_to_zip:
                msg = "Unchanged files (were they exported/overwritten?):\n- " + "\n- ".join(not_updated_files)
                self._log(f"⚠️ WARNING: {msg}")
                if not messagebox.askyesno("Unchanged Files Found", msg + "\n\nContinue anyway?", default=messagebox.NO, parent=self.master):
                    self._log("✋ User chose not to proceed (unchanged files).")
                    proceed_to_zip = False
                else: 
                    self._log("🤔 User chose to proceed despite unchanged files.")

            if proceed_to_zip:
                if not updated_files and not self.exported_stems:
                    self._log("❌ No updated main files or exported stems found.")
                    messagebox.showwarning("No Changes Detected", "No updated main files or actual stems found.\nPlease ensure you exported and overwrote correctly.", parent=self.master)
                    self.btn_conf.config(state=tk.NORMAL)
                else:
                    self._log(f"✔️ Checks complete.")
                    log_msg = []
                    if updated_files: log_msg.append(f"{len(updated_files)} updated main file(s)")
                    if self.exported_stems: log_msg.append(f"{len(self.exported_stems)} actual stem(s) found")
                    else: log_msg.append("No actual stem files found")
                    
                    if log_msg: self._log(f"   - Found: {', '.join(log_msg)}.")

                    self._log("✅ Ready to Zip & Finalize.")
                    self.btn_conf.config(state=tk.DISABLED)
                    self.btn_zip.config(state=tk.NORMAL)
                    self.p_overall['value'] = 2
            else:
                self._log("🚦 Confirmation check aborted by user.")
                self.btn_conf.config(state=tk.NORMAL)
                self.btn_zip.config(state=tk.DISABLED)
                self.p_overall['value'] = 1

        except Exception as e:
             self._log(f"❌ UNEXPECTED ERROR checking exports: {e}")
             messagebox.showerror("Unexpected Check Error", f"Unexpected error during file checking:\n{e}", parent=self.master)
             self.btn_conf.config(state=tk.NORMAL)

    def zip_and_finalize(self):
        if not (self.flp_path and self.flp_metadata and self.dummy_path and self.original_info and self.stems_folder_path):
            self._log("❌ Cannot finalize: Internal state error.")
            messagebox.showerror("Internal Error", "Cannot finalize due to missing internal state. Please restart.", parent=self.master)
            self.reset_state(keep_producer=True)
            self.btn_sel.config(state=tk.NORMAL if self.producer_name else tk.DISABLED)
            return

        flp_dir = os.path.dirname(self.flp_path)
        zip_base_filename = f"{self.flp_metadata['title']} - {self.flp_metadata['bpm']} - {self.flp_metadata['key']} - Stems.zip"
        zip_full_path = os.path.join(self.dummy_path, zip_base_filename)
        final_zip_dest_path = os.path.join(flp_dir, zip_base_filename)

        stem_count = 0
        moved_files_list = []
        created_zip_temp_path = None

        if self.exported_stems:
            self.zip_p_label_var.set("Zipping Stems Progress:")
            self.master.update_idletasks()

        try:
            if self.exported_stems:
                self._log(f"📦 Zipping {len(self.exported_stems)} stems (to temp location)...")
                stem_count, created_zip_temp_path = zip_stems(self.exported_stems, zip_full_path, self.p_zip, self.master)
                if created_zip_temp_path: 
                    self._log(f"✔️ Stems zipped temporarily.")
                else: 
                    raise zipfile.BadZipFile("Zip creation failed silently.")
            else: 
                self._log("ℹ️ No stems found to zip.")

            updated_main_files_dict, _, _, _ = check_exported_files( self.dummy_path, self.original_info, self.stems_folder_path )
            files_to_move_final = { k: v for k, v in updated_main_files_dict.items() if not self.original_info.get(k, {}).get('is_stem_placeholder', False) }

            self._log(f"🚚 Moving final files to: {flp_dir}...")
            os.makedirs(flp_dir, exist_ok=True)

            if files_to_move_final:
                 moved_main = move_final_files(files_to_move_final, flp_dir)
                 moved_files_list.extend(moved_main)
                 if moved_main: 
                     self._log(f"✔️ Moved {len(moved_main)} main export(s).")
                 else: 
                     self._log(f"⚠️ No main files moved (check warnings).")
            else: 
                self._log("ℹ️ No updated main files to move.")

            if created_zip_temp_path and os.path.exists(created_zip_temp_path):
                try:
                    shutil.move(created_zip_temp_path, final_zip_dest_path)
                    moved_files_list.append(os.path.basename(final_zip_dest_path))
                    self._log(f"✔️ Moved Stems Zip file.")
                except Exception as e:
                    self._log(f"❌ FAILED TO MOVE ZIP FILE: {e}. Zip may remain in '{DUMMY_FOLDER_NAME}'.")
                    messagebox.showerror("Zip Move Error", f"Failed to move Stems Zip:\n{e}\nPlease move it manually from '{os.path.basename(self.dummy_path)}' (if cleanup fails).", parent=self.master)

            self._log("🧹 Cleaning up temporary folder...")
            cleanup(self.dummy_path, parent=self.master)

            self._log("🎉 Finalization process completed!")
            self._log(f"   Check results in: {flp_dir}")
            if moved_files_list: self._log(f"   Final files: {', '.join(moved_files_list)}")

            self.last_output_folder = flp_dir

            try:
                if winsound: winsound.MessageBeep(winsound.MB_OK)
                else: print('\a', end='', flush=True)
            except Exception as sound_e: 
                pass

            self.reset_state(keep_producer=True, clear_last_folder=False)
            self._log("🔄 Ready for the next FLP file.")
            self.btn_sel.config(state=tk.NORMAL)
            self.btn_open.config(state=tk.NORMAL)
            self.p_overall['value'] = 3

        except Exception as e:
            self._log(f"❌ UNEXPECTED CRITICAL ERROR during Finalization: {e}")
            messagebox.showerror("Unexpected Finalization Error", f"Unexpected critical error:\n{e}\nProcess halted.", parent=self.master)
            self.reset_after_error()
        finally:
             # Reset zip progress visually without unpacking to avoid UI jumps
             self.zip_p_label_var.set("")
             if self.p_zip: 
                 self.p_zip['value'] = 0
             self.master.update_idletasks()

    def reset_state(self, keep_path=False, keep_producer=False, clear_last_folder=False):
        log_reset = False
        if hasattr(self, 'p_overall'):
            if self.flp_path or self.dummy_path or self.p_overall['value'] > 0:
                log_reset = True
        if log_reset: self._log("🔄 Resetting state...")

        if self.dummy_path and os.path.exists(self.dummy_path):
            self._log(f"   Attempting cleanup of previous dummy folder: {self.dummy_path}")
            cleanup(self.dummy_path, parent=self.master)

        if not keep_path:
            self.flp_path = None
            self.flp_metadata = None

        if clear_last_folder:
            self.last_output_folder = None
            if hasattr(self, 'btn_open'): self.btn_open.config(state=tk.DISABLED)
        elif hasattr(self, 'btn_open') and self.last_output_folder:
             if hasattr(self, 'btn_open'): self.btn_open.config(state=tk.NORMAL)

        self.dummy_path = None
        self.stems_folder_path = None
        self.original_info = None
        self.exported_stems = []

        if not keep_producer:
             self.producer_name = None
             if hasattr(self, 'p_label'): self.p_label.config(text="Producer Name: - Not Set -")
             if hasattr(self, 'btn_sel'): self.btn_sel.config(state=tk.DISABLED)
        else:
             if hasattr(self, 'btn_sel'): self.btn_sel.config(state=tk.NORMAL if self.producer_name else tk.DISABLED)

        if hasattr(self, 'btn_conf'): self.btn_conf.config(state=tk.DISABLED)
        if hasattr(self, 'btn_zip'): self.btn_zip.config(state=tk.DISABLED)
        if hasattr(self, 'p_overall'): self.p_overall['value'] = 0
        if hasattr(self, 'p_zip'): self.p_zip['value'] = 0
        if hasattr(self, 'zip_p_label_var'): self.zip_p_label_var.set("")

    def reset_after_error(self):
        self._log("⚠️ Resetting state after error during finalization.")
        
        self.original_info = None
        self.exported_stems = []
        self.btn_zip.config(state=tk.DISABLED)

        if self.dummy_path and os.path.isdir(self.dummy_path):
             self.btn_conf.config(state=tk.NORMAL)
             self._log("   Dummy folder may still exist. 'Confirm Exports' re-enabled.")
        else:
             self.btn_conf.config(state=tk.DISABLED)
             self.btn_sel.config(state=tk.NORMAL if self.producer_name else tk.DISABLED)
             self._log("   Dummy folder seems cleaned up. Please select FLP again.")

        self.btn_open.config(state=tk.NORMAL if self.last_output_folder or self.flp_path else tk.DISABLED)

        self.p_overall['value'] = 1
        self.p_zip['value'] = 0
        self.zip_p_label_var.set("")

# --- Run ---
if __name__ == "__main__":
    root = tk.Tk()
    app = ExportHelperGUI(root)
    root.mainloop()