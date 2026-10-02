# Eredménynapló — definíciók

**Rögzítve:** 2026-10-02, **mielőtt a hőtérkép, a görbe vagy a „What we got
wrong" lista egyetlen napot megmutatott volna.** Ekkor 2465 lezárt becslés
volt, mind az 5 napos horizonton.

A spec (03, 3.5) öt dolgot kér: kumulált metrikák baseline-nal, napi
hőtérkép a baseline-tól vett eltérés szerint, kumulált iránypontosság-görbe,
a legrosszabb becslések kereshető listája, és letöltés. Ami alább áll, az
mind a lezárt becslésekből (`outcomes/`) jön; új mérés nincs benne, csak a
meglévő sorok összesítése. Ezért p-érték is csak ott van, ahol eddig is volt
(a kumulált verdikt, `spec/06`).

---

## 1. Az egység: lezárási nap × horizont

Ugyanaz, mint a post-mortemnél (`postmortem-es-screener.md`, 1.): egy `d`
kereskedési nap és egy `h` horizont; azok a becslések tartoznak hozzá,
amelyeknek a célnapja `d`. Így a hőtérkép egy cellája és egy post-mortem
ugyanarról a becslés-halmazról beszél.

Csak kereskedési napok vannak benne: hétvégén és ünnepnapon nincs célnap.

## 2. A napi hőtérkép

**Érték:** a modell találati aránya mínusz a naiv baseline találati aránya,
**ugyanazokon a becsléseken**, százalékpontban.

**30 lezárt becslés alatt nincs érték** (2. sarokkő): a cella üres, és a
jelmagyarázat kimondja, miért.

**Sávok** (a határ a nagyobb eltérésű sávba tartozik: a +0,5 már enyhén jobb, a −5 már erősen rosszabb):

| Eltérés | Jelölés |
|---|---|
| ≤ −5 pp | rosszabb, erős |
| −5 … −2 pp | rosszabb |
| −2 … −0,5 pp | rosszabb, enyhe |
| −0,5 … +0,5 pp | azonos (a „Same” küszöbe, `CLAUDE.md`) |
| +0,5 … +2 pp | jobb, enyhe |
| +2 … +5 pp | jobb |
| ≥ +5 pp | jobb, erős |

A szín soha nem egyedüli jelentéshordozó: minden cellának van szöveges
címkéje (dátum, eltérés, darabszám), és a hőtérkép mellett táblázat is van.

**Nincs napi szignifikancia.** Egy nap nem bizonyíték; a hőtérkép azt mutatja,
hogyan oszlik el a kumulált eredmény a napok között, nem azt, hogy melyik nap
„számít”.

## 3. A kumulált iránypontosság-görbe

Horizontonként, a lezárási napok sorrendjében: a modell és a naiv baseline
**addigi összes** lezárt becslésének találati aránya. A görbe csak attól a
naptól kezdődik, amikor a kumulált darabszám eléri a **30-at**.

A görbe ugyanazokat a sorokat összesíti, mint a kumulált verdikt, ezért a
végpontja egyezik a kártyán látható számmal. A verdikt (és a p-érték) a
kártyáé; a görbe nem kap külön verdiktet.

## 4. „What we got wrong”

**Mi a „legrosszabb”:** a legnagyobb **Brier-pont** (`(p − y)²`, ahol `y` az
emelkedés 0/1-e). Ez a magabiztos tévedést bünteti a legjobban: egy 90%-os
„emelkedik”, ami esett, rosszabb, mint egy 55%-os.

**Hány:** horizontonként a **200** legnagyobb Brier-pontú becslés; egyenlő
pontnál az újabb célnap előbb. A lista a tickerre és a névre kereshető.

**Mi van egy sorban:** ticker, a becslés napja, a célnap, a horizont, a modell
emelkedési valószínűsége, a baseline valószínűsége ugyanarra a becslésre, a
tényleges hozam, és a két Brier-pont. Ha a papírt kivezették vagy
felfüggesztették, a sor ezt jelöli (`resolution_type`).

**A visszatartott becslés is benne van**, jelölve. A visszatartás nem mentesít
a mérés alól (`sokk-detektor.md`): ha kihagynánk, a lista épp azokat a
hibákat rejtené el, amelyekre a sokk-detektor figyelmeztetett. A szám a
lezárás után már nem befolyásolhat döntést, ezért itt látszik.

Nem lehet a legjobb becslések szerint rendezni: „What we got right” lista
nincs, mert az pont az a kiemelés, ami ellen a termék épül (ugyanaz az ok,
mint a post-mortemnél).

## 5. Letöltés

**Minden lezárt becslés, hónaponként** (a célnap hónapja szerint), CSV-ben és
Parquetben. Oszlopok: `forecast_id, instrument_id, ticker, session,
target_session, horizon, regime, model_family, model_version, withheld,
prob_up, baseline_prob, actual_return, hit, baseline_hit, brier,
baseline_brier, covered, resolution_type`.

Egy hónap fájlja csak akkor íródik újra, ha az elmúlt 7 napban került bele új
lezárás, vagy még nincs meg. A lezárt sor nem változik (`spec/06`), ezért a
régi hónapok fájljai véglegesek.

A letöltés a kapu mögött van, mint az egész app: az ingyenes adatforrások
miatt licencig csak a tulajdonos látja (`adatlicencek.md`). A publikus
lenyomatok (`manifests/`) ettől függetlenül bárki számára ellenőrizhetők.
