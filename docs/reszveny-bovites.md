# A részvény- és ETF-univerzum bővítése (2026-10-19)

**Rögzítve, mielőtt egyetlen új papír árát lekértük volna.** A tulajdonos
kérése (2026-10-19): több papír; nem amerikai részvény nem kell.

## 1. Részvény: az S&P 1500

- **Forrás:** a Wikipédia „List of S&P 500 / 400 / 600 companies” lapjai,
  2026-10-19-i állapot (CC BY-SA). Csak a tagság, a név és a GICS-szektor
  kerül át; a lap nem árforrás.
- **Mi kerül be:** minden tag, ami még nincs az univerzumban. Szegmens: az S&P
  500 új tagja `sp500`, a MidCap 400 tagja `midcap`, a SmallCap 600 tagja
  `smallcap`.
- **Ha egy papír két listán szerepel** (index-átsorolás közben), a nagyobb
  indexé számít (500 → 400 → 600).
- **Részvényosztály-duplikátum:** ugyanannak a cégnek két osztályából egy
  marad, az „A” osztály (mint 2026-09-19-én: GOOGL, FOXA, NWSA). A cég
  azonosítása a SEC-azonosító (CIK), ahol a lap közli, egyébként a név
  osztály-jelölés nélkül.
- **A meglévő 600 részvény nem változik**, akkor sem, ha azóta indexet
  váltott: a kiesés jelölése (`valid_to`) külön, dátumozott döntés.
- **Nincs likviditási szűrő**: az S&P 600 tagsági szabálya már likviditást
  kér. Amelyik papírnak a modellhez kevés a múltja, arra a meglévő szabály
  szerint nincs becslés (a felület kiírja, miért).

## 2. ETF: kategóriánként egy

- **Név szerinti lista** (lent), kategóriánként a legnagyobb, legismertebb
  alap; egy kategóriából egy, hogy ne legyen duplikátum.
- **Kizárva:** tőkeáttételes és inverz alap, volatilitás-termék (beépített
  értékvesztésük miatt az irány előre „tudható”, ami szépítené a rekordot),
  és az egyetlen eszközt követő alap, ha az eszköz már bent van (például
  bitcoin-ETF a BTC mellett, deviza-ETF a devizapárok mellett).
- **Szűrés:** legalább 730 kereskedési nap múlt 2026-10-16-ig, és a 60 napos
  medián napi dollárforgalom legalább 5 millió dollár. Ami nem megy át,
  kimarad, és a jelentésben látszik.

| Kategória | ETF |
|---|---|
| Szektor | XLY, XLP, XLU, XLB, XLRE, XLC |
| Iparág | SMH, XBI, KRE, ITB, XOP, GDX, XME, XRT, IYT, ITA, IGV, TAN, ICLN, LIT, URA, KWEB |
| Ország és régió | EWJ, EWG, EWU, EWZ, INDA, FXI, EWT, EWY, EWC, EWA, EWW, EPOL, EWQ, EWL, EWI, EWP, EZA, TUR, EIDO, EWS, EWH, ECH, ARGT, VGK |
| Kötvény | SHY, TIP, AGG, MUB, EMB, BKLN |
| Nyersanyag | UNG, CPER, DBA, DBC, PPLT |
| Stílus és faktor | VTV, MTUM, USMV, QUAL, RSP, SCHD, MDY |

## 3. Azonosítók

`CZ00955`-től: előbb az S&P 500 új tagjai, aztán a MidCap 400, aztán a
SmallCap 600 (mindegyiken belül a ticker ábécérendjében), végül az ETF-ek a
fenti sorrendben. Egyszer kiadott azonosító soha nem kerül újra kiadásra.

## 4. Mérés

- Az új papírok élő rekordja az első saját becslésük napján indul.
- A részvényes mérési család ugyanaz marad (a tesztszám a szabályok és az
  időtávok száma, nem a papíroké); a modell az új papírokkal újratanul.
- **Túlélési torzítás:** a mai tagság; a múltban kiesett papírok hiányoznak.
