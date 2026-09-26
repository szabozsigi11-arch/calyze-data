# Post-mortem és screener — definíciók

**Rögzítve:** 2026-09-26, **mielőtt egyetlen post-mortem elkészült volna.**

---

## 1. Mikor „rossz" egy nap

A „rossz nap" küszöbét előre kell kimondani. Ha utólag választanánk meg,
azt választhatnánk, amelyik a legkevesebb kellemetlen jelentést adja.

**Lezárási nap:** egy `d` kereskedési nap és egy `h` horizont. Azok a
becslések tartoznak hozzá, amelyeknek a célnapja `d`, a horizontja `h`.

**Rossz a nap, ha:**
- legalább **30** becslés zárult le rajta ezen a horizonton, és
- a modell találati aránya legalább **5 százalékponttal** alacsonyabb, mint
  a baseline-é **ugyanezeken a becsléseken**.

Nincs p-érték és nincs szignifikancia: a post-mortem **nem bizonyíték
semmire**, hanem egy nap leírása. Egy rossz nap nem mondja meg, hogy a modell
rossz — azt a verdict mondja meg, sok nap alapján. Ezt a felület ki is írja.

Ha egy nap a baseline-nál JOBB volt, arról nem készül „jó nap"-jelentés. A
spec ezt nem kéri, és egy ünneplő jelentés pont az, ami ellen a termék épül.

---

## 2. Mit ír le a post-mortem (spec/06, 7. fejezet)

Minden szám a lementett becslésekből és a kiértékelt kimenetelekből jön, és
semmi nincs benne, amit nem mértünk.

1. **Hány becslés, hány jött be, mennyi volt a baseline.**
2. **Mi a közös a hibákban — szektor.** Azt a szektort nevezzük meg, ahol a
   hibák aránya a legjobban meghaladja a szektor arányát az összes lezárt
   becslésben. Csak akkor, ha legalább **5** hiba esik bele, és a többlet
   legalább **10 százalékpont**. Ha egyik szektor sem ilyen, azt írjuk:
   egyik szektor sem emelkedik ki. Nem keresünk mintázatot ott, ahol nincs.
3. **Mi a közös a hibákban — irány.** A hibás becslésekből hány várt
   emelkedést és hány esést.
4. **Mi a közös a hibákban — rezsim.** A becslés napjának rezsimje, ahogy a
   csomagban lementődött.
5. **A piaci kontextus.** Az összes lezárt papír tényleges hozamának mediánja
   a becslés napjától a célnapig, és hogy hányan emelkedtek.
6. **Hír és sokk.** A hírrendszer a 3. fázisban épül. Addig a jelentés ezt
   mondja: *hírt és sokkot a Calyze még nem figyel* — nem hallgatja el, hogy
   ez hiányzik.

**Nyelvezet:** tényközlő, önostorozás és mentegetőzés nélkül (spec/06). A
generált szövegen futásidőben is átmegy a szólista; ha tiltott kifejezés
kerülne bele, a felület egy csak számokat tartalmazó sablonra esik vissza,
és ezt naplózza (spec/10, 4.).

---

## 3. A screener rendezése

**Alapértelmezett rendezés: ahol a kalibrációnk a legjobb** (spec/02 F3).

**Kalibráció-minőség egy papíron:** a Brier-készség a naiv baseline-hoz,
`1 − Brier(modell) / Brier(baseline)`, az adott papír összes lezárt
becslésén, minden horizonton együtt. **Legalább 30 lezárt becslés kell**; ennél
kevesebbnél a papír „nincs még elég adat" jelölést kap, és a rangsorolt
papírok után, betűrendben áll.

**Amíg egyetlen papírnak sincs 30 lezárt becslése, nincs rangsor:** a
screener betűrendben mutat, és kiírja, miért. Nem találunk ki helyette
másik sorrendet.

**Ami szerint NEM lehet rendezni:** az emelkedés becsült valószínűsége, a
várt hozam, a sáv közepe. Ha egy kattintással ezek szerint lehetne, a
táblázat egy „legjobb papírok" listává válna — pont ezt tiltja a spec
(08, 5.: *nem rangsorol instrumentumokat „lehetőség" szerint*) és a
piacvisszaélési óvatosság (10, 5b: *a screener rendezése a kalibráció
minősége, nem a várt hozam*).

**Megengedett rendezések:** kalibráció-minőség, ticker, szektor, a lezárt
becslések száma.
