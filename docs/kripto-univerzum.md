# A kripto-univerzum — előre rögzített kiválasztás

**Rögzítve:** 2026-10-02, **mielőtt egyetlen jelölt forgalmi adatát
lekértük volna.** A kiválasztás egyszer fut le, az eredménye
(`pipeline/universe/instruments_crypto.csv`) utána csak dátumozott
döntéssel változik, mint a részvényeké.

Forrás: `spec/01` 7. fejezet (BTC, ETH + top 50); a tulajdonos jóváhagyta
2026-10-02-án (`docs/terv-5-fazis.md`, E1).

---

## 1. Jelöltek

A jelöltlista a nagy, ismert kriptoeszközök **neve** (lent, 4. fejezet), a
mai tudásunk szerint összeállítva. Szándékosan bő: a szűrés és a rangsor dönt,
nem a lista.

**Miért nem piaci kapitalizáció-lista:** a CoinGecko API feltételei tiltják a
származtatást és a továbbadást, és a tárolt adatot 24 óránként frissíteni
kell — egy dátumozott pillanatkép a nyilvános repóban ezt sértené
(`docs/adatlicencek.md` a privát repóban). A rangsort ezért ugyanaz a forrás
adja, mint az árakat.

## 2. Kizárás (a lista már ezek nélkül készült)

- **stablecoin** (dollárhoz vagy más pénzhez kötött): nincs mit előre jelezni;
- **wrapped, bridged, liquid-staking és restaking token** (WBTC, stETH …):
  ugyanannak az eszköznek a másolata — hamisan növelné a mintaszámot, mint a
  GOOG/GOOGL a részvényeknél;
- **eszközfedezetű token** (arany, kötvény, ingatlan): nem kripto-kockázat.

## 3. Szűrés és rangsor

1. **Szimbólum:** a Yahoo keresője a névre; az a `CRYPTOCURRENCY` típusú,
   `-USD` végű találat, amelynek neve pontosan `<név> USD` (kis- és nagybetű
   nem számít). Ha nincs ilyen, a jelölt kimarad („nem azonosítható”), és a
   jelentésben látszik. A Yahoo az ütköző neveket számmal különbözteti meg
   (Uniswap: `UNI7083-USD`); a név-egyezés ezt kezeli.
2. **Múlt:** legalább **730 nap** napi gyertya 2026-10-01-ig, és az utolsó
   730 napban nincs **3 napnál hosszabb** hiány.
3. **Rangsor:** a **60 napos medián napi dollárforgalom** 2026-10-01-ig. A
   Yahoo kripto-volumene már dollárban van (ellenőrizve: a BTC napi volumene
   3,3–3,6 × 10¹⁰, ami csak dollárként értelmes), ezért ez maga a `volume`.
4. **Az első 50**, a BTC és az ETH mindenképp benne (ha nem lennének az
   első 50-ben, a 49. és az 50. helyére kerülnek).
5. **Azonosítók:** `CZ00621`-től, a rangsor sorrendjében. Egyszer kiadott
   azonosító soha nem kerül újra kiadásra.

**Túlélési torzítás:** ez a mai lista. Ami 2018-ban top 50 volt, de azóta
összeomlott, hiányzik — ez minden hosszú távú kripto-számot felfelé húz. A
backtest és a labor figyelmeztetése ezt kriptón külön kimondja.

## 4. A jelöltlista

Bitcoin, Ethereum, BNB, XRP, Solana, TRON, Dogecoin, Cardano, Chainlink,
Stellar, Monero, Zcash, Hyperliquid, Bitcoin Cash, Litecoin, Avalanche, Sui,
Hedera, Toncoin, Shiba Inu, Polkadot, UNUS SED LEO, Uniswap, Cronos,
Ethereum Classic, NEAR Protocol, Aptos, Internet Computer, Pepe, Aave,
Bittensor, Ethena, Mantle, OKB, POL (ex-MATIC), Kaspa, Render, Arbitrum,
Filecoin, VeChain, Cosmos, Algorand, Optimism, Injective, Stacks, The Graph,
Immutable, Celestia, Sei, Artificial Superintelligence Alliance, Bonk,
dogwifhat, FLOKI, Jupiter, Worldcoin, Ondo, Pyth Network, Lido DAO, Maker,
Sky, Theta Network, Quant, MultiversX, Arweave, Tezos, EOS, Flow,
The Sandbox, Decentraland, Axie Infinity, Chiliz, Gala, Neo, IOTA, Kava,
Dash, PancakeSwap, THORChain, Curve DAO Token, Synthetix, Compound, 1inch,
Ethereum Name Service, Mina, Oasis, Zilliqa, Kusama, Basic Attention Token,
Enjin Coin, Ankr, Conflux, JasmyCoin, XDC Network, Bitcoin SV, Helium, Nexo,
Gnosis, Trust Wallet Token, BitTorrent, IoTeX, Harmony, Celo, KuCoin Token,
GateToken, LayerZero, Starknet, Bitget Token, Pendle, Raydium, Jito, Sonic,
Fantom, Akash Network, Ocean Protocol, Rocket Pool, Livepeer, Loopring,
yearn.finance, SushiSwap, dYdX, GMX, Osmosis, Holo, Ravencoin, Decred, Qtum,
Waves, ICON, Siacoin, Golem, Storj, Audius, Band Protocol, Ontology,
Nervos Network.

## 5. Adatminőség (a napi letöltésre)

- **A nap UTC 00:00–24:00**; a Yahoo kripto-gyertyája ezt a napot adja. A
  még le nem zárt (mai UTC) gyertya nem kerül be.
- **Folytonosság:** minden UTC-napnak lennie kell. A hiányzó nap hiányként
  jelölődik a futás jelentésében, **nem pótoljuk** (és nem töltjük ki az
  előzővel).
- A gyanús sort (pl. a záró a nap tartományán kívül) megjelöljük, nem
  töröljük, mint a részvényeknél.
- **Hozam = záróár-változás** (kriptón nincs osztalék és felosztás).
- **Forrás:** a Yahoo. A tartalék források (Tiingo, Twelve Data) más
  szimbólumot és más napi zárást használhatnak; amíg nem ellenőriztük, hogy
  ugyanazt a UTC-napot adják, kriptóra nem lépnek be, és a kiesés hiányként
  látszik.
