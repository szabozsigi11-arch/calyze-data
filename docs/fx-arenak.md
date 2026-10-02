# Arénák, sokk-jelzés és hír-aréna devizán — előre rögzítve

**Rögzítve:** 2026-10-02, **mielőtt bármelyik deviza-aréna egyetlen számot
adott volna.** Forrás: `docs/terv-6-fazis.md` (F5), `docs/fx-modell.md`,
`docs/kripto-arenak.md` (a minta). Az alapelv ugyanaz: a szabályok a
részvényesek, a mérés új, saját korrekciós családban.

A deviza árfolyama naponta **egyetlen fixálás**: nyitó, maximum, minimum és
volumen nincs (`fx-univerzum.md`, 2.). Ami ezekre épül, az devizán nem
értelmezhető, és **a korrekció előtt kimarad** — nem utólag, eredmény alapján.

---

## 1. Indikátor-aréna

A részvényes szabályok mind, a fixálásból. A `volume_spike_up` szabály
volumen nélkül soha nem szól, ezért nincs mérve (nem nulla eredménnyel
szerepel, hanem sehogy). Horizont: 5, 20, 60 TARGET-nap. Rezsim: a
deviza-rezsim (`fx-modell.md`, 1.). BH-FDR a deviza-indikátorok saját
családján.

## 2. Minta-aréna

- **Kimarad minden gyertyaminta** (`pipeline/patterns/candles.py`): ezek a
  nyitó–maximum–minimum–záró viszonyára épülnek, devizán a négy ár azonos
  (egy doji például minden nap „szólna”).
- A többi minta (szint-érintés, fej-váll, szerkezettörés, kitörés,
  Fibonacci, top-down, trendvonal) a fixálás-idősoron, ahol a maximum és a
  minimum a fixálás maga.
- BH-FDR a deviza-minták saját családján, a gyertyaminták nélkül számolt
  családméreten.

## 3. Sokk-jelzés a deviza-becslésen

- **Pár-szintű jel:** elmozdulás ≥ 2,5 × a 20 napos szórás. Volumen- és
  rés-jel nincs.
- **Piaci jel (`usd_broad`):** a hét dolláros pár közül legalább **4**
  mozog aznap a saját 60 napos szórásának 2,5-szerese fölött.
- **Visszatartás devizán nincs** az első változatban (mint kriptón).

## 4. Hír-aréna devizán

Ugyanaz a kérdés, mint a `hir-arena.md`-ben, **5 TARGET-napos** utólagos
volatilitással a 20 napos előtti ellen:

| Jel | Mérés | Összevetés |
|---|---|---|
| `instrument_shock` | a jelzett pár-nap | aznap a jelzés nélküli párok aránya |
| `usd_broad` | a dollár-index a jelzett napokon | a jelzés nélküli napok aránya |
| `calendar` (FOMC, EKB, CPI, NFP külön is) | a dollár-index az esemény előtti TARGET-napon | a többi nap aránya |

A dollár-index a `fx-modell.md` 1. fejezetéé. A naptár a `naptar.md`
hivatalos eseményei; a BoE- és BoJ-döntések még nincsenek benne (ha
bekerülnek, az új, dátumozott kiegészítés lesz). Backtest a deviza-rezsim
első címkézett napjától az első élő deviza-becslésig, utána élő, két külön
BH-családban.
