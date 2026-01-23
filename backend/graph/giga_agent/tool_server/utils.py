from copy import deepcopy
from typing import Any, Dict, Tuple


def _simplify_nullable_any_type(schema: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    """If schema has anyOf with exactly {T, null}, remove anyOf and keep non-null branch.

    Returns a tuple of (new_schema, was_anyof_removed).
    """
    any_of = schema.get("anyOf")
    if not isinstance(any_of, list) or len(any_of) != 2:
        return schema, False

    types: list[Any] = []
    for option in any_of:
        if isinstance(option, dict):
            types.append(option.get("type"))
        else:
            types.append(None)

    # Expect exactly one concrete type (string) and one 'null'
    if "null" not in types:
        return schema, False
    non_null_types = [t for t in types if t != "null"]
    if len(non_null_types) != 1 or not isinstance(non_null_types[0], str):
        return schema, False

    non_null_type = non_null_types[0]

    # merge non-null option into the parent, drop anyOf entirely
    non_null_schema = next(
        opt
        for opt in any_of
        if isinstance(opt, dict) and opt.get("type") == non_null_type
    )
    merged: Dict[str, Any] = {k: v for k, v in schema.items() if k != "anyOf"}
    for k, v in non_null_schema.items():
        merged[k] = v

    # If original schema (and merged) have no default, set it to null for nullable fields
    if "default" not in merged:
        merged["default"] = None
    return merged, True


def _transform_object(schema_obj: Dict[str, Any]) -> Dict[str, Any]:
    """Transform an object schema: simplify properties, rebuild required if missing.

    - Removes anyOf when it is exactly {T|null}, keeps other anyOf intact
    - If required is missing, creates it with only properties that originally had no anyOf
    """
    new_obj = deepcopy(schema_obj)
    
    # Гарантируем, что type: "object"
    if new_obj.get("type") is None or new_obj.get("type") == "null":
        new_obj["type"] = "object"
    
    # Гарантируем наличие properties
    if "properties" not in new_obj:
        new_obj["properties"] = {}

    properties = new_obj.get("properties")
    if isinstance(properties, dict):
        required_exists = isinstance(new_obj.get("required"), list)
        required_props = []  # only properties that originally had no anyOf

        for prop_name, prop_schema in properties.items():
            original_prop_schema = prop_schema if isinstance(prop_schema, dict) else {}
            had_anyof_originally = isinstance(original_prop_schema.get("anyOf"), list)

            # Recurse first
            transformed_prop = transform_schema(original_prop_schema)

            # Then try to simplify T|null anyOf at this level
            simplified_prop, removed_anyof = _simplify_nullable_any_type(
                transformed_prop
            )
            properties[prop_name] = simplified_prop

            if not had_anyof_originally:
                required_props.append(prop_name)

        # If required is missing, set it to properties that had no anyOf originally
        if not required_exists:
            new_obj["required"] = required_props

    # Recurse typical containers even if not an object with properties
    if isinstance(new_obj.get("items"), dict):
        new_obj["items"] = transform_schema(new_obj["items"])

    return new_obj


def transform_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively transform a JSON-like schema according to the rules.
    
    Гарантирует, что схема всегда имеет валидный type для OpenAI API.
    """
    if not isinstance(schema, dict):
        # Если schema не словарь, возвращаем базовую схему объекта
        return {"type": "object", "properties": {}}

    # Исправляем type: null на type: object для корневого уровня
    # Это критично для OpenAI API, который требует type: "object" для function calling
    if schema.get("type") is None or schema.get("type") == "null":
        schema["type"] = "object"
        if "properties" not in schema:
            schema["properties"] = {}

    # Обрабатываем anyOf с type: null
    if "anyOf" in schema:
        any_of = schema.get("anyOf", [])
        if isinstance(any_of, list):
            # Удаляем варианты с type: null
            filtered_any_of = [
                opt for opt in any_of
                if isinstance(opt, dict) and opt.get("type") != "null"
            ]
            if filtered_any_of:
                # Если остался только один вариант, извлекаем его
                if len(filtered_any_of) == 1:
                    merged = {k: v for k, v in schema.items() if k != "anyOf"}
                    merged.update(filtered_any_of[0])
                    schema = merged
                else:
                    schema["anyOf"] = filtered_any_of
            else:
                # Если все варианты были null, устанавливаем object
                schema["type"] = "object"
                if "properties" not in schema:
                    schema["properties"] = {}
                del schema["anyOf"]

    # If this node looks like an object with properties
    if isinstance(schema.get("properties"), dict):
        return _transform_object(schema)

    # Otherwise, recurse into known containers and try local simplification
    new_schema = deepcopy(schema)

    # Recurse into nested places
    for key in ("items", "additionalProperties"):
        if isinstance(new_schema.get(key), dict):
            new_schema[key] = transform_schema(new_schema[key])

    # Try local simplification for nullable {T|null}
    new_schema, _ = _simplify_nullable_any_type(new_schema)
    
    # Финальная проверка: если type все еще null, устанавливаем object
    if new_schema.get("type") is None or new_schema.get("type") == "null":
        new_schema["type"] = "object"
        if "properties" not in new_schema:
            new_schema["properties"] = {}
    
    return new_schema


def transform_tool(tool: Dict[str, Any]) -> Dict[str, Any]:
    """Transform a tool's parameters schema, ensuring it's a valid JSON Schema object.
    
    Гарантирует, что схема всегда имеет type: "object" для совместимости с OpenAI API.
    """
    tool = deepcopy(tool)
    parameters = tool.get("parameters", {})
    
    # Если parameters пустой или None, создаем базовую схему объекта
    if not parameters or not isinstance(parameters, dict):
        parameters = {"type": "object", "properties": {}}
    
    # Если type отсутствует или равен null, устанавливаем type: "object"
    if parameters.get("type") is None or parameters.get("type") == "null":
        parameters["type"] = "object"
        # Если properties отсутствуют, добавляем пустой объект
        if "properties" not in parameters:
            parameters["properties"] = {}
    
    # Преобразуем схему
    tool["parameters"] = transform_schema(parameters)
    
    # Финальная проверка: убеждаемся, что type: "object"
    # Это критично для OpenAI API, который требует type: "object" для function calling
    if tool["parameters"].get("type") != "object":
        tool["parameters"]["type"] = "object"
        if "properties" not in tool["parameters"]:
            tool["parameters"]["properties"] = {}
    
    # Дополнительная проверка: удаляем type: null из anyOf, если он там есть
    if "anyOf" in tool["parameters"]:
        any_of = tool["parameters"]["anyOf"]
        if isinstance(any_of, list):
            # Удаляем варианты с type: null
            filtered_any_of = [
                opt for opt in any_of
                if isinstance(opt, dict) and opt.get("type") != "null"
            ]
            if filtered_any_of:
                tool["parameters"]["anyOf"] = filtered_any_of
            else:
                # Если все варианты были null, устанавливаем object
                tool["parameters"]["type"] = "object"
                if "properties" not in tool["parameters"]:
                    tool["parameters"]["properties"] = {}
                del tool["parameters"]["anyOf"]
    
    # Финальная гарантия: type должен быть "object"
    tool["parameters"]["type"] = "object"
    if "properties" not in tool["parameters"]:
        tool["parameters"]["properties"] = {}
    
    return tool
