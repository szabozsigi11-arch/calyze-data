# Konfluencia-motor — definíció

**Rögzítve:** 2026-09-28. **Ez a dokumentum a mérés előtt készült.**

A kereskedők nem egy indikátorra figyelnek, hanem feltételek együttállására:
„kalapács, támasznál, emelkedő trendben”. A konfluencia-motor ezeket a
kombinációkat méri, ugyanazzal a protokollal, mint az egyes jelzéseket.

**Ez a termék legveszélyesebb része.** Sok kombinációt tesztelve a véletlen
is ad „nyerteseket”. A `spec/08` 3. fejezetének öt korlátja ezért itt
számokkal rögzül, a mérés előtt, és utólag nem változik.

---

## 1. Mi egy kombináció

**Egy kiváltó esemény + 0–3 kontextus-feltétel**, legfeljebb 4 feltétel
összesen (1. korlát). A kombináció iránya a kiváltóé.

### Kiváltók (eseménynapok)

Az indikátor-aréna 12 szabálya (`jelzes-definiciok.md`) és a minta-aréna
alapszabályai (`minta-definiciok.md`, `minta-definiciok-2.md`), a
következő megszorításokkal, hogy egy jelzés ne szerepeljen többször:

- gyertyaminták: az összesített szabály (a `|at_level` bontás nem kiváltó,
  mert a szint-kontextus ugyanezt méri);
- támasz-ellenállás: `sr_support_touch`, `sr_resistance_touch`;
- váll-fej-váll: a négy állapot × tető/alj (8);
- szerkezettörés, kitörés-visszateszt, top-down, trendvonal: az összesített
  szabályok;
- Fibonacci: csak a `wick` változat (a négy változat ugyanazt az eseményt
  mérné négyszer), zónánként.

### Kontextus-feltételek (a kiváltó napján ismert állapotok)

Mind a kiváltó irányához igazodik („egyirányú” = long kiváltónál emelkedő,
short-nál csökkenő).

| Azonosító | Mikor igaz |
|---|---|
| `trend` | a záróár az EMA200 egyirányú oldalán van |
| `level` | long: a mélypont élő támasztól, short: a csúcs élő ellenállástól `0,5 · ATR`-en belül (az M7 szabálya) |
| `structure` | a napi szerkezet (M5) egyirányú |
| `htf` | a havi, a heti és a napi szerkezet (M4) egyirányú |
| `calm` | a piaci rezsim nem `stressed` |
| `volume` | a forgalom legalább a 20 napos medián kétszerese |

**Önmagukkal nem párosulnak:** a `level` nem társul gyertyamintához és
támasz-érintéshez (azok már szinten mértek), a `htf` a top-down kiváltóhoz,
a `trend` az EMA200-keresztezéshez, a `structure` a szerkezettöréshez.

---

## 2. A tesztelt család

Minden kiváltó × a megengedett kontextusok 1, 2 és 3 elemű részhalmazai × 3
horizont (5, 20, 60 nap). Az egyedülálló kiváltó nem tartozik a családhoz
(azt a saját arénája méri).

**A család mérete felülről korlátos:** 6 kontextusból legfeljebb 41
részhalmaz jut egy kiváltóra; a teljes szám a futás elején kiíródik, és a
felület kiírja (4. korlát).

---

## 3. Felfedezés és megerősítés — két időszak

| Időszak | Mettől meddig | Mire |
|---|---|---|
| **felfedezés** | a mérés kezdetétől 2018-12-31-ig | itt tesztelünk minden kombinációt |
| **megerősítés** | 2019-01-01-től a legutóbbi lezárt napig | csak a felfedezésen átment kombinációkat nézzük |

A felfedezés kimenetele nem nyúlhat át a határon: egy esemény csak akkor
számít, ha a horizontja 2018-12-31-ig lezárult.

**Egy kombináció akkor kap „Better” jelzést, ha mind a kettő teljesül (5. korlát):**

1. **felfedezés:** legalább 30 lezárt megfigyelés, legalább 30-as effektív
   mintaszám, jobb a naiv baseline-nál, és **Benjamini–Hochberg-korrekció
   után** p < 0,05 a teljes felfedezési családon (3. korlát);
2. **megerősítés:** legalább 30 megfigyelés, jobb a baseline-nál, és
   Benjamini–Hochberg után p < 0,05 a megerősítésre került kombinációk
   családján.

Minden más állapot kiíródik, tompítás nélkül: „Too early” (30 alatt, 2.
korlát), „Same”, „Worse”, „Found, not confirmed” (a felfedezésen átment, a
megerősítésen nem).

**A felületen a megerősítési időszak számai a főszámok.** A felfedezés száma
torzított (a legjobbat választottuk ki), a megerősítésé nem.

---

## 4. Mérés

Ugyanaz a kód, mint az arénákban: irány-találati arány a naiv baseline-hoz,
blokk-bootstrap p-érték, effektív mintaszám, a „Same” sáv ±0,5 pont. A
baseline az adott időszak saját sodródása (a felfedezésé a felfedezésből, a
megerősítésé a megerősítésből).

---

## 5. Élő panel

Az instrumentum-nézeten: a legutóbbi napon mely kiváltók szóltak, mely
kontextusok álltak, és a kombinációjuk mért állapota a fenti szabályokkal —
**és hogy hány kombinációból** választottuk. Ha a kombináció nincs a
családban vagy nincs rá elég adat, a panel ezt mondja ki.

---

## 6. Amit ez a dokumentum szándékosan nem tartalmaz

- **Két kiváltó egy napon.** Két esemény pontosan ugyanazon a napon ritka, és
  a család mérete a kiváltópárokkal négyzetesen nőne.
- **Hangolást.** Egyik szám sem mozog: a 0,5 · ATR, az EMA200, a 2× forgalom
  és a 2018-as határ is egyetlen érték.
- **Napon belüli adatot** (a termék napi idősíkon mér).
