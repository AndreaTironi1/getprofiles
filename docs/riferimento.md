# Riferimento tecnico

## Flusso di un run

1. **Lettura dell'input.** `excel_io.read_cf_column` legge il file (`.csv` oppure Excel) con tutte le
   celle come testo e restituisce la colonna indicata. Se la colonna non esiste, l'errore elenca
   le colonne disponibili.
2. **Pulizia.** `validators.process_input` rimuove gli spazi, porta tutto in maiuscolo, scarta
   le celle vuote, elimina i duplicati (si tiene la prima occorrenza) e marca i formati non
   validi. I codici non validi restano nel report ma non vengono mai inviati all'API.
3. **Checkpoint.** Si carica il checkpoint esistente. Senza `--skip-existing` o `--retry-failed`
   viene ignorato per decidere cosa interrogare, ma resta la base del report.
4. **Chiave.** Si risolve la subscription key: prima la variabile d'ambiente, poi `config.ini`.
   Senza chiave il run termina con errore. Con `--export-only` questo passaggio e le chiamate
   vengono saltati.
5. **Interrogazione.** Per ogni codice valido da lavorare: chiamata all'API, scrittura
   dell'esito nel checkpoint, log di avanzamento.
6. **Report.** Si scrive l'Excel con i fogli `Riepilogo` e `Dettaglio`.

## Validazione del codice fiscale

Il controllo è sul **formato** (16 caratteri: sei lettere, due cifre, una lettera di mese, due
cifre, una lettera, tre cifre, una lettera), con le lettere ammesse al posto delle cifre nei
casi di omocodia. Non viene verificato il carattere di controllo finale né la corrispondenza
con i dati anagrafici.

## API utilizzata

```
GET https://api.io.pagopa.it/api/v1/profiles/{codice_fiscale}
Header: Ocp-Apim-Subscription-Key: <chiave>
```

| Risposta | Gestione | Esito |
|---|---|---|
| 200 | Legge `sender_allowed` e `preferred_languages` | Sì (attivo) oppure Sì (attivo, messaggi bloccati) |
| 404 | Nessun profilo | No (nessun profilo) |
| 403 | Non ritentata | Forbidden (da verificare) |
| 401 | Il run si interrompe subito | nessuno (errore) |
| 429, 5xx, timeout, errore di connessione | Retry con backoff | Errore (non verificabile) dopo l'ultimo tentativo |
| altro | Non ritentata | Errore (non verificabile), con lo stato HTTP |

### Rate limit, retry e interruttore

- **Rate limit.** Un intervallo minimo di `1 / rate` secondi fra due chiamate (default 2 al secondo).
- **Backoff.** Attesa `base_delay * 2^(tentativo - 1)`, più un valore casuale fino a
  `base_delay`, con tetto a `max_delay`. Se il server manda `Retry-After`, l'attesa non scende
  sotto quel valore, sempre entro il tetto.
- **Tentativi.** Fino a `max-retries` ripetizioni dopo il primo tentativo.
- **Interruttore.** Dopo 10 codici consecutivi finiti in errore transitorio, il run si ferma con
  messaggio esplicito. Un qualunque esito riuscito azzera il contatore.

## Checkpoint

File JSON Lines, una riga per esito, solo in aggiunta. Percorso di default:
`data/checkpoint__<nome del file di input>.jsonl`.

Campi di ogni riga: `codice_fiscale`, `timestamp`, `esito`, `http_status`, `sender_allowed`,
`preferred_languages`, `error_detail`, `attempts`.

- Se un codice compare più volte (per esempio dopo `--retry-failed`), vince l'ultima riga.
- Una riga finale troncata da un'interruzione brusca viene ignorata. Una riga corrotta in mezzo
  al file, invece, è un errore.
- Con `--skip-existing` si saltano i codici con un esito definitivo (Sì, No, Forbidden, Errore,
  Scartato). Con `--retry-failed` si riprovano anche quelli finiti in Errore.

Il checkpoint contiene codici fiscali: va trattato come un dato personale.

## Report Excel

**Foglio Riepilogo**: file di input, data di generazione, righe lette, righe vuote scartate,
duplicati rimossi, codici univoci considerati, poi per ogni esito il numero e la percentuale.

**Foglio Dettaglio**, una riga per codice fiscale univoco:

| Colonna | Contenuto |
|---|---|
| `codice_fiscale_originale` | Valore come letto dal file |
| `codice_fiscale` | Valore normalizzato |
| `esito` | Esito, vedi README |
| `sender_allowed` | Se il cittadino accetta messaggi dal servizio |
| `lingue_preferite` | Lingue indicate nel profilo |
| `http_status` | Stato HTTP dell'ultima chiamata |
| `dettaglio_errore` | Descrizione dell'errore, se presente |
| `timestamp` | Momento della verifica |
| `tentativi` | Numero di tentativi usati |

## Sviluppo

```bash
pip install -r requirements-dev.txt
pytest
```

I test sono divisi per modulo (`tests/test_*.py`) e usano solo codici fiscali fittizi.
Se aggiungi un test, usa dati inventati: mai codici fiscali reali.
