# Jelzés-definíciók — az indikátor-aréna alapja

**Rögzítve:** 2026-09-25. **Ez a dokumentum a mérés előtt készült.**

---

## Miért van ez a fájl, és miért nem módosul

Egy indikátor találati aránya nem az indikátor tulajdonsága. **A definícióé.**
Ha az RSI-jelzést úgy határozom meg, hogy „RSI < 30", más számot kapok, mint
ha úgy, hogy „RSI 30 alá esik, miután fölötte volt". Ha a mérés után
finomítanám a szabályt, addig csiszolhatnám, amíg a kívánt eredményt adja — és
a végeredmény nem mérés lenne, hanem válogatás.

Ezért: **a definíciók itt rögzülnek, a mérés előtt, és utólag nem
változnak.** Ha egy definíció rossznak bizonyul, nem átírjuk: új
definícióként vesszük fel, saját néven, és mindkettő mért eredménye látszik.

A fájl minden módosítása a git-történetben nyomon követhető. Ha egy szabály
a mérés után változna, az a commitból kiderül.

---

## Közös szabályok

Ezek minden jelzésre érvényesek.

**1. Mikor szól a jelzés.** A jelzés a kereskedési nap **záróárán** szól, a
záróárból számolva. Napon belüli adatot nem használunk — az 1. fázisban nincs
is.

**2. Mit mérünk.** A jelzés irányának találati arányát `h` kereskedési nap
múlva: emelkedett-e az ár a jelzés napjának zárásától a `h`-adik nap
zárásáig. Horizontok: **5, 20, 60 nap** — ugyanaz, mint a modellnél.

**3. Mihez mérjük.** Ugyanahhoz a **naiv baseline-hoz**, amihez a modellt: az
adott papír adott horizontjának feltétel nélküli emelkedési aránya ugyanazon
az időszakon. A kérdés nem az, hogy „az RSI-jelzés után emelkedett-e", hanem
hogy **gyakrabban emelkedett-e, mint egyébként**.

**4. Hozam vagy irány.** Az irányt mérjük, nem a hozam nagyságát. Az
iránytalálat összevethető a baseline-nal; a hozam nem, mert azt egyetlen nagy
kilengés eldönti.

**5. Ismétlődés-zár (cooldown).** Ha egy szabály feltétele több egymást követő
napon teljesül, **csak az első nap számít**. A zár addig tart, amíg a
feltétel meg nem szűnik. Enélkül egyetlen húzás húsz majdnem azonos
megfigyelést adna, és a mintaszám hazudna.

**6. Minimális előzmény.** Egy papír csak akkor kerül be, ha a jelzés napján
legalább **252 kereskedési napnyi** előzménye van. A 200 napos átlagokhoz
ennyi kell, és így minden szabály ugyanazon a halmazon mér.

**7. Mintaszám-küszöb.** 30 megfigyelés alatt nincs százalék, ugyanúgy, mint
mindenhol máshol. Az **effektív** mintaszám számít: az átfedő ablakok miatt
a nyers darabszám túl kedvező képet adna.

**8. Többszörös összehasonlítás.** Minden szabály minden horizonton mérve
tucatnyi összehasonlítás. FDR-korrekció (Benjamini–Hochberg) nélkül a puszta
véletlen is adna „szignifikáns" találatot.

---

## A túlélési torzítás — amit előre ki kell mondani

**Az univerzumunk a MAI papírokból áll.** Ami 2010-ben csődbe ment vagy
kivezették, az nincs benne. Ez felfelé torzítja **minden** hosszú távú
mérést: a történelem azon szereplőit nézzük, akik túlélték.

Ez a torzítás **a baseline-t és a jelzést egyformán érinti** — mindkettő
ugyanazon a halmazon mérődik —, tehát a kettő *különbsége*, ami az arénában
szerepel, sokkal kevésbé torzított, mint az abszolút találati arány.

Ettől még: az abszolút számok mellett ott lesz, hogy túlélési torzítást
tartalmaznak. Nem hallgatjuk el, és nem is javítjuk fel: a delistelt papírok
adatához nincs ingyenes forrásunk.

---

## A szabályok

Minden szabály neve állandó azonosító. A `dir` a jelzés iránya: `long` =
emelkedést vár, `short` = esést.

### Lendület-követő szabályok

| Azonosító | Feltétel a `t` nap zárásán | `dir` | Zár feloldása |
|---|---|---|---|
| `macd_cross_up` | a MACD-vonal (12/26) a `t-1` napon a szignál (9) alatt volt, `t`-n fölötte | long | amíg a MACD a szignál alá nem kerül |
| `macd_cross_down` | fordítva | short | amíg a MACD a szignál fölé nem kerül |
| `golden_cross` | az 50 napos SMA `t-1`-en a 200 napos alatt, `t`-n fölötte | long | amíg az 50 a 200 alá nem kerül |
| `death_cross` | fordítva | short | amíg az 50 a 200 fölé nem kerül |
| `close_above_ema200` | a záróár `t-1`-en a 200 napos EMA alatt, `t`-n fölötte | long | amíg a záróár az EMA alá nem kerül |
| `close_below_ema200` | fordítva | short | amíg a záróár az EMA fölé nem kerül |

### Visszatérés-váró (mean reversion) szabályok

| Azonosító | Feltétel a `t` nap zárásán | `dir` | Zár feloldása |
|---|---|---|---|
| `rsi_oversold` | az RSI-14 `t-1`-en 30 fölött, `t`-n 30 alatt | long | amíg az RSI 30 fölé nem kerül |
| `rsi_overbought` | az RSI-14 `t-1`-en 70 alatt, `t`-n 70 fölött | short | amíg az RSI 70 alá nem kerül |
| `bollinger_lower` | a záróár a 20/2 Bollinger-szalag alsó széle alatt | long | amíg a záróár a szalagba vissza nem kerül |
| `bollinger_upper` | a záróár a felső szél fölött | short | amíg a záróár a szalagba vissza nem kerül |

### Kereszt-metszeti szabály

| Azonosító | Feltétel a `t` nap zárásán | `dir` | Zár feloldása |
|---|---|---|---|
| `momentum_top_decile` | a 12-1 hónapos momentum az univerzum felső tizedében | long | amíg ki nem esik a felső tizedből |

A 12-1 hónapos momentum az utolsó hónapot kihagyja (a rövid távú
visszafordulás miatt) — ez az akadémiai irodalom bevett definíciója.

### Forgalmi szabály

| Azonosító | Feltétel a `t` nap zárásán | `dir` | Zár feloldása |
|---|---|---|---|
| `volume_spike_up` | a forgalom a 20 napos mediánjának legalább háromszorosa, ÉS a napi hozam pozitív | long | a következő nap, ha a feltétel nem teljesül |

---

## Amit szándékosan nem mérünk (még)

**Paraméter-változatokat.** Nem mérjük az RSI-t 10, 14, 20 és 30 napos
ablakkal egyszerre. Aki sok paraméterváltozatot mér, az előbb-utóbb talál egy
nyertest — és az a nyertes a véletlen lesz. Egy szabály, egy bevett
paraméter, ami a tankönyvekben szerepel.

**Kombinációkat.** Az „RSI < 30 ÉS a trend emelkedő" típusú összetételek a
konfluencia-motorba tartoznak (4. fázis), ahol az FDR-korrekció a
kombinációk számához igazodik.

**Stop-loss és pozícióméret hatását.** Az aréna az irányt méri, nem egy
kereskedési stratégiát. Aki stratégiát mér, az a stopot méri, nem az
indikátort.
