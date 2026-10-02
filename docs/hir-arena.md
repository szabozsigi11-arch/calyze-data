# Hír-aréna — definíció

**Rögzítve:** 2026-10-02. **Ez a dokumentum a mérés előtt készült.**

A hírrendszer minden „fontos nap” jelzése egy előrejelzés: azt állítja, hogy
a következő napokban nagyobb lesz a mozgás a szokásosnál (`spec/07`, 4.
fejezet). Ez az aréna azt méri, igaz-e. Külső hírforrás nem kell hozzá: a
saját jelzéseinket mérjük.

A sokk-jelek mércéje a mérés előtt, a 3. fázisban rögzült
(`sokk-detektor.md`, 4. fejezet); ez a dokumentum azt pontosítja, és
hozzáteszi a naptári jelzést.

---

## 1. Közös mérce

- **Realizált volatilitás a jelzés után:** a jelzés napja (`S`) utáni 5
  kereskedési nap napi log teljes hozamainak szórása.
- **Előtte:** `σ20`, az `S` napot **megelőző** 20 napi log teljes hozam szórása
  (az `S` nap nélkül: a jelzés előtti állapot, ahogy a detektor is számolja,
  és ahogy a `sokk-detektor.md` „jelzés előtti `σ20`”-a mondja).
- **Találat:** a jelzés utáni volatilitás nagyobb, mint `σ20`.

## 2. Papír-szintű sokk-jel (volumen, rés, elmozdulás)

- **Jelzett papír-nap:** ahol a `sokk-detektor.md` 1. fejezetének papír-jelei
  közül legalább egy szólt.
- **Baseline** *(pontosítás a mérés előtt)*: **ugyanazon a napon** a jelzés
  nélküli papírok találati aránya. A „jelzés nélküli papír-napok, ugyanabban
  az időszakban” (`sokk-detektor.md`) így a legszűkebb értelmében áll: a
  piac aznapi általános idegessége a két oldalt egyformán érinti, és nem
  fújja fel a jelzés eredményét.
- A mérés papír-naponként párosít (a jelzett sor ↔ az aznapi baseline-arány),
  és napokra blokkolt bootstrapet használ, mint minden aréna.

## 3. Piaci sokk-jel és visszatartás

- **Piaci sokk-nap:** ahol a VIX-ugrás vagy a keresztpiaci jel szólt.
  Találat: a SPY következő 5 napjának volatilitása nagyobb a SPY `σ20`-ánál.
  Baseline: ugyanez az arány a piaci jel nélküli napokon, ugyanabban az
  időszakban.
- **Visszatartás jogos**, ha a SPY következő 5 napi volatilitása legalább
  **1,5-szerese** `σ20`-nak (`sokk-detektor.md`, 4.). Baseline: ugyanez az
  arány a nem visszatartott napokon.

## 4. Naptári jelzés (új)

- **Jelzett nap:** az `S` kereskedési nap, ha a következő kereskedési napra
  hivatalos esemény esik (`naptar.md`: FOMC, EKB, CPI, NFP).
- Találat a SPY-on, mint a piaci jelnél. Baseline: a naptári jelzés nélküli
  napok, ugyanabban az időszakban (2026-tól, amióta a naptár lefed).
- Eseményfajtánként is külön, ha a fajtának van legalább 30 lezárt napja;
  addig „Too early”.

## 5. Élő és backtest

- **Élő:** a ténylegesen lenyomatolt jelzések (a becslés-csomag sokk- és
  naptár-mezői) — 2026-09-26-tól.
- **Backtest:** a sokk-jeleket az árakból a teljes múltra újraszámoljuk,
  **ugyanazzal a szabállyal** (teszt nézi, hogy a vektoros számítás napra
  pontosan ugyanazt adja, mint a napi detektor). A felületen külön, jelölve:
  a backtest nem bizonyíték.

## 6. Korrekció és verdikt

Benjamini–Hochberg a hír-aréna teljes családján (jelzésfajta × élő/backtest
külön családként). A verdikt a szokásos: 30 alatt „Too early”, ±0,5 pont a
„Same” sávja.

## 7. Amit nem mér

- Irányt: a jelzés nem mond irányt, és nem is mérjük úgy.
- Híreket: a hivatalos közlemények címkék, nem jelzések.
