"""Check values against an execution contract's inputs and output schemas.

Contracts use a small part of JSON Schema: object, string and array types, required,
properties, enum and items. This checks exactly that part. A contract that uses
anything else is refused at startup, so nothing goes unchecked.
"""
SUPPORTED = {"type", "required", "properties", "enum", "items", "description", "additionalProperties"}
TYPES = {"object": dict, "string": str, "array": list}


def supported(schema, where="schema"):
    """Problems that stop this module from checking against the schema."""
    if not isinstance(schema, dict):
        return [f"{where} must be an object"]
    problems = [f"{where}: '{k}' isn't supported" for k in sorted(set(schema) - SUPPORTED)]
    if "type" in schema and schema["type"] not in TYPES:
        problems.append(f"{where}: type '{schema['type']}' isn't supported")
    for name, sub in (schema.get("properties") or {}).items():
        problems += supported(sub, f"{where}.{name}")
    if "items" in schema:
        problems += supported(schema["items"], f"{where}[]")
    return problems


def errors(value, schema, where="input"):
    """Every way value fails schema, as {field, message} pairs (A2A's validation details)."""
    kind = schema.get("type")
    if kind and not isinstance(value, TYPES[kind]):
        return [{"field": where, "message": f"must be a{'n' if kind[0] in 'aeiou' else ''} {kind}"}]
    if "enum" in schema and value not in schema["enum"]:
        return [{"field": where, "message": f"must be one of {', '.join(map(str, schema['enum']))}"}]
    found = []
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                found.append({"field": f"{where}.{key}", "message": "is required"})
            elif isinstance(value[key], str) and not value[key].strip():
                found.append({"field": f"{where}.{key}", "message": "must not be empty"})
        if schema.get("additionalProperties") is False:
            found += [{"field": f"{where}.{k}", "message": "isn't allowed"} for k in sorted(set(value) - set(props))]
        for key, sub in props.items():
            if key in value:
                found += errors(value[key], sub, f"{where}.{key}")
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            found += errors(item, schema["items"], f"{where}[{i}]")
    return found


def describe(found):
    return "; ".join(f"{e['field']} {e['message']}" for e in found)
