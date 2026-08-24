from cwe_tools.context import get_context
from cyclopts import App

app = App(
    name="validate",
    help="Validate CWE Modern generated content.",
)


@app.default
def validate() -> None:
    """Validate all CWE Modern generated content."""
    context = get_context()

    print(f"Validating {context.root}")
    print("No validators registered yet.")
