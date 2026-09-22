from src.core.algorithm.contracts import PlanningAlgorithm
from src.core.algorithm.strategies.beam_anneal import BeamAnneal
from src.core.algorithm.strategies.hybrid_seed_ortools_polish import HybridSeedOrtoolsPolish
from src.core.algorithm.strategies.layered_exact_state_graph import LayeredExactStateGraph
from src.core.algorithm.strategies.ortools_multistart_gls import OrtoolsMultistartGls
from src.core.algorithm.strategies.regret_insertion_ruin_recreate import (
    RegretInsertionRuinRecreate,
)
from src.core.algorithm.strategies.tasty_graph_multistart import TastyGraphMultistart

ALL_STRATEGIES: tuple[type[PlanningAlgorithm], ...] = (
    LayeredExactStateGraph,
    TastyGraphMultistart,
    RegretInsertionRuinRecreate,
    OrtoolsMultistartGls,
    HybridSeedOrtoolsPolish,
    BeamAnneal,
)
