"""
Structured Extraction 模块
"""

from typing import Any, Dict, Type, Optional, List
import json

from llamaindex_study.logger import get_logger

logger = get_logger(__name__)


class StructuredExtractor:
    def __init__(self, llm: Optional[Any] = None):
        self._llm = llm

    def extract(
        self,
        text: str,
        schema: Dict[str, Any],
        prompt_template: Optional[str] = None,
    ) -> Dict[str, Any]:
        if self._llm is None:
            from llamaindex_study.ollama_utils import create_llm

            self._llm = create_llm()

        if prompt_template is None:
            prompt_template = self._default_prompt_template(schema)

        prompt = prompt_template.format(
            text=text, schema=json.dumps(schema, ensure_ascii=False, indent=2)
        )

        result_text = ""
        try:
            response = self._llm.complete(prompt)
            result_text = response.text.strip()

            if result_text.startswith("```"):
                lines = result_text.split("\n")
                if len(lines) > 1:
                    result_text = "\n".join(lines[1:-1])

            return json.loads(result_text)
        except json.JSONDecodeError:
            logger.warning(f"JSON 解析失败，原始响应: {result_text[:200]}")
            return {"error": "解析失败", "raw_response": result_text}
        except Exception as e:
            logger.error(f"提取失败: {e}")
            return {"error": str(e)}

    def _default_prompt_template(self, schema: Dict[str, Any]) -> str:
        return """从以下文本中提取结构化数据，返回 JSON 格式。

schema:
{schema}

文本:
{text}

请只返回 JSON，不要其他内容。"""


class PydanticProgram:
    def __init__(self, llm: Optional[Any] = None):
        self._llm = llm
        self._extractor = StructuredExtractor(llm=llm)

    def run(
        self,
        text: str,
        output_cls: Type,
        prompt_template: Optional[str] = None,
    ) -> Any:
        import typing

        fields = {}
        for name, field_info in typing.get_type_hints(output_cls).items():
            fields[name] = {"type": field_info.__name__}

        schema = {"type": "object", "properties": fields}

        result = self._extractor.extract(text, schema, prompt_template)

        if "error" in result:
            return result

        try:
            return output_cls(**result)
        except Exception as e:
            logger.warning(f"创建 Pydantic 对象失败: {e}")
            return result


class TextToJsonExtractor:
    def __init__(self, llm: Optional[Any] = None):
        self._llm = llm
        self._extractor = StructuredExtractor(llm=llm)

    def extract(
        self,
        text: str,
        fields: List[str],
        prompt_template: Optional[str] = None,
    ) -> Dict[str, Any]:
        schema = {
            "type": "object",
            "properties": {f: {"type": "string"} for f in fields},
            "required": fields,
        }

        result = self._extractor.extract(text, schema, prompt_template)

        if "error" in result:
            return {f: None for f in fields}

        return {f: result.get(f) for f in fields}


_extractor_instance: Optional[StructuredExtractor] = None


def get_extractor() -> StructuredExtractor:
    global _extractor_instance
    if _extractor_instance is None:
        _extractor_instance = StructuredExtractor()
    return _extractor_instance
