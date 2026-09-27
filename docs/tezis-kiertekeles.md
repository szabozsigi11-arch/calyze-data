# A tézisek kiértékelése és a saját kalibráció — előre rögzített definíció

**Rögzítve:** 2026-09-27, az első tézis előtt.
**Forrás:** `spec/09` (napló), `spec/06` (mérési protokoll), `spec/13` (2.1).

Ez a dokumentum azt rögzíti, hogyan mérjük a felhasználó előre rögzített
téziseit. A definíció az első mért tézis előtt készült; ha változik, új
változatként jön, dátummal, és a régi szerint mért eredmények külön
megmaradnak.

A felhasználói adat (a tézisek maguk) **soha nem kerül ebbe a repóba** és a
futások naplójába sem: a napló csak darabszámot ír.

---

## 1. Mi a tézis

Egy állítás: *„ez a papír a következő `h` kereskedési napon emelkedik
(long) / nem emelkedik (short), `p` valószínűséggel"*.

| Mező | Megengedett érték | Miért |
|---|---|---|
| horizont `h` | 5, 20 vagy 60 kereskedési nap | ugyanazok, mint a modellé: így a három szereplő (ember, modell, baseline) ugyanazon az ablakon hasonlítható |
| valószínűség `p` | 0,55–0,95, 0,05-ös lépésben | 50% nem állítás; 95% fölött a mérés egyetlen tévedésen múlna. A 0,05-ös lépés azt a pontosságot kéri, amit egy ember ténylegesen tud mondani |
| irány | long / short | |

A rögzítés ideje (`created_at`) **szerveridő**. A tézis ezután nem
módosítható és nem dátumozható vissza; ezt adatbázis-szabály kényszeríti ki,
nem a felület.

## 2. Az ablak

- **Kezdőnap `S`:** az első NYSE-kereskedési nap, amelynek zárása
  (16:00 New York-i idő) a rögzítés **után vagy vele egyidőben** van.
  Napközben rögzített tézis aznap zárásától indul; zárás után rögzített a
  következő napétól. Így a rögzítés pillanatában ismert napközbeni mozgás
  nem számít bele.
- **Célnap `E`:** `S` után a `h`-adik kereskedési nap.
- **Hozam:** teljes hozam (osztalékkal) `S` zárásától `E` zárásáig, a
  modellel azonos árfolyamsorból (`pipeline.corporate.total_return_prices`).
- **Kivezetés, felfüggesztés:** ha `E`-re nincs ár, az utolsó ismert
  kereskedési nap zárása zár, `resolution_type = delisted_or_halted`
  jelöléssel, pontosan úgy, mint a modell becslésénél.

## 3. Pontozás

A modellel azonos szabály (`pipeline.model.evaluate`): az esemény az
„emelkedik" (`y > 0`).

- `p_up = p`, ha long; `p_up = 1 − p`, ha short.
- **Találat:** `(p_up > 0,5) == (y > 0)`. A short tézis tehát akkor talál,
  ha a hozam nem pozitív.
- **Brier:** `(p_up − [y > 0])²`.

Ugyanerre az ablakra (`S`, `h`, papír) a **modell** és a **naiv baseline**
becslését is kiértékeljük, ugyanígy. Ha aznapra nincs modellbecslés, a
tézis kiértékelődik, de a modell-összevetés üres marad, és ezt a felület
kiírja.

## 4. Mi számít a kalibrációba

| Tétel | Számít? |
|---|---|
| tézis, kiértékelve | **igen** |
| tézis, a végrehajtás lezárva (exit ár megadva) a horizont előtt | **igen** — a lezárás a kereskedést zárja, a mérést nem |
| tézis, a kiértékelés **előtt** törölve | nem; külön darabszámként látszik („deleted before resolution") |
| tézis, a kiértékelés **után** törölve | **igen** — a törlés csak a listából veszi ki, az eredményt nem tünteti el |
| gyors trade | nem („unregistered") |

## 5. A kalibráció

- **Sávok:** 0,55–0,64, 0,65–0,74, 0,75–0,84, 0,85–0,95 (a megadott `p`
  szerint), horizontonként és összesítve.
- Sávonként: `n`, találat, átlagos Brier.
- **Százalék csak `n ≥ 30` mellett** (2. sarokkő). Alatta a sáv
  „Not enough data", a hiányzó darabszámmal.
- **Brier skill score** a baseline-hoz: `1 − Brier_ember / Brier_baseline`,
  ugyanazokon a téziseken. Ez lesz a közösségi rangsor mércéje (H4).
- A kalibrációt **kizárólag a szerver** írja (`user_calibration`); a
  felhasználó csak olvashatja.

## 6. Mikor fut

A napi pipeline a becslések kiértékelése után. Egy tézis akkor zárul, amikor
`E` záróára megvan. A kiértékelés egyszer íródik, utána nem változik.

## 7. Ember kontra modell kontra baseline, és a közösségi rangsor

*Kiegészítés, rögzítve 2026-09-27-én, a rangsor első sora előtt.*

**Összevethető tézis:** kiértékelt, és az ablakára volt modell- és
baseline-becslés (3. fejezet). Csak ezeken hasonlítunk, mindhárom
szereplőre ugyanazokon.

**Ember-aréna (a saját oldalon).** Az átlagos Brier-pontszám különbsége a
naiv baseline-hoz és a modellhez, `n` összevethető tézisen:

| Feltétel | Verdict |
|---|---|
| `n < 30` | Not enough data |
| `|Δ| < 0,005` | Same |
| `Δ ≥ 0,005` a felhasználó javára | Better, **not significant** |
| `Δ ≤ −0,005` | Worse |

A személyes rekordra **nem mondunk szignifikanciát**: a tézisek ablakai
átfednek, egy felhasználó mintája kicsi, és a blokkos bootstrapot erre még
nem futtatjuk. Ezt a felület ki is írja. (A küszöb a modellé, CLAUDE.md,
2026-09-19.)

**Brier skill score (BSS):** `1 − Brier_ember / Brier_baseline`, az
összevethető téziseken.

**Miért nem ad előnyt a könnyű tézis.** A BSS ugyanarra az ablakra mért
baseline-hoz viszonyít. Aki csak ott tesz tézist, ahol a baseline már
magabiztos, és vele egyezően mond valószínűséget, annak a Brier-pontszáma
a baseline-éval egyezik, a BSS-e 0 — akármilyen „könnyű” volt a papír. A
BSS csak akkor pozitív, ha a felhasználó *többet* tud a baseline-nál. Ezt
teszt is igazolja.

**Rangsor.**
- Benne van, akinek legalább **30 összevethető** tézise van, részt vesz
  (a beállításokban kiléphet), és nincs kizárva (admin, indoklással).
- Álnévvel jelenik meg, amit a szerver ad; e-mail, azonosító nem látszik.
- Sorrend: BSS csökkenő; mellette mindig ott az `n`.
- Amíg kevesebb mint két résztvevő van, a rangsor üres, és ezt ki is mondja.
- Csak a szerver számolja; a felhasználó a saját sorát sem írhatja.
