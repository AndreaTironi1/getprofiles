# getprofiles

**Versione 1.0** · disponibile come **script Python** e come **programma Windows con finestra (`.exe`)**.

Strumento che verifica quali codici fiscali di un elenco hanno un profilo su
[App IO](https://io.italia.it) e possono ricevere messaggi dal tuo servizio.

Legge un file Excel o CSV, interroga l'API GetProfile di PagoPA una riga alla volta e produce un
report Excel con un riepilogo e il dettaglio per ogni codice fiscale. Gira in locale: l'unica
comunicazione verso l'esterno è la chiamata all'API di PagoPA.

> **Dati personali.** I codici fiscali sono dati personali. Questo repository non contiene
> elenchi, report o chiavi, e non deve mai contenerne. Leggi [Privacy e sicurezza](#privacy-e-sicurezza)
> prima del primo utilizzo.

## Due modi di usarlo

| | Script Python | Programma con finestra (`.exe`) |
|---|---|---|
| Per chi | Chi usa la riga di comando o vuole automatizzare | Chi non vuole installare nulla |
| File | `main.py` | `GetProfiles-1.0.exe`, dalla pagina [Releases](../../releases) |
| Requisiti | Python 3.10 o superiore, `pip install -r requirements.txt` | Solo Windows. **Python non serve** |
| Chiave API | Variabile d'ambiente o `config.ini` | `config.ini` accanto all'`.exe` (o la chiede il programma al primo avvio) |
| Versione | `python main.py --version` | Nel nome del file e nel titolo della finestra |

In entrambi i casi serve la *subscription key* del tuo servizio su App IO, assegnata da PagoPA all'ente.

## Programma con finestra (.exe)

1. Scarica `GetProfiles-1.0.exe` dalla pagina [Releases](../../releases) e mettilo in una cartella a tua scelta.
2. Fai doppio clic. Se Windows mostra un avviso SmartScreen, scegli *Ulteriori informazioni* e poi *Esegui comunque*: il file non è firmato digitalmente.
3. Scegli il file Excel/CSV, indica il nome della colonna dei codici fiscali e premi **Avvia**. Al primo avvio il programma chiede la chiave e la salva in `config.ini`, nella stessa cartella dell'`.exe`.
4. Al termine vedi riepilogo e dettaglio nella finestra e apri il report con **Apri Excel**.

Le opzioni dello script (`--skip-existing`, `--retry-failed`, `--export-only`, rate, timeout, ...) sono nella finestra come scelte in italiano e sotto *Opzioni avanzate*. **Interrompi** ferma il lavoro tenendo i risultati già ottenuti.

Per creare l'`.exe` da soli: `build_exe.bat` (richiede Python e la `.venv`), risultato in `dist/`.

## Script Python

### Requisiti

- Python 3.10 o superiore
- Le librerie in `requirements.txt` (`requests`, `pandas`, `openpyxl`)

### Installazione

```bash
git clone <URL-DEL-REPOSITORY>
cd getprofiles
python -m venv .venv
```

Attiva l'ambiente virtuale (`.venv\Scripts\activate` su Windows, `source .venv/bin/activate` su
Linux e macOS), poi:

```bash
pip install -r requirements.txt
```

## Configurazione della chiave

Due modi, in ordine di priorità:

1. **Variabile d'ambiente** (consigliata): `IO_API_SUBSCRIPTION_KEY`
2. **File `config.ini`** nella cartella del progetto: copia `config.example.ini` in `config.ini`
   e sostituisci il segnaposto nella sezione `[api]`

```ini
[api]
subscription_key = LA_TUA_CHIAVE
```

`config.ini` è nel `.gitignore`. La chiave non è mai scritta nel codice e non compare nei log.

## Utilizzo

```bash
python main.py --input elenco.xlsx --column codice_fiscale
```

Il file di input può essere `.xlsx` o `.csv`. La colonna con i codici fiscali si chiama
`codice_fiscale` per default; con `--column` si indica un altro nome. Nella cartella `examples/`
c'è un CSV di prova con dati fittizi.

Al termine il report è in `data/report.xlsx`.

### Opzioni

| Opzione | Default | Cosa fa |
|---|---|---|
| `--input` | obbligatoria | File Excel o CSV con i codici fiscali |
| `--column` | `codice_fiscale` | Nome della colonna con i codici fiscali |
| `--output` | `data/report.xlsx` | Percorso del report Excel |
| `--checkpoint` | `data/checkpoint__<nome input>.jsonl` | File di checkpoint |
| `--config` | `./config.ini` | File di configurazione con la chiave |
| `--rate` | `2.0` | Richieste al secondo |
| `--max-retries` | `5` | Tentativi per errori transitori |
| `--base-delay` | `1.0` | Attesa iniziale del backoff, in secondi |
| `--max-delay` | `60.0` | Attesa massima del backoff, in secondi |
| `--timeout` | `10.0` | Timeout di ogni chiamata, in secondi |
| `--skip-existing` | disattivo | Salta i codici che hanno già un esito nel checkpoint |
| `--retry-failed` | disattivo | Come `--skip-existing`, ma riprova quelli finiti in errore |
| `--export-only` | disattivo | Rigenera il report dal checkpoint, senza chiamare l'API |
| `--log-level` | `INFO` | Livello di log |

`--skip-existing` e `--retry-failed` si escludono a vicenda. Senza nessuno dei due, ogni run
interroga di nuovo tutti i codici validi.

### Esempi

Riprendere un lavoro interrotto, saltando i codici già verificati:

```bash
python main.py --input elenco.xlsx --skip-existing
```

Riprovare solo i codici finiti in errore:

```bash
python main.py --input elenco.xlsx --retry-failed
```

Rigenerare il report senza nuove chiamate:

```bash
python main.py --input elenco.xlsx --export-only
```

## Gli esiti

| Esito nel report | Significato |
|---|---|
| Sì (attivo) | Profilo IO presente, il servizio può inviare messaggi |
| Sì (attivo, messaggi bloccati) | Profilo IO presente, ma il cittadino non accetta messaggi dal servizio |
| No (nessun profilo) | Nessun profilo IO |
| Forbidden (da verificare) | Risposta 403: **non** equivale a "nessuna app", va verificato a mano |
| Errore (non verificabile) | Errori transitori persistenti dopo tutti i tentativi, o stato HTTP inatteso |
| Scartato (formato non valido) | Codice fiscale con formato errato, non inviato all'API |
| In sospeso (rieseguire) | Codice valido non ancora verificato |

Dettagli su mapping dei codici HTTP, checkpoint e struttura del report in
[docs/riferimento.md](docs/riferimento.md).

## Robustezza

- **Checkpoint incrementale**: ogni esito è scritto subito su file. Se il programma si interrompe
  si riparte da dove si era arrivati.
- **Retry con backoff esponenziale** per 429, errori 5xx, timeout e problemi di connessione,
  con rispetto dell'intestazione `Retry-After`.
- **Interruttore di sicurezza**: dopo 10 errori transitori consecutivi il run si ferma, perché
  probabilmente c'è un disservizio lato API.
- **Stop immediato su 401**: una chiave non valida non è un problema del singolo codice fiscale.

## Test

```bash
pip install -r requirements-dev.txt
pytest
```

I test usano `requests-mock`: non fanno chiamate reali e non richiedono la chiave.

## Privacy e sicurezza

- **Finalità.** Usa lo strumento per organizzare la comunicazione del tuo servizio, non per altri
  scopi. Concorda l'uso con il DPO dell'ente e documentalo.
- **Chiave.** La subscription key è un segreto dell'ente: variabile d'ambiente o file locale,
  mai in email, chat o repository. Se pensi sia stata esposta, chiedi a PagoPA di ruotarla.
- **File di lavoro.** Input, checkpoint (`.jsonl`) e report contengono codici fiscali. Il
  `.gitignore` li esclude, ma controlla sempre `git status` prima di un commit. Conservali dove
  conservi gli altri dati dell'ente e cancellali quando non servono più.
- **Uso dell'esito.** Sapere che una persona non ha l'app serve a scegliere il canale giusto,
  non a classificarla.

## Struttura del progetto

```
main.py          CLI e orchestrazione
gui.py           Programma con finestra (Tkinter), stessa logica della CLI
version.py       Numero di versione (script ed eseguibile)
build_exe.bat    Crea l'eseguibile Windows con PyInstaller
api_client.py    Client dell'API GetProfile: retry, rate limit, mapping esiti
validators.py    Normalizzazione, validazione e deduplica dei codici fiscali
checkpoint.py    Checkpoint JSONL e logica di ripresa
excel_io.py      Lettura dell'input e scrittura del report
config.py        Risoluzione della chiave
tests/           Test automatici
examples/        File di input di prova con dati fittizi
docs/            Documentazione di riferimento
```

## Licenza

Riuso libero citando la fonte: licenza [MIT](LICENSE). Puoi usare, modificare e distribuire il
codice, anche in un contesto commerciale, a condizione di mantenere l'avviso di copyright
(Andrea Tironi) in tutte le copie e nelle parti derivate.
