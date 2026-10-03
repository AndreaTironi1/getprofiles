"""GUI Tkinter per getprofiles: stessa logica della CLI (main.py), senza riga di comando.

Non modifica nessun modulo esistente: riusa excel_io, checkpoint, validators,
api_client, config e main.select_to_process.
"""

import configparser
import json
import logging
import os
import queue
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter.scrolledtext import ScrolledText

import checkpoint as ckpt
import config as cfg
import excel_io
import validators
from api_client import CircuitBreakerTripped, ProfileApiClient, UnauthorizedError
from main import select_to_process
from version import __version__

MODES = [
    ("all", "Rilavora tutto (ignora i risultati già salvati)"),
    ("skip", "Salta i già elaborati (riprende da dove eri arrivato)"),
    ("retry", "Come sopra, ma rifai anche quelli finiti in errore"),
    ("export", "Solo rigenera l'Excel dai risultati già salvati (nessuna chiamata)"),
]

ADVANCED = [
    ("rate", "Richieste al secondo", "2.0", "Quante verifiche al secondo. Più basso = più prudente."),
    ("max_retries", "Tentativi per errore", "5", "Quante volte riprovare se il servizio risponde con un errore temporaneo."),
    ("base_delay", "Attesa iniziale (s)", "1.0", "Pausa prima del primo nuovo tentativo."),
    ("max_delay", "Attesa massima (s)", "60.0", "Tetto della pausa tra i tentativi."),
    ("timeout", "Timeout chiamata (s)", "10.0", "Dopo quanti secondi una chiamata è considerata persa."),
]


def app_dir() -> Path:
    """Cartella dell'.exe se impacchettato, altrimenti quella del sorgente."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


SETTINGS_PATH = app_dir() / "gui_settings.json"


class QueueLogHandler(logging.Handler):
    def __init__(self, q: queue.Queue):
        super().__init__()
        self.q = q

    def emit(self, record):
        self.q.put(("log", self.format(record)))


def backup_if_exists(path: Path) -> None:
    if path.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M")
        path.with_name(f"{path.name}.bak-{stamp}").write_bytes(path.read_bytes())


def run_job(opts: dict, q: queue.Queue, stop: threading.Event) -> None:
    """Stessa sequenza di main.main(), ma con progresso e stop verso la GUI."""
    logger = logging.getLogger("getprofiles")
    try:
        input_path = Path(opts["input"])
        output_path = Path(opts["output"])
        checkpoint_path = Path(opts["checkpoint"]) if opts["checkpoint"] else ckpt.default_path_for(input_path)

        raw_values = excel_io.read_cf_column(input_path, opts["column"])
        records, stats = validators.process_input(raw_values)
        logger.info(
            "Input: %d righe, %d vuote, %d duplicati, %d CF univoci (%d non validi)",
            stats["total_rows"], stats["blank"], stats["duplicates"],
            stats["unique_valid"] + stats["invalid_format"], stats["invalid_format"],
        )
        entries = ckpt.load(checkpoint_path)
        logger.info("Checkpoint: %d esiti già registrati in %s", len(entries), checkpoint_path)

        interrupted = False
        if opts["mode"] != "export":
            key = cfg.resolve_subscription_key(Path(opts["config"]))
            skip = opts["mode"] in ("skip", "retry")
            to_process = select_to_process(records, entries, opts["mode"] == "retry", skip)
            logger.info("CF da interrogare in questo run: %d", len(to_process))

            client = ProfileApiClient(
                subscription_key=key,
                rate=float(opts["rate"]),
                max_retries=int(opts["max_retries"]),
                base_delay=float(opts["base_delay"]),
                max_delay=float(opts["max_delay"]),
                timeout=float(opts["timeout"]),
            )
            started = time.monotonic()
            total = len(to_process)
            q.put(("progress", 0, total, None))
            for i, record in enumerate(to_process, start=1):
                if stop.is_set():
                    interrupted = True
                    logger.info("Interrotto dall'utente. I risultati già ottenuti sono salvati.")
                    break
                result = client.get_profile(record.normalized)
                entry = ckpt.CheckpointEntry(
                    codice_fiscale=record.normalized,
                    timestamp=datetime.now().isoformat(timespec="seconds"),
                    esito=result.esito,
                    http_status=result.http_status,
                    sender_allowed=result.sender_allowed,
                    preferred_languages=result.preferred_languages,
                    error_detail=result.error_detail,
                    attempts=result.attempts,
                )
                ckpt.append(checkpoint_path, entry)
                entries[record.normalized] = entry
                elapsed = time.monotonic() - started
                eta = (total - i) * elapsed / i if elapsed > 0 else None
                q.put(("progress", i, total, eta))

        excel_io.write_report(output_path, records, entries, stats, input_path)
        logger.info("Report scritto in %s", output_path)
        detail = excel_io.build_detail_rows(records, entries)
        q.put(("done", {"detail": detail, "output": output_path, "interrupted": interrupted}))
    except cfg.ConfigError:
        q.put(("need_key", None))
    except UnauthorizedError:
        q.put(("error", "La chiave API è stata rifiutata (non autorizzata). Controlla la subscription key."))
    except CircuitBreakerTripped:
        q.put(("error", "Il servizio risponde con troppi errori consecutivi: elaborazione fermata. "
                        "I risultati già ottenuti sono salvati; riprova più tardi con «Salta i già elaborati»."))
    except ValueError as exc:
        q.put(("error", str(exc)))
    except Exception as exc:  # errore imprevisto: messaggio leggibile, dettagli nel log
        logger.exception("Errore imprevisto")
        q.put(("error", f"Errore imprevisto: {exc}"))


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"GetProfiles {__version__}: verifica profili App IO")
        self.geometry("980x760")
        self.minsize(820, 620)
        self.q: queue.Queue = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.last_output: Path | None = None
        self.vars: dict[str, tk.Variable] = {}
        self._build()
        self._load_settings()

        handler = QueueLogHandler(self.q)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.INFO)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._poll)

    # ---------- costruzione UI ----------
    def _var(self, name, value=""):
        self.vars[name] = tk.StringVar(value=value)
        return self.vars[name]

    def _file_row(self, parent, row, label, name, default, mode):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
        ttk.Entry(parent, textvariable=self._var(name, default)).grid(row=row, column=1, sticky="ew", padx=6)
        ttk.Button(parent, text="Sfoglia…", command=lambda: self._browse(name, mode)).grid(row=row, column=2)

    def _build(self):
        pad = {"padx": 10, "pady": 4}
        top = ttk.LabelFrame(self, text="1. File")
        top.pack(fill="x", **pad)
        top.columnconfigure(1, weight=1)
        self._file_row(top, 0, "File con i codici fiscali (Excel/CSV)", "input", "", "open")
        ttk.Label(top, text="Nome della colonna dei CF").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Entry(top, textvariable=self._var("column", "codice_fiscale"), width=24).grid(row=1, column=1, sticky="w", padx=6)
        self._file_row(top, 2, "Dove salvare il report Excel", "output", str(app_dir() / "data" / "report.xlsx"), "save")
        self._file_row(top, 3, "File con la chiave API (config.ini)", "config", str(app_dir() / "config.ini"), "open")

        mode = ttk.LabelFrame(self, text="2. Cosa fare")
        mode.pack(fill="x", **pad)
        self._var("mode", "all")
        for value, text in MODES:
            ttk.Radiobutton(mode, text=text, value=value, variable=self.vars["mode"]).pack(anchor="w", padx=8, pady=1)

        self.adv_open = tk.BooleanVar(value=False)
        ttk.Checkbutton(self, text="Opzioni avanzate", variable=self.adv_open, command=self._toggle_adv).pack(anchor="w", padx=10)
        self.adv = ttk.Frame(self)
        for r, (name, label, default, hint) in enumerate(ADVANCED):
            ttk.Label(self.adv, text=label).grid(row=r, column=0, sticky="w", padx=8, pady=1)
            ttk.Entry(self.adv, textvariable=self._var(name, default), width=8).grid(row=r, column=1, padx=6)
            ttk.Label(self.adv, text=hint, foreground="#666").grid(row=r, column=2, sticky="w")
        r = len(ADVANCED)
        ttk.Label(self.adv, text="File di checkpoint").grid(row=r, column=0, sticky="w", padx=8, pady=1)
        ttk.Entry(self.adv, textvariable=self._var("checkpoint", ""), width=40).grid(row=r, column=1, columnspan=2, sticky="w", padx=6)
        ttk.Label(self.adv, text="Vuoto = automatico, accanto al file di input", foreground="#666").grid(row=r + 1, column=1, columnspan=2, sticky="w", padx=6)

        bar = self.bar = ttk.Frame(self)
        bar.pack(fill="x", **pad)
        self.btn_start = ttk.Button(bar, text="Avvia", command=self._start)
        self.btn_start.pack(side="left")
        self.btn_stop = ttk.Button(bar, text="Interrompi", command=self.stop_event.set, state="disabled")
        self.btn_stop.pack(side="left", padx=6)
        self.btn_open = ttk.Button(bar, text="Apri Excel", command=self._open_excel, state="disabled")
        self.btn_open.pack(side="right")
        self.btn_dir = ttk.Button(bar, text="Apri cartella", command=self._open_dir, state="disabled")
        self.btn_dir.pack(side="right", padx=6)

        self.progress = ttk.Progressbar(self, mode="determinate")
        self.progress.pack(fill="x", **pad)
        self.status = tk.StringVar(value="Pronto.")
        ttk.Label(self, textvariable=self.status).pack(anchor="w", padx=10)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, **pad)
        sum_tab, det_tab, log_tab = ttk.Frame(nb), ttk.Frame(nb), ttk.Frame(nb)
        nb.add(sum_tab, text="Riepilogo")
        nb.add(det_tab, text="Dettaglio")
        nb.add(log_tab, text="Log")

        self.tree_sum = ttk.Treeview(sum_tab, columns=("esito", "n", "pct"), show="headings", height=8)
        for c, t, w in (("esito", "Esito", 320), ("n", "CF", 80), ("pct", "%", 80)):
            self.tree_sum.heading(c, text=t)
            self.tree_sum.column(c, width=w, anchor="w")
        self.tree_sum.pack(fill="both", expand=True)

        cols = ("codice_fiscale", "esito", "sender_allowed", "lingue_preferite", "http_status", "dettaglio_errore")
        self.tree_det = ttk.Treeview(det_tab, columns=cols, show="headings")
        for c in cols:
            self.tree_det.heading(c, text=c.replace("_", " "))
            self.tree_det.column(c, width=150 if c != "dettaglio_errore" else 260, anchor="w")
        sb = ttk.Scrollbar(det_tab, orient="vertical", command=self.tree_det.yview)
        self.tree_det.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree_det.pack(fill="both", expand=True)

        self.log = ScrolledText(log_tab, height=10, state="disabled", font=("Consolas", 9))
        self.log.pack(fill="both", expand=True)

    def _toggle_adv(self):
        if self.adv_open.get():
            self.adv.pack(fill="x", padx=10, before=self.bar)
        else:
            self.adv.pack_forget()

    def _browse(self, name, mode):
        if mode == "save":
            path = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")])
        else:
            path = filedialog.askopenfilename(
                filetypes=[("Excel/CSV", "*.xlsx *.xls *.csv"), ("Tutti i file", "*.*")]
                if name == "input" else [("Configurazione", "*.ini"), ("Tutti i file", "*.*")]
            )
        if path:
            self.vars[name].set(path)

    # ---------- impostazioni ----------
    def _load_settings(self):
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for k, v in data.items():
            if k in self.vars:
                self.vars[k].set(v)

    def _save_settings(self):
        try:
            SETTINGS_PATH.write_text(
                json.dumps({k: v.get() for k, v in self.vars.items()}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    # ---------- esecuzione ----------
    def _start(self):
        opts = {k: v.get().strip() if isinstance(v.get(), str) else v.get() for k, v in self.vars.items()}
        if not opts["input"] or not Path(opts["input"]).exists():
            messagebox.showwarning("File mancante", "Scegli un file Excel o CSV di input valido.")
            return
        try:
            for name, label, *_ in ADVANCED:
                float(opts[name])
        except ValueError:
            messagebox.showwarning("Valore non valido", f"Controlla il campo «{label}»: serve un numero.")
            return
        self._save_settings()
        self.stop_event.clear()
        self._clear_results()
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.status.set("Elaborazione in corso…")
        self.progress.config(value=0, maximum=1)
        self.worker = threading.Thread(target=run_job, args=(opts, self.q, self.stop_event), daemon=True)
        self.worker.start()

    def _clear_results(self):
        for tree in (self.tree_sum, self.tree_det):
            tree.delete(*tree.get_children())

    def _poll(self):
        try:
            while True:
                kind, *payload = self.q.get_nowait()
                getattr(self, f"_on_{kind}")(*payload)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _on_log(self, line):
        self.log.config(state="normal")
        self.log.insert("end", line + "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def _on_progress(self, i, total, eta):
        self.progress.config(maximum=max(total, 1), value=i)
        if total == 0:
            self.status.set("Nessun CF da interrogare.")
        else:
            tail = f", circa {int(eta)} s residui" if eta is not None and i < total else ""
            self.status.set(f"{i}/{total} ({i / total * 100:.0f}%){tail}")

    def _on_done(self, res):
        self._finish()
        detail = res["detail"]
        total = len(detail)
        counts = {o: 0 for o in excel_io.REPORT_OUTCOME_ORDER}
        for row in detail:
            counts[row["esito"]] = counts.get(row["esito"], 0) + 1
        for outcome, n in counts.items():
            pct = n / total * 100 if total else 0.0
            self.tree_sum.insert("", "end", values=(outcome, n, f"{pct:.1f}%"))
        for row in detail:
            self.tree_det.insert("", "end", values=tuple("" if row[c] is None else row[c] for c in self.tree_det["columns"]))
        self.last_output = res["output"]
        self.btn_open.config(state="normal")
        self.btn_dir.config(state="normal")
        self.progress.config(value=self.progress["maximum"]) if not res["interrupted"] else None
        self.status.set(("Interrotto. " if res["interrupted"] else "Completato. ") + f"Report: {res['output']}")

    def _on_error(self, msg):
        self._finish()
        self.status.set("Errore.")
        messagebox.showerror("Errore", msg)

    def _on_need_key(self, _=None):
        self._finish()
        self.status.set("Manca la chiave API.")
        key = simpledialog.askstring(
            "Chiave API",
            "Subscription key non trovata.\nIncollala qui: verrà salvata nel file di configurazione.",
            show="*", parent=self,
        )
        if not key or not key.strip():
            return
        path = Path(self.vars["config"].get())
        try:
            backup_if_exists(path)
            parser = configparser.ConfigParser()
            if path.exists():
                parser.read(path, encoding="utf-8")
            if not parser.has_section("api"):
                parser.add_section("api")
            parser.set("api", "subscription_key", key.strip())
            with open(path, "w", encoding="utf-8") as fh:
                parser.write(fh)
        except OSError as exc:
            messagebox.showerror("Errore", f"Impossibile salvare la chiave in {path}: {exc}")
            return
        messagebox.showinfo("Chiave salvata", "Chiave salvata. Premi di nuovo Avvia.")

    def _finish(self):
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")

    def _open_excel(self):
        if self.last_output and self.last_output.exists():
            os.startfile(self.last_output)

    def _open_dir(self):
        if self.last_output:
            os.startfile(self.last_output.parent)

    def _on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno("Uscire?", "Elaborazione in corso. I risultati già ottenuti sono salvati. Uscire?"):
                return
        self._save_settings()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
