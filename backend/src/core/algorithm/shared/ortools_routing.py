import uuid

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from src.core.algorithm.shared.context import AlgorithmContext


def tuned_ortools_route(
    ctx: AlgorithmContext,
    seconds: float,
    first_solution_strategy: int,
    initial_route: list[uuid.UUID] | None = None,
    use_priority_penalty: bool = True,
) -> list[uuid.UUID]:
    """CP Routing (OR-Tools) поверх `ctx.jobs` — окно/смена как ограничения измерения `Time`.

    Дословный перенос `tuned_ortools_route`: узлы — офис (0), заявки (1..N),
    фиктивный конец (N+1); стоимость дуги — время в пути + длительность
    работы у следующей заявки; заявки могут быть пропущены за штраф
    (`AddDisjunction`) — модель допускает частичное покрытие пула, а не
    требует посетить всех. `include_service_in_search_cost` из оригинала не
    перенесён как параметр — оба вызывающих места (`ortools_multistart_gls`,
    `hybrid_seed_ortools_polish`) всегда вызывали с одним и тем же `True`,
    поэтому поведение зашито напрямую, без неиспользуемой развилки.
    `use_priority_penalty` перенесён как есть — единственный параметр,
    который реально варьируется между вызывающими стратегиями.
    """
    jobs = ctx.jobs
    office_node = 0
    dummy_end = len(jobs) + 1
    manager = pywrapcp.RoutingIndexManager(dummy_end + 1, 1, [office_node], [dummy_end])
    routing = pywrapcp.RoutingModel(manager)
    job_by_node = {node + 1: job for node, job in enumerate(jobs)}

    def node_id(node: int) -> uuid.UUID:
        return ctx.office_id if node == office_node else job_by_node[node].request_id

    def travel_between(from_node: int, to_node: int) -> int:
        if from_node == dummy_end or to_node == dummy_end:
            return 0
        return ctx.travel_matrix.minutes(node_id(from_node), node_id(to_node))

    def search_cost(from_index: int, to_index: int) -> int:
        to_node = manager.IndexToNode(to_index)
        service = job_by_node[to_node].service if to_node in job_by_node else 0
        return travel_between(manager.IndexToNode(from_index), to_node) + service

    cost_index = routing.RegisterTransitCallback(search_cost)
    routing.SetArcCostEvaluatorOfAllVehicles(cost_index)

    def time_callback(from_index: int, to_index: int) -> int:
        from_node = manager.IndexToNode(from_index)
        service = job_by_node[from_node].service if from_node in job_by_node else 0
        return service + travel_between(from_node, manager.IndexToNode(to_index))

    time_index = routing.RegisterTransitCallback(time_callback)
    routing.AddDimension(time_index, 720, ctx.shift_end, False, "Time")
    time_dimension = routing.GetDimensionOrDie("Time")
    time_dimension.CumulVar(routing.Start(0)).SetRange(ctx.shift_start, ctx.shift_start)
    time_dimension.CumulVar(routing.End(0)).SetRange(ctx.shift_start, ctx.shift_end)

    drop_base = 10_000_000
    priority_bonus = 10_000 if use_priority_penalty else 0
    for node, job in job_by_node.items():
        index = manager.NodeToIndex(node)
        time_dimension.CumulVar(index).SetRange(job.window_start, job.window_end)
        routing.AddDisjunction([index], drop_base + priority_bonus * job.priority)

    search = pywrapcp.DefaultRoutingSearchParameters()
    search.first_solution_strategy = first_solution_strategy
    search.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    search.time_limit.FromMilliseconds(max(1, round(seconds * 1000)))
    if initial_route:
        node_by_request = {job.request_id: node for node, job in job_by_node.items()}
        initial_nodes = [node_by_request[request_id] for request_id in initial_route]
        assignment = routing.ReadAssignmentFromRoutes([initial_nodes], True)
        solution = routing.SolveFromAssignmentWithParameters(assignment, search)
    else:
        solution = routing.SolveWithParameters(search)
    if solution is None:
        return []
    route: list[uuid.UUID] = []
    index = routing.Start(0)
    while not routing.IsEnd(index):
        node = manager.IndexToNode(index)
        if node in job_by_node:
            route.append(job_by_node[node].request_id)
        index = solution.Value(routing.NextVar(index))
    return route
