from typing import Any, Dict, List, Optional

from rag.logger import get_logger

logger = get_logger(__name__)


def _build_default_tools(kb_id: str) -> List[Any]:
    """Build default tools for ReAct agent including QueryEngineTool and utility tools."""
    from rag.query_engine import create_query_engine
    from llama_index.core.tools import QueryEngineTool, ToolMetadata

    base_engine = create_query_engine(
        kb_id=kb_id,
        mode="vector",
        top_k=5,
    )

    query_tool = QueryEngineTool(
        query_engine=base_engine,
        metadata=ToolMetadata(
            name=f"kb_{kb_id}",
            description=f"Search knowledge base '{kb_id}' for relevant information to answer questions",
        ),
    )

    tools = [query_tool]

    try:
        calc_tool = _create_calculator_tool()
        if calc_tool:
            tools.append(calc_tool)
    except Exception as e:
        logger.warning(f"CalculatorTool creation failed: {e}")

    try:
        converter_tool = _create_unit_converter_tool()
        if converter_tool:
            tools.append(converter_tool)
    except Exception as e:
        logger.warning(f"UnitConverterTool creation failed: {e}")

    return tools


def _create_calculator_tool() -> Optional[Any]:
    """Create a calculator function tool."""
    from llama_index.core.tools import FunctionTool
    import math

    def calculator(expression: str) -> str:
        """Evaluate a mathematical expression.

        Args:
            expression: A mathematical expression string, e.g., "2 + 2", "sqrt(16)", "sin(pi/2)"
        """
        try:
            safe_dict = {
                "abs": abs,
                "round": round,
                "min": min,
                "max": max,
                "pow": pow,
                "sqrt": math.sqrt,
                "sin": math.sin,
                "cos": math.cos,
                "tan": math.tan,
                "log": math.log,
                "log10": math.log10,
                "log2": math.log2,
                "exp": math.exp,
                "pi": math.pi,
                "e": math.e,
            }
            result = eval(expression, {"__builtins__": {}}, safe_dict)
            return str(result)
        except Exception as e:
            return f"Error: {type(e).__name__}: {str(e)}"

    return FunctionTool.from_defaults(
        fn=calculator,
        name="calculator",
        description="A calculator tool for evaluating mathematical expressions. Use this for any math calculations. Input should be a valid mathematical expression as a string.",
    )


def _create_unit_converter_tool() -> Optional[Any]:
    """Create a unit converter function tool."""
    from llama_index.core.tools import FunctionTool

    def convert_units(value: float, from_unit: str, to_unit: str) -> str:
        """Convert values between different units.

        Args:
            value: The numeric value to convert
            from_unit: Source unit (e.g., "km", "miles", "kg", "lbs", "celsius", "fahrenheit")
            to_unit: Target unit (e.g., "km", "miles", "kg", "lbs", "celsius", "fahrenheit")
        """
        conversions = {
            ("km", "miles"): 0.621371,
            ("miles", "km"): 1.60934,
            ("m", "feet"): 3.28084,
            ("feet", "m"): 0.3048,
            ("kg", "lbs"): 2.20462,
            ("lbs", "kg"): 0.453592,
            ("celsius", "fahrenheit"): lambda v: v * 9 / 5 + 32,
            ("fahrenheit", "celsius"): lambda v: (v - 32) * 5 / 9,
            ("km", "m"): 1000,
            ("m", "km"): 0.001,
            ("cm", "m"): 0.01,
            ("m", "cm"): 100,
            ("mm", "cm"): 0.1,
            ("cm", "mm"): 10,
        }

        key = (from_unit.lower(), to_unit.lower())
        if key not in conversions:
            return f"Unsupported conversion: {from_unit} to {to_unit}"

        factor = conversions[key]
        if callable(factor):
            result = float(str(factor(value)))
        else:
            result = float(value) * float(factor)

        return str(round(result, 6))

    return FunctionTool.from_defaults(
        fn=convert_units,
        name="unit_converter",
        description="Convert values between different units of measurement. Supports length (km, miles, m, feet, cm, mm), weight (kg, lbs), and temperature (celsius, fahrenheit).",
    )


def create_react_agent(
    kb_id: str,
    tools: Optional[List[Any]] = None,
    model_id: Optional[str] = None,
) -> Any:
    """Create a ReAct agent for complex reasoning with tool use.

    The ReAct agent combines reasoning and acting to solve complex problems
    by using a loop of thought -> action -> observation.

    Args:
        kb_id: Knowledge base identifier for the query engine tool.
        tools: Optional list of tools to give the agent. If None, uses default tools
               including QueryEngineTool, CalculatorTool, and UnitConverterTool.
        model_id: Optional LLM model ID to use for the agent.

    Returns:
        A ReActAgent instance ready for chat completion.
    """
    from llama_index.core.agent import ReActAgent
    from rag.ollama_utils import create_llm

    if tools is None:
        tools = _build_default_tools(kb_id)

    llm = create_llm(model_id=model_id)

    agent = ReActAgent.from_tools(
        tools=tools,
        llm=llm,
        verbose=True,
    )

    return agent


def query_with_agent(
    kb_id: str,
    query: str,
    tools: Optional[List[Any]] = None,
    model_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Query using a ReAct agent and return structured results.

    Args:
        kb_id: Knowledge base identifier.
        query: User query string.
        tools: Optional list of tools.
        model_id: Optional LLM model ID.

    Returns:
        Dict with 'response' and 'sources' keys.
    """
    try:
        agent = create_react_agent(kb_id=kb_id, tools=tools, model_id=model_id)
        response = agent.chat(query)

        return {
            "response": str(response),
            "sources": [],
        }
    except Exception as e:
        logger.error(f"Agent query failed: {type(e).__name__}: {e}")
        return {
            "response": f"Agent query failed: {type(e).__name__}: {str(e)}",
            "sources": [],
        }
