from __future__ import annotations

import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from whatsapp_db_sender import (
    DEFAULT_DB_PATH,
    DEFAULT_PROFILE_DIR,
    connect_database,
    ensure_schema,
    insert_messages_from_lines,
    insert_outbound_message,
    list_outbound_messages,
)

APP_TITLE = "WhatsApp Sender Manual + DB"
HELP_TEXT = (
    "Captura manualmente número y mensaje, insértalos en la base y luego ejecuta el envío.\n"
    "También puedes pegar un lote usando el formato numero|mensaje, una fila por línea."
)


class WhatsAppSenderApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1080x760")
        self.root.minsize(980, 700)

        self.db_path_var = tk.StringVar(value=str(DEFAULT_DB_PATH))
        self.profile_dir_var = tk.StringVar(value=str(DEFAULT_PROFILE_DIR))
        self.phone_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Listo para capturar datos manualmente.")

        self._build_layout()
        self.refresh_queue()

    def _build_layout(self) -> None:
        wrapper = ttk.Frame(self.root, padding=16)
        wrapper.pack(fill="both", expand=True)

        ttk.Label(wrapper, text=APP_TITLE, font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(wrapper, text=HELP_TEXT, justify="left").pack(anchor="w", pady=(4, 16))

        config_frame = ttk.LabelFrame(wrapper, text="Configuración")
        config_frame.pack(fill="x", pady=(0, 12))
        config_frame.columnconfigure(1, weight=1)
        config_frame.columnconfigure(3, weight=1)

        ttk.Label(config_frame, text="Base de datos").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        ttk.Entry(config_frame, textvariable=self.db_path_var).grid(
            row=0, column=1, sticky="ew", padx=8, pady=8
        )
        ttk.Button(config_frame, text="Buscar", command=self.pick_db_path).grid(
            row=0, column=2, padx=8, pady=8
        )

        ttk.Label(config_frame, text="Perfil Chrome").grid(row=1, column=0, sticky="w", padx=8, pady=8)
        ttk.Entry(config_frame, textvariable=self.profile_dir_var).grid(
            row=1, column=1, sticky="ew", padx=8, pady=8
        )
        ttk.Button(config_frame, text="Buscar", command=self.pick_profile_dir).grid(
            row=1, column=2, padx=8, pady=8
        )

        single_frame = ttk.LabelFrame(wrapper, text="Captura manual")
        single_frame.pack(fill="x", pady=(0, 12))
        single_frame.columnconfigure(1, weight=1)

        ttk.Label(single_frame, text="Número").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        ttk.Entry(single_frame, textvariable=self.phone_var).grid(
            row=0, column=1, sticky="ew", padx=8, pady=8
        )

        ttk.Label(single_frame, text="Mensaje").grid(row=1, column=0, sticky="nw", padx=8, pady=8)
        self.message_text = tk.Text(single_frame, wrap="word", height=6, font=("Segoe UI", 11))
        self.message_text.grid(row=1, column=1, sticky="ew", padx=8, pady=8)

        single_actions = ttk.Frame(single_frame)
        single_actions.grid(row=2, column=0, columnspan=2, sticky="ew", padx=8, pady=(0, 8))
        ttk.Button(single_actions, text="Insertar en cola", command=self.insert_single).pack(side="left")
        ttk.Button(single_actions, text="Insertar y ejecutar", command=self.insert_and_run).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(single_actions, text="Limpiar captura", command=self.clear_single).pack(
            side="left", padx=(8, 0)
        )

        bulk_frame = ttk.LabelFrame(wrapper, text="Carga manual por lote")
        bulk_frame.pack(fill="both", expand=True, pady=(0, 12))

        bulk_help = ttk.Label(
            bulk_frame,
            text="Formato: numero|mensaje. Ejemplo: 5215512345678|Hola desde la captura manual.",
            justify="left",
        )
        bulk_help.pack(anchor="w", padx=8, pady=(8, 0))

        self.bulk_text = tk.Text(bulk_frame, wrap="word", height=10, font=("Consolas", 10))
        self.bulk_text.pack(fill="both", expand=True, padx=8, pady=8)

        bulk_actions = ttk.Frame(bulk_frame)
        bulk_actions.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(bulk_actions, text="Cargar archivo", command=self.load_bulk_file).pack(side="left")
        ttk.Button(bulk_actions, text="Insertar lote", command=self.insert_bulk).pack(side="left", padx=(8, 0))
        ttk.Button(bulk_actions, text="Insertar lote y ejecutar", command=self.insert_bulk_and_run).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(bulk_actions, text="Limpiar lote", command=self.clear_bulk).pack(side="left", padx=(8, 0))

        queue_frame = ttk.LabelFrame(wrapper, text="Últimos registros en la base")
        queue_frame.pack(fill="both", expand=True)

        columns = ("id", "phone", "status", "message")
        self.queue_tree = ttk.Treeview(queue_frame, columns=columns, show="headings", height=10)
        self.queue_tree.heading("id", text="ID")
        self.queue_tree.heading("phone", text="Número")
        self.queue_tree.heading("status", text="Estado")
        self.queue_tree.heading("message", text="Mensaje")
        self.queue_tree.column("id", width=70, anchor="center")
        self.queue_tree.column("phone", width=180)
        self.queue_tree.column("status", width=110, anchor="center")
        self.queue_tree.column("message", width=620)
        self.queue_tree.pack(fill="both", expand=True, padx=8, pady=8)

        queue_actions = ttk.Frame(queue_frame)
        queue_actions.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(queue_actions, text="Refrescar cola", command=self.refresh_queue).pack(side="left")
        ttk.Button(queue_actions, text="Ejecutar envío pendiente", command=self.run_sender).pack(
            side="right"
        )

        ttk.Label(wrapper, textvariable=self.status_var, foreground="#1d4ed8").pack(
            anchor="w", pady=(12, 0)
        )

    def pick_db_path(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Selecciona o crea la base SQLite",
            defaultextension=".db",
            filetypes=[("SQLite", "*.db"), ("Todos los archivos", "*.*")],
        )
        if path:
            self.db_path_var.set(path)
            self.refresh_queue()

    def pick_profile_dir(self) -> None:
        path = filedialog.askdirectory(title="Selecciona la carpeta del perfil de Chrome")
        if path:
            self.profile_dir_var.set(path)

    def load_bulk_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Selecciona archivo de carga manual",
            filetypes=[("Texto", "*.txt"), ("CSV", "*.csv"), ("Todos los archivos", "*.*")],
        )
        if not path:
            return

        try:
            content = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("Error", f"No se pudo leer el archivo.\n\n{exc}")
            return

        self.bulk_text.delete("1.0", tk.END)
        self.bulk_text.insert("1.0", content)
        self.status_var.set(f"Archivo cargado: {Path(path).name}")

    def database_connection(self):
        db_path = Path(self.db_path_var.get().strip() or DEFAULT_DB_PATH)
        connection = connect_database(db_path)
        ensure_schema(connection)
        return connection, db_path

    def insert_single(self) -> None:
        phone = self.phone_var.get()
        message = self.message_text.get("1.0", tk.END)
        connection = None
        try:
            connection, db_path = self.database_connection()
            record_id = insert_outbound_message(connection, phone, message)
        except Exception as exc:
            if connection is not None:
                connection.close()
            messagebox.showerror("Error al insertar", str(exc))
            return
        connection.close()

        self.status_var.set(f"Registro insertado en {db_path.name} con id={record_id}.")
        self.refresh_queue()

    def insert_and_run(self) -> None:
        self.insert_single()
        if "id=" in self.status_var.get():
            self.run_sender()

    def insert_bulk(self) -> None:
        lines = self.bulk_text.get("1.0", tk.END).splitlines()
        connection = None
        try:
            connection, db_path = self.database_connection()
            inserted_ids = insert_messages_from_lines(connection, lines)
        except Exception as exc:
            if connection is not None:
                connection.close()
            messagebox.showerror("Error al insertar lote", str(exc))
            return
        connection.close()

        self.status_var.set(
            f"Se insertaron {len(inserted_ids)} registros manuales en {db_path.name}."
        )
        self.refresh_queue()

    def insert_bulk_and_run(self) -> None:
        self.insert_bulk()
        if "Se insertaron" in self.status_var.get():
            self.run_sender()

    def run_sender(self) -> None:
        db_path = self.db_path_var.get().strip() or str(DEFAULT_DB_PATH)
        profile_dir = self.profile_dir_var.get().strip() or str(DEFAULT_PROFILE_DIR)
        command = [
            sys.executable,
            "whatsapp_db_sender.py",
            "--db",
            db_path,
            "--profile-dir",
            profile_dir,
        ]
        try:
            subprocess.Popen(command)
        except OSError as exc:
            messagebox.showerror("Error al ejecutar", f"No se pudo iniciar el envío.\n\n{exc}")
            return

        self.status_var.set("Se lanzó el proceso de envío con los registros pendientes.")

    def refresh_queue(self) -> None:
        for item in self.queue_tree.get_children():
            self.queue_tree.delete(item)

        connection = None
        try:
            connection, _ = self.database_connection()
            rows = list_outbound_messages(connection, limit=25)
        except Exception as exc:
            if connection is not None:
                connection.close()
            self.status_var.set(f"No se pudo leer la base de datos: {exc}")
            return
        connection.close()

        for row in rows:
            preview = row["message"]
            if len(preview) > 90:
                preview = preview[:87] + "..."
            self.queue_tree.insert(
                "",
                tk.END,
                values=(row["id"], row["phone"], row["status"], preview),
            )

    def clear_single(self) -> None:
        self.phone_var.set("")
        self.message_text.delete("1.0", tk.END)
        self.status_var.set("Captura manual limpia.")

    def clear_bulk(self) -> None:
        self.bulk_text.delete("1.0", tk.END)
        self.status_var.set("Carga manual por lote limpia.")


def main() -> None:
    root = tk.Tk()
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")
    app = WhatsAppSenderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
