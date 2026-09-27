# Minta-definíciók, 2. rész — M1, M4, M5, M6, M9

**Rögzítve:** 2026-09-27. **Ez a dokumentum a mérés előtt készült.**

Az első rész (`minta-definiciok.md`) szabályai itt is érvényesek, változás
nélkül: a pivot `K = 5` napos ablakkal, **felismerhető a `p + 5`. napon**; az
ATR a `t − 1` napig számolt 14 napos Wilder-ATR; az esemény dátuma a
felismerés napja, és a kimenetel attól mérődik; ismétlődés-zár: ugyanaz a
szabály ugyanazon a papíron 5 napon belül csak egyszer számít; mérés 5, 20 és
60 napos horizonton, a naiv baseline-hoz, effektív mintaszámmal.

**A tesztelt család.** Az itt leírt szabályok ugyanabba a családba kerülnek,
mint az első rész szabályai, és a Benjamini–Hochberg-korrekció a *teljes*
minta-családon fut. Ettől az első rész eredményei sem lesznek kedvezőbbek:
egy nagyobb családban a korrekció csak szigorúbb lehet.

**A paraméterek nem mozognak.** Minden alábbi szám egyetlen érték. Ha egy
definíció rossznak bizonyul, új néven vesszük fel, és mindkettő eredménye
látszik.

---

## 1. M5 — Szerkezettörés (BOS) és karakterváltás (ChoCh)

**Szerkezet a `t` napon:** a `t`-ig felismert csúcsok közül a legutóbbi kettő
(`H₀`, `H₁`, időrendben) és a völgyek közül a legutóbbi kettő (`L₀`, `L₁`).

- **emelkedő**, ha `H₁ > H₀` és `L₁ > L₀`
- **csökkenő**, ha `H₁ < H₀` és `L₁ < L₀`
- **semleges** minden más esetben (és ha nincs még két-két pivot)

**Törés felfelé:** az első nap, amikor a záróár a legutóbbi felismert csúcs
(`H₁`) fölé kerül. Egy csúcs egyszer törhető. A szerkezetet a törés napja
ELŐTTI állapotból olvassuk (a mai napot nem számítva).

| Szabály | Mikor | `dir` |
|---|---|---|
| `structure_break_up` | minden felfelé törés | long |
| `structure_break_up\|bos` | emelkedő szerkezetben (folytatás) | long |
| `structure_break_up\|choch` | csökkenő szerkezetben (karakterváltás) | long |
| `structure_break_up\|neutral` | semleges szerkezetben | long |

A lefelé törés (`structure_break_down`) a tükörképe: a záróár a legutóbbi
felismert völgy alá kerül, `dir` short, ugyanazzal a három bontással.

---

## 2. M6 — Kitörés és visszateszt

Az M7 szintjeire épül (első rész, 2. fejezet), változatlan szabályokkal.

**Kitörés:** az a nap, amikor egy élő szint lejár, mert a záróár `1 · ATR`-rel
átlépte (ez az M7 lejárati szabálya — a kitörés és a lejárat ugyanaz az
esemény).

- `breakout_up`: ellenállás fölé → long
- `breakout_down`: támasz alá → short

**A kitörés utáni 20 napban** (a kitörés napja után) az alábbiak közül az
első, ami bekövetkezik — legfeljebb egy:

| Szabály | Mikor (felfelé kitörésnél) | `dir` |
|---|---|---|
| `breakout_up_retest` | a mélypont a szinttől `0,5 · ATR`-en belülre visszaér, a záróár a szint fölött marad | long |
| `breakout_up_failed` | a záróár a szint alá kerül (hamis kitörés) | short |

A lefelé kitörés (`breakout_down_retest`, `breakout_down_failed`) a
tükörképe. Ha 20 napig egyik sem történik, nincs esemény.

---

## 3. M1 — Fibonacci-visszaesés

**Felfelé impulzus:** egy felismert csúcs `H`, és az előtte lévő legutolsó
felismert völgy `L` (`L` napja < `H` napja). Csak akkor impulzus, ha
`H − L ≥ 3 · ATR` (az ATR a `H` napján).

**Visszaesés:** a `H` utáni első felismert völgy `R`. Az esemény napja `R`
felismerésének napja (`R + 5`). **Nincs esemény**, ha a `H` napja és az
esemény napja között bármelyik záróár `H` fölé került (az impulzus
folytatódott, nem visszaesés volt). Ez az ellenőrzés mind a négy változatnál
a `H` pivot kanóc-csúcsához mér, mert a folytatás ténye nem függ attól, honnan
húzzuk a szinteket. *(Pontosítás a mérés előtt, 2026-09-27: az első
változatból nem derült ki, melyik árhoz.)*

**Mélység:** `d = (H − R) / (H − L)`, a változat szerinti árakkal (lent).

| Zóna | Mélység |
|---|---|
| `shallow` | `d < 0,382` |
| `z382` | `0,382 ≤ d < 0,5` |
| `z500` | `0,5 ≤ d < 0,618` |
| `golden` | `0,618 ≤ d < 0,786` (a forrás „arany zónája”) |
| `invalid` | `d ≥ 0,786` (a forrás szerint a szerkezet érvénytelen; a `L` alá esés is ide tartozik) |

**A négy változat** — a forrás szerint vitatott, honnan hova húzzuk, ezért
mind a négyet külön mérjük. A pivotot mindig a kanóc (high/low) jelöli ki; a
változat csak azt mondja meg, melyik árral számolunk:

| Változat | `L` és `R` ára | `H` ára |
|---|---|---|
| `wick` | a gyertya mélypontja (low) | a gyertya csúcsa (high) |
| `body` | a test alja, `min(o, c)` | a test teteje, `max(o, c)` |
| `wick_body` | low | `max(o, c)` |
| `body_wick` | `min(o, c)` | high |

**Szabályok:** `fib_up_<zóna>|<változat>`, `dir` long (a trend folytatását
mérjük). A lefelé impulzus (`fib_down_…`, csúcs → völgy → visszapattanás) a
tükörképe, `dir` short. 5 zóna × 4 változat × 2 irány = 40 szabály.

**Szándékosan nem mérjük** a −27%-os és a 127,2%-os szintet: ezek célárként
használatosak, a termék pedig célárat nem ad (`spec/08`, 5. fejezet).

---

## 4. M4 — Top-down: havi, heti, napi egyezés

**Heti és havi gyertyák** a napiakból: nyitó az első nap nyitója, záró az
utolsó nap záróára, csúcs és mélypont a szélső értékek. Hét: péntekkel záruló
naptári hét; hónap: naptári hónap. **Egy heti vagy havi gyertya csak a lezárása
UTÁNI első kereskedési naptól használható.**

**Pivot a heti és a havi idősíkon:** `k = 2` gyertyás ablakkal (egy csúcs a
két előtte és két utána lévő gyertyánál magasabb), felismerhető a `p + 2`.
gyertya lezárása után. A napi idősíkon a szokásos `K = 5`.

**Irány idősíkonként:** az M5 szerkezet-szabálya (két-két utolsó felismert
pivot): emelkedő, csökkenő vagy semleges.

**Egyezés:** mindhárom idősík emelkedő (`topdown_up`) vagy mindhárom csökkenő
(`topdown_down`). **Az esemény az egyezés első napja** (előző nap még nem volt
egyezés), az ismétlődés-zárral.

**Kiterjedés** (a forrás árnyalata: magasan álló piacon várni kell): a napi
legutóbbi felismert völgy `L` és csúcs `H` között hol áll a záróár.
Emelkedőnél `e = (c − L) / (H − L)`, csökkenőnél `e = (H − c) / (H − L)`.

| Szabály | Mikor | `dir` |
|---|---|---|
| `topdown_up` | minden emelkedő egyezés | long |
| `topdown_up\|ext_low` | `e ≤ 0,5` | long |
| `topdown_up\|ext_high` | `e > 0,5` | long |

A `topdown_down` a tükörképe, `dir` short. Ha `H ≤ L`, csak az összesített
szabály kap eseményt.

A 4 órás idősík nincs benne: ingyen nem érhető el elég mély múlttal, és a
termék napon belüli idősíkon nem mér (`spec/08`, M4).

---

## 5. M9 — Trendvonal

**Emelkedő trendvonal:** két egymást követő felismert völgy `L₁`, `L₂`
(időrendben szomszédosak a völgyek sorában), ha `L₂ > L₁`. Az egyenes a két
völgy mélypontján megy át, előre meghosszabbítva. **A vonal `L₂`
felismerésétől él**, és 252 kereskedési nap után (az `L₂` napjától) törés
nélkül lejár.

**Érintés:** a `t` napon a mélypont a vonaltól `0,5 · ATR`-en belül van, és a
záróár a vonal fölött marad; két érintés között legalább 5 nap. A két alkotó
völgy az 1. és a 2. érintés.

**Törés:** az első nap, amikor a záróár `1 · ATR`-rel a vonal alá kerül (ugyanaz
a küszöb, mint a szintek lejáratánál). Egy vonal egyszer törhet.

| Szabály | Mikor | `dir` |
|---|---|---|
| `trendline_up_break` | minden törés | short |
| `trendline_up_break\|touches_2` | csak a két alkotó völgy érintette | short |
| `trendline_up_break\|touches_3` | három érintés | short |
| `trendline_up_break\|touches_4+` | négy vagy több | short |

A csökkenő trendvonal (`trendline_down_break`, két egymást követő, csökkenő
csúcson át; törés felfelé) a tükörképe, `dir` long.

---

## 6. Amit ez a dokumentum szándékosan nem tartalmaz

- **Kombinációkat.** Hogy a Fibonacci arany zónája egy támasznál ÉS
  top-down egyezés mellett mennyit ér, az a konfluencia-motor dolga; annak
  saját, előre rögzített definíciója lesz (`konfluencia.md`).
- **Order blockot.** A spec az M7 szigorúbb változataként említi; nincs olyan
  definíciója, amit a forrásokból egyértelműen rögzíteni tudnánk.
- **Paraméter-változatokat** (más pivot-ablak, más ATR-szorzó). A Fibonacci
  négy változata nem paraméter-hangolás, hanem a spec kifejezett kérése: a
  forrás maga mondja, hogy vitatott.
