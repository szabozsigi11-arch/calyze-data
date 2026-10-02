# Modell-aréna — definíció

**Rögzítve:** 2026-10-02. **Ez a dokumentum a mérés előtt készült.**

Az `lgbm-core` mellé három modellcsalád kerül (`spec/06`, 4. fejezet). A cél
nem az, hogy a legjobbat kiválasszuk és a helyére tegyük, hanem hogy
kiderüljön: számít-e egyáltalán, milyen modellt használunk — vagy mind
ugyanott áll, a naiv baseline körül.

---

## 1. A családok

Mindegyik **ugyanazt** adja horizontonként (5, 20, 60 nap): egy pontbecslést a
log teljes hozamra. Az irány-valószínűséget és a 90%-os sávot **ugyanaz a
csomagolás** állítja elő mindegyikből, mint az `lgbm-core`-nál: split
conformal sáv a volatilitással normalizált hibákból, és izotón kalibráció, a
kalibrációs ablak két, egymást nem fedő felén (`pipeline/model/predictor.py`).
Így a négy család kimenete ugyanabban a formában, ugyanazzal a módszerrel
mérhető, és csak a pontbecslés módja különbözik.

| Család | Verzió | Mi | Bemenet |
|---|---|---|---|
| `lgbm-core` | v1 | LightGBM (a meglévő, a felület fő modellje) | a feature-tábla |
| `ar-linear` | v1 | **statisztikai kontroll**: ridge-regresszió (λ = 1,0) a horizont hozamára | `ret_1`, `ret_5`, `ret_20`, `ret_60`, `vol_20` |
| `mlp-core` | v1 | **neurális háló**: két rejtett réteg (64, 32 neuron, ReLU), Adam, korai leállás (a tanító sorok 10%-án), legfeljebb 50 kör | ugyanaz a feature-tábla, mint az `lgbm-core`-é |
| `ensemble` | v1 | a három fenti pontbecslés **egyenlő súlyú** átlaga (⅓ – ⅓ – ⅓) | a három család kimenete |

**Közös szabályok:**

- a tanító és a kalibrációs ablak ugyanaz, mint az `lgbm-core`-nál (az utolsó
  252 session a kalibrációé), és ugyanaz a ritkítás (`train_stride`);
- a hiányzó értéket a lineáris és a neurális modell a tanító ablak
  mediánjával tölti ki, és a bemenetet a tanító ablak átlagával és szórásával
  standardizálja (a LightGBM a hiányt maga kezeli);
- a neurális modell a tanító sorok közül legfeljebb 300 000-et használ,
  rögzített véletlen mintával (seed 7) — a futásidő így korlátos;
- minden család hetente tanul újra, mint az `lgbm-core` (a család nem
  változik, csak az adat: `spec/06`, 4.).

**Miért nem N-BEATS vagy PatchTST?** A spec ezeket nevezi meg. Mindkettőhöz
egy nagy mélytanulási könyvtár és nyers idősor-ablakok kellenének, ami az
ingyenes, processzoros futtatásban lassú és törékeny. A neurális háló itt
ugyanazt a bemenetet kapja, mint a LightGBM — így a kérdés tiszta: a
modell*típus* számít-e, azonos információ mellett.

---

## 2. Élő mérés

- **Indul:** minden új család az első lenyomatolt becslése napján, nulláról.
  Visszamenőleges „élő” rekord nincs (`spec/06`, 10.).
- **A becslések külön csomagba kerülnek** (`forecasts-arena/`), saját
  lenyomattal a nyilvános manifestben, ugyanúgy, mint a fő csomag. A fő
  csomagot (és mindent, ami rá épül) ez nem érinti.
- **Kiértékelés:** ugyanazok a metrikák, mint az `lgbm-core` élő rekordjánál:
  irány-találati arány és Brier-pontszám a naiv baseline-hoz, sáv-lefedettség
  a névleges 90%-hoz.
- **Egymás ellen:** minden új család az `lgbm-core` ellen is, **párosítva**
  (ugyanaz a papír, ugyanaz a nap, ugyanaz a horizont), irány-találatban és
  Brier-pontszámban.
- **Korrekció:** Benjamini–Hochberg a modell-aréna teljes családján
  (család × horizont × metrika × összevetés).
- **Ha egy család egy napon nem tud becsülni** (a tanítás vagy a becslés
  elbukik), az a nap nála „not available”, utólag nem pótoljuk.

## 3. Backtest

Ugyanaz a purged walk-forward, mint az `lgbm-core`-nál (`pipeline/model/backtest.py`),
minden családra. A felületen **mindig külön, „backtest” jelöléssel**, és
soha nem keveredik az élő számmal: *„This is a backtest. Backtested results
are not evidence.”*

## 4. Idővonal

Minden családváltozás (új család, új verzió) dátummal az aréna idővonalán.
Egy rossz verzió eredményei nem törölhetők.
