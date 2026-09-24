import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta

from src.core.algorithm.dto import Engineer, Job, PlanningLayer, Stop
from src.core.algorithm.exc import AlgorithmInputError


class ScheduleMaterializer:
    """Превращает порядок заявок в точные arrival/start/finish."""

    def materialize(
        self,
        engineer: Engineer,
        request_ids: Sequence[uuid.UUID],
        jobs_by_id: dict[uuid.UUID, Job],
        layers_by_request: dict[uuid.UUID, PlanningLayer],
        cutoff_at: datetime,
    ) -> tuple[Stop, ...] | None:
        previous_id = engineer.id
        previous_finish = max(engineer.available_from, cutoff_at)
        stops: list[Stop] = []
        for sequence_number, request_id in enumerate(request_ids, start=1):
            job = jobs_by_id[request_id]
            layer = layers_by_request[request_id]
            matching_matrices = [
                item.travel_matrix
                for item in layer.matrices
                if item.vehicle_type == engineer.vehicle_type
            ]
            if len(matching_matrices) != 1:
                raise AlgorithmInputError(
                    f"Для слоя заявки {request_id} нет единственной матрицы "
                    f"транспорта {engineer.vehicle_type}"
                )
            travel_matrix = matching_matrices[0]
            try:
                travel_minutes = travel_matrix.minutes(previous_id, request_id)
                distance_km = travel_matrix.kilometers(previous_id, request_id)
            except (KeyError, IndexError) as exc:
                raise AlgorithmInputError(
                    f"Матрица слоя не покрывает переход {previous_id} -> {request_id}"
                ) from exc
            arrival = previous_finish + timedelta(minutes=travel_minutes)
            start = max(arrival, job.release_at, cutoff_at)
            finish = start + timedelta(minutes=job.service_minutes)
            if start > job.latest_start_at or finish > engineer.shift_end:
                return None
            stops.append(
                Stop(
                    request_id=request_id,
                    sequence_number=sequence_number,
                    arrival=arrival,
                    start=start,
                    finish=finish,
                    travel_minutes=travel_minutes,
                    distance_km=distance_km,
                )
            )
            previous_id = request_id
            previous_finish = finish
        return tuple(stops)
