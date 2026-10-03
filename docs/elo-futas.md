# Részvény élő futás: határidő és lenyomat — rögzítve

**Rögzítve:** 2026-10-03, a 2026-10-02-i (pénteki) tőzsdenap becslése
**előtt**. Az ezt követő minden részvényes becslésre érvényes; ami előtte
készült, az alább név szerint, változatlanul szerepel.

A kripto (`kripto-modell.md`, 6.), a deviza (`fx-modell.md`, 5.) és a kötvény
(`kotveny.md`, 6.) eddig is határidőhöz kötötte az élő becslést. A
részvénynél ez kimaradt; ez a dokumentum pótolja, ugyanazzal az indokkal.

---

## 1. A szabály

- **Egy tőzsdenap becslése csak akkor készül el, ha a következő tőzsdenap
  nyitása (NYSE, 9:30 New York-i idő) előtt rögzül.** Utána a becslés
  ablakának egy része már lezajlott, és a lenyomat utólagos válogatásnak
  látszana — akkor is, ha a modell csak a zárásig lát.
- **Részleges csomagot nem mentünk.** Ha a kész becslés az univerzum 80%-ánál
  kevesebb papírt fed le (a forrás még nem adta ki a napot), a futás nem ment,
  és egy későbbi futás próbálja újra.
- **A futás a nyitásig hatszor indul** (22:30, 00:30, 02:30, 05:30, 09:30 és
  12:30 UTC); a becslés egyszer mentődik. Ha a nyitásig nem sikerül, a nap
  **kiesett napként** látszik, és nem pótoljuk.
- **A lenyomat közvetlenül a becslés után kerül a nyilvános repóba**, minden
  más lépés (kiértékelés, megjelenítés) előtt, hogy egy későbbi lépés hibája
  ne nyelhesse el.

## 2. Ami a szabály előtt történt (2026-09-18 – 2026-10-01)

A rekordban **minden sor marad, ahogy keletkezett** — utólag nem veszünk ki
és nem teszünk be semmit. Ezek a napok viszont nem felelnek meg a fenti
szabálynak, ezért itt és az állapotoldalon jelölve vannak:

| Tőzsdenap | Mi történt |
|---|---|
| 2026-09-21 | a lenyomat 09-23-án készült, a következő nyitás után (kézi indítás a bevezető hét javításai közben) |
| 2026-09-22 | a lenyomat 09-23-án, a következő nyitás után; és csak **1** papírra (részleges) |
| 2026-09-24 | a lenyomat 09-26-án, a következő nyitás után (az ütemezett futás elbukott, a kézi pótlás késett) |
| 2026-09-29 | a becslés elkészült (csak **6** papírra), de a megjelenítés egy átmeneti szerverhibán elbukott, és **a lenyomat nem került a nyilvános repóba** — nyilvánosan nem ellenőrizhető |
| 2026-09-30 | **kiesett**: a forrás a futáskor még nem adta ki a napot, a futás nem próbálta újra |

A többi nap (09-18, 09-23, 09-25, 09-28, 10-01) a nyitás előtt, teljes
lefedettséggel készült.

## 3. Miért nem vesszük ki utólag a fenti napokat

Mert az is utólagos szerkesztés lenne. A szabály az eredményektől függetlenül
(csak az időpont alapján) mondaná meg, mi esik ki, így nem volna válogatás —
de a mérés eddig ezekkel együtt futott, és a változtatást ki kellene mondani
minden számnál. Helyette: a napok név szerint itt állnak, az állapotoldal
jelöli őket, és **2026-10-02-től ilyen nap nem keletkezhet**. Ha később a
tulajdonos úgy dönt, hogy az élő verdikt nélkülük számoljon, az új,
dátumozott kiegészítés lesz.
