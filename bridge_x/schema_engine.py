"""Single JSON Schema contract for all executable tool representations."""
from typing import Any
import hashlib
import json
import re
import uuid
from jsonschema import Draft202012Validator, SchemaError, ValidationError
from referencing import Registry
from .errors import BridgeError
from .schemas import ChatRequest
from .json_utils import valid_value
from .tool_models import ToolCall


def _valid_references(schema):
    """Disallow remote $ref lookups in client-declared JSON Schemas.

    External references are unsupported and could otherwise trigger an
    outbound fetch during schema validation. Local `#/$defs/...` is allowed.
    """
    stack = [schema]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for keyword in ("$ref", "$dynamicRef"):
                ref = item.get(keyword)
                if ref is not None and (not isinstance(ref, str) or not ref.startswith("#")):
                    return False
            # Only schema-bearing keywords contain references. Objects inside
            # enum/const/default/examples are user data, not nested schemas.
            for key in ("properties", "patternProperties", "$defs", "definitions", "dependentSchemas"):
                if isinstance(item.get(key), dict):
                    stack.extend(item[key].values())
            for key in ("additionalProperties", "unevaluatedProperties", "propertyNames", "items",
                        "additionalItems", "unevaluatedItems", "contains", "not", "if", "then", "else"):
                if isinstance(item.get(key), dict):
                    stack.append(item[key])
            for key in ("allOf", "anyOf", "oneOf", "prefixItems"):
                if isinstance(item.get(key), list):
                    stack.extend(item[key])
    return True


def registry(req: ChatRequest):
    result = {}
    for item in req.tools:
        name = item.function["name"]
        if name in result:
            raise BridgeError("DUPLICATE_TOOL", "Duplicate tool name declared", 400)
        schema = item.function.get("parameters", {"type": "object"})
        if not valid_value(schema) or not _valid_references(schema):
            raise BridgeError("INVALID_TOOL_SCHEMA", "External schema references are not supported", 400)
        try:
            Draft202012Validator.check_schema(schema)
        except (SchemaError, RecursionError) as exc:
            raise BridgeError("INVALID_TOOL_SCHEMA", "Invalid tool schema", 400) from exc
        # An explicit empty registry disables jsonschema's implicit remote
        # retrieval, including references rebased by nested $id declarations.
        result[name] = (schema, Draft202012Validator(schema, registry=Registry()), hashlib.sha256(
            json.dumps(schema, sort_keys=True, separators=(",", ":")).encode()).hexdigest())
    return result


def tool_choice_name(req):
    if isinstance(req.tool_choice, dict):
        return req.tool_choice["function"]["name"]
    return None



def _safe_schema_failure(name: str, exc: ValidationError) -> str:
    """Explain schema failures without echoing arguments or remote content."""
    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "", name)[:80]
    validator = exc.validator
    field = ""
    for part in list(exc.absolute_path)[:5]:
        if isinstance(part, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]{0,70}", part):
            field += ("." if field else "") + part
        elif isinstance(part, int):
            field += "[item]"
    location = " at " + field if field else ""
    if validator == "required" and isinstance(exc.instance, dict):
        missing = [k for k in exc.validator_value if k not in exc.instance]
        missing = [k for k in missing if isinstance(k, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]{0,70}", k)]
        if missing:
            return f"Tool {safe_name}{location}: missing required field(s): {', '.join(missing[:8])}"
    if validator == "additionalProperties":
        return f"Tool {safe_name}{location}: unexpected argument field; use only declared schema keys"
    if validator == "type":
        expected = exc.validator_value
        if isinstance(expected, list):
            expected = "/".join(str(t) for t in expected)
        if isinstance(expected, str) and re.fullmatch(r"[a-zA-Z/]{1,40}", expected):
            return f"Tool {safe_name}{location}: expected {expected} value"
    if validator == "enum":
        return f"Tool {safe_name}{location}: value not in allowed enum"
    return f"Tool {safe_name}{location}: violates {validator if validator in {'oneOf','anyOf','allOf','minimum','maximum','minItems','maxItems','minLength','maxLength','pattern','format','const','uniqueItems'} else 'JSON Schema'} constraint"



def _normalize_text_frame_integers(arguments: dict[str, Any], schema: dict[str, Any],
                                   *, only_fields: frozenset[str] | None = None) -> dict[str, Any]:
    """Only repair unambiguous scalar integer fields in model TEXT frames.

    @@FIELD always produces strings, even when the client declared an integer.
    Only a bare, canonical decimal string at a top-level key whose declared
    schema type is exclusively integer (or integer|null) may be converted.
    No coercion of paths, source code, enums with string types, nested objects,
    JSON envelopes, or native tool calls. All resulting values still pass
    the client's full JSON Schema validator before reaching ZCode.
    """
    properties = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(properties, dict):
        return arguments
    fixed = None
    for key, value in arguments.items():
        if only_fields is not None and key not in only_fields:
            continue
        rule = properties.get(key)
        if not isinstance(value, str) or not isinstance(rule, dict):
            continue
        types = rule.get("type")
        if types == "integer":
            pass
        elif isinstance(types, list) and set(types) in ({"integer"}, {"integer", "null"}):
            pass
        else:
            continue
        # Avoid accepting float/scientific/locale notation, whitespace-only,
        # non-ASCII digits, massive numbers or ambiguous leading zeros.
        candidate = value.strip(' \t\r\n')
        if len(candidate) > 20 or not re.fullmatch(r"-?(?:0|[1-9][0-9]{0,18})", candidate):
            continue
        if fixed is None:
            fixed = dict(arguments)
        fixed[key] = int(candidate)
    return fixed if fixed is not None else arguments


def validate_specs(specs: list[dict[str, Any]], req: ChatRequest, max_args_bytes: int,
                    *, normalize_text_scalars: bool = False) -> list[ToolCall]:
    """Single validator shared by native, JSON, legacy and v2 tool intents."""
    if not specs or len(specs) > 16:
        raise BridgeError("INVALID_TOOL_COUNT", "Tool envelope must contain 1–16 tools", 422)
    if req.tool_choice == "none":
        raise BridgeError("TOOL_CHOICE_NONE", "Tool calls are disabled by the client", 422)
    if len(specs) > 1 and not req.parallel_tool_calls:
        raise BridgeError("PARALLEL_TOOLS_DISABLED", "Parallel tool calls were not permitted", 422)
    registered = registry(req)
    if not registered:
        raise BridgeError("TOOL_NOT_AVAILABLE", "The client did not declare tools", 422)
    chosen = tool_choice_name(req)
    result = []
    for candidate in specs:
        if not isinstance(candidate, dict) or set(candidate) != {"name", "arguments"}:
            raise BridgeError("INVALID_TOOL_INTENT", "Each tool must contain exact name and arguments", 422)
        name = candidate["name"]
        arguments = candidate["arguments"]
        if not isinstance(name, str) or name not in registered:
            raise BridgeError("TOOL_NOT_AVAILABLE", "Requested tool is not declared", 422)
        if chosen and chosen != name:
            raise BridgeError("WRONG_FORCED_TOOL", "Tool name differs from tool_choice", 422)
        if not isinstance(arguments, dict) or not valid_value(arguments):
            raise BridgeError("INVALID_TOOL_ARGUMENTS", "Tool arguments must be a bounded JSON object", 422)
        if len(json.dumps(arguments, ensure_ascii=False).encode("utf-8")) > max_args_bytes:
            raise BridgeError("TOOL_ARGUMENTS_TOO_LARGE", "Tool arguments exceeded size limit", 422)
        schema, validator, schema_hash = registered[name]
        if normalize_text_scalars:
            arguments = _normalize_text_frame_integers(arguments, schema)
        elif name == "Read":
            # V12.10.2 regression fix: Molab sometimes emits its Read call as
            # a JSON envelope/native call containing "offset": "10", not as
            # a text @@FIELD. Repair only the two known Read pagination fields
            # when the *declared* ZCode schema requires integer, and only for
            # an unambiguous decimal string. All other JSON/native arguments
            # retain strict original types. Final JSON Schema check is mandatory.
            arguments = _normalize_text_frame_integers(
                arguments, schema, only_fields=frozenset(("offset", "limit")))
        try:
            validator.validate(arguments)
        except ValidationError as exc:
            raise BridgeError("TOOL_SCHEMA_MISMATCH", _safe_schema_failure(name, exc), 422) from exc
        except Exception as exc:
            # Unresolvable local references or unsupported schema keywords must
            # not become a generic HTTP 500 or reveal provider/client contents.
            raise BridgeError("INVALID_TOOL_SCHEMA", "Tool schema could not be resolved safely", 400) from exc
        result.append(ToolCall("call_" + uuid.uuid4().hex, name, arguments, schema_hash,
                               conversation_id=req.conversation_id))
    return result

