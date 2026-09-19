"""A modell rögzített beállításai (spec/06, 2. és 4. fejezet).

Minden szám itt van, egy helyen: a tanítás determinisztikus (fix seed), és a
futás metaadatai közé lementjük a könyvtárverziókat is, hogy egy eredmény
később is újraszámolható legyen.
"""

from __future__ import annotations

from typing import Final

#: Kereskedési napban mért horizontok (≈ 1 hét, 1 hónap, 3 hónap).
HORIZONS: Final[tuple[int, ...]] = (5, 20, 60)

#: A modellcsalád a mérés alanya: az adat változhat, a felépítés nem (spec/06, 4.).
MODEL_FAMILY: Final = "lgbm-core"
#: A verzió a felépítés, a feature-készlet vagy a célváltozó változásakor nő.
MODEL_VERSION: Final = "v1"

SEED: Final = 7

#: A predikciós sáv névleges lefedettsége.
BAND_COVERAGE: Final = 0.90

#: Az utolsó ennyi session a kalibrációé és a conformal kvantilisé (tanításra nem megy).
CALIBRATION_SESSIONS: Final = 252

LGBM_PARAMS: Final[dict[str, object]] = {
    "objective": "regression",
    "learning_rate": 0.03,
    "num_leaves": 63,
    "min_data_in_leaf": 500,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "lambda_l2": 1.0,
    "num_threads": 0,
    "verbosity": -1,
    "seed": SEED,
    "deterministic": True,
    "force_row_wise": True,
}

NUM_BOOST_ROUND: Final = 400

#: A modell nem jósol olyan papírra, aminek ennél rövidebb a múltja.
MIN_HISTORY_SESSIONS: Final = 300
