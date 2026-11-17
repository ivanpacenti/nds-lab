# nds-lab

Un laboratorio per costruire e capire un emulatore Nintendo DS, partendo da
un interprete ARM piccolo e leggibile in Python.

## Avvio

Servono Python 3.12 o successivo e [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/ivanpacenti/nds-lab.git
cd nds-lab
uv sync
uv run nds-lab
uv run nds-lab --trace
```

Risultato atteso

```text
Sum 1..10 = 55 (42 instructions)
```

È disponibile anche `uv run python -m nds_lab`.
In PyCharm apri la cartella del progetto e seleziona `.venv/bin/python` come
interprete dopo `uv sync`. Metti un breakpoint in `CPU.step()` e avvia il
modulo `nds_lab` per seguire ogni istruzione.

## Primo esperimento

La demo carica sei istruzioni ARM reali, codificate a mano in `demo.py`.

```asm
    MOV r0, #0
    MOV r1, #1
loop:
    ADD r0, r0, r1
    ADD r1, r1, #1
    CMP r1, #11
    BNE loop
```

`r0` accumula la somma, `r1` contiene il prossimo numero da aggiungere.
`CMP` aggiorna i flag. Quando `r1` raggiunge 11, il flag Z diventa vero e
`BNE` viene saltata. Il runner termina all'indirizzo successivo al programma.
Questo punto di arresto è una convenzione della demo, non un'istruzione di halt.
Il conteggio di 42 include il salto finale saltato e misura istruzioni visitate,
non cicli hardware.

La traccia mostra indirizzo e opcode, `exec` o `skip`, tutti i registri dopo
il passo e i flag N/Z/C/V. Un trattino rappresenta un flag disattivato.

## Come leggere il codice

- `src/nds_lab/memory.py` implementa una regione di memoria little-endian.
- `src/nds_lab/cpu.py` legge, decodifica ed esegue una istruzione per `step()`.
- `src/nds_lab/demo.py` contiene il programma e la traccia di esecuzione.
- `tests/` verifica il programma completo e i casi limite delle istruzioni.

Il valore conservato in `registers[15]` indica la prossima istruzione da leggere.
Quando un'istruzione usa PC come operando, riceve invece l'indirizzo corrente
più 8, come previsto per queste istruzioni in stato ARM. B/BL usano lo stesso
riferimento. BL conserva l'indirizzo di ritorno in r14.

## Sottoinsieme implementato

- Registri a 32 bit e flag N, Z, C, V.
- MOV, ADD, SUB, CMP con immediati ARM ruotati o registri senza shift.
- Varianti con aggiornamento dei flag e condizioni da EQ ad AL.
- B e BL con offset positivo o negativo.
- Letture e scritture di memoria a 8, 16 e 32 bit tramite API Python.

Le istruzioni non supportate producono `UnsupportedInstruction` se la loro
condizione passa. Gli errori di decodifica lasciano invariati i registri e i flag.
Le condizioni false avanzano il PC senza eseguire il corpo dell'istruzione.

Questa versione è un interprete didattico parziale. Restano da implementare
Thumb, load/store della CPU, shift dei registri, scritture al PC tramite
istruzioni aritmetiche, modalità privilegiate, eccezioni e CPSR/SPSR completi.
La memoria richiede allineamento per accessi a 16/32 bit. Il comportamento
hardware degli accessi disallineati, la mappa DS, ARM7/ARM9 simultanei, timing,
grafica, audio, periferiche, caricamento `.nds` e integrazione iOS sono tappe
successive. Questa demo non esegue giochi DS.

## Verifiche

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Come prossimo esercizio, cambia il limite immediato di CMP da 11 a 6 e prova
a prevedere somma finale e numero di istruzioni prima di eseguire la demo.
La verifica finale di `main()` è fissata a 55, quindi andrà aggiornata insieme
al programma. La prossima estensione del core sarà LDR/STR per leggere e
scrivere dati in memoria direttamente dalle istruzioni ARM.

## Riferimento tecnico

La decodifica segue il formato ARM a 32 bit descritto nella documentazione Arm.
Il riferimento serve per verificare la semantica, mentre il codice di questo
progetto è scritto appositamente per il laboratorio.

- [Arm instruction set, data processing](https://documentation-service.arm.com/static/5ed11a2dca06a95ce53f8f99)
