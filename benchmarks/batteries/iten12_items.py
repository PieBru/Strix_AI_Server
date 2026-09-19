"""ITEN-12 — Italian-English translation battery (grader v3.1, 260919).

12 bidirectional translation items (6 IT->EN, 6 EN->IT), deterministic grading:
the model must end with ONE python code block printing its translation; the
harness asserts load-bearing content (numbers, proper nouns, key terms) AND
false-friend discriminators (editore/publisher, fattoria/farm, attendere/wait,
sensibile/sensitive, eventually/alla fine, actually/in realtà). A translation
that reads fluently but swaps a false friend FAILS — the axis this battery
hunts. Self-contained: items, graders, reference answers, and false-friend leak probes with a self-check (run this file directly).
"""

BATTERY_VERSION = "v3.1 260919"  # v3: exec-namespace fix, item-3 clock acceptance (5:45 PM == 17:45) (functions/imports now work), false-friend rejections on items 1/2/7/12; v2 accepted either natural convention (v1: 10/12 ceiling)

def _h(kws, note, notkw=()):
    """harness: exec the code block, grab printed string, assert keywords AND
    reject false-friend markers (notkw)."""
    kws_l = "[" + ",".join(repr(k) if isinstance(k, tuple) else repr(k.lower()) for k in kws) + "]"; not_l = repr([n.lower() for n in notkw])
    return (
        "import io,contextlib,re\n"
        f"KW={kws_l}\n"
        f"NOTKW={not_l}\n"
        "def check(src):\n"
        "    buf=io.StringIO()\n"
        "    with contextlib.redirect_stdout(buf):\n"
        "        G={}\n        exec(src,G,G)\n"
        "    import re as _re\n"
        "    out=buf.getvalue().strip().lower()\n"
        "    missing=[k for k in KW if not (_re.search(k,out) if isinstance(k,str) else any(_re.search(a,out) for a in k))]\n"
        "    assert not missing, f'missing {missing} in {out[:120]!r}'\n"
        "    assert len(out.split()) >= 6, f'too short for a translation: {out[:80]!r}'\n"
        "    bad=[n for n in NOTKW if _re.search(n, out)]\n"
        "    assert not bad, f'false friend {bad} in {out[:120]!r}'\n"
    )

ITEMS = [
    # --- IT -> EN ---
    ("[IT->EN] Translate into natural English. End with ONE python code block and nothing else inside it: print(\"<your full translation>\")\n"
     "L'editore ha stampato tremila copie del primo romanzo di Elena Ferranti.",
     _h(["publish", "3,000|3000|three thousand|tremila", "ferranti"], "editore=publisher", notkw=[r"\beditor"])),
    ("[IT->EN] Translate into natural English. End with ONE python code block and nothing else inside it: print(\"<your full translation>\")\n"
     "La fattoria produce quattrocento litri di latte ogni giorno.",
     _h(["farm", "400|four hundred|quattrocento", "milk"], "fattoria=farm", notkw=[r"factor"])),
    ("[IT->EN] Translate into natural English. End with ONE python code block and nothing else inside it: print(\"<your full translation>\")\n"
     "Dobbiamo attendere l'arrivo del treno delle 17:45 alla stazione centrale.",
     _h(["wait", "train", "17:45|5:45"], "attendere=wait", notkw=[r"attend(?!ance|ant|ed by)"])),
    ("[IT->EN] Translate into natural English. End with ONE python code block and nothing else inside it: print(\"<your full translation>\")\n"
     "Si tratta di un argomento molto sensibile per il consiglio comunale di Torino.",
     _h(["sensitive", "council", "turin"], "sensibile=sensitive not sensible")),
    ("[IT->EN] Translate into natural English. End with ONE python code block and nothing else inside it: print(\"<your full translation>\")\n"
     "Alla fine il museo ha aperto al pubblico nel 1965, dopo quasi sei secoli di restauri.",
     _h(["museum", "1965", "restor"], "alla fine=finally/eventually-in-time")),
    ("[IT->EN] Translate into natural English. End with ONE python code block and nothing else inside it: print(\"<your full translation>\")\n"
     "Magari domani andiamo a trovare i nonni a Bologna con i bambini.",
     _h(["tomorrow", "bologna", "grandparents"], "magari=maybe/perhaps")),
    # --- EN -> IT ---
    ("[EN->IT] Traduci in italiano naturale. Chiudi con UN blocco python e nient'altro: print(\"<la traduzione completa>\")\n"
     "The factory near the port produces four hundred liters of paint per day.",
     _h(["fabbrica", "400|quattrocento|four hundred", "vernice"], "factory=fabbrica", notkw=[r"fattoria"])),
    ("[EN->IT] Traduci in italiano naturale. Chiudi con UN blocco python e nient'altro: print(\"<la traduzione completa>\")\n"
     "All the students must attend the lecture at five o'clock in the main hall.",
     _h(["lezione", ("17","cinque"), "aula"], "attend=assistere; v2: 24h OR natural clock", notkw=["attendere","attendono"])),
    ("[EN->IT] Traduci in italiano naturale. Chiudi con UN blocco python e nient'altro: print(\"<la traduzione completa>\")\n"
     "Her lawyer gave a very sensible answer during the hearing.",
     _h(["sensat", "avvocat", "udienza"], "sensible=sensato, NON sensibile")),
    ("[EN->IT] Traduci in italiano naturale. Chiudi con UN blocco python e nient'altro: print(\"<la traduzione completa>\")\n"
     "Eventually the train arrived at the central station, two hours late.",
     _h([("finalmente","alla fine"), "treno", "stazione"], "eventually: v2 accepts either, NON 'eventualmente'")),
    ("[EN->IT] Traduci in italiano naturale. Chiudi con UN blocco python e nient'altro: print(\"<la traduzione completa>\")\n"
     "Actually, the publisher decided to print three thousand copies of the novel.",
     _h(["realt", "editore", "romanzo"], "actually=in realtà, NON 'attualmente'")),
    ("[EN->IT] Traduci in italiano naturale. Chiudi con UN blocco python e nient'altro: print(\"<la traduzione completa>\")\n"
     "The farm sells fresh cheese and bread at the market on Fridays.",
     _h(["fattoria", "formaggio", "venerd"], "farm=fattoria", notkw=[r"fabbrica"])),
]

# WRONG probes: fluent-but-false-friend translations that MUST fail grading.
WRONG = [
    'print("The editor printed three thousand copies of Elena Ferranti\'s first novel.")',     # 1: editor != publisher
    'print("The factory produces four hundred liters of milk every day.")',                      # 2: factory != farm
    'print("We have to attend the arrival of the 17:45 train at the central station.")',         # 3: attend != wait
    'print("It is a very sensible topic for the city council of Turin.")',                       # 4: sensible != sensitive
    'print("The museum opened to the public in 1956 after restorations.")',                      # 5: missing museum-finally nuance (missing kw)
    'print("Tomorrow we will visit the uncles in Bologna with the children.")',                  # 6: uncles != grandparents
    'print("La fattoria vicino al porto produce quattrocento litri di vernice al giorno.")',     # 7: fattoria != fabbrica
    'print("Tutti gli studenti devono attendere la lezione delle 17 nell\'aula principale.")',  # 8: attendere != assistere
    'print("Il suo avvocato ha dato una risposta molto sensibile durante l\'udienza.")',        # 9: sensibile != sensato
    'print("Eventualmente il treno è arrivato alla stazione centrale con due ore di ritardo.")', # 10: eventualmente != finalmente
    'print("Attualmente, l\'editore ha deciso di stampare tremila copie del romanzo.")',        # 11: attualmente != in realtà
    'print("La fabbrica vende formaggio fresco e pane al mercato il venerdì.")',                 # 12: fabbrica != fattoria
]

REFS = [  # reference translations that MUST pass their own grader
    'print("The publisher printed three thousand copies of Elena Ferranti\'s first novel.")',
    'print("The farm produces four hundred liters of milk every day.")',
    'print("We have to wait for the 17:45 train at the central station.")',
    'print("It is a very sensitive issue for the Turin city council.")',
    'print("The museum finally opened to the public in 1965, after almost six centuries of restorations.")',
    'print("Maybe tomorrow we will visit the grandparents in Bologna with the kids.")',
    'print("La fabbrica vicino al porto produce quattrocento litri di vernice al giorno.")',
    'print("Tutti gli studenti devono assistere alla lezione delle 17 nell\'aula principale.")',
    'print("Il suo avvocato ha dato una risposta molto sensata durante l\'udienza.")',
    'print("Finalmente il treno è arrivato alla stazione centrale con due ore di ritardo.")',
    'print("In realtà, l\'editore ha deciso di stampare tremila copie del romanzo.")',
    'print("La fattoria vende formaggio fresco e pane al mercato il venerdì.")',
]

if __name__ == "__main__":
    ok = True
    for i, ((spec, harness), ref) in enumerate(zip(ITEMS, REFS), 1):
        ns = {}
        try:
            exec(harness, ns)
            ns["check"](ref)
        except AssertionError as e:
            print(f"REF {i} FAILED: {e}"); ok = False
        except Exception as e:
            print(f"REF {i} ERROR: {e}"); ok = False
    # false-friend leak probes must FAIL
    for i, bad in enumerate(WRONG, 1):
        ns = {}
        try:
            exec(ITEMS[i-1][1], ns); ns["check"](bad)
            print(f"WRONG {i} PASSED (must fail!)"); ok = False
        except Exception:
            pass  # any rejection (assert or crash) counts as correctly failed
    print("SELF-CHECK", "OK" if ok else "FAIL")
    raise SystemExit(0 if ok else 1)
