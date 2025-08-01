from database import list_tables, get_table_columns
from typing import cast, List


def build_schema_snapshot() -> str:
    """Return a plain-text outline of every table and its columns."""
    lines: list[str] = []
    raw_tables = list_tables() or []
    tables = cast(List[str], raw_tables)
    for table in tables:
        cols = get_table_columns(table) or []
        lines.append(f"{table}(")
        for name, dtype in cols:
            lines.append(f"    {name} {dtype},")
        lines.append(")\n")
    return "\n".join(lines)


if __name__ == "__main__":
    schema_text = build_schema_snapshot()
    with open("schema_prompt.txt", "w", encoding="utf-8") as f:
        f.write(schema_text)
    print("✓ schema_prompt.txt generated") 