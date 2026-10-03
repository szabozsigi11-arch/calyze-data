# Kötvények (amerikai államkötvény-hozamgörbe) — előre rögzítve

**Rögzítve:** 2026-10-03, **mielőtt egyetlen kötvény-becslés vagy -mérés
készült volna.** Forrás: `docs/terv-7-fazis.md` (G1–G3, a tulajdonos
jóváhagyásával; a határidős rész a licenc után). A kripto és a deviza
mintája: ami itt nincs kimondva, az ott áll (`kripto-modell.md`,
`fx-modell.md`).

---

## 1. Forrás és időpont (ellenőrizve 2026-10-03-án)

- **Az amerikai pénzügyminisztérium napi hozamgörbéje** (Daily Treasury Par
  Yield Curve Rates), 1990-től. Szövetségi kormányzati adat, közvagyon.
- **A pillanatfelvétel ideje:** a New York-i Fed a jegyzéseket „at or near
  3:30 PM” veszi (New York-i idő); **közzététel** „by 6:00 PM Eastern Time”
  ugyanazon a napon (a minisztérium módszertani oldala). Egy nap „zárása”
  tehát a 15:30-as (ET) pillanatfelvétel.
- **A Yahoo-tanulság** (`fx-univerzum.md`, 1.) után ez az első, amit
  ellenőriztünk: a közlés ugyanaznap, a felvétel után 2,5 órával jön.

## 2. Naptár

**Kötvénynap:** hétfőtől péntekig, kivéve az amerikai szövetségi ünnepeket
és nagypénteket. 2024-ben és 2025-ben pontosan ezek hiányoztak a görbéből.
Ha egy ilyen napra mégsincs görbe, az hiányként jelölődik, nem pótoljuk. A
horizont kötvénynapban számít (5, 20, 60).

**Kiegészítés, 2026-10-03, az első mérés előtt:** a teljes letöltés (1990–2026)
szerint 6 kötvénynapon nincs görbe (állami gyász, 2001. szeptember 11–12., a
Sandy hurrikán), és 20 olyan napra van, amely a naptár szerint nem kötvénynap
(nagypéntek munkaerőpiaci jelentéssel; a szombatra eső ünnep pénteki
megtartása). Ez utóbbiakat **kihagyjuk**: a naptár dönti el, mi kötvénynap, így
a horizont a backtestben és élőben ugyanazokat a napokat számolja. Mindkét
listát a letöltés napi összefoglalója rögzíti.

## 3. Univerzum: 7 idősor

| Azonosító | Mi |
|---|---|
| `UST3M`, `UST2Y`, `UST5Y`, `UST10Y`, `UST30Y` | a fix futamidejű hozam (%) |
| `UST10Y2Y`, `UST30Y5Y` | a meredekség: a két hozam különbsége (százalékpont) |

Mind az öt futamidő 1990-től szerepel; a 30 éves 2002 és 2006 között
hiányzik (a kibocsátás szünetelt). Ami hiányzik, az hiány, nem pótoljuk.

## 4. Mit mérünk: a hozam változását

- **A célváltozó a hozam változása** (h kötvénynap alatt), nem hozam-hozam:
  a meredekség negatív is lehet, a rövid hozam közel nulla volt.
  Technikailag a modell `exp(hozam/100)` „árat” lát, így a log-változás
  pontosan a hozamváltozás / 100; a felületen a hozam %-ban, a változás
  bázispontban látszik.
- **„Emelkedik” = a hozam (vagy a meredekség) nő.** A felület ezt minden
  kötvény-nézeten kimondja; árfolyamra fordítva fordított az irány.

## 5. Rezsim, feature, modell, baseline

- **Rezsim:** a 10 éves hozam napi változásának 20 napos volatilitása és
  az öt futamidő napi változásainak átlagos abszolút páronkénti
  korrelációja 60 napra; bővülő percentilis, legalább 252 nap; calm < 1/3,
  stressed ≥ 0,80. Ellenőrzés (csak közöljük): 2008 októbere, 2020
  márciusa, 2022 szeptembere stressed; 2017 második fele calm.
- **Feature:** a technikai lista a fenti „árból”, volumen és rés nélkül;
  keresztmetszeti: `level_10y` (a 10 éves hozam), `slope_10y2y` és a 20
  napos változása (minden idősorra az aznapi érték); makro a nap előtti
  utolsó ismert értékkel (mint devizán).
- **Modell:** `lgbm-bonds` `v1`, `min_data_in_leaf = 100`; kalibráció az
  utolsó 252 kötvénynap; minimális múlt 300 nap.
- **Baseline:** naiv és momentum; a verdikt a naiv ellen.
- **Backtest:** teszt 504, első tanítás 756 kötvénynap, fold-küszöb 3 000 /
  1 000 sor; saját család (`scope = bonds`).

## 6. Élő becslés

- Kötvénynapokon a közzététel (18:00 ET) után; **csak akkor élő, ha a
  15:30-as (ET) felvétel után legfeljebb 6 órán belül készül.** A futás
  háromszor indul az ablakon belül; a becslés egyszer mentődik.
- Lenyomat a nyilvános repóba (`manifests-bonds/`).

## 7. Arénák és hír-aréna

- **Indikátor-aréna:** a részvényes szabályok a „hozam-áron”, a volumen-
  szabály nélkül (nem szólhat).
- **Minta-aréna:** gyertyaminták nélkül (napi egy érték), a korrekció előtt
  kizárva.
- **Sokk-jel:** idősor-szinten elmozdulás ≥ 2,5 × a 20 napos szórás; piaci
  jel (`curve_broad`): az öt futamidőből legalább **3** mozog 2,5 × a 60
  napos szórás fölött. Visszatartás nincs.
- **Hír-aréna — a kötvénynél ez a fő kérdés:** a FOMC-, CPI- és NFP-nap
  előtti kötvénynapon a 10 éves hozam következő 5 napi volatilitása
  nagyobb-e, mint előtte 20 napon. Ugyanaz a mérő, mint a részvényeknél
  (`hir-arena.md`), saját családban; backtest a rezsim első címkézett
  napjától, élő az első élő kötvény-becsléstől.

## 8. Tézis és gyors trade

A kötvény-idősorra **egyelőre nem lehet tézist vagy gyors trade-et
rögzíteni**: a hozam iránya fordított az árfolyaméhoz képest, és a
zárónapi értesítéshez a kötvény-naptár az adatbázisban még nincs meg. Ha
lesz, az új, dátumozott kiegészítés lesz.
