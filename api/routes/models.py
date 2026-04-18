"""
Vendor and model management endpoints.
"""

from typing import List, Optional

from fastapi import APIRouter, HTTPException

from api.schemas import (
    VendorInfo,
    VendorCreateRequest,
    ModelInfo,
    ModelCreateRequest,
)

router = APIRouter(tags=["models"])


@router.get("/vendors", response_model=List[VendorInfo])
def list_vendors():
    from kb_core.database import init_vendor_db

    db = init_vendor_db()
    vendors = db.get_all(active_only=False)
    return [VendorInfo(**v) for v in vendors]


@router.post("/vendors", response_model=VendorInfo)
def create_vendor(req: VendorCreateRequest):
    from kb_core.database import init_vendor_db
    from kb_processing.parallel_embedding import get_parallel_processor
    from rag.logger import get_logger

    logger = get_logger(__name__)
    db = init_vendor_db()
    db.upsert(
        vendor_id=req.id,
        name=req.name,
        api_base=req.api_base,
        api_key=req.api_key,
        is_active=req.is_active,
    )
    try:
        get_parallel_processor().refresh_endpoints()
    except Exception as e:
        logger.error(
            f"refresh_endpoints() failed after vendor create: {e}", exc_info=True
        )
    return VendorInfo(**db.get(req.id))


@router.get("/vendors/{vendor_id}", response_model=VendorInfo)
def get_vendor(vendor_id: str):
    from kb_core.database import init_vendor_db

    db = init_vendor_db()
    vendor = db.get(vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail=f"供应商 {vendor_id} 不存在")
    return VendorInfo(**vendor)


@router.delete("/vendors/{vendor_id}")
def delete_vendor(vendor_id: str):
    from kb_core.database import init_vendor_db
    from kb_processing.parallel_embedding import get_parallel_processor
    from rag.logger import get_logger

    logger = get_logger(__name__)
    db = init_vendor_db()
    if not db.get(vendor_id):
        raise HTTPException(status_code=404, detail=f"供应商 {vendor_id} 不存在")
    db.delete(vendor_id)
    try:
        get_parallel_processor().refresh_endpoints()
    except Exception as e:
        logger.error(
            f"refresh_endpoints() failed after vendor delete: {e}", exc_info=True
        )
    return {"status": "deleted", "vendor_id": vendor_id}


@router.put("/vendors/{vendor_id}", response_model=VendorInfo)
def update_vendor(vendor_id: str, req: VendorCreateRequest):
    from kb_core.database import init_vendor_db
    from kb_processing.parallel_embedding import get_parallel_processor
    from rag.logger import get_logger

    logger = get_logger(__name__)
    db = init_vendor_db()
    if not db.get(vendor_id):
        raise HTTPException(status_code=404, detail=f"供应商 {vendor_id} 不存在")
    db.upsert(
        vendor_id=vendor_id,
        name=req.name,
        api_base=req.api_base,
        api_key=req.api_key,
        is_active=req.is_active,
    )
    try:
        get_parallel_processor().refresh_endpoints()
    except Exception as e:
        logger.error(
            f"refresh_endpoints() failed after vendor update: {e}", exc_info=True
        )
    return VendorInfo(**db.get(vendor_id))


@router.get("/models", response_model=List[ModelInfo])
def list_models(type: Optional[str] = None):
    from rag.config import get_model_registry

    registry = get_model_registry()
    if type:
        models = registry.get_by_type(type)
    else:
        models = registry.list_models()
    return [ModelInfo(**m) for m in models]


@router.post("/models", response_model=ModelInfo)
def create_model(req: ModelCreateRequest):
    from kb_core.database import init_model_db, init_vendor_db
    from kb_processing.parallel_embedding import get_parallel_processor
    from rag.logger import get_logger

    logger = get_logger(__name__)
    vendor_db = init_vendor_db()
    if not vendor_db.get(req.vendor_id):
        raise HTTPException(
            status_code=400,
            detail=f"供应商 {req.vendor_id} 不存在，请先创建供应商",
        )

    model_db = init_model_db()
    name = req.name or req.id.split("/")[-1]
    model_db.upsert(
        model_id=req.id,
        vendor_id=req.vendor_id,
        name=name,
        type=req.type,
        is_active=req.is_active,
        is_default=req.is_default,
        config=req.config,
    )
    if req.is_default:
        model_db.set_default(req.id)
    from rag.config import get_model_registry

    get_model_registry().reload()
    try:
        get_parallel_processor().refresh_endpoints()
    except Exception as e:
        logger.error(
            f"refresh_endpoints() failed after model create: {e}", exc_info=True
        )
    return ModelInfo(**model_db.get(req.id))


@router.get("/models/{model_id:path}", response_model=ModelInfo)
def get_model(model_id: str):
    from rag.config import get_model_registry

    registry = get_model_registry()
    model = registry.get_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail=f"模型 {model_id} 不存在")
    return ModelInfo(**model)


@router.delete("/models/{model_id:path}")
def delete_model(model_id: str):
    from kb_core.database import init_model_db
    from rag.config import get_model_registry
    from kb_processing.parallel_embedding import get_parallel_processor
    from rag.logger import get_logger

    logger = get_logger(__name__)
    db = init_model_db()
    if not db.get(model_id):
        raise HTTPException(status_code=404, detail=f"模型 {model_id} 不存在")
    db.delete(model_id)
    get_model_registry().reload()
    try:
        get_parallel_processor().refresh_endpoints()
    except Exception as e:
        logger.error(
            f"refresh_endpoints() failed after model delete: {e}", exc_info=True
        )
    return {"status": "deleted", "model_id": model_id}


@router.put("/models/{model_id:path}", response_model=ModelInfo)
def update_model(model_id: str, req: ModelCreateRequest):
    from kb_core.database import init_model_db
    from rag.config import get_model_registry
    from kb_processing.parallel_embedding import get_parallel_processor
    from rag.logger import get_logger

    logger = get_logger(__name__)
    db = init_model_db()
    if not db.get(model_id):
        raise HTTPException(status_code=404, detail=f"模型 {model_id} 不存在")
    db.upsert(
        model_id=model_id,
        vendor_id=req.vendor_id,
        name=req.name or model_id.split("/")[-1],
        type=req.type,
        is_active=req.is_active,
        is_default=req.is_default,
        config=req.config,
    )
    if req.is_default:
        db.set_default(model_id)
    get_model_registry().reload()
    try:
        get_parallel_processor().refresh_endpoints()
    except Exception as e:
        logger.error(
            f"refresh_endpoints() failed after model update: {e}", exc_info=True
        )
    return ModelInfo(**db.get(model_id))


@router.put("/models/{model_id:path}/default")
def set_default_model(model_id: str):
    from kb_core.database import init_model_db
    from rag.config import get_model_registry
    from kb_processing.parallel_embedding import get_parallel_processor
    from rag.logger import get_logger

    logger = get_logger(__name__)
    db = init_model_db()
    if not db.get(model_id):
        raise HTTPException(status_code=404, detail=f"模型 {model_id} 不存在")
    db.set_default(model_id)
    get_model_registry().reload()
    try:
        get_parallel_processor().refresh_endpoints()
    except Exception as e:
        logger.error(
            f"refresh_endpoints() failed after model set default: {e}", exc_info=True
        )
    return {"status": "success", "model_id": model_id}