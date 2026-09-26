# Minta-definíciók — a minta-aréna alapja

**Rögzítve:** 2026-09-26. **Ez a dokumentum a mérés előtt készült.**

Ugyanaz az elv, mint a `jelzes-definiciok.md`-ben: a találati arány nem a
minta tulajdonsága, hanem a definícióé. Egy „kalapács" vagy egy
„váll-fej-váll" felismerése sokkal több szabadságot enged, mint egy
RSI-küszöb — és minden szabadságfok egy lehetőség arra, hogy a mérés után a
kívánt eredményre hangoljuk. Ezért minden küszöb itt, számmal, a mérés előtt
rögzül, és utólag nem változik. Ha egy definíció rossznak bizonyul, új néven
vesszük fel, és mindkettő eredménye látszik.

---

## 0. A legfontosabb szabály: az esemény dátuma a felismerés napja

Egy csúcsot csak utólag lehet csúcsnak látni: akkor csúcs, ha az utána
következő napok alacsonyabbak. **Ha a mérés a csúcs napjától indulna, a
minták egy olyan információval teljesítenének jól, ami akkor még nem volt
meg.** Ez a leggyakoribb hiba a mintakutatásban, és a legnagyobb látszat-
eredményt adja.

Ezért minden esemény arra a napra datálódik, amikor **a rendelkezésre álló
adatokból ténylegesen felismerhető lett**, és a kimenetel attól a naptól
mérődik. Minden alábbi szabálynál meg van nevezve, melyik ez a nap.

---

## 1. Közös alapok

**Gyertya-mennyiségek** (a `t` napra): test `B = |c − o|`, tartomány
`R = h − l`, felső árnyék `U = h − max(o, c)`, alsó árnyék `L = min(o, c) − l`.
Ahol `R = 0`, a gyertyán nincs minta.

**Zöld/piros:** zöld, ha `c > o`; piros, ha `c < o`; doji, ha `B ≤ 0,1 · R`.

**Előzetes trend:** a 10 napos hozam a minta ELŐTTI napig:
`c[t−1] / c[t−11] − 1`. Lefelé, ha negatív; felfelé, ha pozitív. A
fordulómintának csak a megfelelő előzetes trend után van jelentése.

**ATR:** a 14 napos átlagos valódi tartomány (Wilder), a `t−1` napig számolva.

**Csúcs és völgy (pivot):** a `p` nap csúcs, ha `h[p]` a legnagyobb a
`p−5 … p+5` ablakban; völgy, ha `l[p]` a legkisebb. **Felismerhető a `p+5`
napon** — előbb nem.

**Mérés:** ugyanaz a protokoll, mint mindenhol: irány-találati arány 5, 20 és
60 napos horizonton, a naiv baseline-hoz mérve, effektív mintaszámmal,
FDR-korrekcióval, 30 megfigyelés alatt százalék nélkül. Ugyanaz a kód méri,
mint az indikátor-arénát.

**Ismétlődés-zár:** ugyanaz a minta ugyanazon a papíron 5 napon belül csak
egyszer számít.

---

## 2. M7 — Támasz és ellenállás

**Szint:** völgyek (támasz) vagy csúcsok (ellenállás) csoportja, amelyek
árai legfeljebb `0,5 · ATR` távolságra vannak egymástól. A szint ára a
csoport átlaga. **Egy szint akkor létezik, ha legalább két pivot alkotja**,
és a második pivot felismerésének napjától él.

**Érintés:** a `t` napon a támaszt érinti az ár, ha `l[t]` a szinttől
`0,5 · ATR`-en belül van, és a záróár a szint fölött marad. Az ellenállásnál
fordítva. Az érintés felismerhető a `t` napon.

**Esemény:** minden érintés (az ismétlődés-zárral).
- `sr_support_touch` → long (a támasz tart)
- `sr_resistance_touch` → short (az ellenállás tart)

**Bontás, amit a spec kér:**
- **hányadik érintés:** 3., 4., 5. vagy több. A szintet alkotó két pivot is
  érintés, ezért a szint születése utáni első esemény már a harmadik. (Az
  első változat „2., 3., 4." bontást írt, de abban a 2. mindig üres lett
  volna — ezt a mérés előtt javítottuk, lásd a git-történetet.)
- **friss vagy régi szint:** friss, ha az előző érintés 60 napon belül volt

**Egy érintés egyszer számít.** Ha egy érintés napja később pivottá válik
(5 nappal később felismerhető), az nem egy újabb érintés: ugyanaz a
találkozás az árral. Két érintés akkor külön, ha legalább 5 nap van köztük.

**Lejárat:** egy szint megszűnik, ha a záróár `1 · ATR`-rel átlépi (a
támasz alá, az ellenállás fölé zár). Ettől a naptól nem érinthető.

---

## 3. M2 — Gyertya-fordulómintázatok

### A kontextus — ez a lényeg

A spec szerint a minta **támasznál vagy ellenállásnál** jelent valamit, a
chart közepén semmit. Minden előfordulás megkapja a kontextusát:

- `at_level`: a bullish minta mélypontja (`l`) egy élő támasztól, a bearish
  minta csúcsa (`h`) egy élő ellenállástól legfeljebb `0,5 · ATR`-re van —
  a szint a minta napján már felismerhető volt.
- `none`: minden más.

**A kettő külön mérődik.** Ez fogja megmutatni, mennyit ér a kontextus.

### A támogatott minták

| Azonosító | Gyertyák | Szabály | Előzetes trend | `dir` |
|---|---|---|---|---|
| `hammer` | 1 | `L ≥ 2B`, `U ≤ 0,1R`, `B ≤ 0,3R` | le | long |
| `hanging_man` | 1 | mint a `hammer` | fel | short |
| `inverted_hammer` | 1 | `U ≥ 2B`, `L ≤ 0,1R`, `B ≤ 0,3R` | le | long |
| `shooting_star` | 1 | mint az `inverted_hammer` | fel | short |
| `bullish_engulfing` | 2 | tegnap piros, ma zöld, `o ≤ c₋₁` és `c ≥ o₋₁` | le | long |
| `bearish_engulfing` | 2 | tegnap zöld, ma piros, `o ≥ c₋₁` és `c ≤ o₋₁` | fel | short |
| `morning_star` | 3 | 1. piros, `B₁ ≥ 0,6R₁`; 2. `B₂ ≤ 0,3B₁`, teste az 1. záróára alatt; 3. zöld, `c₃` az 1. test felezőpontja fölött | le | long |
| `evening_star` | 3 | tükörképe | fel | short |
| `morning_doji_star` | 3 | mint a `morning_star`, a 2. gyertya doji | le | long |
| `evening_doji_star` | 3 | mint az `evening_star`, a 2. gyertya doji | fel | short |

**A felismerés napja** mindegyiknél a minta utolsó gyertyájának napja.

### Az alacsony megbízhatóságúak — ezeket is mérjük

A spec szerint pont az a lényeg, hogy kiderüljön, van-e bennük bármi.

| Azonosító | Gyertyák | Szabály | Előzetes trend | `dir` |
|---|---|---|---|---|
| `piercing_line` | 2 | tegnap piros, `B₋₁ ≥ 0,6R₋₁`; ma zöld, `o < l₋₁`, `c` a tegnapi test felezőpontja fölött, de `c < o₋₁` | le | long |
| `dark_cloud_cover` | 2 | tükörképe | fel | short |
| `bullish_harami` | 2 | tegnap piros; ma zöld, a mai test a tegnapi testen belül | le | long |
| `bearish_harami` | 2 | tükörképe | fel | short |
| `three_white_soldiers` | 3 | három zöld, mindegyik zár az előző fölött, nyit az előző testén belül | le | long |
| `three_black_crows` | 3 | tükörképe | fel | short |

### A szinonimaszótár

A spec 1.1 fejezete szerint sok „önálló" mintanév ugyanazt a jelet takarja.
Ezeket **nem detektáljuk külön, és nem mérjük külön** — egyszer mérjük
őket, a kanonikus nevükön. A szótár a felületen is látszik.

| Név | Ugyanaz, mint |
|---|---|
| bullish belt hold | `bullish_engulfing` |
| bearish belt hold | `bearish_engulfing` |
| bullish meeting line | `morning_star` |
| bearish meeting line | `evening_star` |
| tower bottom, fry pan bottom | `morning_star` |
| tower top, dumpling top | `evening_star` |
| advanced block | `shooting_star` |
| three stars in the south | `hammer` |

---

## 4. M3 — Váll-fej-váll (és fordított)

### Felismerés

**Váll-fej-váll (tető):** három egymást követő csúcs `P₁` (bal váll), `P₂`
(fej), `P₃` (jobb váll), és a közöttük lévő két völgy `T₁`, `T₂`:

- a fej a legmagasabb: `P₂ > P₁` és `P₂ > P₃`
- a vállak hasonlóak: `|P₁ − P₃| ≤ 0,5 · (P₂ − max(T₁, T₂))`
- előzetes emelkedés: a `P₁` előtti 20 napos hozam pozitív
- a **nyakvonal** a `T₁` és `T₂` völgyön átmenő egyenes, előre meghosszabbítva

**Fordított váll-fej-váll (alj):** tükörképe, völgyekkel és csúcsokkal.

### A négy érvényességi állapot — ez a legfontosabb

Mindegyik **külön esemény, saját felismerési nappal**, és külön mérődik.

| Állapot | Esemény napja | Mi történt addig | `dir` (tető) |
|---|---|---|---|
| `forming` | a `P₃` felismerésének napja (`P₃ + 5`) | a jobb váll kialakult, a nyakvonal ép | short |
| `broken` | az első nap, amikor a záróár a nyakvonal alá kerül, legfeljebb 40 nappal a `P₃` után | tiszta áttörés | short |
| `retested` | áttörés után legfeljebb 20 napon belül az első nap, amikor a csúcs a nyakvonaltól `0,5 · ATR`-en belülre visszaér, és a záróár alatta marad | áttörés **és** visszateszt — a spec szerint ez a „valid" | short |
| `failed` | ha 40 napig nincs áttörés, a 40. nap; ha előbb a záróár a fej fölé kerül, az a nap | a nyakvonal nem tört át | long |

A fordított váll-fej-vállnál minden irány megfordul.

**Miért `long` a `failed`?** Mert a tető elbukása azt jelenti, hogy az
előzetes emelkedés folytatódott. Azt mérjük, hogy a bukás után tényleg
folytatódik-e — ha ez sem jobb a baseline-nál, azt is tudni kell.

A felület a `forming` állapotnál kiírja, hogy a minta még nem érvényes.

---

## 5. Amit ez a dokumentum szándékosan nem tartalmaz

**Paraméter-változatokat.** Nem mérjük a pivotot 3, 5 és 8 napos ablakkal
egyszerre, és a tolerancia sem mozog. Aki sok változatot mér, az talál egy
nyertest — és az a véletlen lesz.

**Order blockot, M5-öt, M6-ot.** A spec az M7 részeként említi az order
blockot szigorúbb definícióval, és külön metodikaként a szerkezettörést és a
visszatesztet. Ezek a konfluencia-motor előtti lépések; egy következő
definíciós dokumentumban kerülnek rögzítésre, nem ebben.

**Kombinációkat.** Hogy a kalapács a támasznál ÉS emelkedő RSI mellett mennyit
ér, az a konfluencia-motor feladata (4. fázis). Itt egyetlen kontextust
mérünk: szinten vagy nem.
