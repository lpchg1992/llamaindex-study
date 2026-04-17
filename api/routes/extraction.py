"""
Structured extraction endpoints.
"""

from typing import List, Dict, Any, Optional

from fastapi import APIRouter

from api.schemas import ExtractRequest, ExtractResponse, TextToJsonRequest

router = APIRouter(tags=["extraction"])


@router.post("/extract", response_model=ExtractResponse)
def extract_structured(req: ExtractRequest):
    from rag.structured_extractor import get_extractor

    extractor = get_extractor()

    try:
        result = extractor.extract(
            text=req.text,
            schema=req.schema_definition,
            prompt_template=req.prompt_template,
        )

        if "error" in result:
            return ExtractResponse(data={}, error=result["error"])

        return ExtractResponse(data=result)
    except Exception as e:
        return ExtractResponse(data={}, error=str(e))


@router.post("/extract/fields", response_model=Dict[str, Any])
def extract_fields(req: TextToJsonRequest):
    from rag.structured_extractor import TextToJsonExtractor

    extractor = TextToJsonExtractor()

    try:
        return extractor.extract(
            text=req.text,
            fields=req.fields,
            prompt_template=req.prompt_template,
        )
    except Exception as e:
        return {f: None for f in req.fields}