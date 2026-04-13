"""
结构化数据提取模块

提供从非结构化文本中提取结构化数据的能力，基于 LLM 实现。

支持：
- 从文本提取 JSON 格式的结构化数据
- 支持自定义 schema 和 prompt
- Pydantic 对象直接映射

用法:
    from llamaindex_study.structured_extractor import StructuredExtractor

    extractor = StructuredExtractor()
    result = extractor.extract(text, schema={"name": {"type": "string"}, "age": {"type": "int"}})
"""

from typing import Any, Dict, Type, Optional, List
import json

from llamaindex_study.logger import get_logger

logger = get_logger(__name__)


class StructuredExtractor:
    """
    结构化数据提取器
    
    使用 LLM 从文本中提取结构化数据（JSON 格式）。
    
    Attributes:
        _llm: LLM 实例（如果为 None，自动创建）
    """
    
    def __init__(self, llm: Optional[Any] = None):
        """初始化提取器"""
        self._llm = llm

    def extract(
        self,
        text: str,
        schema: Dict[str, Any],
        prompt_template: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        从文本提取结构化数据
        
        Args:
            text: 源文本
            schema: JSON Schema 定义期望的数据结构
            prompt_template: 自定义 prompt 模板
        
        Returns:
            提取的结构化数据（字典）或包含 error 的字典
        """
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
        """默认的 prompt 模板"""
        return """从以下文本中提取结构化数据，返回 JSON 格式。

schema:
{schema}

文本:
{text}

请只返回 JSON，不要其他内容。"""


class PydanticProgram:
    """
    Pydantic 程序
    
    基于 StructuredExtractor，提供 Pydantic 类型直接映射能力。
    
    Attributes:
        _llm: LLM 实例
        _extractor: 底层提取器
    """
    
    def __init__(self, llm: Optional[Any] = None):
        """初始化 Pydantic 程序"""
        self._llm = llm
        self._extractor = StructuredExtractor(llm=llm)

    def run(
        self,
        text: str,
        output_cls: Type,
        prompt_template: Optional[str] = None,
    ) -> Any:
        """
        从文本提取并映射到 Pydantic 对象
        
        Args:
            text: 源文本
            output_cls: Pydantic 类型
            prompt_template: 自定义 prompt
        
        Returns:
            Pydantic 对象实例或包含 error 的字典
        """
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
    """
    文本到 JSON 提取器
    
    简化版提取器，直接指定要提取的字段列表。
    
    Attributes:
        _llm: LLM 实例
        _extractor: 底层提取器
    """
    
    def __init__(self, llm: Optional[Any] = None):
        """初始化提取器"""
        self._llm = llm
        self._extractor = StructuredExtractor(llm=llm)

    def extract(
        self,
        text: str,
        fields: List[str],
        prompt_template: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        从文本提取指定字段
        
        Args:
            text: 源文本
            fields: 要提取的字段列表
            prompt_template: 自定义 prompt
        
        Returns:
            字段到值的字典
        """
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
    """获取全局 StructuredExtractor 实例（单例模式）"""
    global _extractor_instance
    if _extractor_instance is None:
        _extractor_instance = StructuredExtractor()
    return _extractor_instance
