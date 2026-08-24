from cyclopts import App

from cwe_tools.commands.assets import app as assets_app
from cwe_tools.commands.generate import app as generate_app
from cwe_tools.commands.transform import app as transform_app
from cwe_tools.commands.validate import app as validate_app

app = App(
    name="cwe",
    help="Developer tooling for CWE Modern.",
)

app.command(generate_app)
app.command(transform_app)
app.command(assets_app)
app.command(validate_app)


def main() -> None:
    app()
