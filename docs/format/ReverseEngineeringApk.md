# Samsung Notes — Reverse Engineering Asset & Template

> Contesto: parte del progetto `feat/opensdocx-app` (viewer Linux open-source per `.sdocx`).
> Obiettivo di questa sessione: recuperare i design/template di pagina di default di Samsung Notes.

---

## 1. Setup ambiente

- Dispositivo Android target: `gts7fewifi` (Samsung Galaxy Tab S7 FE, presumibilmente)
- Package: `com.samsung.android.app.notes`
- Tool usati: `adb`, `apktool`, `unzip`, `strings`, `pdftotext` (poppler)

### Problema iniziale: ADB non vedeva il device
- **Causa**: cavo USB "charge-only" (senza linee dati D+/D-), non un problema di driver/udev su Arch/CachyOS
- **Fix**: cambiato cavo → risolto
- Nota per il futuro: se `lsusb` non mostra il vendor id Samsung (`04e8`), controllare cavo/porta prima di tutto il resto (udev rules, gruppi plugdev, ecc.)

---

## 2. Estrazione APK

```bash
# Trova il path dell'APK installato
adb shell pm path com.samsung.android.app.notes
# → package:/data/app/~~<hash>==/com.samsung.android.app.notes-<hash>==/base.apk

# Pull dell'APK
adb pull "/data/app/~~<hash>==/com.samsung.android.app.notes-<hash>==/base.apk" ./samsung_notes.apk
```

- `run-as com.samsung.android.app.notes` → **fallisce** (`package not debuggable`). Niente accesso a `/data/data/` senza root.
- `/sdcard/Android/data/com.samsung.android.app.notes/files/` → risultato vuoto/poco utile (i template scaricati non sono cachati qui, vedi sezione 5)
- Nessuno split APK aggiuntivo (solo `base.apk`, ~151MB; presenti anche `base.dm`, `lib`, `oat` ma irrilevanti per gli asset)

### ⚠️ Due metodi di estrazione — uno inutile, uno corretto

| Metodo | Risultato |
|---|---|
| `unzip base.apk -d notes_extracted/` | Estrae tutto ma i file in `res/` hanno **nomi hashati** (es. `L56.pdf`, `9Ww.pdf`) — Android li rinomina in build per resource shrinking |
| `apktool d samsung_notes.apk -o notes_apktool` | **Legge `resources.arsc`** e ricostruisce i **nomi originali** (es. `journal_01.pdf`) — metodo corretto, usare sempre questo per i nomi reali |

```bash
yay -S apktool   # se non installato
apktool d samsung_notes.apk -o notes_apktool
```

---

## 3. Template dinamici (layout)

Percorso: `assets/template/dynamic_template_00X_00Y.xml` (10 file totali)

- Definiscono **struttura/layout**: posizione box di testo, font, colori, dimensioni pagina
- Attributo chiave: `background="<nome>.pdf"` referenzia lo sfondo grafico (quando presente)
- Esempio (`dynamic_template_001_000.xml`, journal):
  ```xml
  <template version="1" thumbnail="journal_01.png">
      <page id="1" width="2000" height="2800" background="journal_01.pdf">
          ...
      </page>
  </template>
  ```

### Mappatura template → sfondo trovata
```bash
grep -h "background=" notes_extracted/assets/template/*.xml
```
Risultato: 7 riferimenti a `journal_01.pdf` ... `journal_07.pdf` + 1 a colore piatto `#FFFACD`

### 2 template SENZA background (= pattern generato a runtime, vedi sezione 4)
- `dynamic_template_002_000.xml` (layout tipo "Cornell notes": header/keyword/notes/summary)
- `dynamic_template_003_000.xml` (weekly ToDo list)

---

## 4. Sfondi grafici (PDF bundlati)

Trovati in `notes_apktool/res/raw/` (nomi reali grazie ad apktool):

```
journal_01.pdf … journal_07.pdf     (7 file)
planner_v4.pdf
planner_land_v1.pdf
planner_long_v1.pdf
```
Totale: 10 PDF di sfondo statico, coprono le categorie **Journal** e **Planner**.

### Cartelle NON pertinenti (falsi indizi scartati)
- `assets/pdfda/rtdetr_doclaynet_toc_v1.13.7_quant.ort.onnx` → modello ONNX per analisi layout di PDF importati (document layout detection), non uno sfondo
- `assets/hwrgen_template/math_basic_cooljazz_80.plt` → modello per generazione/riconoscimento scrittura a mano, non uno sfondo pagina
- `schemaorg_apache_xmlbeans/system/.../*.xsb` → **schema OOXML standard di PowerPoint** (namespace `openxmlformats.org/presentationml`, classi tipo `CT_Background`, `org.openxmlformats.schemas.presentationml...`). È libreria Apache POI/XMLBeans generica bundlata forse per import/export Office, **NON è il formato interno `.sdocx`** di Samsung. Falsa pista, da non rincorrere ulteriormente.

---

## 5. Le 5 categorie di template dell'app: cosa abbiamo capito

L'app mostra 5 categorie: **Planner, Journal, Basic, Academic, Creative**. Solo 2 sono bundlate come file statici nell'APK:

| Categoria | Dove si trova | Meccanismo |
|---|---|---|
| **Journal** | `res/raw/journal_01-07.pdf` | PDF statico bundlato nell'APK |
| **Planner** | `res/raw/planner_*.pdf` | PDF statico bundlato nell'APK |
| **Basic** | ❌ nessun file | **Generato a runtime**: flag `linedPaperEnabled="true"` + `linedPagerColor="#..."` sui `textBox` del template XML → il renderer disegna righe/quadretti proceduralmente via Canvas. **Per il viewer: se un `.sdocx` ha questo flag, va ridisegnato il pattern a codice, non cercato un asset.** |
| **Academic** | ❌ non nell'APK | Scaricato **on-demand** da server Samsung al primo utilizzo (confermato da stringa `change_template_download_pdf_using_mobile_data: "Download using mobile data?"` in `strings.xml`) |
| **Creative** | ❌ non nell'APK | Come Academic, download on-demand |

---

## 6. Stato attuale / prossimo step (DA RIPRENDERE QUI)

Hai già scaricato tutti i template Academic/Creative dall'app, ma:

```bash
adb shell find /sdcard/Android/data/com.samsung.android.app.notes/files -type f
# → risultato VUOTO
```

**Conclusione**: la cache dei template scaricati è in `/data/data/com.samsung.android.app.notes/` (storage interno privato), **non accessibile senza root** (confermato anche da `run-as` fallito in precedenza).

### Piano B in corso — intercettare l'URL via logcat

```bash
adb logcat -c
adb logcat | grep -iE "http|url|download|cdn|akamai|cloudfront"
```
Poi sul telefono: nuova nota → cambia template → categoria Academic/Creative → toccare un template (idealmente uno non ancora scaricato, per forzare la richiesta di rete) → osservare l'output del logcat per un URL Samsung/CDN.

**Limite noto**: se il traffico è HTTPS con certificate pinning, l'URL potrebbe non comparire in chiaro nel log.

### Piano C (se logcat non basta) — mitmproxy

```bash
adb shell settings put global http_proxy <IP_PC>:8080
```
+ mitmproxy sul PC, con certificato CA installato manualmente sul telefono per intercettare anche HTTPS. Più lavoro di setup ma affidabile al 100%.

---

## Comandi di riferimento rapido

```bash
# Estrazione pulita con nomi reali
apktool d samsung_notes.apk -o notes_apktool

# Trova tutti gli sfondi statici
find notes_apktool/res/raw -iname "*.pdf"

# Trova tutti i template XML e i loro background
grep -h "background=" notes_extracted/assets/template/*.xml

# Cerca stringhe di categoria/download nell'app
grep -i "academic\|creative\|download" notes_apktool/res/values/strings.xml
```