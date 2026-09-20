from fastapi import APIRouter

from src.api.planning import router as planning_router

router = APIRouter(prefix="/api")
router.include_router(planning_router)
