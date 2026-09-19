# Воспроизведение диагностических проб

Пробы предназначены для commit `3b8985c77dc41a9fffbb025f1b80fa630dbf178e`. Они используют существующие helper-функции tests и показывают фактическое поведение, включая ошибки; успешный выход скрипта не означает соответствия требованиям. Все приложения работают на отдельных временных SQLite, исходный код и реальные базы не изменяются. Геокодирование и маршрутизация только demo.

Запуск из `backend/` после установки frozen-зависимостей (см. VERIFICATION.md):

```sh
python3 - <<'PY'
from pathlib import Path
text = Path('docs/audits/2026-09-19/REPRODUCE.md').read_text()
script = text.split('```python\n', 1)[1].split('\n```', 1)[0]
Path('/private/tmp/beeline_audit_probes.py').write_text(script)
PY
PYTHONPATH=src:tests PYTHONDONTWRITEBYTECODE=1 \
  /private/tmp/beeline-audit-20260919-venv/bin/python /private/tmp/beeline_audit_probes.py
```

При повторении на другом компьютере замените путь к Python своей средой с зависимостями uv.lock; каталог временных результатов указан внизу скрипта. Результаты содержат время и случайные UUID только там, где это необходимо; сравнивайте семантику.

```python
"""Read-only source audit; all application writes use disposable SQLite databases."""
import asyncio
import json
import tempfile
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import select

from beeline_backend.application.planner import DeterministicPlanningAlgorithm, validate_candidate
from beeline_backend.config import Settings
from beeline_backend.domain.model import Priority, RequestStatus
from beeline_backend.infrastructure.importer import XlsxDatasetImporter
from beeline_backend.infrastructure.models import DayEventRow, OutboxJobRow, PlanRow, RequestRow
from beeline_backend.presentation.api import create_app
from conftest import synthetic_xlsx
from test_http_flow import FailOncePlanner
from test_planner_contract import _snapshot

MOSCOW = ZoneInfo('Europe/Moscow')
RESULTS = {}

def record(name, **values):
    RESULTS[name] = values
    print(json.dumps({name: values}, ensure_ascii=False, default=str))

async def pure_probes():
    planner = DeterministicPlanningAlgorithm()
    snap = _snapshot()
    snap.requests[0].status = RequestStatus.COMPLETED
    result = await planner.plan(snap)
    validate_candidate(snap, result)
    record('completed_reassigned', assigned=len(result.assignments), validator='accepted')

    snap = _snapshot().model_copy(update={'as_of': _snapshot().as_of.replace(hour=13)})
    result = await planner.plan(snap)
    validate_candidate(snap, result)
    record('planning_in_past', as_of=snap.as_of, start=result.assignments[0].start_at, validator='accepted')

    snap = _snapshot()
    snap.engineers[0].skills.add('emergency')
    snap.engineers[0].shift_end = snap.as_of.replace(hour=10)
    snap.requests[0].priority = Priority.URGENT
    emergency = snap.requests[0].model_copy(update={'id': uuid4(), 'external_id': '2', 'required_skill': 'emergency', 'service_minutes': 80, 'full_normative_minutes': 100})
    snap.requests.append(emergency)
    result = await planner.plan(snap)
    validate_candidate(snap, result)
    record('priority_under_shortage', assigned=[next(r.required_skill for r in snap.requests if r.id == a.request_id) for a in result.assignments], emergency_unassigned=any(u.request_id == emergency.id for u in result.unassigned))

    snap = _snapshot()
    snap.engineers[0].transport = 'walking'
    walking = snap.travel_by_profile['driving'].model_copy(deep=True)
    walking.profile = 'walking'
    walking.cells[0][1].duration_seconds = 6000
    snap.travel_by_profile['walking'] = walking
    result = await planner.plan(snap)
    validate_candidate(snap, result)
    record('walking_uses_driving', actual_travel_seconds=result.assignments[0].travel_seconds, walking_seconds=6000, validator='accepted')

    snap = _snapshot()
    snap.engineers[0].skills = {'local'}
    result = await planner.plan(snap)
    validate_candidate(snap, result)
    record('skill_is_enforced', assigned=len(result.assignments), reason=result.unassigned[0].reason_code)

    snap = _snapshot(locked=True).model_copy(update={'engineers': []})
    try:
        await planner.plan(snap)
    except Exception as exc:
        record('unavailable_locked_engineer', exception=type(exc).__name__)

def new_client(directory):
    return TestClient(create_app(Settings(app_env='test', database_url=f'sqlite+aiosqlite:///{directory}/audit.db', geocoder_mode='demo', routing_provider='demo')), raise_server_exceptions=False)

def seed(client, data=None, key='audit-import'):
    response = client.post('/api/v1/imports', files={'file': ('Восток Синтетические данные.xlsx', data or synthetic_xlsx.__wrapped__())}, headers={'Idempotency-Key': key})
    assert response.status_code == 200, response.text
    return response.json()['scenario_id']

def plan(client, scenario, **extra):
    response = client.post('/api/v1/plans/run', json={'scenario_id': scenario, 'planning_date':'2026-08-17', 'as_of':'2026-08-17T13:00:00+03:00', **extra})
    assert response.status_code == 200, response.text
    return response.json()['plan_id']

def fact(client, request, status, **extra):
    response = client.post(f'/api/v1/requests/{request}/facts', json={'status':status,'effective_at':'2026-08-17T10:00:00+03:00','actor':'audit','reason':'audit', **extra})
    assert response.status_code == 200, response.text

def event(scenario, kind, key, payload, effective_at='2026-08-17T13:00:00+03:00'):
    return {'scenario_id':scenario,'planning_date':'2026-08-17','event_type':kind,'effective_at':effective_at,'payload':payload,'idempotency_key':key,'actor':'audit'}

def http_probes():
    with tempfile.TemporaryDirectory(prefix='beeline-http-') as d, new_client(d) as client:
        scenario=seed(client)
        first=plan(client, scenario)
        assignments=client.get(f'/api/v1/plans/{first}').json()['assignments']
        target=assignments[0]
        for status in ['SENT','EN_ROUTE','IN_PROGRESS','COMPLETED']:
            fact(client, target['request_id'], status)
        second=plan(client, scenario)
        current=client.get(f'/api/v1/plans/{second}').json()
        record('http_completed_reassigned', completed_request_assigned=any(a['request_id']==target['request_id'] for a in current['assignments']), planned_start=current['assignments'][0]['start_at'])
        malformed=client.post('/api/v1/events', json=event(scenario,'urgent_request','bad-uuid',{'request_id':'not-a-uuid'}))
        record('invalid_event_uuid', http_status=malformed.status_code)
        mixed=client.post('/api/v1/requests', json={'scenario_id':scenario,'planning_date':'2026-08-17','external_id':'mixed','address':'Москва тест','district':'test','window_start':'2026-08-17T12:00:00','window_end':'2026-08-17T14:00:00+03:00','service_minutes':30,'required_skill':'local','idempotency_key':'mixed','actor':'audit'})
        record('mixed_datetime_offsets', http_status=mixed.status_code)

    with tempfile.TemporaryDirectory(prefix='beeline-http-') as d, new_client(d) as client:
        scenario=seed(client)
        first=plan(client, scenario)
        approve=client.post(f'/api/v1/plans/{first}/approve',json={'expected_base_plan_id':None,'actor':'audit'})
        assert approve.status_code==200,approve.text
        target=client.get(f'/api/v1/plans/{first}').json()['assignments'][0]
        for status in ['SENT','EN_ROUTE']:
            fact(client,target['request_id'],status)
        result=client.post('/api/v1/events',json=event(scenario,'engineer_unavailable','unavailable',{'engineer_id':target['engineer_id']}))
        record('http_unavailable_locked_engineer', http_status=result.status_code)

    with tempfile.TemporaryDirectory(prefix='beeline-http-') as d, new_client(d) as client:
        scenario=seed(client)
        clock, geocoder, router, _=client.app.state.providers
        failing=FailOncePlanner()
        client.app.state.providers=(clock,geocoder,router,failing)
        payload={'scenario_id':scenario,'planning_date':'2026-08-17','external_id':'new-emergency','address':'Москва тест','district':'test','window_start':'2026-08-17T00:01:00+03:00','window_end':'2026-08-17T23:59:00+03:00','service_minutes':80,'required_skill':'emergency','priority':'urgent','idempotency_key':'retry-request','actor':'audit'}
        first=client.post('/api/v1/requests',json=payload)
        retry=client.post('/api/v1/requests',json=payload)
        record('new_request_retry', first_status=first.status_code,retry_status=retry.status_code,duplicate=retry.json().get('duplicate'),replanning=retry.json().get('replanning'),planner_attempts=failing.attempts)

    with tempfile.TemporaryDirectory(prefix='beeline-http-') as d, new_client(d) as client:
        scenario=seed(client)
        first=plan(client,scenario)
        target=client.get(f'/api/v1/plans/{first}').json()['assignments'][0]
        for status in ['SENT','EN_ROUTE']:
            fact(client,target['request_id'],status)
        fact(client,target['request_id'],'IN_PROGRESS',actual_start='2026-08-17T10:00:00+03:00')
        cancelled=client.post('/api/v1/events',json=event(scenario,'request_cancelled','cancel-future',{'request_id':target['request_id']},effective_at='2026-08-17T17:00:00+03:00'))
        assert cancelled.status_code==200,cancelled.text
        before=plan(client,scenario,as_of='2026-08-17T12:00:00+03:00')
        async def inspect():
            async with client.app.state.session_factory() as session:
                row=await session.get(PlanRow,__import__('uuid').UUID(before))
                r=next(r for r in row.input_snapshot['requests'] if r['id']==target['request_id'])
                from beeline_backend.infrastructure.models import RequestStatusEventRow
                latest=await session.scalar(select(RequestStatusEventRow).where(RequestStatusEventRow.request_id==__import__('uuid').UUID(target['request_id'])).order_by(RequestStatusEventRow.recorded_at.desc()))
                return r['status'],len(row.input_snapshot['events']),latest.actual_start
        status,events,actual=client.portal.call(inspect)
        record('future_fact_leaks_into_snapshot',snapshot_as_of='12:00',cancel_effective='17:00',snapshot_status=status,visible_events=events)
        record('cancel_event_loses_actual_start',actual_start=actual)

def dataset_probes():
    for path in sorted(Path('../docs/source_files/Dataset').glob('*Синтетические данные.xlsx')):
        imported=XlsxDatasetImporter().parse(path.name,path.read_bytes())
        record('dataset_'+imported.scenario_code, requests=len(imported.requests),planning_date=imported.planning_date,issues=Counter(i.reason_code for i in imported.issues),types=Counter(r.work_code for r in imported.requests),combined=[{'bk':r.bk_type,'hd':r.hd_type,'code':r.work_code,'service':r.service_minutes} for r in imported.requests if r.bk_type=='Подключение' and r.work_code=='equipment_order'][:2])

def extra_probes():
    from io import BytesIO
    from openpyxl import load_workbook
    from beeline_backend.infrastructure.models import EngineerRow, LocationRow
    from beeline_backend.presentation.api import _provider_bundle
    record('unknown_router_falls_back', selected=_provider_bundle(Settings(routing_provider='dgsi'))[2].name)
    with tempfile.TemporaryDirectory(prefix='beeline-http-') as d, new_client(d) as client:
        scenario=seed(client)
        workbook=load_workbook(BytesIO(synthetic_xlsx.__wrapped__()))
        workbook.active['G3']='Москва, измененный адрес'
        stream=BytesIO(); workbook.save(stream)
        seed(client,stream.getvalue(),'changed-import')
        requests=client.get('/api/v1/requests',params={'scenario_id':scenario,'planning_date':'2026-08-17'}).json()
        latest=client.get(f'/api/v1/plans/{plan(client,scenario)}').json()
        record('reimport_list_differs_from_plan', listed=len(requests),planned_or_unassigned=len(latest['assignments'])+len(latest['unassigned']))
        workbook=load_workbook(BytesIO(synthetic_xlsx.__wrapped__()))
        for row in (3,4):
            for col in ('D','E'):
                workbook.active[f'{col}{row}']=workbook.active[f'{col}{row}'].value.replace('17.08','18.08')
        stream=BytesIO();workbook.save(stream)
        seed(client,stream.getvalue(),'next-day')
        next_day=client.get(f'/api/v1/plans/{plan(client,scenario,planning_date="2026-08-18",as_of="2026-08-18T08:00:00+03:00")}').json()
        record('second_date_has_no_shifts',assignments=len(next_day['assignments']),reasons=[r['reason_code'] for r in next_day['unassigned']])

    with tempfile.TemporaryDirectory(prefix='beeline-http-') as d, new_client(d) as client:
        scenario=seed(client)
        async def move_home():
            async with client.app.state.session_factory() as session:
                home=LocationRow(address='Дом в Ступино',normalized_address='дом в ступино',region='Ступино',latitude=54.9,longitude=38.0,coordinate_source='audit',coordinate_version=1,created_at=datetime.now(MOSCOW))
                session.add(home);await session.flush()
                engineer=await session.scalar(select(EngineerRow))
                engineer.home_location_id=home.id
                await session.commit()
        client.portal.call(move_home)
        result=client.post('/api/v1/plans/run',json={'scenario_id':scenario,'planning_date':'2026-08-17','as_of':'2026-08-17T08:00:00+03:00'})
        record('separate_home_missing_from_matrix', http_status=result.status_code)

    for path in sorted(Path('../docs/source_files/Dataset').glob('*Синтетические данные.xlsx')):
        with tempfile.TemporaryDirectory(prefix='beeline-real-') as d, new_client(d) as client:
            response=client.post('/api/v1/imports',files={'file':(path.name,path.read_bytes())})
            assert response.status_code==200,response.text
            scenario=response.json()['scenario_id']
            created=plan(client,scenario,as_of='2026-08-17T08:00:00+03:00')
            current=client.get(f'/api/v1/plans/{created}').json()
            approved=client.post(f'/api/v1/plans/{created}/approve',json={'expected_base_plan_id':None,'actor':'audit'})
            assert approved.status_code==200,approved.text
            async def imported_priorities():
                async with client.app.state.session_factory() as session:
                    return list((await session.scalars(select(RequestRow.priority))).all())
            record('smoke_'+path.name.split(' ')[0],assigned=len(current['assignments']),unassigned=len(current['unassigned']),engineers=current['metrics']['engineers_used'],priorities=dict(Counter(client.portal.call(imported_priorities))),approved=approved.status_code,providers='demo only')

if __name__=='__main__':
    asyncio.run(pure_probes())
    http_probes()
    dataset_probes()
    extra_probes()
    Path('/private/tmp/beeline_audit_results.json').write_text(json.dumps(RESULTS,ensure_ascii=False,indent=2,default=str))

```
