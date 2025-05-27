import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
import subprocess
import threading
import queue
import os

class XCheckApp:
    def __init__(self, root):
        self.root = root
        self.root.title("File System Checker (via WSL)")
        self.root.geometry("1000x700")
        self.root.minsize(800, 600)

        self.style = ttk.Style()
        self.style.theme_use('clam')

        self.bg_color = '#f5f5f5'
        self.primary_color = '#4a6fa5'
        self.success_color = '#4caf50'   # Green for success
        self.error_color = '#f44336'     # Red for errors/fail
        self.warning_color = '#ff9800'
        self.text_color = '#333333'

        self.style.configure('.', background=self.bg_color, foreground=self.text_color)
        self.style.configure('TButton', font=('Segoe UI', 10), padding=6)
        self.style.configure('Primary.TButton', foreground='white', background=self.primary_color)
        self.style.configure('Success.TButton', foreground='white', background=self.success_color)
        self.style.configure('Danger.TButton', foreground='white', background=self.error_color)

        self.output_queue = queue.Queue()
        self.running_process = None

        self.build_ui()
        self.check_queue()

    def build_ui(self):
        main_frame = ttk.Frame(self.root)
        main_frame.pack(expand=True, fill=tk.BOTH, padx=10, pady=10)

        # Header
        header = ttk.Label(main_frame, text=" File System Checker", font=('Segoe UI', 16, 'bold'),
                           foreground=self.primary_color)
        header.pack(pady=(0, 10), anchor='w')

        # File Selection
        file_frame = ttk.Frame(main_frame)
        file_frame.pack(fill=tk.X)

        self.file_entry = ttk.Entry(file_frame)
        self.file_entry.pack(side=tk.LEFT, expand=True, fill=tk.X)

        ttk.Button(file_frame, text="Browse...", command=self.browse_file, style="Primary.TButton").pack(side=tk.LEFT, padx=5)

        # Options
        options_frame = ttk.Frame(main_frame)
        options_frame.pack(fill=tk.X, pady=5)

        self.verbose_var = tk.BooleanVar()
        ttk.Checkbutton(options_frame, text="Verbose output", variable=self.verbose_var).pack(side=tk.LEFT, padx=5)

        self.repair_var = tk.BooleanVar()
        ttk.Checkbutton(options_frame, text="Attempt repairs", variable=self.repair_var).pack(side=tk.LEFT, padx=5)

        # Action Buttons
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=10)

        self.run_btn = ttk.Button(btn_frame, text="Run Verification", command=self.run_verification, style="Success.TButton")
        self.run_btn.pack(side=tk.LEFT, padx=5)

        self.stop_btn = ttk.Button(btn_frame, text="Stop", command=self.stop_verification, style="Danger.TButton", state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        self.clear_btn = ttk.Button(btn_frame, text="Clear Output", command=self.clear_output, style="Primary.TButton")
        self.clear_btn.pack(side=tk.LEFT, padx=5)

        self.save_btn = ttk.Button(btn_frame, text="Save Output...", command=self.save_output, style="Primary.TButton")
        self.save_btn.pack(side=tk.LEFT, padx=5)

        # Tabs
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(expand=True, fill=tk.BOTH)

        # Output tab
        self.output_text = ScrolledText(self.notebook, wrap=tk.WORD, font=("Consolas", 10))
        # Configure tags for coloring
        self.output_text.tag_config("error", foreground=self.error_color, font=("Consolas", 10, "bold"))
        self.output_text.tag_config("success", foreground=self.success_color, font=("Consolas", 10, "bold"))
        self.output_text.tag_config("fail", foreground=self.error_color, font=("Consolas", 10, "bold"))
        self.output_text.tag_config("warning", foreground=self.warning_color)
        self.notebook.add(self.output_text, text="Verification Output")

        # Stats tab
        self.stats_text = ScrolledText(self.notebook, wrap=tk.WORD, font=("Segoe UI", 10), state=tk.DISABLED)
        self.notebook.add(self.stats_text, text="Statistics")

        # Status
        self.status_label = ttk.Label(main_frame, text="Ready", font=('Segoe UI', 9), anchor='w')
        self.status_label.pack(fill=tk.X, pady=5)

    def browse_file(self):
        path = filedialog.askopenfilename(filetypes=[("Image files", "*.img *.IMG")])
        if path:
            self.file_entry.delete(0, tk.END)
            self.file_entry.insert(0, path)

    def run_verification(self):
        file_path = self.file_entry.get().strip()
        if not file_path or not os.path.isfile(file_path):
            messagebox.showerror("Error", "Please select a valid image file.")
            return

        self.clear_output()
        self.status_label.config(text=f"Verifying {os.path.basename(file_path)}...")
        self.run_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)

        thread = threading.Thread(target=self.verification_thread, args=(file_path,), daemon=True)
        thread.start()

    def verification_thread(self, filepath):
        try:
            # Convert Windows path to WSL path
            wsl_path = subprocess.check_output(['wsl', 'wslpath', filepath]).decode().strip()
            cmd = ['wsl', './xcheck', wsl_path]
            if self.verbose_var.get():
                cmd.append('-v')
            if self.repair_var.get():
                cmd.append('-r')

            self.running_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            # Read stdout asynchronously
            for line in self.running_process.stdout:
                self.output_queue.put(('output', line))
            # Read stderr asynchronously
            for line in self.running_process.stderr:
                self.output_queue.put(('error', line))

            self.running_process.wait()
            self.output_queue.put(('done', None))

        except Exception as e:
            self.output_queue.put(('error', f"[ERROR] {str(e)}\n"))
            self.output_queue.put(('done', None))

    def stop_verification(self):
        if self.running_process and self.running_process.poll() is None:
            self.running_process.terminate()
            self.output_queue.put(('output', "[INFO] Process terminated by user.\n"))
            self.output_queue.put(('done', None))

    def clear_output(self):
        self.output_text.delete('1.0', tk.END)
        self.stats_text.config(state=tk.NORMAL)
        self.stats_text.delete('1.0', tk.END)
        self.stats_text.config(state=tk.DISABLED)

    def save_output(self):
        output = self.output_text.get("1.0", tk.END).strip()
        if not output:
            messagebox.showinfo("No Output", "Nothing to save.")
            return
        file = filedialog.asksaveasfilename(defaultextension=".txt",
                                            filetypes=[("Text Files", "*.txt")])
        if file:
            with open(file, "w") as f:
                f.write(output)
            messagebox.showinfo("Saved", f"Output saved to {file}")

    def check_queue(self):
        try:
            while True:
                tag, message = self.output_queue.get_nowait()

                if tag in ('output', 'error'):
                    line = message.strip()
                    # Color lines containing [PASS] green
                    if '[PASS]' in line:
                        self.append_output(message, tag='success')
                    # Color lines containing [FAIL] red
                    elif '[FAIL]' in line:
                        self.append_output(message, tag='fail')
                    # Errors in red as well
                    elif tag == 'error':
                        self.append_output(message, tag='error')
                    else:
                        self.append_output(message)
                elif tag == 'done':
                    self.update_status("Verification complete.")
                    self.run_btn.config(state=tk.NORMAL)
                    self.stop_btn.config(state=tk.DISABLED)
                    self.generate_statistics()
        except queue.Empty:
            pass
        self.root.after(100, self.check_queue)

    def append_output(self, text, tag=None):
        self.output_text.insert(tk.END, text, tag)
        self.output_text.see(tk.END)

    def update_status(self, text):
        self.status_label.config(text=text)

    def generate_statistics(self):
        output = self.output_text.get("1.0", tk.END)
        fail_count = output.count("[FAIL]")
        pass_count = output.count("[PASS]")
        total_checks = fail_count + pass_count

        stats = f"Total Checks: {total_checks}\n[PASS]: {pass_count}\n[FAIL]: {fail_count}"

        self.stats_text.config(state=tk.NORMAL)
        self.stats_text.delete('1.0', tk.END)
        self.stats_text.insert(tk.END, stats)
        self.stats_text.config(state=tk.DISABLED)

if __name__ == "__main__":
    root = tk.Tk()
    app = XCheckApp(root)
    root.mainloop()
