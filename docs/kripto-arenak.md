# Arénák, sokk-jelzés és hír-aréna kriptón — előre rögzítve

**Rögzítve:** 2026-10-02, **mielőtt bármelyik kripto-aréna egyetlen számot
adott volna.** Forrás: `docs/terv-5-fazis.md` (E5), `docs/kripto-modell.md`.

Az alapelv: **a szabályok ugyanazok, a mérés új.** Minden, ami itt nincs
külön kimondva, szóról szóra a részvényes definíció.

---

## 1. Indikátor- és minta-aréna

- **Szabályok:** a részvényes indikátor-aréna (`jelzes-definiciok.md`) és
  minta-aréna (`minta-definiciok.md`, `minta-definiciok-2.md`) minden
  szabálya, változtatás nélkül, a kripto-univerzum 50 papírjára
  (`kripto-univerzum.md`).
- **Horizont:** 5, 20, 60 **nap** (24/7: a nap = kereskedési nap).
- **Baseline:** ugyanaz a naiv irány-baseline, mint a részvényeknél.
- **Rezsim-bontás:** a kripto-rezsimmel (`kripto-modell.md`, 1.).
- **Korrekció:** a BH-FDR **arénánként és eszközosztályonként külön
  családban** fut: a kripto-indikátorok a kripto-indikátorokkal, a
  kripto-minták a kripto-mintákkal. A részvényes eredmények nem változnak
  attól, hogy a kripto bekerült.
- **Túlélési torzítás:** a mai lista; a felület ugyanúgy kimondja.

## 2. Sokk-jelzés a kripto-becslésen

- **Papír-szintű jel** (a részvényes detektor küszöbeivel): volumen
  60 napos z ≥ 3, illetve elmozdulás ≥ 2,5 × a 20 napos szórás. **Rés-jel
  nincs:** 24/7-es piacon nincs zárvatartás, amit a nyitás átugorhatna.
- **Piaci jel (`crypto_broad`):** a 10-es rezsim-kosárból (`kripto-modell.md`,
  1.) legalább **5** papír mozog aznap a saját 60 napos szórásának
  2,5-szerese fölött. VIX-jel nincs (a VIX a részvénypiac mutatója).
- **Visszatartás kriptón nincs az első változatban.** A részvényes
  visszatartás (VIX-ugrás és keresztpiaci kimozdulás együtt) mért szabály;
  kriptóra még nincs mért megfelelője. A jelzett becslés megjelenik, és
  jelölve van. Ha később lesz kripto-visszatartás, az új, dátumozott
  definíció lesz.
- A jel a becslés-csomagba kerül, és a lenyomat fedi (mint a részvényeknél).

## 3. Hír-aréna kriptón

Ugyanaz a kérdés, mint a `hir-arena.md`-ben: a „fontos nap” jelzés
előrejelzés arra, hogy a következő **5 nap** realizált volatilitása
meghaladja az előtte lévő 20 napét (a jelzés napja nélkül).

| Jel | Mérés | Összevetés |
|---|---|---|
| `instrument_shock` | a jelzett papír-nap | ugyanazon a napon a jelzés nélküli kripto-papírok aránya |
| `crypto_broad` | a BTC a jelzett napokon | a jelzés nélküli napok aránya |
| `calendar` (és FOMC, CPI, NFP, EKB külön) | a BTC az esemény előtti napon | a többi nap aránya |

- **Időszak:** backtest a kripto-rezsim első címkézett napjától
  (2019-01-07) az első élő kripto-becslés napjáig; **élő** onnantól, a
  lenyomatolt jelekből. A kettő két külön BH-családban, mint a
  részvényeknél.
- Az esemény-naptár a részvényes `naptar.md` hivatalos dátumai; kriptón a
  „következő nap” a következő UTC-nap.
