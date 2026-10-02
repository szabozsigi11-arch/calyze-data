# A kripto-modell, a kripto-rezsim és a kripto-mérés — előre rögzítve

**Rögzítve:** 2026-10-02, **mielőtt a kripto-modell egyetlen backtest-foldot
vagy élő becslést adott volna, és mielőtt a rezsim-címkéket megnéztük volna.**
Forrás: `docs/terv-5-fazis.md` (E3), `spec/06` (a protokoll minden
eszközosztályra ugyanaz), `docs/kripto-univerzum.md`, `tezis-kiertekeles.md`
10. fejezet (a nap UTC 00:00–24:00).

Ami itt nincs külön kimondva, az **szóról szóra a részvényes modellé**
(`pipeline/model/config.py`, `predictor.py`, `baselines.py`, `split.py`).

---

## 1. Rezsim (calm / normal / stressed)

Ugyanaz a felépítés, mint a részvényeknél (`pipeline/features/regime.py`),
más kosárral:

- **Volatilitás:** a BTC 20 napos realizált volatilitása.
- **Összefonódás:** a kosár napi hozamainak átlagos **abszolút** páronkénti
  korrelációja 60 napra.
- **Kosár (szabály, nem kézi választás):** a kripto-univerzum rangsorában
  (`instruments_crypto.csv`) az első 10 olyan papír, amelynek Yahoo-múltja
  2017-12-31-ig elkezdődik: **BTC, ETH, XRP, BNB, ZEC, DOGE, ADA, TRX, LINK,
  LTC**.
- **Bővülő percentilis**, legalább **365 nap** előzménnyel (a részvényeknél
  252 session — ugyanaz az egy év, naptári napban).
- `stress = (vol_pct + corr_pct) / 2`; calm < 1/3, stressed ≥ 0,80.

**Ellenőrzés (csak közöljük, nem hangolunk utána):** a stressed címke
aránya 2020 márciusában, 2022 május–júniusában és 2022 novemberében; a calm
aránya 2023 első félévében. Ha nem az, amit vártunk, azt kiírjuk, és a
definíció **nem** változik visszamenőleg.

## 2. Feature-ök

- **Technikai:** a részvényekével azonos lista (`technical.py`), a kripto
  záróárából (osztalék nincs). Az évesítés szorzója (√252) változatlan: a
  sáv a napi szórásból × √h-ból áll, a szorzó kiesik, a fa-modellnek pedig
  skálafüggetlen.
- **Keresztmetszeti** (az aznapi értékekből): `breadth_50` (a
  kripto-papírok hány százaléka van az 50 napos EMA felett) és `btc_rel_20`
  (a papír 20 napos hozama mínusz a BTC-é; a BTC-nél nulla). Szektor nincs.
- **Makro:** a részvényes modell FRED-sorai (VIX, változása, 10 éves hozam,
  hozamgörbe, dollár), a kripto-napra **a nap végén már ismert utolsó
  értékkel** (legfeljebb 5 napos előre töltés; hétvégén a pénteki).
- **Rezsim:** a `stress` érték feature, a címke nem.

## 3. Modell

- **Család és verzió:** `lgbm-crypto` `v1`. Ugyanaz a LightGBM-beállítás,
  egyetlen eltéréssel: `min_data_in_leaf = 100` (a panel a részvényesnek kb.
  huszadrésze; az 500 a hosszú horizonton szinte üres fákat adna). Más
  hangolás nincs.
- **Horizont:** 5, 20, 60 **nap** (naptári nap = kereskedési nap).
- **Célváltozó:** log hozam a nap zárásától a h-adik nap zárásáig.
- **Minimális múlt:** 300 nap.
- **Kalibráció:** az utolsó **365 nap** (a részvényeknél 252 session).
- **Sáv és valószínűség:** split conformal + izotón kalibráció, mint a
  részvényeknél; névleges lefedettség 90%.

## 4. Baseline-ok

- **naiv** (a tanító ablak alap találati aránya és átlagos hozama) és
  **momentum** (a 20 napos irány szerinti mért esély), a részvényekével
  azonos szabállyal.
- **Szektor-baseline nincs** (nincs szektor), **piaci árazású baseline
  nincs** (nincs megbízható ingyenes opciós lánc); a felület ezt kimondja.
- A verdikt a **naiv** ellen szól (mint a részvényeknél a főverdikt), a
  momentum külön sor.

## 5. Backtest

Purged walk-forward, a részvényekével azonos szabállyal, kripto-méretekkel:

- teszt-ablak **730 nap**, az első fold előtt legalább **730 nap**
  tanítás; purge és embargo h nap;
- egy fold akkor fut, ha legalább **3 000** tanító és **1 000** kalibrációs
  sor van (a részvényeknél 10 000 / 1 000; a korai kripto-panelben kb. 15
  papír van);
- a mérési rekordok **külön családban** (`scope = crypto`), saját
  FDR-korrekcióval; a részvényekével soha nem keverednek.

## 6. Élő becslés és lenyomat

- Naponta **00:30 UTC** után, az előző (lezárt) UTC-napra, minden aktív
  kripto-papírra, mindhárom horizonton.
- **Legfeljebb 6 órával a nap zárása (24:00 UTC) után.** A kripto közben is
  kereskedik: egy később elkészülő becslés ablakának egy része már lezajlott,
  és bár a modell csak a zárásig lát, a késői lenyomat utólagos válogatásnak
  látszhatna. Ami 6 órán belül nem készül el, az a nap kimarad, és **nem
  pótoljuk** (kiegészítés, rögzítve 2026-10-02-án, az első élő becslés előtt).
- A becslés-csomag a privát tárba (`forecasts-crypto/`), a lenyomata (hash
  és darabszám) a nyilvános repóba (`manifests-crypto/`), commit–reveal,
  mint a részvényeknél. **Az élő rekord az első lenyomatolt naptól számít**;
  a backtest külön, jelölve.
- Sokk- és naptári jelölés a kriptón E5-ben jön; addig a becslés nem kap
  ilyen jelölést, és ez a csomagban is ki van mondva.
