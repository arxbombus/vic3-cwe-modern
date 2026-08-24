from cwe_tools.context import get_context
from cyclopts import App

app = App(
    name="generate",
    help="Generate CWE Modern content.",
)


@app.command
def superstates() -> None:
    """Generate modern superstate content."""
    context = get_context()

    # Temporary until generate_superstates.py is migrated.
    print(f"Repository: {context.root}")
    print("Superstate generator not yet migrated.")


@app.command
def eras() -> None:
    """Generate Era 11-20 content."""
    context = get_context()

    # Temporary until generate_era11_20.py is migrated.
    print(f"Repository: {context.root}")
    print("Era generator not yet migrated.")
