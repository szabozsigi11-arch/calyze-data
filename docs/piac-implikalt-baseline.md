# Piac-implikált baseline — definíció

**Rögzítve:** 2026-09-26, **a mérés előtt.** Forrás: spec/06 2. fejezet,
spec/05 2.1b.

---

## 0. Amit ez a szám jelent — és amit nem

Az opciós árakból kiolvasható valószínűség **kockázatsemleges**. Azt árazza,
mennyit ér egy fogadás az emelkedésre, de nem tartalmazza azt a többlethozamot,
amit a befektetők a kockázat vállalásáért elvárnak. Ezért **rendszeresen
alacsonyabb esélyt mutat az emelkedésre, mint a valóság.**

A felület ezt a számot így nevezi: *„a piac által árazott valószínűség"*, és
mellé kiírja, hogy kockázatsemleges. Soha nem írja, hogy „a piac szerint ennyi
az esély".

---

## 1. Módszer: a két szomszédos call ára

A legegyszerűbb képlet (Black–Scholes, egyetlen volatilitással, a mostani áron)
a valószínűséget gyakorlatilag 50% köré teszi — egy 25%-os volatilitású
papírnál 50,4%, egy 50%-osnál 48,1%. **Ez nem a piac véleménye, hanem a képlet
mellékterméke.** A piac iránybeli árazása a szomszédos kötési árak közti
különbségben (a volatilitás-ferdeségben) van.

Ezért a **digitális opció** közelítését használjuk (Breeden–Litzenberger):

    P(S_T > K̄) ≈ −(C(K₂) − C(K₁)) / (K₂ − K₁) · e^(rT)

- `K₁ < K₂` két szomszédos call kötési ár; a párt úgy választjuk, hogy a
  felezőpontja `K̄ = (K₁ + K₂) / 2` a legközelebb essen a mai záróárhoz,
- `C` a call **közép-ára**: `(bid + ask) / 2`,
- `T` az opció lejáratáig hátralévő idő évben (naptári nap / 365),
- `r` a 3 hónapos amerikai állampapír-hozam (FRED `DGS3MO`, amit a napi
  futás már amúgy is letölt) a becslés napján; ha aznapra nincs, az utolsó
  ismert érték. (Az első változat `DTB3`-at írt; a kettő erre a célra
  gyakorlatilag azonos, és a mérés előtt a meglévő sorozatra javítottuk.)

A kapott valószínűséget [0,01; 0,99] közé vágjuk. Ha a közelítés ezen kívül
esik, az rossz árat jelez, és a papír aznap „nem elérhető".

---

## 2. Melyik lejárat

A horizontjainkhoz ritkán van pontosan egyező lejárat. A célnaphoz
**legközelebbi** lejáratot használjuk, ha legfeljebb ennyi kereskedési nap
az eltérés:

| Horizont | Legnagyobb eltérés |
|---|---|
| 5 nap | 2 nap |
| 20 nap | 5 nap |
| 60 nap | 10 nap |

Ennél nagyobb eltérésnél az adott horizonton „nem elérhető".

---

## 3. Mikor megbízható a lánc (a „likvid" definíciója)

Mindkét kötési áron:

- van vételi és eladási ajánlat (`bid > 0`, `ask > 0`),
- a szórás legfeljebb a közép-ár 25%-a: `(ask − bid) / mid ≤ 0,25`,
- a nyitott pozíciók száma legalább **100**.

Ha bármelyik nem teljesül, a papír azon a horizonton „nem elérhető", és a
csomag rögzíti, miért (`no_chain`, `no_expiry`, `illiquid`, `bad_price`,
`fetch_failed`).

---

## 4. Az implikált sáv

A 90%-os sáv összevetéséhez az implikált volatilitást használjuk (a két
kötési ár `impliedVolatility` értékének lineáris interpolációja a mai árra),
lognormális feltevéssel, a mi horizontunkra (`T = h / 252`):

    alsó = (r − σ²/2)·T − 1,645·σ·√T
    felső = (r − σ²/2)·T + 1,645·σ·√T

Ez a mi sávunkkal azonos alakú, tehát a lefedettségük közvetlenül összevethető.

---

## 5. Mikor és hogyan

- **Naponta egyszer**, a napi futásban, a becslés ELŐTT lekérve — a zárás
  utáni árakkal.
- Az értékek **a becslés-csomagba kerülnek**, tehát a napi lenyomat őket is
  fedi: utólag nem lehet másik piaci árat mellé tenni.
- **Ha a lekérés elhal, a becslés akkor is elkészül**, implikált baseline
  nélkül. Egy nem hivatalos forrás kiesése nem állíthatja meg a mérést.

---

## 6. A mérésben

A lezárt becsléseken ugyanazok a mérőszámok, mint a többi baseline-nál:
irány-találat, Brier-pontszám, sáv-lefedettség. A verdict (spec/06) a
baseline-család **legkeményebb** tagja ellen szól — az implikált csak ott
tag, ahol elérhető, és a papír oldalán mindig látszik, hogy a család kiből
áll.

**Előre kimondva:** a kockázatsemleges torzítás miatt az implikált
valószínűség iránytalálata várhatóan gyenge lesz, a Brier-pontszáma és a sáv
lefedettsége viszont érdemi mérce. Ha az eredmény ezt mutatja, az nem a
baseline hibája, hanem az, amit előre leírtunk.
