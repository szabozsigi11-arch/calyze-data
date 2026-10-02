# A deviza-modell, a deviza-rezsim és a deviza-mérés — előre rögzítve

**Rögzítve:** 2026-10-02, **mielőtt a deviza-modell egyetlen backtest-foldot
vagy élő becslést adott volna, és mielőtt a rezsim-címkéket megnéztük volna.**
Forrás: `docs/terv-6-fazis.md` (F3–F4), `docs/fx-univerzum.md`,
`tezis-kiertekeles.md` 11. fejezet. Ami nincs külön kimondva, az a
részvényes modellé, illetve a kripto-modellé (`kripto-modell.md`).

---

## 1. Rezsim

- **Dollár-index:** a hét dolláros pár napi log változásának átlaga, a dollár
  erősödése felé előjelezve (EURUSD, GBPUSD, AUDUSD, NZDUSD: −; USDCAD,
  USDCHF, USDJPY: +).
- **Volatilitás:** a dollár-index 20 napos realizált volatilitása.
- **Összefonódás:** a hét dolláros pár (dollár felé előjelezve) átlagos
  abszolút páronkénti korrelációja 60 napra.
- Bővülő percentilis, legalább **252** TARGET-nap előzménnyel;
  calm < 1/3, stressed ≥ 0,80.
- **Ellenőrzés (csak közöljük):** a stressed aránya 2008 októberében, 2015
  januárjában (a frank leválasztása) és 2020 márciusában; a calm aránya
  2017 második félévében.

## 2. Feature-ök

- **Technikai:** a részvényes lista, a fixálásból. Mivel naponta egy
  árfolyam van, **kimarad** a `volume_anomaly_20` (nincs volumen) és a
  `gap_1` (nyitó = záró, a napi hozam másolata lenne).
- **Keresztmetszeti:** `usd_ret_20` — a dollár-index 20 napos változása
  (minden párra ugyanaz az aznapi érték).
- **Makro:** a részvényes FRED-sorok, a fixálás napja **előtti** naptári
  nap utolsó ismert értékével (a 14:10 CET-es fixáláskor az aznapi amerikai
  adat még nincs meg), legfeljebb 5 napos előre töltéssel.
- **Kamatkülönbözet (carry):** **nem** feature. A tervben szerepelt, de a
  nem-amerikai rövid kamatok napi, ingyenes, hivatalos forrása nincs meg; ha
  lesz, új modellverzió lesz.
- **Rezsim:** a `stress` érték feature, a címke nem.

## 3. Modell és baseline

- **Család és verzió:** `lgbm-fx` `v1`; a részvényes beállítás
  `min_data_in_leaf = 100`-zal (mint kriptón; a panel kb. tizedrésze a
  részvényesnek).
- **Horizont:** 5, 20, 60 **TARGET-nap**; célváltozó: a log árfolyamváltozás
  fixálástól fixálásig.
- **Minimális múlt:** 300 nap. **Kalibráció:** az utolsó 252 TARGET-nap.
- **Baseline:** naiv és momentum (a részvényekével azonos szabállyal); a
  verdikt a naiv ellen szól. Piaci árazású baseline nincs.

## 4. Backtest

Purged walk-forward a részvényekével azonos ablakokkal (teszt 504, első
tanítás 756 TARGET-nap), a fold-küszöb **3 000** tanító és **1 000**
kalibrációs sor. Saját családban (`scope = fx`), saját FDR-rel.

## 5. Élő becslés

- Hétköznap 15:20 UTC-kor, az EKB közlése után, a legutóbbi fixálásra,
  mind a 28 párra, mindhárom horizonton.
- **Csak akkor élő, ha a fixálás után legfeljebb 6 órán belül készül**
  (`fx-univerzum.md`, 5.); a kimaradt nap nem pótolható.
- Csomag a privát tárba (`forecasts-fx/`), lenyomat a nyilvános repóba
  (`manifests-fx/`). Az élő rekord az első lenyomatolt naptól számít.
