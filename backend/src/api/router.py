from fastapi import APIRouter

from src.api.engineers.router import router as engineers_router
from src.api.planning.router import router as planning_router
from src.api.plans.router import router as plans_router
from src.api.requests.router import router as requests_router

router = APIRouter(prefix="/api")
router.include_router(planning_router)
router.include_router(plans_router)
router.include_router(requests_router)
router.include_router(engineers_router)
